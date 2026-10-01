import uuid
from urllib.parse import unquote, urlparse


def build_object_url(event: dict) -> str | None:
    """Build the full MinIO object URL from a notification event payload.

    Extracts endpoint, bucket name, and object key from the event
    and returns: "{endpoint}/{bucket}/{key}"
    """
    try:
        record = event["Records"][0]
        endpoint = record["responseElements"]["x-minio-origin-endpoint"]
        bucket = record["s3"]["bucket"]["name"]
        key = unquote(record["s3"]["object"]["key"])
        return f"{endpoint}/{bucket}/{key}"
    except (KeyError, IndexError):
        return None


def object_key_from_url(object_url: str, bucket: str) -> str | None:
    """Extract the object key from a MinIO object URL ("{endpoint}/{bucket}/{key}").

    Returns None when the URL does not point into ``bucket`` — callers must not
    delete anything in that case.
    """
    if not isinstance(object_url, str):
        return None
    try:
        segments = urlparse(object_url).path.lstrip("/").split("/", 1)
        if len(segments) != 2 or segments[0] != bucket or not segments[1]:
            return None
        return segments[1]
    except (AttributeError, TypeError, ValueError):
        return None


def object_key_from_event(event: dict) -> str | None:
    """Extract the URL-decoded object key from a MinIO notification event."""
    try:
        record = event["Records"][0]
        key = unquote(record["s3"]["object"]["key"])
        return key or None
    except (KeyError, IndexError):
        return None


def build_id(event: dict) -> str:
    """Build unique ID from x-amz-request-id + x-minio-deployment-id."""
    try:
        record = event["Records"][0]
        request_id = record["responseElements"]["x-amz-request-id"]
        deployment_id = record["responseElements"]["x-minio-deployment-id"]
        return f"{request_id}{deployment_id}"
    except (KeyError, IndexError):
        return str(uuid.uuid4())


def extract_video_id(event: dict) -> str | None:
    """Extract video_id from the object key if it follows videos/{id}/{filename} format."""
    try:
        record = event["Records"][0]
        key = unquote(record["s3"]["object"]["key"])
        parts = key.split("/")
        if len(parts) >= 3 and parts[0] == "videos":
            return parts[1]
        return None
    except (KeyError, IndexError):
        return None
