import hmac
import hashlib
import time
import logging

from fastapi import Request, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)

SIGNATURE_MAX_AGE_MS = 30_000  # 30 seconds


async def check_proxy_signature(request: Request) -> None:
    """FastAPI dependency that verifies HMAC-SHA256 proxy signatures from the API gateway.

    Every request forwarded by the gateway includes two headers:
    - ``x-proxy-signature``: HMAC-SHA256 of ``"{METHOD}:{URL}:{TIMESTAMP}"``
    - ``x-proxy-timestamp``: Unix epoch in milliseconds

    Verification steps:
    1. Check both headers are present
    2. Validate timestamp is a valid number
    3. Reject if timestamp is older than 30 seconds (replay protection)
    4. Recompute the HMAC and compare using ``hmac.compare_digest`` (constant-time)
    """
    signature = request.headers.get("x-proxy-signature")
    timestamp = request.headers.get("x-proxy-timestamp")

    if not signature or not timestamp:
        raise HTTPException(status_code=403, detail="Missing proxy signature")

    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid proxy timestamp")

    elapsed = int(time.time() * 1000) - ts
    if elapsed > SIGNATURE_MAX_AGE_MS:
        raise HTTPException(status_code=403, detail="Proxy signature expired")

    payload = f"{request.method}:{request.url.path}:{timestamp}"
    expected = hmac.new(
        settings.proxy_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid proxy signature")
