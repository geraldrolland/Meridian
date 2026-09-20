import logging
from datetime import datetime, timezone, timedelta

from kafka.errors import NoBrokersAvailable

from app.celery_app import celery_app
from app.database_sync import get_sync_session
from app.lock import acquire_lock, release_lock
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
    1. Acquire Redis lock (2 min TTL)
    2. Extract video_id from event
    3. Fetch Video record, set object_url + status=PROCESSING
    4. Set notification status=RECEIVED
    5. Create Outbox entry
    6. Commit atomically
    7. Release lock
    """
    session = get_sync_session()
    try:
        pending = (
            session.query(BucketNotificationEvent)
            .filter(BucketNotificationEvent.status == NotificationStatus.PENDING.value)
            .limit(BATCH_SIZE)
            .all()
        )

        if not pending:
            return {"processed": 0}

        processed = 0

        for notification in pending:
            lock = acquire_lock(notification.id)
            if lock is None:
                logger.debug("Lock held for notification %s, skipping", notification.id)
                continue

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

                outbox = Outbox(
                    topic="video.queued",
                    payload={
                        "event_id": uuid.uuid4().hex,
                        "origin_service": "video-service",
                        "video_id": video_id, 
                        "object_url": object_url
                        }
                )
                session.add(outbox)

                session.commit()
                processed += 1

                logger.info(
                    "Processed notification %s → video %s status=%s",
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
                        session.commit()
                except Exception:
                    session.rollback()
                logger.exception(
                    "Error processing notification %s", notification.id
                )
            finally:
                release_lock(lock)

        return {"processed": processed, "total_pending": len(pending)}

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
    1. Acquire Redis lock (2 min TTL)
    2. Publish to Kafka
    3. If success → set status=PROCESSED
    4. If NoBrokersAvailable → skip, event stays PENDING for next beat cycle
    5. If other error → increment retry_count
       - If retry_count >= 5 → status=FAILED, set video.status=FAILED
       - Else → set retry_after=now+2min
    6. Commit atomically
    7. Release lock
    """
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
            lock = acquire_lock(event.id, prefix="outbox")
            if lock is None:
                continue

            try:
                outbox = session.get(Outbox, event.id)
                if outbox is None or outbox.status != OutboxStatus.PENDING.value:
                    continue

                # Publish to Kafka synchronously
                kafka_producer.publish(outbox.topic, outbox.payload)

                outbox.status = OutboxStatus.PROCESSED.value
                session.commit()
                processed += 1
                logger.info("Processed outbox event %s", outbox.id)

            except NoBrokersAvailable:
                logger.warning(
                    "Kafka broker unavailable, skipping outbox event %s", event.id
                )
                raise  # Let Celery retry the task later

            except Exception:
                session.rollback()
                try:
                    outbox = session.get(Outbox, event.id)
                    if outbox:
                        new_count = (outbox.retry_count or 0) + 1
                        if new_count >= 5:
                            outbox.retry_count = 5
                            outbox.retry_after = None
                            outbox.status = OutboxStatus.FAILED.value
                            video_id = outbox.payload.get("video_id")
                            if video_id:
                                video = session.get(Video, video_id)
                                if video:
                                    video.status = VideoStatus.DLQ_PENDING.value
                        else:
                            outbox.retry_count = new_count
                            outbox.retry_after = datetime.now(timezone.utc) + timedelta(minutes=2)
                        session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("Error processing outbox event %s", event.id)
                    raise
            finally:
                release_lock(lock)

        return {"processed": processed, "total_pending": len(pending)}

    finally:
        session.close()


@celery_app.task(
    name="app.tasks.process_failed_videos",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    default_retry_delay=60,
)
def process_failed_videos():
    """Query DLQ_PENDING videos and publish to video.DLQ topic.

    For each video:
    1. Acquire Redis lock (2 min TTL)
    2. Re-fetch video, confirm DLQ_PENDING
    3. Publish DLQ message to video.DLQ topic
    4. Set status=FAILED
    5. Commit atomically
    6. Release lock
    """
    session = get_sync_session()
    try:
        videos = (
            session.query(Video)
            .filter(Video.status == VideoStatus.DLQ_PENDING.value)
            .limit(BATCH_SIZE)
            .all()
        )

        if not videos:
            return {"processed": 0}

        processed = 0

        for video in videos:
            lock = acquire_lock(video.id, prefix="dlq")
            if lock is None:
                continue

            try:
                v = session.get(Video, video.id)
                if v is None or v.status != VideoStatus.DLQ_PENDING.value:
                    continue

                dlq_payload = {
                    "video_id": v.id,
                    "user_id": v.user_id,
                    "filename": v.filename,
                    "reason": "processing_failed",
                }

                kafka_producer.publish("video.DLQ", dlq_payload)

                v.status = VideoStatus.FAILED.value
                session.commit()
                processed += 1

                logger.info("Published video %s to DLQ", v.id)

            except NoBrokersAvailable:
                logger.warning(
                    "Kafka broker unavailable, skipping video %s", video.id
                )
                raise

            except Exception:
                session.rollback()
                logger.exception(
                    "Error processing DLQ video %s", video.id
                )
                raise
            finally:
                release_lock(lock)

        return {"processed": processed, "total_pending": len(videos)}

    finally:
        session.close()
