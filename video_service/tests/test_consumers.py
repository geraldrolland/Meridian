"""Tests for app.consumers -- all 5 Kafka consumers."""

import asyncio
import json
import sys
from unittest.mock import patch, MagicMock, AsyncMock

from sqlalchemy.exc import IntegrityError

sys.modules.setdefault("asyncpg", MagicMock())
sys.modules.setdefault("aiokafka", MagicMock())

if "redis.asyncio" not in sys.modules:
    try:
        import redis.asyncio  # noqa: F401
    except Exception:
        _redis_mod = MagicMock()
        _redis_asyncio = MagicMock()
        _redis_mod.asyncio = _redis_asyncio
        sys.modules["redis"] = _redis_mod
        sys.modules["redis.asyncio"] = _redis_asyncio


class _FakeMsg:
    def __init__(self, value, topic="bucketnotifications", partition=0, offset=0):
        self.value = value
        self.topic = topic
        self.partition = partition
        self.offset = offset


class _FakeConsumer:
    def __init__(self, messages, topic="bucketnotifications"):
        self._messages = list(messages)
        self.commit = AsyncMock()
        self.stop = AsyncMock()
        for m in self._messages:
            if m.topic is None:
                m.topic = topic

    def __aiter__(self):
        self._iter = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise asyncio.CancelledError


class _AsyncSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_session():
    session = MagicMock()
    session.get = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


def _factory(session):
    def _f():
        return _AsyncSessionCM(session)
    return _f


def _minio_event(key="videos/vid1/file.mp4", size=1024):
    return {
        "EventName": "s3:ObjectCreated:Put",
        "Key": key,
        "Records": [
            {
                "eventVersion": "2.0",
                "eventSource": "minio:s3",
                "awsRegion": "us-east-1",
                "eventTime": "2024-01-01T00:00:00.000Z",
                "eventName": "ObjectCreated:Put",
                "userIdentity": {"principalId": "minio"},
                "requestParameters": {
                    "accessKey": "minioadmin",
                    "region": "",
                    "sourceIPAddress": "127.0.0.1",
                },
                "responseElements": {
                    "x-amz-request-id": "REQ1",
                    "x-amz-id-2": "ID2",
                    "x-minio-origin-endpoint": "http://minio:9000",
                    "x-minio-deployment-id": "DEP1",
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "Config",
                    "bucket": {
                        "name": "viduploads",
                        "ownerIdentity": {"principalId": "minio"},
                        "arn": "arn:aws:s3:::viduploads",
                    },
                    "object": {
                        "key": key,
                        "size": size,
                        "eTag": "d41d8cd98f00b204e9800998ecf8427e",
                    },
                },
            }
        ],
    }


def _make_video(status="QUEUED", user_id=1, num_of_retries=0):
    video = MagicMock()
    video.status = status
    video.user_id = user_id
    video.num_of_retries = num_of_retries
    video.notif_reference_id = None
    video.video_url = None
    video.manifest_url = None
    video.size = None
    return video


async def _run_notification(consumer):
    from app.consumers.notification_consumer import consume_messages
    await consume_messages(consumer)


async def _run_processing(consumer):
    from app.consumers.processing_consumer import consume_processing_messages
    await consume_processing_messages(consumer)


async def _run_generating(consumer):
    from app.consumers.manifest_generating_consumer import consume_manifest_generating_messages
    await consume_manifest_generating_messages(consumer)


async def _run_completed(consumer):
    from app.consumers.manifest_completed_consumer import consume_manifest_completed_messages
    await consume_manifest_completed_messages(consumer)


async def _run_failure(consumer):
    from app.consumers.failure_consumer import consume_failure_messages
    await consume_failure_messages(consumer)


# ---------------------------------------------------------------------------
# TestNotificationConsumer
# ---------------------------------------------------------------------------

