import json
import logging
import math
import os
import uuid
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.websockets import WebSocket
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.check_proxy_signature import check_proxy_signature
from app.middleware.get_user_session import get_user_session
from app.minio_client import (
    abort_multipart_upload,
    cleanup_video_obj,
    complete_multipart_upload,
    generate_part_urls,
    generate_upload_data,
    initiate_multipart_upload,
)
from app.models.session import SessionData
from app.models.outbox import Outbox
from app.models.video import (
    AbortUploadRequest,
    CompleteUploadRequest,
    UploadRequest,
    Video,
    VideoStatus,
)
from app.utils.notification_utils import object_key_from_url
from app.websocket import ws_video_endpoint

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/video",
    dependencies=[Depends(check_proxy_signature)],
)

ws_router = APIRouter(prefix="/api/video")


def _video_response(video: Video) -> dict:
    """Serialize a Video record to a JSON-safe dict for API responses."""
    return {
        "id": video.id,
        "filename": video.filename,
        "status": video.status,
        "user_id": video.user_id,
        "published": video.published,
        "num_of_retries": video.num_of_retries,
        "notif_reference_id": video.notif_reference_id,
        "thumbnail_url": video.thumbnail_url,
        "manifest_url": video.manifest_url,
        "created_at": video.created_at.isoformat(),
    }


@router.get("/{video_id}")
async def get_video(
    video_id: str,
    status: VideoStatus | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: SessionData | None = Depends(get_user_session),
):
    """Get a video by ID with optional status filter."""
    video = await session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if user is None or video.user_id != user.userId:
        raise HTTPException(status_code=403, detail="Not authorized to access this video")

    if status is not None and video.status != status.value:
        raise HTTPException(status_code=404, detail="Video not found with that status")

    return _video_response(video)


@router.post("/{video_id}/retry")
async def retry_video(
    video_id: str,
    session: AsyncSession = Depends(get_session),
    user: SessionData | None = Depends(get_user_session),
):
    """Retry a video in RETRY status — sets it back to QUEUED with published=false."""
    video = await session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if user is None or video.user_id != user.userId:
        raise HTTPException(status_code=403, detail="Not authorized to access this video")

    if video.status != VideoStatus.RETRY.value:
        raise HTTPException(status_code=400, detail="Video is not in RETRY status")

    video.status = VideoStatus.QUEUED.value
    video.published = False
    video.num_of_retries += 1
    await session.commit()

    logger.info("Video %s retried — status=QUEUED, published=false", video_id)
    return _video_response(video)


# Statuses where Celery workers are actively processing this video —
# deleting mid-flight could let a task re-create rows right after the
# cleanup consumers removed them.
ACTIVE_DELETE_BLOCKED_STATUSES = {
    VideoStatus.QUEUED.value,
    VideoStatus.PROCESSING.value,
    VideoStatus.GENERATING_MANIFEST.value,
}


@router.delete("/{video_id}")
async def delete_video(
    video_id: str,
    session: AsyncSession = Depends(get_session),
    user: SessionData | None = Depends(get_user_session),
):
    """Delete a video: emit a `video.deleted` outbox event and remove the row.

    Both happen in one transaction — consumers (manifest_service,
    media_processing_service) react to the event and clean up their
    own stores. The original upload in `viduploads` is removed too when
    `video_url` is known. Returns 409 while the video is actively processing.
    """
    video = await session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if user is None or video.user_id != user.userId:
        raise HTTPException(status_code=403, detail="Not authorized to access this video")

    if video.status in ACTIVE_DELETE_BLOCKED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Video is being processed — wait for it to finish before deleting",
        )

    # Captured before session.delete() — attributes are unreachable after commit.
    stored_video_url: str | None = video.video_url

    # Release any in-progress multipart upload (best effort).
    if video.multipart_upload_id:
        try:
            abort_multipart_upload(video_id, video.storage_filename, video.multipart_upload_id)
        except Exception:
            logger.warning("Could not abort multipart upload for video %s", video_id, exc_info=True)
        video.multipart_upload_id = None

    outbox = Outbox(
        topic="video.deleted",
        payload={"video_id": video_id},
        video_id=video_id,
    )
    session.add(outbox)
    await session.delete(video)
    await session.commit()

    # The row is gone — now drop the original upload from viduploads so the
    # bucket does not keep orphaned source videos (best effort).
    if stored_video_url:
        object_key = object_key_from_url(stored_video_url, settings.minio_bucket)
        if object_key is None:
            logger.warning(
                "video_url for video %s does not point at bucket %s — skipping object delete",
                video_id,
                settings.minio_bucket,
            )
        else:
            try:
                cleanup_video_obj(object_key, settings.minio_bucket)
            except Exception:
                logger.warning(
                    "Could not delete source object %s/%s for video %s",
                    settings.minio_bucket,
                    object_key,
                    video_id,
                    exc_info=True,
                )

    logger.info("Video %s deleted — video.deleted event queued", video_id)
    return {"id": video_id, "deleted": True}


