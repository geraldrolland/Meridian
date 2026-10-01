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
    mock_config.settings.minio_bucket = "viduploads"

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
    manifest_url=None,
    thumbnail_url=None,
    multipart_upload_id=None,
    video_url=None,
):
    v = MagicMock()
    v.id = video_id
    v.status = status
    v.published = published
    v.num_of_retries = num_of_retries
    v.filename = filename
    v.user_id = user_id
    v.manifest_url = manifest_url
    v.thumbnail_url = thumbnail_url
    v.storage_filename = "abcdef12.mp4"
    v.multipart_upload_id = multipart_upload_id
    v.video_url = video_url
    v.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return v


def _make_user(user_id=1, email="a@b.com"):
    return SessionData(userId=user_id, email=email)


class TestGetVideo:
    @pytest.mark.asyncio
    async def test_returns_video_when_found(self, _mock_heavy_deps):
        from app.routes.video import get_video

        video = _make_video(
            status=VideoStatus.COMPLETED.value,
            published=True,
            manifest_url="http://minio:9000/manifest/vid-123/manifest_abc.mpd",
        )
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        result = await get_video(video_id="vid-123", status=None, session=session, user=user)

        assert result["id"] == "vid-123"
        assert result["status"] == "COMPLETED"
        assert result["published"] is True
        assert result["filename"] == "test.mp4"
        assert result["user_id"] == 1
        assert result["manifest_url"] == "http://minio:9000/manifest/vid-123/manifest_abc.mpd"
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


class TestDeleteVideo:
    @pytest.mark.asyncio
    async def test_deletes_video_and_queues_video_deleted_event(self, _mock_heavy_deps):
        from app.models.outbox import Outbox
        from app.routes.video import delete_video

        video = _make_video(status=VideoStatus.COMPLETED.value, user_id=1)
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result == {"id": "vid-123", "deleted": True}
        session.add.assert_called_once()
        outbox = session.add.call_args[0][0]
        assert isinstance(outbox, Outbox)
        assert outbox.topic == "video.deleted"
        assert outbox.payload == {"video_id": "vid-123"}
        assert outbox.video_id == "vid-123"
        session.delete.assert_awaited_once_with(video)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, _mock_heavy_deps):
        from app.routes.video import delete_video
        from fastapi import HTTPException

        session = _make_mock_session(video=None)
        user = _make_user(user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            await delete_video(video_id="nonexistent", session=session, user=user)

        assert exc_info.value.status_code == 404
        session.delete.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_403_when_no_session(self, _mock_heavy_deps):
        from app.routes.video import delete_video
        from fastapi import HTTPException

        video = _make_video(user_id=1)
        session = _make_mock_session(video=video)

        with pytest.raises(HTTPException) as exc_info:
            await delete_video(video_id="vid-123", session=session, user=None)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_403_when_user_id_mismatch(self, _mock_heavy_deps):
        from app.routes.video import delete_video
        from fastapi import HTTPException

        video = _make_video(user_id=1)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=99)

        with pytest.raises(HTTPException) as exc_info:
            await delete_video(video_id="vid-123", session=session, user=user)

        assert exc_info.value.status_code == 403
        session.delete.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [
            VideoStatus.QUEUED.value,
            VideoStatus.PROCESSING.value,
            VideoStatus.GENERATING_MANIFEST.value,
        ],
    )
    async def test_returns_409_while_actively_processing(
        self, _mock_heavy_deps, status
    ):
        from app.routes.video import delete_video
        from fastapi import HTTPException

        video = _make_video(status=status, user_id=1)
        session = _make_mock_session(video=video)
        user = _make_user(user_id=1)

        with pytest.raises(HTTPException) as exc_info:
            await delete_video(video_id="vid-123", session=session, user=user)

        assert exc_info.value.status_code == 409
        assert "being processed" in exc_info.value.detail
        session.delete.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [
            VideoStatus.AWAITING_UPLOAD.value,
            VideoStatus.COMPLETED.value,
            VideoStatus.FAILED.value,
            VideoStatus.RETRY.value,
        ],
    )
    async def test_allows_delete_for_non_active_statuses(
        self, _mock_heavy_deps, status
    ):
        from app.routes.video import delete_video

        video = _make_video(status=status, user_id=1)
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result["deleted"] is True
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aborts_in_progress_multipart_upload(self, _mock_heavy_deps):
        from app.routes.video import delete_video

        video = _make_video(
            status=VideoStatus.AWAITING_UPLOAD.value,
            user_id=1,
            multipart_upload_id="upload-xyz",
        )
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        with patch("app.routes.video.abort_multipart_upload") as mock_abort:
            await delete_video(video_id="vid-123", session=session, user=user)

        mock_abort.assert_called_once_with("vid-123", "abcdef12.mp4", "upload-xyz")
        assert video.multipart_upload_id is None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_survives_multipart_abort_failure(self, _mock_heavy_deps):
        from app.routes.video import delete_video

        video = _make_video(
            status=VideoStatus.AWAITING_UPLOAD.value,
            user_id=1,
            multipart_upload_id="upload-xyz",
        )
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        with patch(
            "app.routes.video.abort_multipart_upload",
            side_effect=Exception("minio down"),
        ):
            result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result["deleted"] is True
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deletes_source_object_from_viduploads(self, _mock_heavy_deps):
        from app.routes.video import delete_video

        video = _make_video(
            status=VideoStatus.COMPLETED.value,
            user_id=1,
            video_url="http://minio:9000/viduploads/videos/vid-123/test.mp4",
        )
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        with patch("app.routes.video.cleanup_video_obj") as mock_cleanup:
            result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result["deleted"] is True
        mock_cleanup.assert_called_once_with("videos/vid-123/test.mp4", "viduploads")

    @pytest.mark.asyncio
    async def test_skips_object_delete_when_video_url_missing(self, _mock_heavy_deps):
        from app.routes.video import delete_video

        video = _make_video(status=VideoStatus.COMPLETED.value, user_id=1, video_url=None)
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        with patch("app.routes.video.cleanup_video_obj") as mock_cleanup:
            result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result["deleted"] is True
        mock_cleanup.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_object_delete_when_url_points_to_other_bucket(self, _mock_heavy_deps):
        from app.routes.video import delete_video

        video = _make_video(
            status=VideoStatus.COMPLETED.value,
            user_id=1,
            video_url="http://minio:9000/manifest/videos/vid-123/test.mp4",
        )
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        with patch("app.routes.video.cleanup_video_obj") as mock_cleanup:
            result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result["deleted"] is True
        mock_cleanup.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_survives_source_object_cleanup_failure(self, _mock_heavy_deps):
        from app.routes.video import delete_video

        video = _make_video(
            status=VideoStatus.COMPLETED.value,
            user_id=1,
            video_url="http://minio:9000/viduploads/videos/vid-123/test.mp4",
        )
        session = _make_mock_session(video=video)
        session.add = MagicMock()
        user = _make_user(user_id=1)

        with patch(
            "app.routes.video.cleanup_video_obj",
            side_effect=Exception("minio down"),
        ):
            result = await delete_video(video_id="vid-123", session=session, user=user)

        assert result["deleted"] is True
        session.commit.assert_awaited_once()
