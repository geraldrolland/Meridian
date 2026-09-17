from celery import Celery

from app.config import settings

celery_app = Celery(
    "video_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    result_expires=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=False,
)

celery_app.conf.beat_schedule = {
    "process-notifications-every-15-seconds": {
        "task": "app.tasks.process_notifications",
        "schedule": 15.0,
    },
    "process-outbox-every-10-seconds": {
        "task": "app.tasks.process_outbox_events",
        "schedule": 10.0,
    },
}

celery_app.autodiscover_tasks(["app"])
