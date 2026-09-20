import asyncio
import hmac
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlmodel import select

from app.config import settings
from app.database import async_session_factory
from app.models import DashboardVideo, RetryRequest
from app.consumer import get_redis, publish_update

logger = logging.getLogger(__name__)

router = APIRouter()

PROXY_SIGNATURE_MAX_AGE_MS = 60_000

connections: dict[str, list[WebSocket]] = {}
_pubsub_task: asyncio.Task | None = None


def _verify_proxy_signature(path: str, signature: str, timestamp_str: str) -> bool:
    try:
        ts = int(timestamp_str)
        age = int(time.time() * 1000) - ts
        if age > PROXY_SIGNATURE_MAX_AGE_MS or age < -PROXY_SIGNATURE_MAX_AGE_MS:
            return False
    except (ValueError, TypeError):
        return False

    payload = f"GET:{path}:{timestamp_str}"
    expected = hmac.new(
        settings.proxy_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def start_pubsub_listener() -> None:
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe("dashboard:notification")
    logger.info("Shared pubsub listener started on dashboard:notification")

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                data = message["data"].decode("utf-8")
                try:
                    payload = json.loads(data)
                    user_id = str(payload.get("user_id", ""))
                except json.JSONDecodeError:
                    logger.warning("Failed to parse pubsub message")
                    continue

                sockets = connections.get(user_id, [])
                stale: list[WebSocket] = []
                for ws in sockets:
                    try:
                        await ws.send_text(data)
                    except Exception:
                        stale.append(ws)

                for ws in stale:
                    sockets.remove(ws)

                if not sockets:
                    connections.pop(user_id, None)
            else:
                await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        logger.info("Shared pubsub listener cancelled")
    finally:
        await pubsub.unsubscribe("dashboard:notification")
        await pubsub.close()
        logger.info("Shared pubsub listener stopped")


@router.get("/api/dashboard/videos")
async def list_dlq_videos(user_id: int = Query(...)):
    async with async_session_factory() as session:
        result = await session.execute(
            select(DashboardVideo)
            .where(DashboardVideo.user_id == user_id)
            .order_by(DashboardVideo.created_at.desc())
        )
        videos = result.scalars().all()
        return [
            {
                "video_id": v.id,
                "user_id": v.user_id,
                "filename": v.filename,
                "status": v.status,
                "reason": v.reason,
                "retry_count": v.retry_count,
                "last_retry_at": v.last_retry_at.isoformat() if v.last_retry_at else None,
                "final_status": v.final_status,
                "created_at": v.created_at.isoformat(),
                "updated_at": v.updated_at.isoformat(),
            }
            for v in videos
        ]


@router.post("/api/dashboard/videos/{video_id}/retry")
async def retry_video(video_id: str):
    async with async_session_factory() as session:
        result = await session.execute(
            select(DashboardVideo).where(DashboardVideo.id == video_id)
        )
        video = result.scalar_one_or_none()
        if video is None:
            return {"error": "not_found"}

        video.retry_count += 1
        video.last_retry_at = datetime.now(timezone.utc).replace(tzinfo=None)
        video.status = "RETRYING"
        await session.commit()

        retry_payload = {
            "video_id": video.id,
            "user_id": video.user_id,
            "filename": video.filename,
            "reason": video.reason or "retry_requested",
        }

        from kafka import KafkaProducer

        producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        producer.send(settings.kafka_retry_topic, retry_payload)
        producer.flush()
        producer.close()

        await publish_update(video.id, "RETRYING", video.filename, video.user_id)

        return {"status": "retrying", "video_id": video_id}


@router.websocket("/ws/dashboard/{user_id}")
async def dashboard_ws(websocket: WebSocket, user_id: str):
    proxy_sig = websocket.headers.get("x-proxy-signature")
    proxy_ts = websocket.headers.get("x-proxy-timestamp")

    if proxy_sig and proxy_ts:
        ws_path = f"/ws/dashboard/{user_id}"
        if not _verify_proxy_signature(ws_path, proxy_sig, proxy_ts):
            logger.warning("Invalid proxy signature for WS connection")
            await websocket.close(code=4003, reason="Invalid proxy signature")
            return
    else:
        await websocket.close(code=4003, reason="Missing proxy signature")
        logger.warning("No proxy signature on WS connection — direct access not allowed")
        return

    await websocket.accept()

    connections.setdefault(user_id, []).append(websocket)
    logger.info("WS connected for user %s (total: %d)", user_id, len(connections[user_id]))

    try:
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        logger.info("WS disconnected for user %s", user_id)
    except Exception as e:
        logger.error("WS error for user %s: %s", user_id, e)
    finally:
        sockets = connections.get(user_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            connections.pop(user_id, None)
        logger.info("WS cleaned up for user %s", user_id)
