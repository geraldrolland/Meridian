import os
import subprocess
import glob

class Segmentation:
    def __init__(self, video_path: str, output_dir: str, seg_prefix: str, seg_duration: int):
        self.video_path = video_path
        self.output_dir = output_dir
        self.seg_prefix = seg_prefix
        self.seg_duration = seg_duration

    def generate_segments(self) -> list[str]:
        """Generate video segments using ffmpeg.

        Cuts at ``seg_duration`` boundaries by forcing keyframes there, so
        the produced chunk count matches the MPD's segment plan
        (ceil(duration / seg_duration)). Timestamps are kept continuous
        across chunks (no reset) so downstream .m4s segments carry
        monotonic tfdt values, which MSE needs to place frames correctly.

        Returns:
            List of segment file paths.
        """
        segment_pattern = os.path.join(self.output_dir, f"{self.seg_prefix}%d.mp4")
        command = [
            "ffmpeg",
            "-i", self.video_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-force_key_frames", f"expr:gte(t,n_forced*{self.seg_duration})",
            "-sc_threshold", "0",
            "-f", "segment",
            "-segment_time", str(self.seg_duration),
            # The source's start PTS offset (e.g. 0.066s) makes the first
            # boundary keyframe measure a hair under seg_duration, which
            # otherwise merges it into segment 1 (12s instead of 6s) and
            # leaves one segment short of the MPD's plan. Only our forced
            # keyframes exist here, so a generous delta is safe.
            "-segment_time_delta", "0.5",
            "-segment_start_number", "1",
            "-reset_timestamps", "0",
            segment_pattern
        ]
        subprocess.run(command, check=True)

        # Return list of generated segment files
        return sorted(glob.glob(os.path.join(self.output_dir, f"{self.seg_prefix}*.mp4")))
