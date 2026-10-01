"""Tests for app.media_service module."""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.modules["ffmpeg"] = MagicMock()

from app.media_service.segmentation import Segmentation
from app.media_service.thumbnail import GenerateThumbnail
from app.media_service.transcoder import (
    MediaTranscoder,
    _start_time_seconds,
    offset_tfdt,
)
from app.media_service.cleanup import MediaCleanup, cleanup_jobs
from app.media_service.generate_init import GenerateInit
from app.models.transcode_task import TranscodeTask
from app.models.upload_task import UploadTask
from app.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _box(box_type: bytes, payload: bytes) -> bytes:
    """Build a raw ISO-BMFF box (size includes the 8-byte header)."""
    return (len(payload) + 8).to_bytes(4, "big") + box_type + payload


def make_fragment_bytes(timescale: int = 15360, tfdt_value: int = 0,
                        tfdt_version: int = 0, fragments: int = 1) -> bytes:
    """Minimal fragmented MP4: moov(mdhd) + N x moof(tfdt) + mdat."""
    mdhd_payload = (
        bytes(4)                                   # version + flags
        + (0).to_bytes(4, "big") * 2               # creation, modification
        + timescale.to_bytes(4, "big")
        + (0).to_bytes(4, "big")                   # duration
    )
    moov = _box(b"moov", _box(b"trak", _box(b"mdia", _box(b"mdhd", mdhd_payload))))
    if tfdt_version == 1:
        tfdt_payload = bytes([1, 0, 0, 0]) + tfdt_value.to_bytes(8, "big")
    else:
        tfdt_payload = bytes([0, 0, 0, 0]) + tfdt_value.to_bytes(4, "big")
    parts = [moov]
    for _ in range(fragments):
        parts.append(_box(b"moof", _box(b"traf", _box(b"tfdt", tfdt_payload))))
    parts.append(_box(b"mdat", b"\x00" * 16))
    return b"".join(parts)


def read_tfdt_values(data: bytes) -> list[int]:
    """Return every baseMediaDecodeTime found in ``data``."""
    values = []
    i = 0
    while True:
        i = data.find(b"tfdt", i)
        if i < 0:
            return values
        version = data[i + 4]
        if version == 1:
            values.append(int.from_bytes(data[i + 8:i + 16], "big"))
        else:
            values.append(int.from_bytes(data[i + 8:i + 12], "big"))
        i += 4


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

class TestSegmentation:
    def test_init(self):
        seg = Segmentation("/input.mp4", "/out", "seg", 6)
        assert seg.video_path == "/input.mp4"
        assert seg.output_dir == "/out"
        assert seg.seg_prefix == "seg"
        assert seg.seg_duration == 6

    @patch("app.media_service.segmentation.glob.glob")
    @patch("app.media_service.segmentation.subprocess.run")
    def test_generate_segments_success(self, mock_run, mock_glob):
        mock_run.return_value = MagicMock(returncode=0)
        mock_glob.return_value = ["/out/seg1.mp4", "/out/seg2.mp4"]

        seg = Segmentation("/input.mp4", "/out", "seg_", 6)
        result = seg.generate_segments()

        assert result == ["/out/seg1.mp4", "/out/seg2.mp4"]
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "ffmpeg" in args
        assert "-segment_time" in args
        # chunks must land on exact seg_duration boundaries so the segment
        # count matches the MPD, and must keep their original timestamps so
        # downstream .m4s fragments get monotonic tfdt values
        assert "-force_key_frames" in args
        assert args[args.index("-force_key_frames") + 1] == "expr:gte(t,n_forced*6)"
        assert "-sc_threshold" in args
        # tolerates the source start-PTS offset at the first boundary
        assert "-segment_time_delta" in args
        assert float(args[args.index("-segment_time_delta") + 1]) > 0
        assert "-reset_timestamps" in args
        assert args[args.index("-reset_timestamps") + 1] == "0"

    @patch("app.media_service.segmentation.subprocess.run")
    def test_generate_segments_failure(self, mock_run):
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(1, "ffmpeg")

        seg = Segmentation("/input.mp4", "/out", "seg", 6)
        with pytest.raises(CalledProcessError):
            seg.generate_segments()


# ---------------------------------------------------------------------------
# GenerateThumbnail
# ---------------------------------------------------------------------------

