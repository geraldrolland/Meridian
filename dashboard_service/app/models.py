from datetime import datetime, timezone
from enum import Enum

from sqlmodel import SQLModel, Field


class VideoStatus(str, Enum):
    FAILED = "FAILED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class DashboardVideo(SQLModel, table=True):
    __tablename__ = "dashboard_videos"

    id: str = Field(max_length=36, primary_key=True)
    user_id: int = Field(nullable=False, index=True)
    filename: str = Field(max_length=512)
    status: str = Field(default=VideoStatus.FAILED.value, max_length=32)
    reason: str | None = Field(default=None, max_length=512)
    retry_count: int = Field(default=0)
    last_retry_at: datetime | None = Field(default=None)
    final_status: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class DLQEvent(SQLModel):
    video_id: str
    user_id: int
    filename: str
    reason: str = "processing_failed"


class RetryRequest(SQLModel):
    video_id: str
