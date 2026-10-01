import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, JSON, ForeignKeyConstraint
from sqlmodel import SQLModel, Field


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class Outbox(SQLModel, table=True):
    """Transaction outbox for reliable event publishing."""

    __tablename__ = "outbox"

    # video_id must not block DELETE on videos: the row survives with
    # video_id=NULL so events (e.g. video.deleted) stay publishable.
    # Existing DBs:
    #   ALTER TABLE outbox DROP CONSTRAINT IF EXISTS outbox_video_id_fkey;
    #   ALTER TABLE outbox ALTER COLUMN video_id DROP NOT NULL;
    #   ALTER TABLE outbox ADD CONSTRAINT outbox_video_id_fkey
    #     FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE SET NULL;
    __table_args__ = (
        ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            name="outbox_video_id_fkey",
            ondelete="SET NULL",
        ),
    )

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        max_length=36,
    )
    topic: str = Field(max_length=255)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    payload: dict = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default=OutboxStatus.PENDING.value, max_length=32)
    video_id: str | None = Field(default=None, max_length=36, nullable=True)
    retry_count: int = Field(default=0)
    retry_after: datetime | None = Field(default=None, nullable=True)
