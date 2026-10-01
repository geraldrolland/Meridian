"""Tests for app.consumer -- Kafka consume_messages loop."""

import asyncio
import json
import sys
from unittest.mock import patch, MagicMock, AsyncMock

from sqlalchemy.exc import IntegrityError

sys.modules.setdefault("asyncpg", MagicMock())
sys.modules.setdefault("ffmpeg", MagicMock())
sys.modules.setdefault("minio", MagicMock())
sys.modules.setdefault("redis", MagicMock())
sys.modules.setdefault("aiokafka", MagicMock())


class _FakeMsg:
    def __init__(self, value, topic="video.queued", partition=0, offset=0):
        self.value = value
        self.topic = topic
        self.partition = partition
        self.offset = offset


class _FakeConsumer:
    def __init__(self, messages):
        self._messages = list(messages)
        self.commit = AsyncMock()
        self.stop = AsyncMock()

    def __aiter__(self):
        self._iter = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise asyncio.CancelledError


async def _consume(consumer):
    from app.consumer import consume_messages
    await consume_messages(consumer)


def _run(consumer):
    asyncio.run(_consume(consumer))


def _payload(**overrides):
    base = {
        "event_id": "evt1",
        "timestamp": "2024-01-01T00:00:00Z",
        "origin_service": "video_service",
        "video_id": "vid1",
        "object_url": "http://minio:9000/viduploads/videos/vid1/file.mp4",
    }
    base.update(overrides)
    return base


class _AsyncSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_session():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


def _factory(session):
    def _f():
        return _AsyncSessionCM(session)
    return _f


class TestConsumeMessages:

    def test_null_value_commits_and_skips(self):
        consumer = _FakeConsumer([_FakeMsg(None)])
        with patch("app.consumer.async_session_factory") as mock_factory:
            _run(consumer)
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_validation_error_sleeps_without_commit(self):
        msg = _FakeMsg(json.dumps({"event_id": "evt1"}).encode())
        consumer = _FakeConsumer([msg])
        with patch("app.consumer.async_session_factory") as mock_factory, \
             patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            _run(consumer)
        mock_factory.assert_not_called()
        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_happy_path_persists_job_and_outbox_and_offset(self):
        msg = _FakeMsg(json.dumps(_payload()).encode())
        consumer = _FakeConsumer([msg])
        session = _make_session()

        with patch("app.consumer.async_session_factory", return_value=_AsyncSessionCM(session)):
            _run(consumer)

        assert session.add.call_count == 2
        added_outbox = session.add.call_args_list[0][0][0]
        added_job = session.add.call_args_list[1][0][0]
        assert added_outbox.topic == "job.processing"
        assert added_outbox.payload == {"video_id": "vid1"}
        assert added_job.id == "job:evt1"
        assert added_job.video_id == "vid1"
        assert added_job.object_url == "http://minio:9000/viduploads/videos/vid1/file.mp4"
        session.commit.assert_awaited_once()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_json_decode_error_commits_offset(self):
        msg = _FakeMsg(b"not-json{")
        consumer = _FakeConsumer([msg])
        with patch("app.consumer.async_session_factory") as mock_factory:
            _run(consumer)
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_integrity_error_commits_offset(self):
        msg = _FakeMsg(json.dumps(_payload()).encode())
        consumer = _FakeConsumer([msg])
        session = _make_session()
        session.commit = AsyncMock(
            side_effect=IntegrityError("INSERT", {}, Exception("duplicate"))
        )

        with patch("app.consumer.async_session_factory", return_value=_AsyncSessionCM(session)):
            _run(consumer)

        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_generic_error_sleeps_without_kafka_commit(self):
        msg = _FakeMsg(json.dumps(_payload()).encode())
        consumer = _FakeConsumer([msg])
        session = _make_session()
        session.commit = AsyncMock(side_effect=Exception("db down"))

        with patch("app.consumer.async_session_factory", return_value=_AsyncSessionCM(session)), \
             patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            _run(consumer)

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()

    def test_cancelled_stops_consumer(self):
        consumer = _FakeConsumer([])
        _run(consumer)
        consumer.stop.assert_awaited_once()
        consumer.commit.assert_not_awaited()


class TestVideoDeletedDispatch:
    """video.deleted topic: cleanup only — no Job/Outbox rows."""

    def test_cleans_up_and_commits_offset(self):
        msg = _FakeMsg(
            json.dumps({"video_id": "vid1"}).encode(), topic="video.deleted"
        )
        consumer = _FakeConsumer([msg])
        with patch("app.consumer.async_session_factory") as mock_factory, \
             patch("app.consumer._handle_video_deleted") as mock_handle:
            _run(consumer)

        mock_handle.assert_called_once_with("vid1")
        mock_factory.assert_not_called()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_missing_video_id_skips_handler_but_commits(self):
        msg = _FakeMsg(
            json.dumps({"video_id": None}).encode(), topic="video.deleted"
        )
        consumer = _FakeConsumer([msg])
        with patch("app.consumer._handle_video_deleted") as mock_handle:
            _run(consumer)

        mock_handle.assert_not_called()
        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_handler_integrity_error_still_commits_offset(self):
        msg = _FakeMsg(
            json.dumps({"video_id": "vid1"}).encode(), topic="video.deleted"
        )
        consumer = _FakeConsumer([msg])
        with patch(
            "app.consumer._handle_video_deleted",
            side_effect=IntegrityError("DELETE", {}, Exception("gone")),
        ):
            _run(consumer)

        consumer.commit.assert_awaited()
        consumer.stop.assert_awaited()

    def test_handler_error_sleeps_without_kafka_commit(self):
        msg = _FakeMsg(
            json.dumps({"video_id": "vid1"}).encode(), topic="video.deleted"
        )
        consumer = _FakeConsumer([msg])
        with patch(
            "app.consumer._handle_video_deleted",
            side_effect=Exception("minio down"),
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            _run(consumer)

        mock_sleep.assert_awaited_with(1)
        consumer.commit.assert_not_awaited()
        consumer.stop.assert_awaited()


class TestHandleVideoDeleted:
    """_handle_video_deleted: query jobs by video, run cleanup_jobs."""

    def test_queries_jobs_and_calls_cleanup(self):
        from app.consumer import _handle_video_deleted

        jobs = [MagicMock(), MagicMock()]
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = jobs

        with patch("app.consumer.get_sync_session", return_value=session), \
             patch("app.consumer.cleanup_jobs") as mock_cleanup:
            _handle_video_deleted("vid1")

        session.query.return_value.filter.return_value.all.assert_called_once()
        mock_cleanup.assert_called_once_with(jobs, session)
        session.close.assert_called_once()

    def test_no_jobs_skips_cleanup(self):
        from app.consumer import _handle_video_deleted

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        with patch("app.consumer.get_sync_session", return_value=session), \
             patch("app.consumer.cleanup_jobs") as mock_cleanup:
            _handle_video_deleted("vid1")

        mock_cleanup.assert_not_called()
        session.close.assert_called_once()
