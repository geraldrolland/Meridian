import uuid
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import unquote

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field


class NotificationStatus(str, Enum):
    """Processing state of a bucket notification event."""

    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    FAILED = "FAILED"


class BucketNotificationEvent(SQLModel, table=True):
    """SQLModel table for bucket notification events."""

    __tablename__ = "bucket_notification_events"

    id: str = Field(primary_key=True, max_length=128)
    event: dict = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(
        default=NotificationStatus.PENDING.value,
        max_length=16,
    )
    video_id: str = Field(max_length=36, foreign_key="videos.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    def build_id(self) -> str:
        """Build unique ID from x-amz-request-id + x-minio-deployment-id."""
        try:
            record = self.event["Records"][0]
            request_id = record["responseElements"]["x-amz-request-id"]
            deployment_id = record["responseElements"]["x-minio-deployment-id"]
            return f"{request_id}{deployment_id}"
        except (KeyError, IndexError):
            return str(uuid.uuid4())

    def extract_video_id(self) -> str | None:
        """Extract video_id from the object key if it follows videos/{id}/{filename} format."""
        try:
            record = self.event["Records"][0]
            key = unquote(record["s3"]["object"]["key"])
            parts = key.split("/")
            if len(parts) >= 3 and parts[0] == "videos":
                return parts[1]
            return None
        except (KeyError, IndexError):
            return None
