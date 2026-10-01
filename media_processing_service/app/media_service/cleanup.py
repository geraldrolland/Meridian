"""Media cleanup utilities for removing bucket objects and temp files."""

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from app.minio_client import delete_object
from app.config import settings
from app.models.transcode_task import TranscodeTask
from app.models.upload_task import UploadTask
from app.utils import resolve_object_key

logger = logging.getLogger(__name__)


class MediaCleanup:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def cleanup_bucket(self, object_keys: list[str], bucket_name: str):
        """Delete multiple objects from a MinIO bucket concurrently."""
        if not object_keys:
            return
        with ThreadPoolExecutor(max_workers=len(object_keys)) as pool:
            futures = {
                pool.submit(delete_object, key, bucket_name): key
                for key in object_keys
            }
            for future in as_completed(futures):
                key = futures[future]
                future.result()
        logger.info("Cleaned up %d objects from %s", len(object_keys), bucket_name)

    def cleanup_temp_files(self, video_id: str):
        """Remove any file or directory whose name starts with *video_id*."""
        dirs = [
            settings.vid_download_dir,
            settings.vid_segment_dir,
            settings.vid_transcode_dir,
            settings.vid_thumbnail_dir,
        ]
        for base_dir in dirs:
            if not os.path.isdir(base_dir):
                continue
            for entry in os.listdir(base_dir):
                if entry.startswith(video_id):
                    path = os.path.join(base_dir, entry)
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    logger.info("Removed: %s", path)


def cleanup_jobs(jobs, db) -> None:
    """Remove a deleted video's job artifacts, then the job rows.

    Per job:
      1. upload files → object keys (``resolve_object_key``) → concurrent
         bucket deletes (one thread per key)
      2. thumbnail object (from ``vid_thumbnail_url``)
      3. local temp files for the video
      4. delete the job row (transcode/upload tasks cascade)

    Commits once after **all** jobs are deleted.

    Args:
        jobs: Job rows belonging to the deleted video.
        db: Open database session (caller closes it).
    """
    cleanup = MediaCleanup()
    for job in jobs:
        transcode_ids = [
            row.id
            for row in db.query(TranscodeTask.id)
            .filter(TranscodeTask.job_id == job.id)
            .all()
        ]
        upload_tasks = (
            db.query(UploadTask)
            .filter(UploadTask.transcode_id.in_(transcode_ids))
            .all()
            if transcode_ids
            else []
        )

        object_keys = []
        for upload_task in upload_tasks:
            for fp in upload_task.upload_files or []:
                object_keys.append(resolve_object_key(fp, settings.vid_transcode_dir))
        if object_keys:
            cleanup.cleanup_bucket(object_keys, settings.minio_segment_bucket)

        thumb_keys = []
        if job.vid_thumbnail_url:
            path_parts = urlparse(job.vid_thumbnail_url).path.lstrip("/").split("/", 1)
            if len(path_parts) > 1:
                thumb_keys.append(path_parts[1])
        if thumb_keys:
            cleanup.cleanup_bucket(thumb_keys, settings.minio_thumbnail_bucket)

        cleanup.cleanup_temp_files(job.video_id)
        db.delete(job)

    db.commit()
    logger.info("Cleaned up %d job(s) for deleted video", len(jobs))
