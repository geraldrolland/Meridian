"""Kafka consumer for the media processing service.

Subscribes to the video.queued topic and persists Job records together
with a `job.processing` outbox event.

Also subscribes to video.deleted: fetches every job for the video and
runs `cleanup_jobs` (segment/thumbnail objects, temp files, job rows).
"""

import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition, ConsumerRebalanceListener
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db_config import async_session_factory, get_sync_session
from app.media_service.cleanup import cleanup_jobs
from app.models.event import VideoQueuedEvent
from app.models.job import Job
from app.models.outbox import Outbox

logger = logging.getLogger(__name__)


class AppRebalanceListener(ConsumerRebalanceListener):
    """Logs Kafka partition rebalance events for the media processing consumer group."""

    async def on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        logger.info("Partitions revoked: %s", revoked)

    async def on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        logger.info("Partitions assigned: %s", assigned)


def _handle_video_deleted(video_id: str) -> None:
    """Delete every job (and its artifacts) for a deleted video.

    Runs in a worker thread — MinIO deletes and the sync session block.
    `cleanup_jobs` commits once after all job rows are removed; the
    transcode/upload task FKs cascade with each job.
    """
    session = get_sync_session()
    try:
        jobs = session.query(Job).filter(Job.video_id == video_id).all()
        if jobs:
            cleanup_jobs(jobs, session)
        else:
            logger.info("No jobs to clean up for deleted video %s", video_id)
    finally:
        session.close()


async def consume_messages(consumer: AIOKafkaConsumer) -> None:
    """Main consumer loop. Runs until cancelled."""
    try:
        async for msg in consumer:
            try:
                raw_value: bytes = msg.value
                if raw_value is None:
                    logger.warning("Received empty message at offset %d", msg.offset)
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                event_dict: dict[str, Any] = json.loads(raw_value.decode("utf-8"))

                if msg.topic == settings.kafka_video_deleted_topic:
                    deleted_video_id = event_dict.get("video_id")
                    if not deleted_video_id:
                        logger.warning(
                            "video.deleted message without video_id, skipping"
                        )
                        await consumer.commit(
                            {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                        )
                        continue
                    try:
                        await asyncio.to_thread(_handle_video_deleted, deleted_video_id)
                        logger.info(
                            "Cleaned up jobs for deleted video %s", deleted_video_id
                        )
                    except IntegrityError:
                        logger.warning(
                            "IntegrityError while cleaning jobs for video %s, skipping",
                            deleted_video_id,
                            exc_info=True,
                        )
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                event = VideoQueuedEvent.model_validate(event_dict)

                # 2. Create Job object in memory
                job = Job(
                    id=f"job:{event.event_id}",
                    video_id=event.video_id,
                    object_url=event.object_url,
                )

                outbox = Outbox(
                    topic="job.processing",
                    payload={
                        "video_id": event.video_id
                        }
                )

                # 4. Commit job to DB
                async with async_session_factory() as session:
                    session.add(outbox)
                    session.add(job)
                    await session.commit()

                # 5. Log successful commit
                logger.info(
                    "Job committed event_id=%s origin_service=%s timestamp=%s topic=%s",
                    event.event_id,
                    event.origin_service,
                    event.timestamp,
                    msg.topic,
                )

                # 6. Commit Kafka offset
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except IntegrityError:
                logger.warning(
                    "IntegrityError for event_id=%s, committing offset and releasing locks",
                    event.event_id,
                )
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except json.JSONDecodeError as e:
                logger.error("Failed to decode message JSON: %s", e)
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except Exception as e:
                logger.error("Error processing message: %s", e, exc_info=True)
                await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logger.info("Consumer task cancelled")
    finally:
        await consumer.stop()
        logger.info("Consumer stopped")


async def start_consumer() -> None:
    """Create and start the Kafka consumer."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_id,
        auto_offset_reset=settings.kafka_auto_offset_reset,
        enable_auto_commit=False,
        session_timeout_ms=30000,
        max_poll_interval_ms=300000,
        rebalance_timeout_ms=60000,
    )

    await consumer.start()
    consumer.subscribe(
        [settings.kafka_topic, settings.kafka_video_deleted_topic],
        listener=AppRebalanceListener(),
    )
    logger.info(
        "Kafka consumer started — topics=%s group=%s",
        [settings.kafka_topic, settings.kafka_video_deleted_topic],
        settings.kafka_consumer_group_id,
    )

    await consume_messages(consumer)
