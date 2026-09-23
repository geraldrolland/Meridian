import logging

from app.celery_app import celery_app
from app.database_sync import get_sync_session
from app.lock import LockState, acquire_lock, release_lock
from app.models.notification import BucketNotificationEvent, NotificationStatus
from app.models.video import Video, VideoStatus
from app.utils.notification_utils import build_object_url

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


@celery_app.task(
    name="app.tasks.process_notifications",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    default_retry_delay=60,
)
def process_notifications():
    """Process PENDING notification records in batches.

    For each notification:
    1. Acquire PROCESS lock
    2. Extract video_id, update video status + notification status
    3. Acquire COMMIT lock, commit, release COMMIT lock
    4. Release PROCESS lock

    Outbox event creation is handled separately by process_queued_videos.
    """
    session = get_sync_session()
    try:
        pending = (
            session.query(BucketNotificationEvent)
            .filter(
                BucketNotificationEvent.status == NotificationStatus.PENDING.value,
            )
            .limit(BATCH_SIZE)
            .all()
        )

        if not pending:
            return {"processed": 0}

        processed = 0

        for notification in pending:
            process_lock = acquire_lock(LockState.PROCESS, notification.id)
            if process_lock is None:
                logger.debug("Lock held for notification %s, skipping", notification.id)
                continue

            commit_lock = None
            try:
                notif = session.get(BucketNotificationEvent, notification.id)
                if notif is None or notif.status != NotificationStatus.PENDING.value:
                    continue

                video_id = notif.extract_video_id()
                if video_id is None:
                    notif.status = NotificationStatus.FAILED.value
                    session.commit()
                    logger.warning(
                        "Could not extract video_id from notification %s",
                        notif.id,
                    )
                    continue

                video = session.get(Video, video_id)
                if video is None:
                    notif.status = NotificationStatus.FAILED.value
                    session.commit()
                    logger.warning(
                        "Video %s not found for notification %s",
                        video_id,
                        notif.id,
                    )
                    continue

                object_url = build_object_url(notif.event)

                video.video_url = object_url
                video.size = notif.event["Records"][0]["s3"]["object"]["size"]
                video.status = VideoStatus.QUEUED.value

                notif.status = NotificationStatus.RECEIVED.value

                commit_lock = acquire_lock(LockState.COMMIT, notification.id)
                session.commit()
                processed += 1

                logger.info(
                    "Processed notification %s -> video %s status=%s",
                    notif.id,
                    video_id,
                    VideoStatus.QUEUED.value,
                )

            except Exception:
                session.rollback()
                try:
                    notif = session.get(BucketNotificationEvent, notification.id)
                    if notif:
                        notif.status = NotificationStatus.FAILED.value
                        video = session.get(Video, notif.video_id)
                        if video:
                            video.status = VideoStatus.FAILED.value
                        session.commit()
                except Exception:
                    session.rollback()
                logger.exception(
                    "Error processing notification %s", notification.id
                )
            finally:
                if commit_lock:
                    release_lock(commit_lock)
                release_lock(process_lock)

        return {"processed": processed, "total_pending": len(pending)}

    finally:
        session.close()
