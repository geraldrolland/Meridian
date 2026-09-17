import logging

import redis

from app.config import settings

logger = logging.getLogger(__name__)

redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=2,
    decode_responses=True,
)

LOCK_TTL = 120  # 2 minutes
LOCK_BLOCKING_TIMEOUT = 5  # seconds


def acquire_lock(entity_id: str, prefix: str = "notification") -> redis.lock.Lock | None:
    """Acquire a distributed lock for an entity.

    Returns the lock object if acquired, None if already locked by another worker.
    """
    lock = redis_client.lock(
        name=f"{prefix}:{entity_id}",
        timeout=LOCK_TTL,
        blocking_timeout=LOCK_BLOCKING_TIMEOUT,
    )
    acquired = lock.acquire(blocking=True)
    if acquired:
        return lock
    return None


def release_lock(lock: redis.lock.Lock) -> None:
    """Release a distributed lock."""
    try:
        lock.release()
    except redis.exceptions.LockNotOwnedError:
        logger.warning("Lock already expired or released")
