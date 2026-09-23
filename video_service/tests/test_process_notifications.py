import sys
from unittest.mock import MagicMock

import pytest


def _make_mock_module(name: str) -> MagicMock:
    mod = MagicMock()
    mod.__name__ = name
    mod.__package__ = name
    return mod


class _FakeEnumMember:
    def __init__(self, value):
        self.value = value
    def __eq__(self, other):
        if isinstance(other, _FakeEnumMember):
            return self.value == other.value
        return self.value == other
    def __ne__(self, other):
        return not self.__eq__(other)
    def __repr__(self):
        return f"FakeEnum({self.value!r})"


class _FakeColumn:
    def __init__(self, value=None):
        self._value = value
    def is_(self, other):
        return self._value is other
    def __lt__(self, other):
        return False
    def __or__(self, other):
        return True


MOCK_BUCKET_NOTIFICATION_EVENT = MagicMock(name="BucketNotificationEvent")
MOCK_VIDEO_CLASS = MagicMock(name="Video")
MOCK_OUTBOX_CLASS = MagicMock(name="Outbox")

MOCK_NOTIFICATION_STATUS = MagicMock(name="NotificationStatus")
MOCK_NOTIFICATION_STATUS.PENDING = _FakeEnumMember("PENDING")
MOCK_NOTIFICATION_STATUS.RECEIVED = _FakeEnumMember("RECEIVED")
MOCK_NOTIFICATION_STATUS.FAILED = _FakeEnumMember("FAILED")

MOCK_VIDEO_STATUS = MagicMock(name="VideoStatus")
MOCK_VIDEO_STATUS.AWAITING_UPLOAD = _FakeEnumMember("AWAITING_UPLOAD")
MOCK_VIDEO_STATUS.QUEUED = _FakeEnumMember("QUEUED")
MOCK_VIDEO_STATUS.PROCESSING = _FakeEnumMember("PROCESSING")
MOCK_VIDEO_STATUS.COMPLETED = _FakeEnumMember("COMPLETED")
MOCK_VIDEO_STATUS.FAILED = _FakeEnumMember("FAILED")
MOCK_VIDEO_STATUS.RETRY = _FakeEnumMember("RETRY")

MOCK_OUTBOX_STATUS = MagicMock(name="OutboxStatus")
MOCK_OUTBOX_STATUS.PENDING = _FakeEnumMember("PENDING")
MOCK_OUTBOX_STATUS.PROCESSED = _FakeEnumMember("PROCESSED")
MOCK_OUTBOX_STATUS.FAILED = _FakeEnumMember("FAILED")

MOCK_LOCK_STATE = MagicMock(name="LockState")
MOCK_LOCK_STATE.PROCESS = _FakeEnumMember("PROCESS")
MOCK_LOCK_STATE.COMMIT = _FakeEnumMember("COMMIT")

MOCK_SETTINGS = MagicMock()
MOCK_SETTINGS.outbox_max_retry = 5
MOCK_SETTINGS.video_max_retry = 5

MOCK_GET_SYNC_SESSION = MagicMock()
MOCK_ACQUIRE_LOCK = MagicMock(return_value=MagicMock())
MOCK_RELEASE_LOCK = MagicMock()
MOCK_KAFKA_PRODUCER = MagicMock()
MOCK_BUILD_OBJECT_URL = MagicMock(return_value="http://minio/test.mp4")


