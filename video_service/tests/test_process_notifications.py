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


MOCK_BUCKET_NOTIFICATION_EVENT = MagicMock(name="BucketNotificationEvent")
MOCK_VIDEO_CLASS = MagicMock(name="Video")
MOCK_OUTBOX_CLASS = MagicMock(name="Outbox")

MOCK_NOTIFICATION_STATUS = MagicMock(name="NotificationStatus")
MOCK_NOTIFICATION_STATUS.PENDING = _FakeEnumMember("PENDING")
MOCK_NOTIFICATION_STATUS.RECEIVED = _FakeEnumMember("RECEIVED")
MOCK_NOTIFICATION_STATUS.FAILED = _FakeEnumMember("FAILED")

MOCK_VIDEO_STATUS = MagicMock(name="VideoStatus")
MOCK_VIDEO_STATUS.QUEUED = _FakeEnumMember("QUEUED")
MOCK_VIDEO_STATUS.PROCESSING = _FakeEnumMember("PROCESSING")
MOCK_VIDEO_STATUS.FAILED = _FakeEnumMember("FAILED")

MOCK_OUTBOX_STATUS = MagicMock(name="OutboxStatus")
MOCK_OUTBOX_STATUS.PENDING = _FakeEnumMember("PENDING")
MOCK_OUTBOX_STATUS.PROCESSED = _FakeEnumMember("PROCESSED")
MOCK_OUTBOX_STATUS.FAILED = _FakeEnumMember("FAILED")


@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    kafka_mod = _make_mock_module("kafka")
    kafka_errors = _make_mock_module("kafka.errors")
    kafka_errors.NoBrokersAvailable = type("NoBrokersAvailable", (Exception,), {})

    notif_mod = _make_mock_module("app.models.notification")
    notif_mod.BucketNotificationEvent = MOCK_BUCKET_NOTIFICATION_EVENT
    notif_mod.NotificationStatus = MOCK_NOTIFICATION_STATUS

    outbox_mod = _make_mock_module("app.models.outbox")
    outbox_mod.Outbox = MOCK_OUTBOX_CLASS
    outbox_mod.OutboxStatus = MOCK_OUTBOX_STATUS

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

    mock_modules = {
        "kafka": kafka_mod,
        "kafka.errors": kafka_errors,
        "app.config": _make_mock_module("app.config"),
        "app.database_sync": _make_mock_module("app.database_sync"),
        "app.lock": _make_mock_module("app.lock"),
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

    import app.lock as lock_mod
    lock_mod.acquire_lock = MagicMock(return_value=MagicMock())
    lock_mod.release_lock = MagicMock()

    import app.producer as prod_mod
    prod_mod.kafka_producer = MagicMock()

    import app.utils.notification_utils as notif_utils
    notif_utils.build_object_url = MagicMock(return_value="http://minio/test.mp4")


class TestProcessNotifications:
    def test_sets_queued_on_success(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = MagicMock(name="video_record")
        mock_video.id = "video-123"

        mock_notif = MagicMock(name="notif_record")
        mock_notif.id = "notif-1"
        mock_notif.status = _FakeEnumMember("PENDING")
        mock_notif.extract_video_id.return_value = "video-123"
        mock_notif.event = {"Records": [{"s3": {"object": {"size": 2048}}}]}

        mock_session = MagicMock(name="session")

        notif_entity = tasks_mod.BucketNotificationEvent
        video_entity = tasks_mod.Video

        def fake_get(entity, entity_id):
            if entity is notif_entity:
                return mock_notif
            if entity is video_entity:
                return mock_video
            return MagicMock()

        mock_session.get.side_effect = fake_get

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        result = process_notifications()

        assert mock_video.status == "QUEUED"
        assert result["processed"] == 1

    def test_extracts_size_from_event(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = MagicMock(name="video_record")
        mock_video.id = "video-123"

        mock_notif = MagicMock(name="notif_record")
        mock_notif.id = "notif-1"
        mock_notif.status = _FakeEnumMember("PENDING")
        mock_notif.extract_video_id.return_value = "video-123"
        mock_notif.event = {"Records": [{"s3": {"object": {"size": 4096}}}]}

        mock_session = MagicMock(name="session")

        notif_entity = tasks_mod.BucketNotificationEvent
        video_entity = tasks_mod.Video

        def fake_get(entity, entity_id):
            if entity is notif_entity:
                return mock_notif
            if entity is video_entity:
                return mock_video
            return MagicMock()

        mock_session.get.side_effect = fake_get

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        assert mock_video.size == 4096

    def test_creates_outbox_entry(self, _mock_heavy_deps):
        from app.tasks import process_notifications
        import app.tasks as tasks_mod

        mock_video = MagicMock(name="video_record")
        mock_video.id = "video-123"

        mock_notif = MagicMock(name="notif_record")
        mock_notif.id = "notif-1"
        mock_notif.status = _FakeEnumMember("PENDING")
        mock_notif.extract_video_id.return_value = "video-123"
        mock_notif.event = {"Records": [{"s3": {"object": {"size": 1024}}}]}

        mock_session = MagicMock(name="session")

        notif_entity = tasks_mod.BucketNotificationEvent
        video_entity = tasks_mod.Video

        def fake_get(entity, entity_id):
            if entity is notif_entity:
                return mock_notif
            if entity is video_entity:
                return mock_video
            return MagicMock()

        mock_session.get.side_effect = fake_get

        tasks_mod.get_sync_session = MagicMock(return_value=mock_session)
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_notif]

        process_notifications()

        mock_session.add.assert_called_once()
        outbox_arg = mock_session.add.call_args[0][0]
        assert MOCK_OUTBOX_CLASS.call_args[1]["topic"] == "video.processing"
        assert MOCK_OUTBOX_CLASS.call_args[1]["payload"]["video_id"] == "video-123"
