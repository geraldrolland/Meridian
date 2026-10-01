"""SQLModel table and enums for upload tasks."""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, Column, ForeignKeyConstraint
from sqlmodel import SQLModel, Field


class UploadStatus(str, Enum):
    """Upload state of a transcoded file."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadTask(SQLModel, table=True):
    """SQLModel table for upload tasks."""

    __tablename__ = "upload_tasks"

    # Cascades with transcode_tasks (which cascade with jobs) so one
    # db.delete(job) removes the whole tree.
    # Existing DBs:
    #   ALTER TABLE upload_tasks DROP CONSTRAINT IF EXISTS upload_tasks_transcode_id_fkey;
    #   ALTER TABLE upload_tasks ADD CONSTRAINT upload_tasks_transcode_id_fkey
    #     FOREIGN KEY (transcode_id) REFERENCES transcode_tasks(id) ON DELETE CASCADE;
    __table_args__ = (
        ForeignKeyConstraint(
            ["transcode_id"],
            ["transcode_tasks.id"],
            name="upload_tasks_transcode_id_fkey",
            ondelete="CASCADE",
        ),
    )

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        max_length=36,
    )
    transcode_id: str = Field(max_length=36)
    upload_files: list = Field(default=[], sa_column=Column(JSON, nullable=True))
    status: str = Field(default=UploadStatus.PENDING.value, max_length=16)
    num_of_retries: int = Field(default=0)
    retry_after: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
