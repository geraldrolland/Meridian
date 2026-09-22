import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.session import SessionData
from app.models.video import Video, VideoStatus


@pytest.fixture(autouse=True)
def _mock_heavy_deps():
    sys.modules.pop("app.routes.video", None)

    mock_db = MagicMock()
    mock_db.get_session = MagicMock(return_value=AsyncMock())

    mock_config = MagicMock()
    mock_config.settings.allowed_video_extensions = [
        "mp4", "mov", "avi", "mkv", "webm", "flv", "wmv",
    ]
    mock_config.settings.multipart_threshold = 100 * 1024 * 1024
    mock_config.settings.default_part_size = 5 * 1024 * 1024

    mock_minio = MagicMock()

    mock_middleware = MagicMock()

    patched = {
        "app.database": mock_db,
        "app.config": mock_config,
        "app.minio_client": mock_minio,
        "app.middleware": mock_middleware,
        "app.middleware.check_proxy_signature": mock_middleware,
        "app.middleware.get_user_session": mock_middleware,
    }

    import app.models.video as _real_video_mod

    with patch.dict(sys.modules, patched), \
         patch.object(_real_video_mod, "Video", Video), \
         patch.object(_real_video_mod, "VideoStatus", VideoStatus):
        yield


def _make_mock_session(video=None):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=video)
    return mock_session


def _make_video(
    video_id="vid-123",
    status=VideoStatus.AWAITING_UPLOAD.value,
    published=False,
    num_of_retries=0,
    filename="test.mp4",
    user_id=1,
):
    v = MagicMock()
    v.id = video_id
    v.status = status
    v.published = published
    v.num_of_retries = num_of_retries
    v.filename = filename
    v.user_id = user_id
    v.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return v


def _make_user(user_id=1, role="user", email="a@b.com"):
    return SessionData(userId=user_id, role=role, email=email)


class TestGetVideo:
    @pytest.mark.asyncio
    async def test_returns_video_when_found(self, _mock_heavy_deps):
        from app.routes.video import get_video

        video = _make_video(status=VideoStatus.COMPLETED.value, published=True)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        result = await get_video(video_id="vid-123", status=None, session=session, user=user)

        assert result["id"] == "vid-123"
        assert result["status"] == "COMPLETED"
        assert result["published"] is True
        assert result["filename"] == "test.mp4"
        assert result["user_id"] == 1
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, _mock_heavy_deps):
        from app.routes.video import get_video
        from fastapi import HTTPException

        session = _make_mock_session(video=None)
        user = _make_user(user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            await get_video(video_id="nonexistent", session=session, user=user)

        assert exc_info.value.status_code == 404
        assert "Video not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_404_when_status_mismatch(self, _mock_heavy_deps):
        from app.routes.video import get_video
        from fastapi import HTTPException

        video = _make_video(status=VideoStatus.QUEUED.value)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            await get_video(
                video_id="vid-123",
                status=VideoStatus.COMPLETED,
                session=session,
                user=user,
            )

        assert exc_info.value.status_code == 404
        assert "not found with that status" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_video_when_status_matches(self, _mock_heavy_deps):
        from app.routes.video import get_video

        video = _make_video(status=VideoStatus.QUEUED.value)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        result = await get_video(
            video_id="vid-123",
            status=VideoStatus.QUEUED,
            session=session,
            user=user,
        )

        assert result["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_returns_403_when_no_session(self, _mock_heavy_deps):
        from app.routes.video import get_video
        from fastapi import HTTPException

        video = _make_video(user_id=1)
        session = _make_mock_session(video=video)

        with pytest.raises(HTTPException) as exc_info:
            await get_video(video_id="vid-123", status=None, session=session, user=None)

        assert exc_info.value.status_code == 403
        assert "Not authorized" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_403_when_user_id_mismatch(self, _mock_heavy_deps):
        from app.routes.video import get_video
        from fastapi import HTTPException

        video = _make_video(user_id=1)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=99)

        with pytest.raises(HTTPException) as exc_info:
            await get_video(video_id="vid-123", status=None, session=session, user=user)

        assert exc_info.value.status_code == 403
        assert "Not authorized" in exc_info.value.detail


class TestRetryVideo:
    @pytest.mark.asyncio
    async def test_retries_video_in_retry_status(self, _mock_heavy_deps):
        from app.routes.video import retry_video

        video = _make_video(
            status=VideoStatus.RETRY.value,
            published=False,
            num_of_retries=2,
            user_id=1,
        )
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        result = await retry_video(video_id="vid-123", session=session, user=user)

        assert result["status"] == "QUEUED"
        assert result["published"] is False
        assert video.num_of_retries == 3
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_400_when_not_retry_status(self, _mock_heavy_deps):
        from app.routes.video import retry_video
        from fastapi import HTTPException

        video = _make_video(status=VideoStatus.QUEUED.value, user_id=1)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            await retry_video(video_id="vid-123", session=session, user=user)

        assert exc_info.value.status_code == 400
        assert "not in RETRY status" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, _mock_heavy_deps):
        from app.routes.video import retry_video
        from fastapi import HTTPException

        session = _make_mock_session(video=None)
        user = _make_user(user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            await retry_video(video_id="nonexistent", session=session, user=user)

        assert exc_info.value.status_code == 404
        assert "Video not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_403_when_no_session(self, _mock_heavy_deps):
        from app.routes.video import retry_video
        from fastapi import HTTPException

        video = _make_video(status=VideoStatus.RETRY.value, user_id=1)
        session = _make_mock_session(video=video)

        with pytest.raises(HTTPException) as exc_info:
            await retry_video(video_id="vid-123", session=session, user=None)

        assert exc_info.value.status_code == 403
        assert "Not authorized" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_403_when_user_id_mismatch(self, _mock_heavy_deps):
        from app.routes.video import retry_video
        from fastapi import HTTPException

        video = _make_video(status=VideoStatus.RETRY.value, user_id=1)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=99)

        with pytest.raises(HTTPException) as exc_info:
            await retry_video(video_id="vid-123", session=session, user=user)

        assert exc_info.value.status_code == 403
        assert "Not authorized" in exc_info.value.detail
