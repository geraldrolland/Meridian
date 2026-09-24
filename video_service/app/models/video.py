import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel
from sqlmodel import SQLModel, Field


class VideoStatus(str, Enum):
    """Lifecycle states for a video record."""

    AWAITING_UPLOAD = "AWAITING_UPLOAD"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    GENERATING_MANIFEST = "GENERATING_MANIFEST"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY = "RETRY"


class UploadRequest(BaseModel):
    """Pydantic model for upload request body validation."""

    filename: str
    content_type: str = "video/mp4"
    file_size: int = 0


class PresignedPostUpload(BaseModel):
    """Response for small file uploads (single presigned POST)."""

    mode: str = "presigned_post"
    url: str
    fields: dict[str, str]


class UploadPartUrl(BaseModel):
    """A single part's presigned URL."""

    part_number: int
    url: str


class MultipartUpload(BaseModel):
    """Response for large file uploads (multipart)."""

    mode: str = "multipart"
    video_id: str
    upload_id: str
    part_size: int
    total_parts: int
    parts: list[UploadPartUrl]


class UploadPartResult(BaseModel):
    """A completed part with its ETag."""

    part_number: int
    etag: str


class CompleteUploadRequest(BaseModel):
    """Request to complete a multipart upload."""

    upload_id: str
    parts: list[UploadPartResult]


class AbortUploadRequest(BaseModel):
    """Request to abort a multipart upload."""

    upload_id: str


class Video(SQLModel, table=True):
    """SQLModel table for videos."""

    __tablename__ = "videos"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        max_length=36,
    )
    filename: str = Field(max_length=512)
    size: int | None = Field(default=None, nullable=True)
    user_id: int = Field(nullable=False)
    status: str = Field(
        default=VideoStatus.AWAITING_UPLOAD.value,
        max_length=32,
    )
    upload_url: str | None = Field(default=None, max_length=2048)
    video_url: str | None = Field(default=None, max_length=2048, exclude=True)
    multipart_upload_id: str | None = Field(default=None, max_length=256, nullable=True)
    total_parts: int | None = Field(default=None, nullable=True)
    num_of_retries: int = Field(default=0)
    notif_reference_id: str | None = Field(default=None, max_length=128, unique=True, nullable=True)
    thumbnail_url: str | None = Field(default=None, max_length=2048, nullable=True)
    # Existing DBs: ALTER TABLE videos ADD COLUMN IF NOT EXISTS manifest_url VARCHAR(2048);
    manifest_url: str | None = Field(default=None, max_length=2048, nullable=True)
    published: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
