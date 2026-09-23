import logging

from app.celery_app import celery_app
from app.database_sync import get_sync_session
from app.lock import LockState, acquire_lock, release_lock
from app.models.outbox import Outbox
from app.models.video import Video, VideoStatus

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.process_queued_videos",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    default_retry_delay=60,
)
def process_queued_videos():
    """Query videos with status=QUEUED and published=false in batches of 50.

    For each video:
    1. Acquire PROCESS lock
    2. Set video.published = True
    3. Create Outbox event with topic=video.queued
    4. Acquire COMMIT lock, commit, release COMMIT lock
    5. Release PROCESS lock
    """
    session = get_sync_session()
    try:
        videos = (
            session.query(Video)
            .filter(
                Video.status == VideoStatus.QUEUED.value,
                Video.published == False,  # noqa: E712
            )
            .limit(50)
            .all()
        )

        if not videos:
            return {"processed": 0}

        processed = 0

        for video in videos:
            process_lock = acquire_lock(LockState.PROCESS, video.id)
            if process_lock is None:
                continue

            commit_lock = None
            try:
                v = session.get(Video, video.id)
                if v is None or v.status != VideoStatus.QUEUED.value or v.published:
                    continue

                v.published = True

                outbox = Outbox(
                    topic="video.queued",
                    video_id=v.id,
                    payload={
                        "origin_service": "video-service",
                        "video_id": v.id,
                        "object_url": v.video_url,
                    },
                )
                session.add(outbox)

                commit_lock = acquire_lock(LockState.COMMIT, video.id)
                session.commit()
                processed += 1

                logger.info(
                    "Published video %s to outbox (topic=video.queued)",
                    v.id,
                )

            except Exception:
                session.rollback()
                logger.exception(
                    "Error processing queued video %s", video.id
                )
                raise
            finally:
                if commit_lock:
                    release_lock(commit_lock)
                release_lock(process_lock)

        return {"processed": processed, "total_pending": len(videos)}

    finally:
        session.close()