def _setup_common_mocks(monkeypatch):
    kafka_mod = _make_mock_module("kafka")
    kafka_errors = _make_mock_module("kafka.errors")
    kafka_errors.NoBrokersAvailable = type("NoBrokersAvailable", (Exception,), {})

    notif_mod = _make_mock_module("app.models.notification")
    notif_mod.BucketNotificationEvent = MOCK_BUCKET_NOTIFICATION_EVENT
    notif_mod.NotificationStatus = MOCK_NOTIFICATION_STATUS
    MOCK_BUCKET_NOTIFICATION_EVENT.status = _FakeColumn("PENDING")

    outbox_mod = _make_mock_module("app.models.outbox")
    outbox_mod.Outbox = MOCK_OUTBOX_CLASS
    outbox_mod.OutboxStatus = MOCK_OUTBOX_STATUS
    MOCK_OUTBOX_CLASS.retry_after = _FakeColumn(None)
    MOCK_OUTBOX_CLASS.status = _FakeColumn("PENDING")

    video_mod = _make_mock_module("app.models.video")
    video_mod.Video = MOCK_VIDEO_CLASS
    video_mod.VideoStatus = MOCK_VIDEO_STATUS

    celery_mod = _make_mock_module("app.celery_app")

    def fake_task(**kwargs):
        def decorator(func):
            func.name = kwargs.get("name", "")
            return func
        return decorator

    celery_mod.celery_app = MagicMock()
    celery_mod.celery_app.task = fake_task

    lock_mod = _make_mock_module("app.lock")
    lock_mod.LockState = MOCK_LOCK_STATE
    lock_mod.acquire_lock = MOCK_ACQUIRE_LOCK
    lock_mod.release_lock = MOCK_RELEASE_LOCK

    config_mod = _make_mock_module("app.config")
    config_mod.settings = MOCK_SETTINGS
    config_mod.logger = MagicMock()

    producer_mod = _make_mock_module("app.producer")
    producer_mod.kafka_producer = MOCK_KAFKA_PRODUCER

    notif_utils_mod = _make_mock_module("app.utils.notification_utils")
    notif_utils_mod.build_object_url = MOCK_BUILD_OBJECT_URL

    db_sync_mod = _make_mock_module("app.database_sync")
    db_sync_mod.get_sync_session = MOCK_GET_SYNC_SESSION

    mock_modules = {
        "kafka": kafka_mod,
        "kafka.errors": kafka_errors,
        "app.config": config_mod,
        "app.database_sync": db_sync_mod,
        "app.lock": lock_mod,
        "app.producer": producer_mod,
        "app.celery_app": celery_mod,
        "app.models": _make_mock_module("app.models"),
        "app.models.notification": notif_mod,
        "app.models.outbox": outbox_mod,
        "app.models.video": video_mod,
        "app.utils": _make_mock_module("app.utils"),
        "app.utils.notification_utils": notif_utils_mod,
    }

    for mod_name, mock_mod in mock_modules.items():
        monkeypatch.setitem(sys.modules, mod_name, mock_mod)

    for task_mod_name in [
        "app.tasks",
        "app.tasks.process_notifications",
        "app.tasks.process_queued_videos",
        "app.tasks.process_outbox_events",
    ]:
        sys.modules.pop(task_mod_name, None)

    MOCK_ACQUIRE_LOCK.reset_mock()
    MOCK_ACQUIRE_LOCK.return_value = MagicMock()
    MOCK_RELEASE_LOCK.reset_mock()
    MOCK_KAFKA_PRODUCER.reset_mock()
    MOCK_GET_SYNC_SESSION.reset_mock()
    MOCK_BUILD_OBJECT_URL.return_value = "http://minio/test.mp4"


def _make_mock_notification(notification_id="notif-1", video_id="video-123", size=2048):
    mock_notif = MagicMock(name="notif_record")
    mock_notif.id = notification_id
    mock_notif.status = _FakeEnumMember("PENDING")
    mock_notif.extract_video_id.return_value = video_id
    mock_notif.event = {"Records": [{"s3": {"object": {"size": size}}}]}
    return mock_notif


def _make_mock_video(video_id="video-123", status="AWAITING_UPLOAD", published=False):
    mock_video = MagicMock(name="video_record")
    mock_video.id = video_id
    mock_video.user_id = 1
    mock_video.filename = "test.mp4"
    mock_video.status = _FakeEnumMember(status)
    mock_video.published = published
    mock_video.num_of_retries = 0
    mock_video.video_url = "http://minio/test.mp4"
    return mock_video


def _make_mock_session(entities):
    mock_session = MagicMock(name="session")

    def fake_get(entity, entity_id):
        return entities.get((entity, entity_id), MagicMock())

    mock_session.get.side_effect = fake_get
    return mock_session


