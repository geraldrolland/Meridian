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
    """Mimics a SQLAlchemy column for use in filter expressions."""
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
MOCK_VIDEO_STATUS.DLQ_PENDING = _FakeEnumMember("DLQ_PENDING")

MOCK_OUTBOX_STATUS = MagicMock(name="OutboxStatus")
MOCK_OUTBOX_STATUS.PENDING = _FakeEnumMember("PENDING")
MOCK_OUTBOX_STATUS.PROCESSED = _FakeEnumMember("PROCESSED")
MOCK_OUTBOX_STATUS.FAILED = _FakeEnumMember("FAILED")

MOCK_LOCK_STATE = MagicMock(name="LockState")
MOCK_LOCK_STATE.PROCESS = _FakeEnumMember("PROCESS")
MOCK_LOCK_STATE.COMMIT = _FakeEnumMember("COMMIT")


def _setup_common_mocks(monkeypatch):
    kafka_mod = _make_mock_module("kafka")
    kafka_errors = _make_mock_module("kafka.errors")
    kafka_errors.NoBrokersAvailable = type("NoBrokersAvailable", (Exception,), {})

    notif_mod = _make_mock_module("app.models.notification")
    notif_mod.BucketNotificationEvent = MOCK_BUCKET_NOTIFICATION_EVENT
    notif_mod.NotificationStatus = MOCK_NOTIFICATION_STATUS
    MOCK_BUCKET_NOTIFICATION_EVENT.status = _FakeColumn("PENDING")
    MOCK_BUCKET_NOTIFICATION_EVENT.retry_after = _FakeColumn(None)

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
    lock_mod.acquire_lock = MagicMock(return_value=MagicMock())
    lock_mod.release_lock = MagicMock()

    mock_modules = {
        "kafka": kafka_mod,
        "kafka.errors": kafka_errors,
        "app.config": _make_mock_module("app.config"),
        "app.database_sync": _make_mock_module("app.database_sync"),
        "app.lock": lock_mod,
        "app.producer": _make_mock_module("app.producer"),
        "app.celery_app": celery_mod,
        "app.models": _make_mock_module("app.models"),
        "app.models.notification": notif_mod,
        "app.models.outbox": outbox_mod,
        "app.models.video": video_mod,
        "app.utils": _make_mock_module("app.utils"),
        "app.utils.notification_utils": _make_mock_module("app.utils.notification_utils"),
    }

    for mod_name, mock_mod in mock_modules.items():
        monkeypatch.setitem(sys.modules, mod_name, mock_mod)

    sys.modules.pop("app.tasks", None)

    import app.config as cfg
    cfg.settings = MagicMock()
    cfg.logger = MagicMock()

    import app.lock as lock_mod_inst
    lock_mod_inst.LockState = MOCK_LOCK_STATE
    lock_mod_inst.acquire_lock = MagicMock(return_value=MagicMock())
    lock_mod_inst.release_lock = MagicMock()

    import app.producer as prod_mod
    prod_mod.kafka_producer = MagicMock()

    import app.utils.notification_utils as notif_utils
    notif_utils.build_object_url = MagicMock(return_value="http://minio/test.mp4")


def _make_mock_notification(notification_id="notif-1", video_id="video-123", size=2048):
    mock_notif = MagicMock(name="notif_record")
    mock_notif.id = notification_id
    mock_notif.status = _FakeEnumMember("PENDING")
    mock_notif.extract_video_id.return_value = video_id
    mock_notif.event = {"Records": [{"s3": {"object": {"size": size}}}]}
    return mock_notif