@router.post("/upload", status_code=201)
async def upload_video(
    body: UploadRequest,
    session: AsyncSession = Depends(get_session),
    user: SessionData = Depends(get_user_session),
):
    """Create a video record and return upload data.

    Small files (file_size <= threshold): single presigned POST.
    Large files (file_size > threshold): server-side multipart initiation.
    """
    ext = os.path.splitext(body.filename)[1].lstrip(".").lower()
    if ext not in settings.allowed_video_extensions:
        raise HTTPException(
            status_code=422,
            detail=f"File extension '{ext}' is not allowed. Allowed: {', '.join(settings.allowed_video_extensions)}",
        )

    video = Video(
        filename=body.filename,
        storage_filename=f"{uuid.uuid4().hex[:8]}.{ext}",
        user_id=user.userId,
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)

    if body.file_size > settings.multipart_threshold:
        total_parts = math.ceil(body.file_size / settings.default_part_size)
        upload_id = initiate_multipart_upload(video.id, video.storage_filename, body.content_type)
        part_urls = generate_part_urls(video.id, video.storage_filename, upload_id, total_parts)

        video.multipart_upload_id = upload_id
        video.total_parts = total_parts
        await session.commit()

        return {
            **_video_response(video),
            "upload": {
                "mode": "multipart",
                "video_id": video.id,
                "upload_id": upload_id,
                "part_size": settings.default_part_size,
                "total_parts": total_parts,
                "parts": part_urls,
            },
        }

    upload = generate_upload_data(video.id, video.storage_filename, body.content_type)
    return {
        **_video_response(video),
        "upload": upload,
    }


@router.post("/{video_id}/upload/complete")
async def complete_upload(
    video_id: str,
    body: CompleteUploadRequest,
    session: AsyncSession = Depends(get_session),
    user: SessionData | None = Depends(get_user_session),
):
    """Complete a multipart upload server-side."""
    video = await session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if user is None or video.user_id != user.userId:
        raise HTTPException(status_code=403, detail="Not authorized to access this video")

    if video.multipart_upload_id is None:
        raise HTTPException(status_code=400, detail="Video has no multipart upload in progress")

    parts_data = [{"part_number": p.part_number, "etag": p.etag} for p in body.parts]
    complete_multipart_upload(video_id, video.storage_filename, body.upload_id, parts_data)
    video.multipart_upload_id = None
    await session.commit()

    logger.info("Multipart upload completed for video %s", video_id)
    return {"status": video.status}


@router.post("/{video_id}/upload/abort")
async def abort_upload(
    video_id: str,
    body: AbortUploadRequest,
    session: AsyncSession = Depends(get_session),
    user: SessionData | None = Depends(get_user_session),
):
    """Abort a multipart upload, discarding all uploaded parts."""
    video = await session.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if user is None or video.user_id != user.userId:
        raise HTTPException(status_code=403, detail="Not authorized to access this video")

    if video.multipart_upload_id is None:
        raise HTTPException(status_code=400, detail="Video has no multipart upload in progress")

    abort_multipart_upload(video_id, video.storage_filename, body.upload_id)

    video.status = VideoStatus.FAILED.value
    video.multipart_upload_id = None
    await session.commit()

    logger.info("Multipart upload aborted for video %s", video_id)
    return {"status": video.status}


@ws_router.websocket("/ws/video/notification")
async def video_ws(websocket: WebSocket):
    session_cookie = websocket.cookies.get("session")
    if not session_cookie:
        await websocket.close(code=4001, reason="Missing session")
        return
    session_data = json.loads(unquote(session_cookie))
    user_id = str(session_data["userId"])
    await ws_video_endpoint(websocket, user_id)
