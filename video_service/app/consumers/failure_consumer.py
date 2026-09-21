import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition

from app.config import settings
from app.database import async_session_factory

from app.consumers.base import AppRebalanceListener

logger = logging.getLogger(__name__)

TOPICS = [settings.kafka_job_failed_topic, settings.kafka_manifest_failed_topic]


async def consume_failure_messages(consumer: AIOKafkaConsumer) -> None:
    """Failure consumer loop. Consumes job.failed and manifest.failed events."""
    try:
        async for msg in consumer:
            try:
                raw_value: bytes = msg.value
                if raw_value is None:
                    logger.warning("[failure] Received empty message at offset %d", msg.offset)
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                event_dict: dict[str, Any] = json.loads(raw_value.decode("utf-8"))
                video_id = event_dict.get("video_id")

                if not video_id:
                    logger.warning("[failure] Missing video_id in event, skipping")
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                async with async_session_factory() as session:
                    from app.models.video import Video, VideoStatus

                    video = await session.get(Video, video_id)
                    if video is None:
                        logger.info(
                            "[failure] Video %s not found, skipping",
                            video_id,
                        )
                    elif video.num_of_retries + 1 > settings.video_max_retry:
                        video.status = VideoStatus.FAILED.value
                        await session.commit()
                        logger.info(
                            "[failure] Video %s set to FAILED (num_of_retries=%d)",
                            video_id,
                            video.num_of_retries,
                        )
                    else:
                        video.status = VideoStatus.RETRY.value
                        await session.commit()
                        logger.info(
                            "[failure] Video %s set to RETRY (num_of_retries=%d)",
                            video_id,
                            video.num_of_retries,
                        )

                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except json.JSONDecodeError as e:
                logger.error("[failure] Failed to decode message JSON: %s", e)
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except Exception as e:
                logger.error("[failure] Error processing message: %s", e, exc_info=True)
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("[failure] Consumer task cancelled")
    finally:
        await consumer.stop()
        logger.info("[failure] Consumer stopped")


async def start_failure_consumer() -> None:
    """Create and start the Kafka failure consumer."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_failure_consumer_group_id,
        auto_offset_reset=settings.kafka_auto_offset_reset,
        enable_auto_commit=False,
        session_timeout_ms=30000,
        max_poll_interval_ms=300000,
        rebalance_timeout_ms=60000,
    )

    await consumer.start()
    consumer.subscribe(TOPICS, listener=AppRebalanceListener())
    logger.info(
        "Kafka failure consumer started — topics=%s group=%s",
        TOPICS,
        settings.kafka_failure_consumer_group_id,
    )

    await consume_failure_messages(consumer)
