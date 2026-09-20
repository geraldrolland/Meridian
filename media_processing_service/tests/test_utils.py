"""Tests for app.utils module."""

from unittest.mock import patch

from app.utils import build_object_url, resolve_object_key


class TestBuildObjectUrl:
    """Tests for build_object_url."""

    @patch("app.utils.settings")
    def test_basic_url(self, mock_settings):
        mock_settings.minio_endpoint = "minio:9000"
        result = build_object_url("abc/seg_001.mp4", "vidsegments")
        assert result == "http://minio:9000/vidsegments/abc/seg_001.mp4"

    @patch("app.utils.settings")
    def test_thumbnail_bucket(self, mock_settings):
        mock_settings.minio_endpoint = "minio:9000"
        result = build_object_url("vid1/thumb.jpg", "vidthumbnails")
        assert result == "http://minio:9000/vidthumbnails/vid1/thumb.jpg"

    @patch("app.utils.settings")
    def test_custom_endpoint(self, mock_settings):
        mock_settings.minio_endpoint = "minio.local:9000"
        result = build_object_url("key.mp4", "bucket")
        assert result == "http://minio.local:9000/bucket/key.mp4"

    @patch("app.utils.settings")
    def test_empty_key(self, mock_settings):
        mock_settings.minio_endpoint = "minio:9000"
        result = build_object_url("", "bucket")
        assert result == "http://minio:9000/bucket/"


class TestResolveObjectKey:
    """Tests for resolve_object_key."""

    def test_standard_path(self):
        result = resolve_object_key(
            "/app/vid_transcoded/abc/720p/seg_001.mp4",
            "/app/vid_transcoded",
        )
        assert result == "abc/720p/seg_001.mp4"

    def test_short_prefix_matches_last_component(self):
        result = resolve_object_key(
            "/tmp/transcoded/abc/seg.mp4",
            "/tmp/transcoded",
        )
        assert result == "abc/seg.mp4"

    def test_windows_backslashes(self):
        result = resolve_object_key(
            "C:\\app\\vid_transcoded\\abc\\seg.mp4",
            "C:\\app\\vid_transcoded",
        )
        assert result == "vid_transcoded/abc/seg.mp4"

    def test_prefix_not_found_fallback_three_parts(self):
        result = resolve_object_key("/a/b/c/file.mp4", "/nonexistent")
        assert result == "b/c/file.mp4"

    def test_prefix_not_found_fallback_two_parts(self):
        result = resolve_object_key("/a/file.mp4", "/nonexistent")
        assert result == "/a/file.mp4"

    def test_deep_path(self):
        result = resolve_object_key("/a/b/c/d/e/f.mp4", "/a/b/c")
        assert result == "d/e/f.mp4"

    def test_prefix_at_end_of_path(self):
        result = resolve_object_key("/app/transcoded/file.mp4", "transcoded")
        assert result == "file.mp4"
