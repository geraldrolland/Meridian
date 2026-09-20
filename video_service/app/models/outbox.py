import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class Outbox(SQLModel, table=True):
    """Transaction outbox for reliable event publishing."""

    __tablename__ = "outbox"

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
    video_id: str = Field(max_length=36, foreign_key="videos.id")
    retry_count: int = Field(default=0)
    retry_after: datetime | None = Field(default=None, nullable=True)
