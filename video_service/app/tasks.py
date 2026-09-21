import logging
from datetime import datetime, timezone, timedelta

from app.celery_app import celery_app
from app.config import settings
from app.database_sync import get_sync_session
from app.lock import LockState, acquire_lock, release_lock
from app.models.notification import BucketNotificationEvent, NotificationStatus
from app.models.outbox import Outbox, OutboxStatus
from app.models.video import Video, VideoStatus
from app.producer import kafka_producer
from app.utils.notification_utils import build_object_url
import uuid

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
        now = datetime.now(timezone.utc)
        pending = (
            session.query(BucketNotificationEvent)
            .filter(
                BucketNotificationEvent.status == NotificationStatus.PENDING.value,
                (BucketNotificationEvent.retry_after.is_(None)) | (BucketNotificationEvent.retry_after < now),
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
                        if notif.num_of_retry >= settings.bucketnotification_max_retry:
                            notif.num_of_retry = settings.bucketnotification_max_retry
                            notif.retry_after = None
                            notif.status = NotificationStatus.FAILED.value
                            video = session.get(Video, notif.video_id)
                            if video:
                                video.status = VideoStatus.FAILED.value
                        else:
                            notif.num_of_retry += 1
                            notif.retry_after = datetime.now(timezone.utc) + timedelta(minutes=2)
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


@celery_app.task(
    name="app.tasks.process_outbox_events",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    default_retry_delay=60,
)
def process_outbox_events():
    """Process PENDING outbox events in batches of 100.

    For each event:
    1. Acquire PROCESS lock
    2. Publish to Kafka
    3. Acquire COMMIT lock, commit, release COMMIT lock
    4. Release PROCESS lock
    """
    kafka_producer.initialize()
    session = get_sync_session()
    try:
        now = datetime.now(timezone.utc)
        pending = (
            session.query(Outbox)
            .filter(
                Outbox.status == OutboxStatus.PENDING.value,
                (Outbox.retry_after.is_(None)) | (Outbox.retry_after < now),
            )
            .limit(BATCH_SIZE)
            .all()
        )

        if not pending:
            return {"processed": 0}

        processed = 0

        for event in pending:
            process_lock = acquire_lock(LockState.PROCESS, event.id)
            if process_lock is None:
                continue

            commit_lock = None
            try:
                outbox = session.get(Outbox, event.id)
                if outbox is None or outbox.status != OutboxStatus.PENDING.value:
                    continue

                kafka_producer.publish(outbox.topic, outbox.payload)

                outbox.status = OutboxStatus.PROCESSED.value

                commit_lock = acquire_lock(LockState.COMMIT, event.id)
                session.commit()
                processed += 1
                logger.info("Processed outbox event %s", outbox.id)

            except Exception:
                session.rollback()
                try:
                    outbox = session.get(Outbox, event.id)
                    if outbox:
                        new_count = (outbox.retry_count or 0) + 1
                        if new_count >= settings.outbox_max_retry:
                            outbox.retry_count = settings.outbox_max_retry
                            outbox.retry_after = None
                            outbox.status = OutboxStatus.FAILED.value
                            video_id = outbox.payload.get("video_id")
                            if video_id:
                                video = session.get(Video, video_id)
                                if video:
                                    video.status = VideoStatus.RETRY.value
                        else:
                            outbox.retry_count = new_count
                            outbox.retry_after = datetime.now(timezone.utc) + timedelta(minutes=2)
                        session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("Error processing outbox event %s", event.id)
                    raise
            finally:
                if commit_lock:
                    release_lock(commit_lock)
                release_lock(process_lock)

        return {"processed": processed, "total_pending": len(pending)}

    finally:
        session.close()
