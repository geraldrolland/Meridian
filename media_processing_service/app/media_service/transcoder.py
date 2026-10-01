"""Media transcoding module using ffmpeg piped output."""

import logging
import os
import subprocess

from app.config import settings
from app.utils import has_audio_stream

logger = logging.getLogger(__name__)

# Boxes whose payload contains child boxes we may need to visit.
_CONTAINER_BOXES = frozenset({b"moov", b"trak", b"mdia", b"moof", b"traf"})


def _iter_boxes(data: bytes, start: int, end: int):
    """Yield ``(box_type, body_start, body_end)`` for top-level boxes in a range."""
    offset = start
    while offset + 8 <= end:
        size = int.from_bytes(data[offset:offset + 4], "big")
        box_type = bytes(data[offset + 4:offset + 8])
        header = 8
        if size == 1:
            if offset + 16 > end:
                break
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            break
        yield box_type, offset + header, offset + size
        offset += size


def _iter_all_boxes(data: bytes):
    """Yield every box in the file, recursing into container boxes."""
    stack = [(0, len(data))]
    while stack:
        start, end = stack.pop()
        for box_type, body_start, body_end in _iter_boxes(data, start, end):
            if box_type in _CONTAINER_BOXES:
                stack.append((body_start, body_end))
            yield box_type, body_start, body_end


def _mdhd_timescale(data: bytes) -> int:
    """Return the media timescale (mdhd) of the file's first track."""
    for box_type, body_start, _ in _iter_all_boxes(data):
        if box_type == b"mdhd":
            version = data[body_start]
            index = body_start + (20 if version == 1 else 12)
            return int.from_bytes(data[index:index + 4], "big")
    raise ValueError("mdhd box not found while reading media timescale")


def offset_tfdt(data: bytes, offset_seconds: float) -> bytes:
    """Shift every ``tfdt`` box in a fragmented MP4 by ``offset_seconds``.

    ffmpeg 7.x's fragmented-mp4 muxer rebases each output file's timeline to
    zero, so every segment would otherwise carry ``tfdt = 0`` and MSE would
    lay all segments on top of each other at playback position 0 (a stuck /
    static video). The segment's original start timestamp is re-applied here
    after encoding, in units of the track's media timescale.

    Raises:
        ValueError: if the file carries no timeline to patch.
    """
    if offset_seconds == 0:
        return data
    timescale = _mdhd_timescale(data)
    shift = int(round(offset_seconds * timescale))
    if shift == 0:
        return data

    buf = bytearray(data)
    patched = 0
    for box_type, body_start, _ in _iter_all_boxes(buf):
        if box_type != b"tfdt":
            continue
        version = buf[body_start]
        value_index = body_start + 4
        if version == 1:
            value = int.from_bytes(buf[value_index:value_index + 8], "big") + shift
            if value >= 1 << 64:
                raise ValueError("tfdt overflow for 64-bit baseMediaDecodeTime")
            buf[value_index:value_index + 8] = value.to_bytes(8, "big")
        else:
            value = int.from_bytes(buf[value_index:value_index + 4], "big") + shift
            if value >= 1 << 32:
                raise ValueError("tfdt overflow for 32-bit baseMediaDecodeTime")
            buf[value_index:value_index + 4] = value.to_bytes(4, "big")
        patched += 1

    if patched == 0:
        raise ValueError(
            "no tfdt box found in transcoded segment; refusing to upload "
            "a file whose playback timeline cannot be set"
        )
    logger.debug("Shifted %d tfdt box(es) by %.6fs", patched, offset_seconds)
    return bytes(buf)


