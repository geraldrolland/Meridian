import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import async_session_factory
from app.models.events import MinIOEvent
from app.models.video import Video, VideoStatus
from app.utils.notification_utils import build_id, build_object_url, extract_video_id
from app.websocket import publish_update

from app.consumers.base import AppRebalanceListener

logger = logging.getLogger(__name__)


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
                    video_id = extract_video_id(event_dict)
                    if not video_id:
                        logger.warning(
                            "Could not extract video_id from event at offset %d",
                            msg.offset,
                        )
                        await consumer.commit(
                            {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                        )
                        continue

                    video = await session.get(Video, video_id)
                    if video is None:
                        logger.warning(
                            "Video %s not found for event at offset %d",
                            video_id,
                            msg.offset,
                        )
                        await consumer.commit(
                            {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                        )
                        continue

                    video.notif_reference_id = build_id(event_dict)
                    video.video_url = build_object_url(event_dict)
                    video.size = event_dict["Records"][0]["s3"]["object"]["size"]
                    video.status = VideoStatus.QUEUED.value
                    await session.commit()

                    if video.user_id is not None:
                        await publish_update(
                            video_id=video_id,
                            status=video.status,
                            user_id=video.user_id,
                        )

                logger.info(
                    "Processed video_id=%s topic=%s partition=%d offset=%d eventName=%s key=%s",
                    video_id,
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
                    "Duplicate event at offset %d, skipping",
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
