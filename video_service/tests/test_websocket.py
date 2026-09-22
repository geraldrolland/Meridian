import asyncio
import hashlib
import hmac
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _sign_ws(path: str, timestamp: str, secret: str = "test-secret") -> str:
    payload = f"GET:{path}:{timestamp}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


# ── verify_proxy_signature ──────────────────────────────────────────

class TestVerifyProxySignature:
    @patch("app.websocket.settings")
    def test_valid_signature(self, mock_settings):
        mock_settings.jwt_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        ts = str(int(time.time() * 1000))
        sig = _sign_ws("/ws/video/notification", ts)
        assert verify_proxy_signature("/ws/video/notification", sig, ts) is True

    @patch("app.websocket.settings")
    def test_expired_timestamp(self, mock_settings):
        mock_settings.jwt_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        ts = str(int(time.time() * 1000) - 61_000)
        sig = _sign_ws("/ws/video/notification", ts)
        assert verify_proxy_signature("/ws/video/notification", sig, ts) is False

    @patch("app.websocket.settings")
    def test_invalid_signature(self, mock_settings):
        mock_settings.jwt_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        ts = str(int(time.time() * 1000))
        assert verify_proxy_signature("/ws/video/notification", "bad-sig", ts) is False

    @patch("app.websocket.settings")
    def test_non_numeric_timestamp(self, mock_settings):
        mock_settings.jwt_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        assert verify_proxy_signature("/ws/video/notification", "sig", "not-a-number") is False

    @patch("app.websocket.settings")
    def test_none_timestamp(self, mock_settings):
        mock_settings.jwt_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        assert verify_proxy_signature("/ws/video/notification", "sig", None) is False


# ── publish_update ──────────────────────────────────────────────────

class TestPublishUpdate:
    @pytest.mark.asyncio
    async def test_publishes_correct_json(self):
        from app.websocket import publish_update

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        with patch("app.websocket.get_redis", return_value=mock_redis):
            await publish_update("vid-1", "QUEUED", 42)

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "video:notification"
        payload = json.loads(call_args[0][1])
        assert payload["video_id"] == "vid-1"
        assert payload["status"] == "QUEUED"
        assert payload["user_id"] == 42


# ── ws_video_endpoint ───────────────────────────────────────────────

class TestWsVideoEndpoint:
    @pytest.mark.asyncio
    async def test_rejects_missing_proxy_signature(self):
        from app.websocket import ws_video_endpoint

        ws = AsyncMock()
        ws.headers = {}
        ws.close = AsyncMock()

        await ws_video_endpoint(ws, "123")

        ws.close.assert_called_once_with(code=4003, reason="Missing proxy signature")
        ws.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_invalid_proxy_signature(self):
        from app.websocket import ws_video_endpoint

        ws = AsyncMock()
        ws.headers = {"x-proxy-signature": "bad", "x-proxy-timestamp": str(int(time.time() * 1000))}
        ws.close = AsyncMock()

        with patch("app.websocket.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret"
            await ws_video_endpoint(ws, "123")

        ws.close.assert_called_once_with(code=4003, reason="Invalid proxy signature")
        ws.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_valid_connection(self):
        from app.websocket import ws_video_endpoint, connections

        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        sig = _sign_ws("/ws/video/notification", ts)
        ws.headers = {"x-proxy-signature": sig, "x-proxy-timestamp": ts}

        with patch("app.websocket.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret"
            task = asyncio.create_task(ws_video_endpoint(ws, "42"))
            await asyncio.sleep(0.05)

        ws.accept.assert_called_once()
        assert "42" in connections
        assert ws in connections["42"]

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        connections.pop("42", None)

    @pytest.mark.asyncio
    async def test_cleans_up_on_disconnect(self):
        from app.websocket import ws_video_endpoint, connections

        connections.pop("99", None)

        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        sig = _sign_ws("/ws/video/notification", ts)
        ws.headers = {"x-proxy-signature": sig, "x-proxy-timestamp": ts}

        with patch("app.websocket.settings") as mock_settings:
            mock_settings.jwt_secret = "test-secret"
            task = asyncio.create_task(ws_video_endpoint(ws, "99"))
            await asyncio.sleep(0.05)

        ws.accept.assert_called_once()
        assert "99" in connections
        assert ws in connections["99"]

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert ws not in connections.get("99", [])
        connections.pop("99", None)


# ── start_pubsub_listener ───────────────────────────────────────────

class TestStartPubsubListener:
    @pytest.mark.asyncio
    async def test_routes_message_to_connected_client(self):
        from app.websocket import start_pubsub_listener, connections

        connections.clear()

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock()
        connections["77"] = [mock_ws]

        payload_data = json.dumps({
            "video_id": "v-1",
            "status": "QUEUED",
            "filename": "test.mp4",
            "user_id": 77,
        })

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "message", "data": payload_data.encode()}
            raise asyncio.CancelledError()

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_pubsub.get_message = fake_get_message

        mock_redis = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("app.websocket.get_redis", return_value=mock_redis):
            try:
                await start_pubsub_listener()
            except asyncio.CancelledError:
                pass

        mock_ws.send_text.assert_called_once()
        sent_data = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_data["video_id"] == "v-1"
        assert sent_data["user_id"] == 77

        connections.pop("77", None)

    @pytest.mark.asyncio
    async def test_removes_stale_connection(self):
        from app.websocket import start_pubsub_listener, connections

        connections.clear()

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock(side_effect=Exception("connection closed"))
        connections["88"] = [mock_ws]

        payload_data = json.dumps({
            "video_id": "v-2",
            "status": "FAILED",
            "filename": "fail.mp4",
            "user_id": 88,
        })

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "message", "data": payload_data.encode()}
            raise asyncio.CancelledError()

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_pubsub.get_message = fake_get_message

        mock_redis = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("app.websocket.get_redis", return_value=mock_redis):
            try:
                await start_pubsub_listener()
            except asyncio.CancelledError:
                pass

        assert "88" not in connections

    @pytest.mark.asyncio
    async def test_skips_malformed_json(self):
        from app.websocket import start_pubsub_listener, connections

        connections.clear()

        call_count = 0

        async def fake_get_message(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "message", "data": b"not-json"}
            raise asyncio.CancelledError()

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_pubsub.get_message = fake_get_message

        mock_redis = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("app.websocket.get_redis", return_value=mock_redis):
            try:
                await start_pubsub_listener()
            except asyncio.CancelledError:
                pass

        assert len(connections) == 0
