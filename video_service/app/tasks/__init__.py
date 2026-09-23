"""Celery tasks package for the video service."""

from app.tasks.process_notifications import process_notifications  # noqa: F401
from app.tasks.process_queued_videos import process_queued_videos  # noqa: F401
from app.tasks.process_outbox_events import process_outbox_events  # noqa: F401
