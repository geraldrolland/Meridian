import logging
from datetime import datetime, timezone, timedelta

from app.celery_app import celery_app
from app.config import settings
from app.database_sync import get_sync_session
from app.lock import LockState, acquire_lock, release_lock
from app.models.outbox import Outbox, OutboxStatus
from app.models.video import Video, VideoStatus
from app.producer import kafka_producer

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


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
                                    if video.num_of_retries + 1 > settings.video_max_retry:
                                        video.num_of_retries = settings.video_max_retry
                                        video.status = VideoStatus.FAILED.value
                                    else:
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