class TestNotificationConsumer:

    def test_null_value_commits(self):
        consumer = _FakeConsumer([_FakeMsg(None)])
        asyncio.run(_run_notification(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_invalid_video_key_commits(self):
        event = _minio_event(key="other/file.mp4")
        consumer = _FakeConsumer([_FakeMsg(json.dumps(event).encode())])
        session = _make_session()
        with patch(
            "app.consumers.notification_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_notification(consumer))
        session.get.assert_not_called()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_video_not_found_commits(self):
        event = _minio_event()
        consumer = _FakeConsumer([_FakeMsg(json.dumps(event).encode())])
        session = _make_session()
        session.get.return_value = None
        with patch(
            "app.consumers.notification_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_notification(consumer))
        session.get.assert_awaited_once()
        session.commit.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_happy_path_updates_video_and_publishes(self):
        event = _minio_event(key="videos/vid1/file.mp4", size=2048)
        consumer = _FakeConsumer([_FakeMsg(json.dumps(event).encode())])
        session = _make_session()
        video = _make_video(status="AWAITING_UPLOAD", user_id=7)
        session.get.return_value = video

        with patch(
            "app.consumers.notification_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.notification_consumer.publish_update", new=AsyncMock()
        ) as mock_publish:
            asyncio.run(_run_notification(consumer))

        assert video.status == "QUEUED"
        assert video.size == 2048
        assert video.video_url is not None
        assert video.notif_reference_id is not None
        session.commit.assert_awaited_once()
        mock_publish.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_no_publish_when_user_id_none(self):
        event = _minio_event()
        consumer = _FakeConsumer([_FakeMsg(json.dumps(event).encode())])
        session = _make_session()
        video = _make_video(user_id=None)
        session.get.return_value = video

        with patch(
            "app.consumers.notification_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.notification_consumer.publish_update", new=AsyncMock()
        ) as mock_publish:
            asyncio.run(_run_notification(consumer))

        session.commit.assert_awaited_once()
        mock_publish.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_json_decode_error_commits(self):
        consumer = _FakeConsumer([_FakeMsg(b"not-json{")])
        asyncio.run(_run_notification(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_integrity_error_rolls_back_and_commits(self):
        event = _minio_event()
        consumer = _FakeConsumer([_FakeMsg(json.dumps(event).encode())])
        session = _make_session()
        video = _make_video()
        session.get.return_value = video
        session.commit = AsyncMock(
            side_effect=IntegrityError("UPDATE", {}, Exception("dup"))
        )

        with patch(
            "app.consumers.notification_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_notification(consumer))

        session.rollback.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_generic_error_sleeps_without_commit(self):
        event = _minio_event()
        consumer = _FakeConsumer([_FakeMsg(json.dumps(event).encode())])
        session = _make_session()
        session.get = AsyncMock(side_effect=Exception("db down"))

        with patch(
            "app.consumers.notification_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(_run_notification(consumer))

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_cancelled_stops_consumer(self):
        consumer = _FakeConsumer([])
        asyncio.run(_run_notification(consumer))
        consumer.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestProcessingConsumer
# ---------------------------------------------------------------------------

class TestProcessingConsumer:

    def test_null_value_commits(self):
        consumer = _FakeConsumer([_FakeMsg(None)], topic="video.processing")
        asyncio.run(_run_processing(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_missing_video_id_commits(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"event_id": "e1"}).encode())],
            topic="video.processing",
        )
        with patch("app.consumers.processing_consumer.async_session_factory") as mock_factory:
            asyncio.run(_run_processing(consumer))
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()

    def test_video_not_queued_skips_status_change(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="video.processing",
        )
        session = _make_session()
        video = _make_video(status="COMPLETED")
        session.get.return_value = video

        with patch(
            "app.consumers.processing_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.processing_consumer.publish_update", new=AsyncMock()
        ) as mock_publish:
            asyncio.run(_run_processing(consumer))

        assert video.status == "COMPLETED"
        session.commit.assert_not_awaited()
        mock_publish.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_happy_path_sets_processing(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="video.processing",
        )
        session = _make_session()
        video = _make_video(status="QUEUED", user_id=3)
        session.get.return_value = video

        with patch(
            "app.consumers.processing_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.processing_consumer.publish_update", new=AsyncMock()
        ) as mock_publish:
            asyncio.run(_run_processing(consumer))

        assert video.status == "PROCESSING"
        session.commit.assert_awaited_once()
        mock_publish.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_video_not_found_still_commits_offset(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "missing"}).encode())],
            topic="video.processing",
        )
        session = _make_session()
        session.get.return_value = None

        with patch(
            "app.consumers.processing_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_processing(consumer))

        session.commit.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_json_decode_error_commits(self):
        consumer = _FakeConsumer([_FakeMsg(b"nope")], topic="video.processing")
        asyncio.run(_run_processing(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_generic_error_sleeps_without_commit(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="video.processing",
        )
        session = _make_session()
        session.get = AsyncMock(side_effect=Exception("db down"))

        with patch(
            "app.consumers.processing_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(_run_processing(consumer))

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_cancelled_stops_consumer(self):
        consumer = _FakeConsumer([], topic="video.processing")
        asyncio.run(_run_processing(consumer))
        consumer.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestManifestGeneratingConsumer
# ---------------------------------------------------------------------------

class TestManifestGeneratingConsumer:

    def test_null_value_commits(self):
        consumer = _FakeConsumer([_FakeMsg(None)], topic="manifest.generating")
        asyncio.run(_run_generating(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_missing_video_id_commits(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({}).encode())],
            topic="manifest.generating",
        )
        with patch(
            "app.consumers.manifest_generating_consumer.async_session_factory"
        ) as mock_factory:
            asyncio.run(_run_generating(consumer))
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()

    def test_happy_path_sets_generating_manifest(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="manifest.generating",
        )
        session = _make_session()
        video = _make_video(status="PROCESSING", user_id=5)
        session.get.return_value = video

        with patch(
            "app.consumers.manifest_generating_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.manifest_generating_consumer.publish_update", new=AsyncMock()
        ) as mock_publish:
            asyncio.run(_run_generating(consumer))

        assert video.status == "GENERATING_MANIFEST"
        session.commit.assert_awaited_once()
        mock_publish.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_video_not_found_commits_without_update(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "missing"}).encode())],
            topic="manifest.generating",
        )
        session = _make_session()
        session.get.return_value = None

        with patch(
            "app.consumers.manifest_generating_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_generating(consumer))

        session.commit.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_json_decode_error_commits(self):
        consumer = _FakeConsumer([_FakeMsg(b"bad")], topic="manifest.generating")
        asyncio.run(_run_generating(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_generic_error_sleeps_without_commit(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="manifest.generating",
        )
        session = _make_session()
        session.get = AsyncMock(side_effect=Exception("db down"))

        with patch(
            "app.consumers.manifest_generating_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(_run_generating(consumer))

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_cancelled_stops_consumer(self):
        consumer = _FakeConsumer([], topic="manifest.generating")
        asyncio.run(_run_generating(consumer))
        consumer.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestManifestCompletedConsumer
# ---------------------------------------------------------------------------

class TestManifestCompletedConsumer:

    def test_null_value_commits(self):
        consumer = _FakeConsumer([_FakeMsg(None)], topic="manifest.completed")
        asyncio.run(_run_completed(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_missing_video_id_commits(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({}).encode())],
            topic="manifest.completed",
        )
        with patch(
            "app.consumers.manifest_completed_consumer.async_session_factory"
        ) as mock_factory:
            asyncio.run(_run_completed(consumer))
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()

    def test_happy_path_sets_completed(self):
        manifest_url = "http://minio:9000/manifest/vid1/manifest_abc12345.mpd"
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({
                "video_id": "vid1",
                "manifest_url": manifest_url,
            }).encode())],
            topic="manifest.completed",
        )
        session = _make_session()
        video = _make_video(status="GENERATING_MANIFEST", user_id=9)
        video.manifest_url = None
        session.get.return_value = video

        with patch(
            "app.consumers.manifest_completed_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.manifest_completed_consumer.publish_update", new=AsyncMock()
        ) as mock_publish:
            asyncio.run(_run_completed(consumer))

        assert video.status == "COMPLETED"
        assert video.manifest_url == manifest_url
        session.commit.assert_awaited_once()
        mock_publish.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_happy_path_without_manifest_url(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="manifest.completed",
        )
        session = _make_session()
        video = _make_video(status="GENERATING_MANIFEST", user_id=9)
        video.manifest_url = None
        session.get.return_value = video

        with patch(
            "app.consumers.manifest_completed_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.manifest_completed_consumer.publish_update", new=AsyncMock()
        ):
            asyncio.run(_run_completed(consumer))

        assert video.status == "COMPLETED"
        assert video.manifest_url is None
        session.commit.assert_awaited_once()

    def test_video_not_found_commits_without_update(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "missing"}).encode())],
            topic="manifest.completed",
        )
        session = _make_session()
        session.get.return_value = None

        with patch(
            "app.consumers.manifest_completed_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_completed(consumer))

        session.commit.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_json_decode_error_commits(self):
        consumer = _FakeConsumer([_FakeMsg(b"bad")], topic="manifest.completed")
        asyncio.run(_run_completed(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_generic_error_sleeps_without_commit(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="manifest.completed",
        )
        session = _make_session()
        session.get = AsyncMock(side_effect=Exception("db down"))

        with patch(
            "app.consumers.manifest_completed_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(_run_completed(consumer))

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_cancelled_stops_consumer(self):
        consumer = _FakeConsumer([], topic="manifest.completed")
        asyncio.run(_run_completed(consumer))
        consumer.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# TestFailureConsumer
# ---------------------------------------------------------------------------

class TestFailureConsumer:

    def test_null_value_commits(self):
        consumer = _FakeConsumer([_FakeMsg(None)], topic="job.failed")
        asyncio.run(_run_failure(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_missing_video_id_commits(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({}).encode())],
            topic="job.failed",
        )
        with patch("app.consumers.failure_consumer.async_session_factory") as mock_factory:
            asyncio.run(_run_failure(consumer))
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()

    def test_video_not_found_commits_without_status_change(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "missing"}).encode())],
            topic="job.failed",
        )
        session = _make_session()
        session.get.return_value = None

        with patch(
            "app.consumers.failure_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ):
            asyncio.run(_run_failure(consumer))

        session.commit.assert_not_awaited()
        consumer.commit.assert_awaited()

    def test_sets_failed_when_retries_exhausted(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="manifest.failed",
        )
        session = _make_session()
        video = _make_video(status="RETRY", user_id=2, num_of_retries=5)
        session.get.return_value = video

        with patch(
            "app.consumers.failure_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.failure_consumer.publish_update", new=AsyncMock()
        ) as mock_publish, patch(
            "app.consumers.failure_consumer.settings"
        ) as mock_settings:
            mock_settings.video_max_retry = 5
            asyncio.run(_run_failure(consumer))

        assert video.status == "FAILED"
        assert video.num_of_retries == 5
        session.commit.assert_awaited_once()
        mock_publish.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_sets_retry_when_retries_remain(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="job.failed",
        )
        session = _make_session()
        video = _make_video(status="PROCESSING", user_id=2, num_of_retries=1)
        session.get.return_value = video

        with patch(
            "app.consumers.failure_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch(
            "app.consumers.failure_consumer.publish_update", new=AsyncMock()
        ) as mock_publish, patch(
            "app.consumers.failure_consumer.settings"
        ) as mock_settings:
            mock_settings.video_max_retry = 5
            asyncio.run(_run_failure(consumer))

        assert video.status == "RETRY"
        assert video.num_of_retries == 1
        session.commit.assert_awaited_once()
        mock_publish.assert_awaited_once()
        consumer.commit.assert_awaited()

    def test_json_decode_error_commits(self):
        consumer = _FakeConsumer([_FakeMsg(b"bad")], topic="job.failed")
        asyncio.run(_run_failure(consumer))
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_generic_error_sleeps_without_commit(self):
        consumer = _FakeConsumer(
            [_FakeMsg(json.dumps({"video_id": "vid1"}).encode())],
            topic="job.failed",
        )
        session = _make_session()
        session.get = AsyncMock(side_effect=Exception("db down"))

        with patch(
            "app.consumers.failure_consumer.async_session_factory",
            return_value=_AsyncSessionCM(session),
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(_run_failure(consumer))

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_cancelled_stops_consumer(self):
        consumer = _FakeConsumer([], topic="job.failed")
        asyncio.run(_run_failure(consumer))
        consumer.stop.assert_awaited_once()
