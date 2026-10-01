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


def _text_frame(text: str) -> dict:
    """ASGI frame for an inbound text message (what receive() yields)."""
    return {"type": "websocket.receive", "text": text}


_disconnect_frame = {"type": "websocket.disconnect", "code": 1000}


async def _block_forever():
    """Stand-in for receive() on an idle connection."""
    await asyncio.Event().wait()
    return _disconnect_frame


def _connected_ws() -> AsyncMock:
    ws = AsyncMock()
    ts = str(int(time.time() * 1000))
    ws.headers = {"x-proxy-signature": _sign_ws("/ws/video/notification", ts), "x-proxy-timestamp": ts}
    ws.receive = _block_forever
    return ws


# ── verify_proxy_signature ──────────────────────────────────────────

class TestVerifyProxySignature:
    @patch("app.websocket.settings")
    def test_valid_signature(self, mock_settings):
        mock_settings.proxy_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        ts = str(int(time.time() * 1000))
        sig = _sign_ws("/ws/video/notification", ts)
        assert verify_proxy_signature("/ws/video/notification", sig, ts) is True

    @patch("app.websocket.settings")
    def test_expired_timestamp(self, mock_settings):
        mock_settings.proxy_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        ts = str(int(time.time() * 1000) - 61_000)
        sig = _sign_ws("/ws/video/notification", ts)
        assert verify_proxy_signature("/ws/video/notification", sig, ts) is False

    @patch("app.websocket.settings")
    def test_invalid_signature(self, mock_settings):
        mock_settings.proxy_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        ts = str(int(time.time() * 1000))
        assert verify_proxy_signature("/ws/video/notification", "bad-sig", ts) is False

    @patch("app.websocket.settings")
    def test_non_numeric_timestamp(self, mock_settings):
        mock_settings.proxy_secret = "test-secret"
        from app.websocket import verify_proxy_signature

        assert verify_proxy_signature("/ws/video/notification", "sig", "not-a-number") is False

    @patch("app.websocket.settings")
    def test_none_timestamp(self, mock_settings):
        mock_settings.proxy_secret = "test-secret"
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
        assert payload["thumbnail_url"] is None
        assert payload["manifest_url"] is None

    @pytest.mark.asyncio
    async def test_publishes_thumbnail_and_manifest_urls(self):
        from app.websocket import publish_update

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        with patch("app.websocket.get_redis", return_value=mock_redis):
            await publish_update(
                "vid-1",
                "COMPLETED",
                42,
                thumbnail_url="http://minio:9000/vidthumbnails/vid1/thumb.jpg",
                manifest_url="http://minio:9000/manifest/vid1/manifest.mpd",
            )

        payload = json.loads(mock_redis.publish.call_args[0][1])
        assert payload["thumbnail_url"] == "http://minio:9000/vidthumbnails/vid1/thumb.jpg"
        assert payload["manifest_url"] == "http://minio:9000/manifest/vid1/manifest.mpd"


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
            mock_settings.proxy_secret = "test-secret"
            await ws_video_endpoint(ws, "123")

        ws.close.assert_called_once_with(code=4003, reason="Invalid proxy signature")
        ws.accept.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_valid_connection(self):
        from app.websocket import ws_video_endpoint, connections

        ws = _connected_ws()

        with patch("app.websocket.settings") as mock_settings:
            mock_settings.proxy_secret = "test-secret"
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

        ws = _connected_ws()

        with patch("app.websocket.settings") as mock_settings:
            mock_settings.proxy_secret = "test-secret"
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


# ── segment report dispatch ─────────────────────────────────────────