def _make_mock_video(video_id="video-123", status="AWAITING_UPLOAD"):
    mock_video = MagicMock(name="video_record")
    mock_video.id = video_id
    mock_video.user_id = 1
    mock_video.filename = "test.mp4"
    mock_video.status = _FakeEnumMember(status)
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
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()

        mock_session = _make_mock_session({
            (tasks_mod.BucketNotificationEvent, "notif-1"): mock_notif,
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        result = process_notifications()

        assert mock_video.status == "QUEUED"
        assert result["processed"] == 1

    def test_extracts_size_from_event(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification(size=4096)

        mock_session = _make_mock_session({
            (tasks_mod.BucketNotificationEvent, "notif-1"): mock_notif,
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        assert mock_video.size == 4096

    def test_creates_outbox_entry(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()

        mock_session = _make_mock_session({
            (tasks_mod.BucketNotificationEvent, "notif-1"): mock_notif,
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        mock_session.add.assert_called_once()
        assert MOCK_OUTBOX_CLASS.call_args[1]["topic"] == "video.queued"
        assert MOCK_OUTBOX_CLASS.call_args[1]["payload"]["video_id"] == "video-123"
        assert MOCK_OUTBOX_CLASS.call_args[1]["payload"]["origin_service"] == "video-service"

    def test_acquires_process_and_commit_locks(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()

        mock_session = _make_mock_session({
            (tasks_mod.BucketNotificationEvent, "notif-1"): mock_notif,
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        tasks_mod.acquire_lock = MagicMock(return_value=MagicMock())
        tasks_mod.release_lock = MagicMock()

        process_notifications()

        assert tasks_mod.acquire_lock.call_count == 2
        tasks_mod.acquire_lock.assert_any_call(MOCK_LOCK_STATE.PROCESS, "notif-1")
        tasks_mod.acquire_lock.assert_any_call(MOCK_LOCK_STATE.COMMIT, "notif-1")
        assert tasks_mod.release_lock.call_count == 2

    def test_returns_zero_when_no_pending(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_session = MagicMock(name="session")
        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = process_notifications()

        assert result == {"processed": 0}

    def test_retry_increments_num_of_retry_and_sets_retry_after(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()
        mock_notif.num_of_retry = 2

        mock_session = _make_mock_session({
            (tasks_mod.BucketNotificationEvent, "notif-1"): mock_notif,
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        mock_session.commit.side_effect = Exception("simulated error")

        process_notifications()

        assert mock_notif.num_of_retry == 3
        assert mock_notif.retry_after is not None

    def test_retry_exceeds_sets_notification_and_video_failed(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = _make_mock_video()
        mock_notif = _make_mock_notification()
        mock_notif.num_of_retry = 5
        mock_notif.video_id = "video-123"

        mock_session = _make_mock_session({
            (tasks_mod.BucketNotificationEvent, "notif-1"): mock_notif,
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        mock_session.commit.side_effect = Exception("simulated error")

        process_notifications()

        assert mock_notif.num_of_retry == 5
        assert mock_notif.retry_after is None
        assert mock_notif.status == "FAILED"
        assert mock_video.status == "FAILED"


class TestProcessFailedVideos:
    def test_creates_dlq_outbox_entry(self, _mock_heavy_deps):
        from app.tasks import process_failed_videos
        import app.tasks as tasks_mod

        mock_video = _make_mock_video(status="DLQ_PENDING")

        mock_session = _make_mock_session({
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        result = process_failed_videos()

        mock_session.add.assert_called_once()
        assert MOCK_OUTBOX_CLASS.call_args[1]["topic"] == "video.DLQ"
        payload = MOCK_OUTBOX_CLASS.call_args[1]["payload"]
        assert payload["origin_service"] == "video-service"
        assert payload["video_id"] == "video-123"
        assert payload["user_id"] == 1
        assert payload["filename"] == "test.mp4"
        assert payload["reason"] == "processing_failed"
        assert result["processed"] == 1

    def test_sets_video_status_to_failed(self, _mock_heavy_deps):
        from app.tasks import process_failed_videos
        import app.tasks as tasks_mod

        mock_video = _make_mock_video(status="DLQ_PENDING")

        mock_session = _make_mock_session({
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        process_failed_videos()

        assert mock_video.status == "FAILED"

    def test_returns_zero_when_no_dlq_pending(self, _mock_heavy_deps):
        from app.tasks import process_failed_videos
        import app.tasks as tasks_mod

        mock_session = MagicMock(name="session")
        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = process_failed_videos()

        assert result == {"processed": 0}

    def test_skips_when_lock_not_acquired(self, _mock_heavy_deps):
        from app.tasks import process_failed_videos
        import app.tasks as tasks_mod

        mock_video = _make_mock_video(status="DLQ_PENDING")

        mock_session = _make_mock_session({
            (tasks_mod.Video, "video-123"): mock_video,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_video]

        tasks_mod.acquire_lock = MagicMock(return_value=None)

        result = process_failed_videos()

        assert result["processed"] == 0
        mock_session.add.assert_not_called()


class TestProcessOutboxEvents:
    def test_publishes_to_kafka(self, _mock_heavy_deps):
        from app.tasks import process_outbox_events
        import app.tasks as tasks_mod

        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")
        mock_outbox.topic = "video.queued"
        mock_outbox.payload = {"video_id": "video-123"}
        mock_outbox.retry_count = 0
        mock_outbox.retry_after = None

        mock_session = _make_mock_session({
            (tasks_mod.Outbox, "outbox-1"): mock_outbox,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        tasks_mod.kafka_producer = MagicMock()

        process_outbox_events()

        tasks_mod.kafka_producer.publish.assert_called_once_with("video.queued", {"video_id": "video-123"})

    def test_sets_status_to_processed(self, _mock_heavy_deps):
        from app.tasks import process_outbox_events
        import app.tasks as tasks_mod

        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")
        mock_outbox.topic = "video.queued"
        mock_outbox.payload = {"video_id": "video-123"}
        mock_outbox.retry_count = 0
        mock_outbox.retry_after = None

        mock_session = _make_mock_session({
            (tasks_mod.Outbox, "outbox-1"): mock_outbox,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        tasks_mod.kafka_producer = MagicMock()

        process_outbox_events()

        assert mock_outbox.status == "PROCESSED"

    def test_returns_zero_when_no_pending(self, _mock_heavy_deps):
        from app.tasks import process_outbox_events
        import app.tasks as tasks_mod

        mock_session = MagicMock(name="session")
        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        result = process_outbox_events()

        assert result == {"processed": 0}

    def test_skips_when_lock_not_acquired(self, _mock_heavy_deps):
        from app.tasks import process_outbox_events
        import app.tasks as tasks_mod

        mock_outbox = MagicMock(name="outbox_record")
        mock_outbox.id = "outbox-1"
        mock_outbox.status = _FakeEnumMember("PENDING")

        mock_session = _make_mock_session({
            (tasks_mod.Outbox, "outbox-1"): mock_outbox,
        })

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_outbox]

        tasks_mod.acquire_lock = MagicMock(return_value=None)
        tasks_mod.kafka_producer = MagicMock()

        result = process_outbox_events()

        assert result["processed"] == 0
        tasks_mod.kafka_producer.publish.assert_not_called()
