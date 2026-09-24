import logging
from datetime import datetime, timedelta

from minio import Minio
from minio.datatypes import PostPolicy

from app.config import settings

logger = logging.getLogger(__name__)

client = Minio(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)

# Used exclusively for presigned URLs handed to browsers. SigV4 signs the
# Host header, so the URL must be built with the endpoint the browser
# connects to (public), not the internal Docker hostname. `region` is set
# explicitly so minio-py signs locally instead of calling GetBucketLocation
# over HTTP against an endpoint that is unreachable from inside the container.
presign_client = Minio(
    endpoint=settings.minio_public_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
    region="us-east-1",
)


# ── Small file: single presigned POST ──────────────────────────────

def generate_upload_data(video_id: str, filename: str, content_type: str = "video/mp4") -> dict:
    """Generate presigned POST form data with Content-Type restriction.

    Returns a dict with:
      - url: the POST target URL (http://<public_endpoint>/<bucket>)
      - fields: dict of hidden form fields to include in the POST
    """
    object_key = f"videos/{video_id}/{filename}"
    policy = PostPolicy(settings.minio_bucket, datetime.utcnow() + timedelta(hours=2))
    policy.add_equals_condition("key", object_key)
    policy.add_starts_with_condition("Content-Type", "video/")
    form_data = presign_client.presigned_post_policy(policy)
    logger.info("Generated presigned POST data for object: %s", object_key)
    return {
        "url": f"http://{settings.minio_public_endpoint}/{settings.minio_bucket}",
        "fields": {**form_data, "key": object_key},
    }


# ── Large file: multipart upload ───────────────────────────────────

def initiate_multipart_upload(video_id: str, filename: str, content_type: str = "video/mp4") -> str:
    """Initiate a multipart upload server-side with Content-Type header.

    Returns the upload_id needed for part uploads.
    """
    object_key = f"videos/{video_id}/{filename}"
    upload_id = client._create_multipart_upload(
        settings.minio_bucket,
        object_key,
        headers={"Content-Type": content_type},
    )
    logger.info("Initiated multipart upload for %s — upload_id=%s", object_key, upload_id)
    return upload_id


def generate_part_urls(video_id: str, filename: str, upload_id: str, total_parts: int) -> list[dict]:
    """Generate presigned PUT URLs for each part.

    Returns a list of {"part_number": int, "url": str}.
    """
    object_key = f"videos/{video_id}/{filename}"
    urls = []
    for i in range(1, total_parts + 1):
        url = presign_client.get_presigned_url(
            "PUT",
            settings.minio_bucket,
            object_key,
            expires=timedelta(hours=2),
            extra_query_params={
                "uploadId": upload_id,
                "partNumber": str(i),
            },
        )
        urls.append({"part_number": i, "url": url})
    logger.info("Generated %d part URLs for %s", total_parts, object_key)
    return urls


def complete_multipart_upload(video_id: str, filename: str, upload_id: str, parts: list[dict]) -> dict:
    """Complete a multipart upload server-side.

    Args:
        parts: list of {"part_number": int, "etag": str}

    Returns:
        {"location": str, "etag": str}
    """
    from minio.datatypes import Part

    object_key = f"videos/{video_id}/{filename}"
    part_list = [Part(part_number=p["part_number"], etag=p["etag"]) for p in parts]
    result = client._complete_multipart_upload(
        settings.minio_bucket,
        object_key,
        upload_id,
        part_list,
    )
    logger.info("Completed multipart upload for %s — location=%s", object_key, result.location)
    return {"location": result.location, "etag": result.etag}


def abort_multipart_upload(video_id: str, filename: str, upload_id: str) -> None:
    """Abort a multipart upload, discarding all uploaded parts."""
    object_key = f"videos/{video_id}/{filename}"
    client._abort_multipart_upload(settings.minio_bucket, object_key, upload_id)
    logger.info("Aborted multipart upload for %s — upload_id=%s", object_key, upload_id)
