import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.session import SessionData
from app.models.video import (
    UploadRequest,
    Video,
    VideoStatus,
)

MOCK_UPLOAD_RESPONSE = {
    "url": "http://minio:9000/viduploads",
    "fields": {
        "key": "videos/vid-123/test.mp4",
        "policy": "eyJleHBpcmF0aW9uIjog...",
        "x-amz-algorithm": "AWS4-HMAC-SHA256",
        "x-amz-credential": "minioadmin/20260101/us-east-1/s3/aws4_request",
        "x-amz-date": "20260101T000000Z",
        "x-amz-signature": "abcdef1234567890",
    },
}

MOCK_MULTIPART_PARTS = [
    {"part_number": 1, "url": "http://minio/part1"},
    {"part_number": 2, "url": "http://minio/part2"},
    {"part_number": 3, "url": "http://minio/part3"},
]


@pytest.fixture(autouse=True)
def _mock_heavy_deps():
    # Ensure the route module is always freshly imported
    sys.modules.pop("app.routes.video", None)

    # Create fresh mocks per test to avoid state leakage
    mock_db = MagicMock()
    mock_db.get_session = MagicMock(return_value=AsyncMock())

    mock_config = MagicMock()
    mock_config.settings.allowed_video_extensions = [
        "mp4", "mov", "avi", "mkv", "webm", "flv", "wmv",
    ]
    mock_config.settings.multipart_threshold = 100 * 1024 * 1024
    mock_config.settings.default_part_size = 5 * 1024 * 1024

    mock_minio = MagicMock()
    mock_minio.generate_upload_data.return_value = MOCK_UPLOAD_RESPONSE
    mock_minio.initiate_multipart_upload.return_value = "upload-id-123"
    mock_minio.generate_part_urls.return_value = MOCK_MULTIPART_PARTS

    mock_middleware = MagicMock()

    patched = {
        "app.database": mock_db,
        "app.config": mock_config,
        "app.minio_client": mock_minio,
        "app.middleware": mock_middleware,
        "app.middleware.check_proxy_signature": mock_middleware,
        "app.middleware.get_user_session": mock_middleware,
    }

    # Ensure the real app.models.video module isn't corrupted by other test fixtures
    # (test_multipart_upload.py replaces Video with a MagicMock and doesn't restore it)
    import app.models.video as _real_video_mod

    with patch.dict(sys.modules, patched), \
         patch.object(_real_video_mod, "Video", Video), \
         patch.object(_real_video_mod, "VideoStatus", VideoStatus):
        yield {
            "settings": mock_config.settings,
            "generate_upload_data": mock_minio.generate_upload_data,
            "initiate_multipart_upload": mock_minio.initiate_multipart_upload,
            "generate_part_urls": mock_minio.generate_part_urls,
        }


def _make_mock_session():
    """Create a mock session with sync add() and async commit/refresh."""
    mock_session = AsyncMock()
    captured = []

    def capture_add(video):
        captured.append(video)

    mock_session.add = MagicMock(side_effect=capture_add)
    mock_session._captured = captured
    return mock_session


class TestUploadEndpoint:
    @pytest.mark.asyncio
    async def test_sets_user_id_from_session(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="test.mp4")
        user = SessionData(userId=42, role="user", email="a@b.com")

        await upload_video(body=body, session=mock_session, user=user)

        assert len(mock_session._captured) == 1
        assert mock_session._captured[0].user_id == 42

    @pytest.mark.asyncio
    async def test_raises_error_when_no_session(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="test.mp4")

        with pytest.raises((AttributeError, TypeError)):
            await upload_video(body=body, session=mock_session, user=None)

    @pytest.mark.asyncio
    async def test_returns_201_with_upload_data(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="test.mp4")
        user = SessionData(userId=1, role="user", email="a@b.com")

        result = await upload_video(body=body, session=mock_session, user=user)

        assert "upload" in result
        assert result["upload"]["url"] == "http://minio:9000/viduploads"
        assert isinstance(result["upload"]["fields"], dict)
        assert "key" in result["upload"]["fields"]
        assert "policy" in result["upload"]["fields"]
        assert "x-amz-signature" in result["upload"]["fields"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_extension(self, _mock_heavy_deps):
        from app.routes.video import upload_video
        from fastapi import HTTPException

        mock_session = _make_mock_session()
        body = UploadRequest(filename="malicious.txt")
        user = SessionData(userId=1, role="user", email="a@b.com")

        with pytest.raises(HTTPException) as exc_info:
            await upload_video(body=body, session=mock_session, user=user)

        assert exc_info.value.status_code == 422
        assert "not allowed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_allows_valid_extension(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="clip.mkv")
        user = SessionData(userId=1, role="user", email="a@b.com")

        result = await upload_video(body=body, session=mock_session, user=user)

        assert "upload" in result
        assert result["filename"] == "clip.mkv"

    @pytest.mark.asyncio
    async def test_content_type_forwarded(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="test.webm", content_type="video/webm")
        user = SessionData(userId=1, role="user", email="a@b.com")

        await upload_video(body=body, session=mock_session, user=user)

        _mock_heavy_deps["generate_upload_data"].assert_called_once()
        call_args = _mock_heavy_deps["generate_upload_data"].call_args
        assert call_args[0][2] == "video/webm"  # third positional arg is content_type

    @pytest.mark.asyncio
    async def test_large_file_uses_multipart(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="large.mp4", file_size=200 * 1024 * 1024)  # 200MB
        user = SessionData(userId=1, role="user", email="a@b.com")

        result = await upload_video(body=body, session=mock_session, user=user)

        assert result["upload"]["mode"] == "multipart"
        assert result["upload"]["upload_id"] == "upload-id-123"
        assert result["upload"]["total_parts"] == 40  # 200MB / 5MB
        assert len(result["upload"]["parts"]) == 3

    @pytest.mark.asyncio
    async def test_small_file_uses_presigned_post(self, _mock_heavy_deps):
        from app.routes.video import upload_video

        mock_session = _make_mock_session()
        body = UploadRequest(filename="small.mp4", file_size=1024)  # 1KB
        user = SessionData(userId=1, role="user", email="a@b.com")

        result = await upload_video(body=body, session=mock_session, user=user)

        assert result["upload"]["url"] == "http://minio:9000/viduploads"
        assert "fields" in result["upload"]