class TestGenerateThumbnail:
    def test_init(self):
        gen = GenerateThumbnail("/video.mp4", "/thumbs", "thumb1")
        assert gen.video_path == "/video.mp4"
        assert gen.output_dir == "/thumbs"
        assert gen.thumbnail_prefix == "thumb1"

    @patch("app.media_service.thumbnail.subprocess.run")
    def test_generate_thumbnail_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        gen = GenerateThumbnail("/video.mp4", "/thumbs", "thumb1")
        result = gen.generate_thumbnail()

        assert result == os.path.join("/thumbs", "thumb1.jpg")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "ffmpeg" in args
        assert "-vframes" in args

    @patch("app.media_service.thumbnail.subprocess.run")
    def test_generate_thumbnail_failure(self, mock_run):
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(1, "ffmpeg")

        gen = GenerateThumbnail("/video.mp4", "/thumbs", "thumb1")
        with pytest.raises(CalledProcessError):
            gen.generate_thumbnail()


# ---------------------------------------------------------------------------
# MediaTranscoder
# ---------------------------------------------------------------------------

class TestMediaTranscoder:
    def test_init(self):
        t = MediaTranscoder("/input.mp4", "/tmp/transcoded")
        assert t.input_file == "/input.mp4"
        assert t.output_dir == "/tmp/transcoded"
        assert t.codec == "libx264"

    def test_init_custom_codec(self):
        t = MediaTranscoder("/input.mp4", "/tmp/transcoded", codec="libx265")
        assert t.codec == "libx265"

    def test_renditions_dict(self):
        assert "360p" in settings.renditions
        assert "480p" in settings.renditions
        assert "720p" in settings.renditions
        assert "1080p" in settings.renditions
        for key in settings.renditions:
            assert "width" in settings.renditions[key]
            assert "height" in settings.renditions[key]
            assert "bitrate" in settings.renditions[key]

    @patch("app.media_service.transcoder.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("app.media_service.transcoder.has_audio_stream", return_value=True)
    @patch("app.media_service.transcoder._start_time_seconds", return_value=6.066016)
    @patch("app.media_service.transcoder.subprocess.Popen")
    def test_run_transcoder_all_renditions(self, mock_popen, mock_start, mock_has_audio, mock_open, mock_makedirs):
        mock_process = MagicMock()
        mock_process.communicate.return_value = (make_fragment_bytes(), b"")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        t = MediaTranscoder("/tmp/downloads/vid1/video.mp4", "/tmp/transcoded")
        paths = t.run_transcoder()

        assert isinstance(paths, list)
        assert len(paths) == 5
        assert all(p.endswith("video.m4s") for p in paths)
        assert mock_popen.call_count == 5

        # every saved rendition is re-stamped with the chunk start time
        written = [c[0][0] for c in mock_open.return_value.__enter__.return_value.write.call_args_list]
        assert len(written) == 5
        expected = round(6.066016 * 15360)
        for data in written:
            assert read_tfdt_values(data) == [expected]

    @patch("app.media_service.transcoder.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("app.media_service.transcoder.has_audio_stream", return_value=True)
    @patch("app.media_service.transcoder._start_time_seconds", return_value=0.0)
    @patch("app.media_service.transcoder.subprocess.Popen")
    def test_audio_extraction_failure(self, mock_popen, mock_start, mock_has_audio, mock_open, mock_makedirs):
        mock_process = MagicMock()
        mock_process.communicate.return_value = (b"", b"error")
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        t = MediaTranscoder("/tmp/downloads/vid1/video.mp4", "/tmp/transcoded")
        with pytest.raises(RuntimeError, match="Audio extraction failed"):
            t.run_transcoder()

    @patch("app.media_service.transcoder.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("app.media_service.transcoder.has_audio_stream", return_value=False)
    @patch("app.media_service.transcoder._start_time_seconds", return_value=12.066016)
    @patch("app.media_service.transcoder.subprocess.Popen")
    def test_run_transcoder_without_audio(
        self, mock_popen, mock_start, mock_has_audio, mock_open, mock_makedirs
    ):
        mock_process = MagicMock()
        mock_process.communicate.return_value = (make_fragment_bytes(), b"")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        transcoder = MediaTranscoder("/tmp/downloads/vid1/video.mp4", "/tmp/transcoded")
        paths = transcoder.run_transcoder()

        assert len(paths) == 4
        assert all("audio" not in path for path in paths)
        assert mock_popen.call_count == 4

    @patch("app.media_service.transcoder.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("app.media_service.transcoder.has_audio_stream", return_value=False)
    @patch("app.media_service.transcoder._start_time_seconds", return_value=42.066016)
    @patch("app.media_service.transcoder.subprocess.Popen")
    def test_rendition_command_scales_input_without_raw_frames(
        self, mock_popen, mock_start, mock_has_audio, mock_open, mock_makedirs
    ):
        """Each rendition must scale with -s; never reinterpret raw RGB24."""
        mock_process = MagicMock()
        mock_process.communicate.return_value = (make_fragment_bytes(), b"")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        transcoder = MediaTranscoder("/tmp/downloads/vid1/seg_7.mp4", "/tmp/transcoded")
        transcoder.run_transcoder()

        cmds = [call[0][0] for call in mock_popen.call_args_list]
        assert len(cmds) == 4
        for cmd in cmds:
            assert "rawvideo" not in cmd
            assert "rgb24" not in cmd
            assert "-s" in cmd
            assert cmd[cmd.index("-i") + 1].endswith("seg_7.mp4")
        sizes = [cmd[cmd.index("-s") + 1] for cmd in cmds]
        assert sizes == ["640x360", "854x480", "1280x720", "1920x1080"]

    @patch("app.media_service.transcoder.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("app.media_service.transcoder.has_audio_stream", return_value=True)
    @patch("app.media_service.transcoder._start_time_seconds", return_value=0.0)
    @patch("app.media_service.transcoder.subprocess.Popen")
    def test_rendition_command_drops_audio(
        self, mock_popen, mock_start, mock_has_audio, mock_open, mock_makedirs
    ):
        """Video renditions must be video-only.

        Audio rides in its own representation. Mapping the source audio into
        a video segment made init.mp4 (video-only) disagree with the media
        segment, and Chromium rejected the append with
        CHUNK_DEMUXER_ERROR_APPEND_FAILED.
        """
        mock_process = MagicMock()
        mock_process.communicate.return_value = (make_fragment_bytes(), b"")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        MediaTranscoder("/tmp/downloads/vid1/video.mp4", "/tmp/transcoded").run_transcoder()

        cmds = [call[0][0] for call in mock_popen.call_args_list]
        video_cmds = [c for c in cmds if "-c:v" in c]
        assert len(video_cmds) == 4
        for cmd in video_cmds:
            assert "-an" in cmd
            assert cmd[cmd.index("-map") + 1] == "0:v:0"

        audio_cmd = next(c for c in cmds if "-vn" in c)
        assert "-acodec" in audio_cmd

    @patch("app.media_service.transcoder.subprocess.run")
    def test_start_time_seconds(self, mock_run):
        mock_run.return_value = MagicMock(stdout="6.066016\n")
        assert _start_time_seconds("/chunks/seg_2.mp4") == pytest.approx(6.066016)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffprobe"
        assert cmd[-1] == "/chunks/seg_2.mp4"

    @patch("app.media_service.transcoder.subprocess.run")
    def test_start_time_seconds_missing_value(self, mock_run):
        mock_run.return_value = MagicMock(stdout="N/A\n")
        with pytest.raises(ValueError, match="no start_time"):
            _start_time_seconds("/chunks/seg_1.mp4")


class TestOffsetTfdt:
    def test_shifts_tfdt_by_start_offset(self):
        data = make_fragment_bytes(timescale=15360, tfdt_value=0)
        out = offset_tfdt(data, 6.066016)
        assert read_tfdt_values(out) == [round(6.066016 * 15360)]

    def test_zero_offset_is_noop(self):
        data = make_fragment_bytes(tfdt_value=0)
        assert offset_tfdt(data, 0.0) == data

    def test_patches_every_fragment(self):
        data = make_fragment_bytes(timescale=90000, tfdt_value=0, fragments=3)
        out = offset_tfdt(data, 18.066)
        assert read_tfdt_values(out) == [round(18.066 * 90000)] * 3

    def test_supports_64bit_tfdt(self):
        data = make_fragment_bytes(timescale=15360, tfdt_value=0, tfdt_version=1)
        out = offset_tfdt(data, 324.066)
        assert read_tfdt_values(out) == [round(324.066 * 15360)]

    def test_raises_without_tfdt(self):
        mdhd_payload = bytes(4) + (0).to_bytes(4, "big") * 2 + (90000).to_bytes(4, "big") + (0).to_bytes(4, "big")
        moov = _box(b"moov", _box(b"trak", _box(b"mdia", _box(b"mdhd", mdhd_payload))))
        with pytest.raises(ValueError, match="no tfdt box"):
            offset_tfdt(moov, 6.0)

    def test_raises_without_mdhd(self):
        broken = _box(b"moof", _box(b"traf", _box(b"tfdt", bytes(8))))
        with pytest.raises(ValueError, match="mdhd box"):
            offset_tfdt(broken, 6.0)

    @patch("app.media_service.transcoder.os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    def test_save_renditions(self, mock_open, mock_makedirs):
        mock_file = mock_open.return_value.__enter__.return_value
        t = MediaTranscoder("/tmp/downloads/abc/video.mp4", "/tmp/transcoded")
        results = {
            "360p": b"\x00" * 10,
            "720p": b"\x00" * 20,
            "audio": b"\x00" * 5,
        }

        paths = t.save_renditions(results, "vid123")

        assert len(paths) == 3
        assert all(p.endswith("video.m4s") for p in paths)
        assert any("vid123" in p and "360p" in p for p in paths)
        assert any("vid123" in p and "720p" in p for p in paths)
        assert any("vid123" in p and "audio" in p for p in paths)
        assert mock_makedirs.call_count == 3
        assert mock_file.write.call_count == 3


# ---------------------------------------------------------------------------
# MediaCleanup
# ---------------------------------------------------------------------------

class TestMediaCleanup:
    def test_singleton(self):
        a = MediaCleanup()
        b = MediaCleanup()
        assert a is b

    def test_cleanup_bucket_empty_list(self):
        cleanup = MediaCleanup()
        # Should return without error
        cleanup.cleanup_bucket([], "bucket")

    @patch("app.media_service.cleanup.delete_object")
    def test_cleanup_bucket_deletes_objects(self, mock_delete):
        cleanup = MediaCleanup()
        cleanup.cleanup_bucket(["key1", "key2"], "mybucket")
        assert mock_delete.call_count == 2
        mock_delete.assert_any_call("key1", "mybucket")
        mock_delete.assert_any_call("key2", "mybucket")

    @patch("app.media_service.cleanup.delete_object")
    def test_cleanup_bucket_propagates_error(self, mock_delete):
        mock_delete.side_effect = Exception("MinIO error")
        cleanup = MediaCleanup()
        with pytest.raises(Exception, match="MinIO error"):
            cleanup.cleanup_bucket(["key1"], "mybucket")

    @patch("app.media_service.cleanup.shutil.rmtree")
    @patch("app.media_service.cleanup.os.remove")
    @patch("app.media_service.cleanup.os.path.isdir")
    @patch("app.media_service.cleanup.os.listdir")
    @patch("app.media_service.cleanup.settings")
    def test_cleanup_temp_files(self, mock_settings, mock_listdir, mock_isdir, mock_remove, mock_rmtree):
        mock_settings.vid_download_dir = "/tmp/downloads"
        mock_settings.vid_segment_dir = "/tmp/segments"
        mock_settings.vid_transcode_dir = "/tmp/transcoded"
        mock_settings.vid_thumbnail_dir = "/tmp/thumbnails"

        # Each base_dir is a directory; listdir returns mixed entries
        base_dirs = {
            "/tmp/downloads", "/tmp/segments", "/tmp/transcoded", "/tmp/thumbnails",
        }
        # video123 under segments is a directory; others are files
        dir_entries = {os.path.join("/tmp/segments", "video123")}
        mock_isdir.side_effect = lambda p: p in base_dirs or p in dir_entries

        def _listdir(path):
            return {
                "/tmp/downloads": ["video123_meta", "other_video123", "unrelated"],
                "/tmp/segments": ["video123", "other_video123_extra", "unrelated"],
                "/tmp/transcoded": ["video123"],
                "/tmp/thumbnails": ["video123_thumb.jpg", "unrelated"],
            }[path]

        mock_listdir.side_effect = _listdir

        cleanup = MediaCleanup()
        cleanup.cleanup_temp_files("video123")

        # video123 is a dir under segments → rmtree
        assert mock_rmtree.call_count == 1
        mock_rmtree.assert_any_call(os.path.join("/tmp/segments", "video123"))
        # video123_meta (downloads), video123 (transcoded), video123_thumb.jpg (thumbnails) → os.remove
        assert mock_remove.call_count == 3
        mock_remove.assert_any_call(os.path.join("/tmp/downloads", "video123_meta"))
        mock_remove.assert_any_call(os.path.join("/tmp/transcoded", "video123"))
        mock_remove.assert_any_call(os.path.join("/tmp/thumbnails", "video123_thumb.jpg"))

        # Ensure non-matching entries were NOT deleted
        all_removed = [c.args[0] if c.args else "" for c in mock_remove.call_args_list]
        all_rmtreed = [c.args[0] if c.args else "" for c in mock_rmtree.call_args_list]
        for name in ["other_video123", "other_video123_extra", "unrelated"]:
            assert not any(name in p for p in all_removed + all_rmtreed)

    @patch("app.media_service.cleanup.shutil.rmtree")
    @patch("app.media_service.cleanup.os.listdir")
    @patch("app.media_service.cleanup.os.path.isdir")
    @patch("app.media_service.cleanup.settings")
    def test_cleanup_temp_files_missing_base_dir(self, mock_settings, mock_isdir, mock_listdir, mock_rmtree):
        mock_settings.vid_download_dir = "/tmp/downloads"
        mock_settings.vid_segment_dir = "/tmp/segments"
        mock_settings.vid_transcode_dir = "/tmp/transcoded"
        mock_settings.vid_thumbnail_dir = "/tmp/thumbnails"
        # All base dirs missing
        mock_isdir.return_value = False

        cleanup = MediaCleanup()
        cleanup.cleanup_temp_files("video123")

        mock_rmtree.assert_not_called()
        mock_listdir.assert_not_called()


# ---------------------------------------------------------------------------
# cleanup_jobs (video.deleted)
# ---------------------------------------------------------------------------

def _make_job(job_id="job:1", video_id="vid1", thumb=None):
    job = MagicMock()
    job.id = job_id
    job.video_id = video_id
    job.vid_thumbnail_url = thumb
    return job


def _make_cleanup_session(transcode_rows, upload_rows):
    """Session mock answering both queries cleanup_jobs issues."""
    session = MagicMock()

    def _query(model):
        q = MagicMock()
        if model is TranscodeTask.id:
            q.filter.return_value.all.return_value = transcode_rows
        else:
            assert model is UploadTask
            q.filter.return_value.all.return_value = upload_rows
        return q

    session.query.side_effect = _query
    session.delete = MagicMock()
    session.commit = MagicMock()
    return session


def _tc_row(tc_id):
    row = MagicMock()
    row.id = tc_id
    return row


class TestCleanupJobs:
    @patch("app.media_service.cleanup.MediaCleanup.cleanup_temp_files")
    @patch("app.media_service.cleanup.delete_object")
    def test_deletes_segment_and_thumbnail_objects_then_job(
        self, mock_delete, mock_temp
    ):
        job = _make_job(thumb="http://minio:9000/vidthumbnails/vid1/thumb.jpg")
        upload = MagicMock()
        upload.upload_files = [
            "/tmp/transcoded/vid1/720p/seg_001.mp4",
            "/tmp/transcoded/vid1/720p/seg_002.mp4",
        ]
        session = _make_cleanup_session([_tc_row("tc1")], [upload])

        cleanup_jobs([job], session)

        assert mock_delete.call_count == 3
        mock_delete.assert_any_call("vid1/720p/seg_001.mp4", "vidsegments")
        mock_delete.assert_any_call("vid1/720p/seg_002.mp4", "vidsegments")
        mock_delete.assert_any_call("vid1/thumb.jpg", "vidthumbnails")
        mock_temp.assert_called_once_with("vid1")
        session.delete.assert_called_once_with(job)
        session.commit.assert_called_once()

    @patch("app.media_service.cleanup.MediaCleanup.cleanup_temp_files")
    @patch("app.media_service.cleanup.delete_object")
    def test_multiple_jobs_commit_once(self, mock_delete, mock_temp):
        job1 = _make_job("job:1")
        job2 = _make_job("job:2")
        upload = MagicMock()
        upload.upload_files = ["/tmp/transcoded/vid1/720p/seg_001.mp4"]
        session = _make_cleanup_session([_tc_row("tc1")], [upload])

        cleanup_jobs([job1, job2], session)

        assert session.delete.call_count == 2
        session.delete.assert_any_call(job1)
        session.delete.assert_any_call(job2)
        session.commit.assert_called_once()

    @patch("app.media_service.cleanup.MediaCleanup.cleanup_temp_files")
    @patch("app.media_service.cleanup.delete_object")
    def test_job_without_transcode_tasks_still_deleted(
        self, mock_delete, mock_temp
    ):
        job = _make_job()
        session = _make_cleanup_session([], [])

        cleanup_jobs([job], session)

        mock_delete.assert_not_called()
        session.delete.assert_called_once_with(job)
        session.commit.assert_called_once()

    @patch("app.media_service.cleanup.MediaCleanup.cleanup_temp_files")
    @patch("app.media_service.cleanup.delete_object")
    def test_upload_files_empty_skips_segment_deletes(
        self, mock_delete, mock_temp
    ):
        job = _make_job()
        upload = MagicMock()
        upload.upload_files = []
        session = _make_cleanup_session([_tc_row("tc1")], [upload])

        cleanup_jobs([job], session)

        mock_delete.assert_not_called()
        session.delete.assert_called_once_with(job)
        session.commit.assert_called_once()

    @patch("app.media_service.cleanup.MediaCleanup.cleanup_temp_files")
    @patch("app.media_service.cleanup.delete_object")
    def test_object_delete_failure_propagates_without_commit(
        self, mock_delete, mock_temp
    ):
        mock_delete.side_effect = Exception("minio down")
        job = _make_job()
        upload = MagicMock()
        upload.upload_files = ["/tmp/transcoded/vid1/720p/seg_001.mp4"]
        session = _make_cleanup_session([_tc_row("tc1")], [upload])

        with pytest.raises(Exception, match="minio down"):
            cleanup_jobs([job], session)

        session.delete.assert_not_called()
        session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# GenerateInit
# ---------------------------------------------------------------------------

class TestGenerateInit:
    def test_init(self):
        g = GenerateInit("/input.mp4", "/out", ["360p", "720p"])
        assert g.input_file == "/input.mp4"
        assert g.output_dir == "/out"
        assert g.representation == ["360p", "720p"]

    @patch("app.media_service.generate_init.has_audio_stream", return_value=True)
    @patch("app.media_service.generate_init.get_video_framerate", return_value=30.0)
    @patch("app.media_service.generate_init.subprocess.Popen")
    def test_generate_init_file(self, mock_popen, mock_get_framerate, mock_has_audio):
        mock_process = MagicMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        g = GenerateInit("/input.mp4", "/out", ["360p", "480p"])
        paths = g.generate_init_file()

        assert len(paths) == 3
        assert paths[0].endswith(os.path.join("360p", "init.mp4"))
        assert paths[1].endswith(os.path.join("480p", "init.mp4"))
        assert paths[2].endswith(os.path.join("audio", "init.mp4"))
        assert mock_popen.call_count == 3
        assert mock_get_framerate.called

        # First video stream only — cover-art (attached_pic) streams must not be mapped
        video_args = mock_popen.call_args_list[0][0][0]
        assert video_args[video_args.index("-map") + 1] == "0:v:0"
        # First audio stream only — multi-audio inputs must not map every track
        audio_args = mock_popen.call_args_list[2][0][0]
        assert audio_args[audio_args.index("-map") + 1] == "0:a:0"

    @patch("app.media_service.generate_init.has_audio_stream", return_value=False)
    @patch("app.media_service.generate_init.get_video_framerate", return_value=30.0)
    @patch("app.media_service.generate_init.subprocess.Popen")
    def test_generate_init_without_audio(self, mock_popen, mock_get_framerate, mock_has_audio, tmp_path):
        mock_process = MagicMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        generator = GenerateInit("/input.mp4", str(tmp_path), ["360p"])
        paths = generator.generate_init_file()

        assert len(paths) == 1
        assert paths[0].endswith(os.path.join("360p", "init.mp4"))
        assert mock_popen.call_count == 1

    @patch("app.media_service.generate_init.get_video_framerate", return_value=30.0)
    @patch("app.media_service.generate_init.subprocess.Popen")
    def test_generate_init_failure(self, mock_popen, mock_get_framerate):
        mock_process = MagicMock()
        mock_process.communicate.return_value = (b"", b"error")
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        g = GenerateInit("/input.mp4", "/out", ["360p"])
        with pytest.raises(RuntimeError, match="Init segment failed"):
            g.generate_init_file()
