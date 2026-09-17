import hmac
import hashlib
import time
import pytest
from unittest.mock import patch, MagicMock


def _sign(method: str, path: str, timestamp: str, secret: str = "test-secret") -> str:
    payload = f"{method}:{path}:{timestamp}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def mock_settings():
    with patch("app.middleware.check_proxy_signature.settings") as settings:
        settings.proxy_secret = "test-secret"
        yield settings


@pytest.fixture
def make_request():
    def _make(method="GET", path="/api/video/upload", headers=None):
        request = MagicMock()
        request.method = method
        request.url.path = path
        request.headers = headers or {}
        return request
    return _make


@pytest.mark.asyncio
async def test_valid_signature(mock_settings, make_request):
    from app.middleware.check_proxy_signature import check_proxy_signature

    ts = str(int(time.time() * 1000))
    sig = _sign("GET", "/api/video/upload", ts)
    request = make_request(headers={"x-proxy-signature": sig, "x-proxy-timestamp": ts})

    await check_proxy_signature(request)


@pytest.mark.asyncio
async def test_missing_headers(make_request):
    from app.middleware.check_proxy_signature import check_proxy_signature
    from fastapi import HTTPException

    request = make_request(headers={})

    with pytest.raises(HTTPException) as exc_info:
        await check_proxy_signature(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_expired_timestamp(mock_settings, make_request):
    from app.middleware.check_proxy_signature import check_proxy_signature
    from fastapi import HTTPException

    ts = str(int(time.time() * 1000) - 60_000)
    sig = _sign("GET", "/api/video/upload", ts)
    request = make_request(headers={"x-proxy-signature": sig, "x-proxy-timestamp": ts})

    with pytest.raises(HTTPException) as exc_info:
        await check_proxy_signature(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_invalid_signature(mock_settings, make_request):
    from app.middleware.check_proxy_signature import check_proxy_signature
    from fastapi import HTTPException

    ts = str(int(time.time() * 1000))
    request = make_request(headers={"x-proxy-signature": "bad-sig", "x-proxy-timestamp": ts})

    with pytest.raises(HTTPException) as exc_info:
        await check_proxy_signature(request)
    assert exc_info.value.status_code == 403
