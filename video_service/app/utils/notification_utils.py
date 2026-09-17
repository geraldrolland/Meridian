from urllib.parse import unquote


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
