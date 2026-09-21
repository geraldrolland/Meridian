import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition

from app.config import settings
from app.database import async_session_factory
from app.websocket import publish_update

from app.consumers.base import AppRebalanceListener

logger = logging.getLogger(__name__)


async def consume_manifest_generating_messages(consumer: AIOKafkaConsumer) -> None:
    """Manifest generating consumer loop. Consumes manifest.generating events."""
    try:
        async for msg in consumer:
            try:
                raw_value: bytes = msg.value
                if raw_value is None:
                    logger.warning("[manifest-generating] Received empty message at offset %d", msg.offset)
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                event_dict: dict[str, Any] = json.loads(raw_value.decode("utf-8"))
                video_id = event_dict.get("video_id")

                if not video_id:
                    logger.warning("[manifest-generating] Missing video_id in event, skipping")
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                async with async_session_factory() as session:
                    from app.models.video import Video, VideoStatus

                    video = await session.get(Video, video_id)
                    if video is None:
                        logger.info(
                            "[manifest-generating] Video %s not found, skipping",
                            video_id,
                        )
                    else:
                        video.status = VideoStatus.GENERATING_MANIFEST.value
                        await session.commit()
                        logger.info(
                            "[manifest-generating] Video %s status set to GENERATING_MANIFEST",
                            video_id,
                        )

                        if video.user_id is not None:
                            await publish_update(
                                video_id=video_id,
                                status=VideoStatus.GENERATING_MANIFEST.value,
                                user_id=video.user_id,
                            )

                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except json.JSONDecodeError as e:
                logger.error("[manifest-generating] Failed to decode message JSON: %s", e)
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except Exception as e:
                logger.error("[manifest-generating] Error processing message: %s", e, exc_info=True)
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("[manifest-generating] Consumer task cancelled")
    finally:
        await consumer.stop()
        logger.info("[manifest-generating] Consumer stopped")


async def start_manifest_generating_consumer() -> None:
    """Create and start the Kafka manifest generating consumer."""
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_manifest_generating_consumer_group_id,
        auto_offset_reset=settings.kafka_auto_offset_reset,
        enable_auto_commit=False,
        session_timeout_ms=30000,
        max_poll_interval_ms=300000,
        rebalance_timeout_ms=60000,
    )

    await consumer.start()
    consumer.subscribe([settings.kafka_manifest_generating_topic], listener=AppRebalanceListener())
    logger.info(
        "Kafka manifest generating consumer started — topic=%s group=%s",
        settings.kafka_manifest_generating_topic,
        settings.kafka_manifest_generating_consumer_group_id,
    )

    await consume_manifest_generating_messages(consumer)