def _start_time_seconds(path: str) -> float:
    """Read a media file's start timestamp (seconds) with ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=start_time",
            "-of", "default=nw=1:nk=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    value = result.stdout.strip()
    if not value or value == "N/A":
        raise ValueError(f"ffprobe reported no start_time for {path}")
    return float(value)


class MediaTranscoder:
    """Transcodes a video file into multiple CMAF .m4s renditions using ffmpeg.

    Each rendition runs one ffmpeg process that reads the input file,
    scales it to the rendition size with ``-s`` and writes CMAF bytes to
    stdout. Because ffmpeg's fragmented-mp4 muxer rebases timestamps to
    zero, each result is then re-stamped with the input chunk's start
    time (``offset_tfdt``) so segments keep a monotonic playback timeline.

    Audio is extracted as a separate .m4s stream.
    """

    def __init__(self, input_file: str, output_dir: str, codec: str = "libx264"):
        self.input_file = input_file
        self.codec = codec
        self.output_dir = output_dir

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def __extract_audio(self) -> bytes:
        """Extract the audio stream from the input file (copy, no re-encode)."""
        process = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", self.input_file,
                "-vn", "-acodec", "copy",
                "-f", "mp4", "-movflags",
                "+cmaf+dash+frag_keyframe+empty_moov",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        audio_bytes, stderr = process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"Audio extraction failed (rc={process.returncode}): "
                f"{stderr.decode()}"
            )
        return audio_bytes

    def __transcode_rendition(
        self, width: int, height: int, bitrate: str
    ) -> bytes:
        """Transcode the input file to a single rendition.

        One ffmpeg process reads the input directly and scales it to the
        rendition size with ``-s`` (never reinterpreted raw frames) and
        writes fragmented CMAF bytes to stdout. ffmpeg zeroes the fragment
        timeline, so ``run_transcoder`` re-stamps it afterwards.

        Args:
            width: Target width in pixels.
            height: Target height in pixels.
            bitrate: Target video bitrate, e.g. "800k".

        Returns:
            The encoded MP4/CMAF bytes.
        """
        process = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", self.input_file,
                "-map", "0:v:0",
                "-an",
                "-s", f"{width}x{height}",
                "-c:v", self.codec, "-b:v", bitrate,
                "-pix_fmt", "yuv420p",
                "-movflags", "+cmaf+dash+frag_keyframe+empty_moov",
                "-f", "mp4", "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        video_bytes, stderr = process.communicate()

        if process.returncode != 0:
            raise RuntimeError(
                f"Transcoder failed (rc={process.returncode}): "
                f"{stderr.decode()}"
            )
        return video_bytes

    # ------------------------------------------------------------------
    # Private rendition methods
    # ------------------------------------------------------------------

    def __transcode_360p(self) -> bytes:
        r = settings.renditions["360p"]
        return self.__transcode_rendition(r["width"], r["height"], r["bitrate"])

    def __transcode_480p(self) -> bytes:
        r = settings.renditions["480p"]
        return self.__transcode_rendition(r["width"], r["height"], r["bitrate"])

    def __transcode_720p(self) -> bytes:
        r = settings.renditions["720p"]
        return self.__transcode_rendition(r["width"], r["height"], r["bitrate"])

    def __transcode_1080p(self) -> bytes:
        r = settings.renditions["1080p"]
        return self.__transcode_rendition(r["width"], r["height"], r["bitrate"])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_transcoder(self) -> list[str]:
        """Transcode the input file into all renditions and save to disk.

        Transcodes each video rendition and extracts audio, then saves
        all results to:
            <output_dir>/<video_id>/<rendition>/<segment_stem>.m4s

        video_id is extracted from the input file's parent directory.

        Returns:
            List of saved file paths.
        """
        has_audio = has_audio_stream(self.input_file)
        start_seconds = _start_time_seconds(self.input_file)
        audio_bytes = self.__extract_audio() if has_audio else None
        if not has_audio:
            logger.info("No audio stream in %s; skipping audio transcode", self.input_file)

        results: dict[str, bytes] = {}
        for name, method in [
            ("360p", self.__transcode_360p),
            ("480p", self.__transcode_480p),
            ("720p", self.__transcode_720p),
            ("1080p", self.__transcode_1080p),
        ]:
            results[name] = method()
            logger.info("Transcoded %s (%d bytes)", name, len(results[name]))

        if audio_bytes is not None:
            results["audio"] = audio_bytes
            logger.info("Extracted audio (%d bytes)", len(audio_bytes))

        # ffmpeg's fragment muxer rebases every file to t=0; put the chunk's
        # start timestamp back so dash.js sees a monotonic timeline.
        results = {
            name: offset_tfdt(data, start_seconds)
            for name, data in results.items()
        }

        video_id = os.path.basename(os.path.dirname(self.input_file))
        return self.save_renditions(results, video_id)

    def save_renditions(
        self, results: dict[str, bytes], video_id: str
    ) -> list[str]:
        """Save transcoded rendition bytes to disk.

        Writes each entry to:
            <output_dir>/<video_id>/<rendition>/<segment_stem>.m4s

        Args:
            results: Dict mapping rendition name to .m4s bytes.
            video_id: The video ID used as the top-level directory.

        Returns:
            List of saved file paths.
        """
        segment_stem = os.path.splitext(
            os.path.basename(self.input_file)
        )[0]
        saved_files: list[str] = []

        for rendition, data in results.items():
            out_dir = os.path.join(
                self.output_dir, video_id, rendition
            )
            os.makedirs(out_dir, exist_ok=True)

            out_path = os.path.join(out_dir, f"{segment_stem}.m4s")
            with open(out_path, "wb") as f:
                f.write(data)
            saved_files.append(out_path)
            logger.info(
                "Saved %s → %s (%d bytes)",
                rendition, out_path, len(data),
            )

        return saved_files
