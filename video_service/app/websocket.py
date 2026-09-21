import asyncio
import hmac
import hashlib
import json
import logging
import time
from typing import Any

import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings

logger = logging.getLogger(__name__)

redis_client: redis.Redis | None = None
connections: dict[str, list[WebSocket]] = {}

PROXY_SIGNATURE_MAX_AGE_MS = 60_000


def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
        )
    return redis_client


def verify_proxy_signature(path: str, signature: str, timestamp_str: str) -> bool:
    try:
        ts = int(timestamp_str)
        age = int(time.time() * 1000) - ts
        if age > PROXY_SIGNATURE_MAX_AGE_MS or age < -PROXY_SIGNATURE_MAX_AGE_MS:
            return False
    except (ValueError, TypeError):
        return False

    payload = f"GET:{path}:{timestamp_str}"
    expected = hmac.new(
        settings.jwt_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def publish_update(video_id: str, status: str, user_id: int) -> None:
    r = get_redis()
    message = json.dumps({
        "video_id": video_id,
        "status": status,
        "user_id": user_id,
    })
    await r.publish("video:notification", message)


async def start_pubsub_listener() -> None:
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe("video:notification")
    logger.info("Shared pubsub listener started on video:notification")

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
        await pubsub.unsubscribe("video:notification")
        await pubsub.close()
        logger.info("Shared pubsub listener stopped")


async def ws_video_endpoint(websocket: WebSocket, user_id: str) -> None:
    proxy_sig = websocket.headers.get("x-proxy-signature")
    proxy_ts = websocket.headers.get("x-proxy-timestamp")

    if proxy_sig and proxy_ts:
        ws_path = f"/ws/video/{user_id}"
        if not verify_proxy_signature(ws_path, proxy_sig, proxy_ts):
            logger.warning("Invalid proxy signature for WS connection")
            await websocket.close(code=4003, reason="Invalid proxy signature")
            return
    else:
        await websocket.close(code=4003, reason="Missing proxy signature")
        logger.warning("No proxy signature on WS connection -- direct access not allowed")
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
