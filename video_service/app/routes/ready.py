import logging

from fastapi import APIRouter, Response
from kombu import Connection
from sqlalchemy import text

from app.config import settings
from app.database import engine as db_engine
from app.lock import redis_client
from app.minio_client import client as minio_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ready")
async def ready(response: Response):
    """Check Redis, DB, MinIO, and RabbitMQ connectivity. Returns 200 if all are reachable, 500 otherwise."""
    redis_ok = False
    db_ok = False
    minio_ok = False
    rabbitmq_ok = False

    try:
        redis_client.ping()
        redis_ok = True
    except Exception as exc:
        logger.warning("Readiness check: Redis unreachable: %s", exc)

    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("Readiness check: DB unreachable: %s", exc)

    try:
        minio_client.bucket_exists(settings.minio_bucket)
        minio_ok = True
    except Exception as exc:
        logger.warning("Readiness check: MinIO unreachable: %s", exc)

    try:
        with Connection(settings.celery_broker_url) as conn:
            conn.connect()
        rabbitmq_ok = True
    except Exception as exc:
        logger.warning("Readiness check: RabbitMQ unreachable: %s", exc)

    if redis_ok and db_ok and minio_ok and rabbitmq_ok:
        return {"status": "ok", "redis": "ok", "db": "ok", "minio": "ok", "rabbitmq": "ok"}

    response.status_code = 500
    return {
        "status": "error",
        "redis": "ok" if redis_ok else "unreachable",
        "db": "ok" if db_ok else "unreachable",
        "minio": "ok" if minio_ok else "unreachable",
        "rabbitmq": "ok" if rabbitmq_ok else "unreachable",
    }