@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    _setup_common_mocks(monkeypatch)


class TestProcessNotifications:
    def test_sets_queued_on_success(self, _mock_heavy_deps):
        from app.tasks.process_notifications import process_notifications

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()

        mock_session = _make_mock_session({
            (MOCK_BUCKET_NOTIFICATION_EVENT, "notif-1"): mock_notif,
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        result = process_notifications()

        assert mock_video.status == "QUEUED"
        assert result["processed"] == 1

    def test_extracts_size_from_event(self, _mock_heavy_deps):
        from app.tasks.process_notifications import process_notifications

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification(size=4096)

        mock_session = _make_mock_session({
            (MOCK_BUCKET_NOTIFICATION_EVENT, "notif-1"): mock_notif,
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        assert mock_video.size == 4096

    def test_does_not_create_outbox_entry(self, _mock_heavy_deps):
        from app.tasks.process_notifications import process_notifications

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()

        mock_session = _make_mock_session({
            (MOCK_BUCKET_NOTIFICATION_EVENT, "notif-1"): mock_notif,
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        mock_session.add.assert_not_called()
        assert mock_video.status == "QUEUED"

    def test_acquires_process_and_commit_locks(self, _mock_heavy_deps):
        from app.tasks.process_notifications import process_notifications

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()

        mock_session = _make_mock_session({
            (MOCK_BUCKET_NOTIFICATION_EVENT, "notif-1"): mock_notif,
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        assert MOCK_ACQUIRE_LOCK.call_count == 2
        MOCK_ACQUIRE_LOCK.assert_any_call(MOCK_LOCK_STATE.PROCESS, "notif-1")
        MOCK_ACQUIRE_LOCK.assert_any_call(MOCK_LOCK_STATE.COMMIT, "notif-1")
        assert MOCK_RELEASE_LOCK.call_count == 2

    def test_returns_zero_when_no_pending(self, _mock_heavy_deps):
        from app.tasks.process_notifications import process_notifications

        mock_session = MagicMock(name="session")
        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = process_notifications()

        assert result == {"processed": 0}

    def test_on_error_sets_notification_and_video_failed(self, _mock_heavy_deps):
        from app.tasks.process_notifications import process_notifications

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()
        mock_notif.video_id = "video-123"

        mock_session = _make_mock_session({
            (MOCK_BUCKET_NOTIFICATION_EVENT, "notif-1"): mock_notif,
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        mock_session.commit.side_effect = Exception("simulated error")

        process_notifications()

        assert mock_notif.status == "FAILED"
        assert mock_video.status == "FAILED"


class TestProcessOutboxEvents:
    def test_publishes_to_kafka(self, _mock_heavy_deps):
        from app.tasks.process_outbox_events import process_outbox_events

        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")
        mock_outbox.topic = "video.queued"
        mock_outbox.payload = {"video_id": "video-123"}
        mock_outbox.retry_count = 0
        mock_outbox.retry_after = None

        mock_session = _make_mock_session({
            (MOCK_OUTBOX_CLASS, "outbox-1"): mock_outbox,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        process_outbox_events()

        MOCK_KAFKA_PRODUCER.publish.assert_called_once_with("video.queued", {"video_id": "video-123"})

    def test_sets_status_to_processed(self, _mock_heavy_deps):
        from app.tasks.process_outbox_events import process_outbox_events

        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")
        mock_outbox.topic = "video.queued"
        mock_outbox.payload = {"video_id": "video-123"}
        mock_outbox.retry_count = 0
        mock_outbox.retry_after = None

        mock_session = _make_mock_session({
            (MOCK_OUTBOX_CLASS, "outbox-1"): mock_outbox,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        process_outbox_events()

        assert mock_outbox.status == "PROCESSED"

    def test_returns_zero_when_no_pending(self, _mock_heavy_deps):
        from app.tasks.process_outbox_events import process_outbox_events

        mock_session = MagicMock(name="session")
        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = process_outbox_events()

        assert result == {"processed": 0}

    def test_skips_when_lock_not_acquired(self, _mock_heavy_deps):
        from app.tasks.process_outbox_events import process_outbox_events

        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")

        mock_session = _make_mock_session({
            (MOCK_OUTBOX_CLASS, "outbox-1"): mock_outbox,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        MOCK_ACQUIRE_LOCK.return_value = None

        result = process_outbox_events()

        assert result["processed"] == 0
        MOCK_KAFKA_PRODUCER.publish.assert_not_called()

    def test_retry_exhausted_sets_outbox_failed_and_video_retry(self, _mock_heavy_deps):
        from app.tasks.process_outbox_events import process_outbox_events

        mock_video = _make_mock_video(status="PROCESSING")
        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")
        mock_outbox.topic = "video.queued"
        mock_outbox.payload = {"video_id": "video-123"}
        mock_outbox.retry_count = 4
        mock_outbox.retry_after = None

        mock_session = _make_mock_session({
            (MOCK_OUTBOX_CLASS, "outbox-1"): mock_outbox,
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        MOCK_KAFKA_PRODUCER.publish.side_effect = Exception("kafka down")

        process_outbox_events()

        assert mock_outbox.status == "FAILED"
        assert mock_outbox.retry_count == 5
        assert mock_video.status == "RETRY"


class TestProcessQueuedVideos:
    def test_sets_published_true_and_creates_outbox(self, _mock_heavy_deps):
        from app.tasks.process_queued_videos import process_queued_videos

        mock_video = _make_mock_video(status="QUEUED", published=False)

        mock_session = _make_mock_session({
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        result = process_queued_videos()

        assert mock_video.published is True
        mock_session.add.assert_called_once()
        assert result["processed"] == 1

    def test_outbox_has_correct_topic_and_payload(self, _mock_heavy_deps):
        from app.tasks.process_queued_videos import process_queued_videos

        mock_video = _make_mock_video(status="QUEUED", published=False)
        mock_video.video_url = "http://minio/viduploads/test.mp4"

        mock_session = _make_mock_session({
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        MOCK_OUTBOX_CLASS.reset_mock()

        process_queued_videos()

        mock_session.add.assert_called_once()
        call_kwargs = MOCK_OUTBOX_CLASS.call_args[1]
        assert call_kwargs["topic"] == "video.queued"
        assert call_kwargs["payload"]["origin_service"] == "video-service"
        assert call_kwargs["payload"]["video_id"] == "video-123"
        assert call_kwargs["payload"]["object_url"] == "http://minio/viduploads/test.mp4"

    def test_returns_zero_when_no_queued_unpublished(self, _mock_heavy_deps):
        from app.tasks.process_queued_videos import process_queued_videos

        mock_session = MagicMock(name="session")
        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = process_queued_videos()

        assert result == {"processed": 0}

    def test_skips_when_lock_not_acquired(self, _mock_heavy_deps):
        from app.tasks.process_queued_videos import process_queued_videos

        mock_video = _make_mock_video(status="QUEUED", published=False)

        mock_session = _make_mock_session({
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        MOCK_ACQUIRE_LOCK.return_value = None

        result = process_queued_videos()

        assert result["processed"] == 0
        mock_session.add.assert_not_called()

    def test_acquires_process_and_commit_locks(self, _mock_heavy_deps):
        from app.tasks.process_queued_videos import process_queued_videos

        mock_video = _make_mock_video(status="QUEUED", published=False)

        mock_session = _make_mock_session({
            (MOCK_VIDEO_CLASS, "video-123"): mock_video,
        })

        MOCK_GET_SYNC_SESSION.return_value = mock_session
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        process_queued_videos()

        assert MOCK_ACQUIRE_LOCK.call_count == 2
        MOCK_ACQUIRE_LOCK.assert_any_call(MOCK_LOCK_STATE.PROCESS, "video-123")
        MOCK_ACQUIRE_LOCK.assert_any_call(MOCK_LOCK_STATE.COMMIT, "video-123")
        assert MOCK_RELEASE_LOCK.call_count == 2
