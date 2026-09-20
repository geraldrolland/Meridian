import asyncio
import json
import logging

import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer, TopicPartition

from app.config import settings
from app.database import async_session_factory
from app.models import DashboardVideo, VideoStatus, DLQEvent

logger = logging.getLogger(__name__)

redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
        )
    return redis_client


async def publish_update(video_id: str, status: str, filename: str, user_id: int) -> None:
    r = get_redis()
    message = json.dumps({
        "video_id": video_id,
        "status": status,
        "filename": filename,
        "user_id": user_id,
    })
    await r.publish("dashboard:notification", message)


async def consume_dlq(consumer: AIOKafkaConsumer) -> None:
    try:
        async for msg in consumer:
            try:
                raw_value: bytes = msg.value
                if raw_value is None:
                    await consumer.commit(
                        {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                    )
                    continue

                event_dict = json.loads(raw_value.decode("utf-8"))
                event = DLQEvent.model_validate(event_dict)

                async with async_session_factory() as session:
                    from sqlmodel import select

                    existing = (
                        await session.execute(
                            select(DashboardVideo).where(
                                DashboardVideo.id == event.video_id
                            )
                        )
                    ).scalar_one_or_none()

                    if existing is None:
                        record = DashboardVideo(
                            id=event.video_id,
                            user_id=event.user_id,
                            filename=event.filename,
                            status=VideoStatus.FAILED.value,
                            reason=event.reason,
                            retry_count=0,
                        )
                        session.add(record)
                    else:
                        existing.status = VideoStatus.FAILED.value
                        existing.reason = event.reason

                    await session.commit()

                await publish_update(
                    event.video_id,
                    VideoStatus.FAILED.value,
                    event.filename,
                    event.user_id,
                )

                retry_payload = json.dumps(event_dict).encode("utf-8")
                await consumer.send(settings.kafka_retry_topic, retry_payload)
                logger.info(
                    "[dlq] Processed video %s, sent retry to %s",
                    event.video_id,
                    settings.kafka_retry_topic,
                )

                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except json.JSONDecodeError as e:
                logger.error("[dlq] Failed to decode message JSON: %s", e)
                await consumer.commit(
                    {TopicPartition(msg.topic, msg.partition): msg.offset + 1}
                )

            except Exception as e:
                logger.error("[dlq] Error processing message: %s", e, exc_info=True)
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("[dlq] Consumer task cancelled")
    finally:
        await consumer.stop()
        logger.info("[dlq] Consumer stopped")


async def start_dlq_consumer() -> None:
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
    consumer.subscribe([settings.kafka_dlq_topic])
    logger.info(
        "Dashboard DLQ consumer started — topic=%s group=%s",
        settings.kafka_dlq_topic,
        settings.kafka_consumer_group_id,
    )

    await consume_dlq(consumer)
