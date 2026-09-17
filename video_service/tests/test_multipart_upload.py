import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_module(name: str) -> MagicMock:
    mod = MagicMock()
    mod.__name__ = name
    mod.__package__ = name
    return mod


class _FakeEnumMember:
    def __init__(self, value):
        self.value = value
    def __eq__(self, other):
        if isinstance(other, _FakeEnumMember):
            return self.value == other.value
        return self.value == other
    def __repr__(self):
        return f"FakeEnum({self.value!r})"


MOCK_VIDEO_CLASS = MagicMock(name="Video")
MOCK_VIDEO_STATUS = MagicMock(name="VideoStatus")
MOCK_VIDEO_STATUS.AWAITING_UPLOAD = _FakeEnumMember("AWAITING_UPLOAD")
MOCK_VIDEO_STATUS.QUEUED = _FakeEnumMember("QUEUED")
MOCK_VIDEO_STATUS.FAILED = _FakeEnumMember("FAILED")


@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    mock_modules = {
        "app.config": _make_mock_module("app.config"),
        "app.minio_client": _make_mock_module("app.minio_client"),
        "app.models": _make_mock_module("app.models"),
        "app.models.video": _make_mock_module("app.models.video"),
    }

    for mod_name, mock_mod in mock_modules.items():
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, mock_mod)

    import app.config as cfg_mod
    cfg_mod.settings = MagicMock()
    cfg_mod.settings.multipart_threshold = 100 * 1024 * 1024  # 100MB
    cfg_mod.settings.default_part_size = 5 * 1024 * 1024       # 5MB
    cfg_mod.settings.minio_bucket = "vid_uploads"

    import app.models.video as video_mod
    video_mod.Video = MOCK_VIDEO_CLASS
    video_mod.VideoStatus = MOCK_VIDEO_STATUS


class TestMultipartUploadFunctions:
    def test_initiate_multipart_upload(self, _mock_heavy_deps):
        mock_client = MagicMock()
        mock_client._create_multipart_upload.return_value = "upload-id-123"

        with patch("app.minio_client.client", mock_client), \
             patch("app.minio_client.settings", sys.modules["app.config"].settings):
            from app.minio_client import initiate_multipart_upload
            result = initiate_multipart_upload("vid-123", "test.mp4", "video/mp4")

        assert result == "upload-id-123"
        mock_client._create_multipart_upload.assert_called_once_with(
            "vid_uploads",
            "videos/vid-123/test.mp4",
            headers={"Content-Type": "video/mp4"},
        )

    def test_generate_part_urls(self, _mock_heavy_deps):
        mock_client = MagicMock()
        mock_client.get_presigned_url.return_value = "http://minio/part-url"

        with patch("app.minio_client.client", mock_client), \
             patch("app.minio_client.settings", sys.modules["app.config"].settings):
            from app.minio_client import generate_part_urls
            result = generate_part_urls("vid-123", "test.mp4", "upload-id-123", 3)

        assert len(result) == 3
        assert result[0]["part_number"] == 1
        assert result[0]["url"] == "http://minio/part-url"
        assert result[2]["part_number"] == 3
        assert mock_client.get_presigned_url.call_count == 3

    def test_complete_multipart_upload(self, _mock_heavy_deps):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.location = "http://minio/videos/vid-123/test.mp4"
        mock_result.etag = "etag-abc"
        mock_client._complete_multipart_upload.return_value = mock_result

        parts = [
            {"part_number": 1, "etag": "etag-1"},
            {"part_number": 2, "etag": "etag-2"},
        ]

        with patch("app.minio_client.client", mock_client), \
             patch("app.minio_client.settings", sys.modules["app.config"].settings):
            from app.minio_client import complete_multipart_upload
            result = complete_multipart_upload("vid-123", "test.mp4", "upload-id-123", parts)

        assert result["location"] == "http://minio/videos/vid-123/test.mp4"
        assert result["etag"] == "etag-abc"
        mock_client._complete_multipart_upload.assert_called_once()

    def test_abort_multipart_upload(self, _mock_heavy_deps):
        mock_client = MagicMock()

        with patch("app.minio_client.client", mock_client), \
             patch("app.minio_client.settings", sys.modules["app.config"].settings):
            from app.minio_client import abort_multipart_upload
            abort_multipart_upload("vid-123", "test.mp4", "upload-id-123")

        mock_client._abort_multipart_upload.assert_called_once_with(
            "vid_uploads",
            "videos/vid-123/test.mp4",
            "upload-id-123",
        )
