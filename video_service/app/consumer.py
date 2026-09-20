import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition, ConsumerRebalanceListener
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import async_session_factory
from app.models.events import MinIOEvent
from app.models.notification import BucketNotificationEvent

logger = logging.getLogger(__name__)


class AppRebalanceListener(ConsumerRebalanceListener):
    """Logs Kafka partition rebalance events for the video consumer group."""

    async def on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        logger.info("Partitions revoked: %s", revoked)

    async def on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        logger.info("Partitions assigned: %s", assigned)


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

                validated = MinIOEvent.model_validate(event_dict)

                async with async_session_factory() as session:
                    record = BucketNotificationEvent(event=event_dict)
                    record.id = record.build_id()
                    session.add(record)
                    await session.commit()
                    event_id = record.id

                logger.info(
                    "Stored event id=%s topic=%s partition=%d offset=%d eventName=%s key=%s",
                    event_id,
                    msg.topic,
                    msg.partition,
                    msg.offset,
                    validated.EventName,
                    validated.Key,
                )

                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except json.JSONDecodeError as e:
                logger.error("Failed to decode message JSON: %s", e)
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except IntegrityError:
                await session.rollback()
                logger.warning(
                    "Duplicate notification at offset %d, skipping",
                    msg.offset,
                )
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
    consumer.subscribe([settings.kafka_topic], listener=AppRebalanceListener())
    logger.info(
        "Kafka consumer started — topic=%s group=%s",
        settings.kafka_topic,
        settings.kafka_consumer_group_id,
    )

    await consume_messages(consumer)


async def consume_retry_messages(consumer: AIOKafkaConsumer) -> None:
    """Main retry consumer loop. Runs until cancelled."""
    try:
        async for msg in consumer:
            try:
                raw_value: bytes = msg.value
                if raw_value is None:
                    logger.warning("[retry] Received empty message at offset %d", msg.offset)
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                event_dict: dict[str, Any] = json.loads(raw_value.decode("utf-8"))
                video_id = event_dict.get("video_id")

                if not video_id:
                    logger.warning("[retry] Missing video_id in retry event, skipping")
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                async with async_session_factory() as session:
                    from app.models.video import Video, VideoStatus

                    video = await session.get(Video, video_id)
                    if video and video.status == VideoStatus.FAILED.value:
                        video.status = VideoStatus.QUEUED.value
                        await session.commit()

                        from app.models.outbox import Outbox

                        outbox = Outbox(
                            topic="video.queued",
                            payload={
                                "event_id": video_id,
                                "origin_service": "video-service",
                                "video_id": video_id,
                                "object_url": video.video_url,
                            },
                        )
                        session.add(outbox)
                        await session.commit()

                        logger.info(
                            "[retry] Re-queued video %s for retry", video_id
                        )
                    else:
                        logger.info(
                            "[retry] Video %s not found or not FAILED, skipping",
                            video_id,
                        )

                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except json.JSONDecodeError as e:
                logger.error("[retry] Failed to decode message JSON: %s", e)
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except Exception as e:
                logger.error("[retry] Error processing message: %s", e, exc_info=True)
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("[retry] Consumer task cancelled")
    finally:
        await consumer.stop()
        logger.info("[retry] Consumer stopped")


async def start_retry_consumer() -> None:
    """Create and start the Kafka retry consumer."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_retry_consumer_group_id,
        auto_offset_reset=settings.kafka_auto_offset_reset,
        enable_auto_commit=False,
        session_timeout_ms=30000,
        max_poll_interval_ms=300000,
        rebalance_timeout_ms=60000,
    )

    await consumer.start()
    consumer.subscribe([settings.kafka_retry_topic], listener=AppRebalanceListener())
    logger.info(
        "Kafka retry consumer started — topic=%s group=%s",
        settings.kafka_retry_topic,
        settings.kafka_retry_consumer_group_id,
    )

    await consume_retry_messages(consumer)