class TestSegmentReportDispatch:
    @staticmethod
    async def _run(ws: AsyncMock, user_id: str) -> None:
        from app.websocket import ws_video_endpoint

        with patch("app.websocket.settings") as mock_settings:
            mock_settings.proxy_secret = "test-secret"
            await ws_video_endpoint(ws, user_id)

    @pytest.mark.asyncio
    async def test_sends_recommendation_for_segment_report(self):
        from app.websocket import connections

        report = {
            "type": "segment_report",
            "video_id": "v-9",
            "seq": 7,
            "bandwidth": 5_000_000,
            "latency": 0.05,
            "seg_download_time": 1.4,
            "current_buffer_duration": 20.0,
            "current_rendition": "480p",
        }
        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        ws.headers = {"x-proxy-signature": _sign_ws("/ws/video/notification", ts), "x-proxy-timestamp": ts}
        ws.receive = AsyncMock(
            side_effect=[_text_frame(json.dumps(report)), _disconnect_frame]
        )

        await self._run(ws, "55")

        assert ws.receive.call_count == 2
        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "abr_recommendation"
        assert sent["video_id"] == "v-9"
        assert sent["seq"] == 7
        assert sent["current_rendition"] == "480p"
        # safe bandwidth 3.75 Mbps with 20s buffer -> one step up to 720p
        assert sent["recommended_rendition"] == "720p"
        assert sent["reason"] == "headroom"
        assert ws not in connections.get("55", [])

    @pytest.mark.asyncio
    async def test_ignores_non_json_message(self):
        from app.websocket import ws_video_endpoint

        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        ws.headers = {"x-proxy-signature": _sign_ws("/ws/video/notification", ts), "x-proxy-timestamp": ts}
        ws.receive = AsyncMock(side_effect=[_text_frame("not-json"), _disconnect_frame])

        await self._run(ws, "56")

        assert ws.receive.call_count == 2
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_unknown_message_type(self):
        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        ws.headers = {"x-proxy-signature": _sign_ws("/ws/video/notification", ts), "x-proxy-timestamp": ts}
        ws.receive = AsyncMock(
            side_effect=[_text_frame(json.dumps({"type": "something_else"})), _disconnect_frame]
        )

        await self._run(ws, "57")

        assert ws.receive.call_count == 2
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_invalid_segment_report(self):
        invalid = {
            "type": "segment_report",
            "video_id": "v-1",
            "seq": -1,
            "bandwidth": 5_000_000,
            "latency": 0.05,
            "seg_download_time": 1.4,
            "current_buffer_duration": 20.0,
            "current_rendition": "480p",
        }
        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        ws.headers = {"x-proxy-signature": _sign_ws("/ws/video/notification", ts), "x-proxy-timestamp": ts}
        ws.receive = AsyncMock(side_effect=[_text_frame(json.dumps(invalid)), _disconnect_frame])

        await self._run(ws, "58")

        assert ws.receive.call_count == 2
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_binary_frame(self):
        """A proxy that re-frames text as binary must not kill the reply loop."""
        report = {
            "type": "segment_report",
            "video_id": "v-9",
            "seq": 7,
            "bandwidth": 5_000_000,
            "latency": 0.05,
            "seg_download_time": 1.4,
            "current_buffer_duration": 20.0,
            "current_rendition": "480p",
        }
        ws = AsyncMock()
        ts = str(int(time.time() * 1000))
        ws.headers = {"x-proxy-signature": _sign_ws("/ws/video/notification", ts), "x-proxy-timestamp": ts}
        ws.receive = AsyncMock(
            side_effect=[
                {"type": "websocket.receive", "bytes": json.dumps(report).encode()},
                _disconnect_frame,
            ]
        )

        await self._run(ws, "59")

        assert ws.receive.call_count == 2
        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "abr_recommendation"
        assert sent["recommended_rendition"] == "720p"

    @pytest.mark.asyncio
    async def test_safe_send_wraps_send_text(self):
        from app.websocket import safe_send, send_locks

        ws = AsyncMock()
        try:
            await safe_send(ws, "hello")
            ws.send_text.assert_called_once_with("hello")
        finally:
            send_locks.pop(id(ws), None)


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
