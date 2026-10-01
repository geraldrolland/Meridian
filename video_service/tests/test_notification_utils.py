"""Tests for app.utils.notification_utils — URL/key helpers."""

from app.utils.notification_utils import (
    build_object_url,
    extract_video_id,
    object_key_from_event,
    object_key_from_url,
)


def _event(key="videos/vid1/file.mp4", endpoint="http://minio:9000", bucket="viduploads"):
    return {
        "EventName": "s3:ObjectCreated:Put",
        "Key": key,
        "Records": [
            {
                "responseElements": {
                    "x-amz-request-id": "REQ1",
                    "x-minio-origin-endpoint": endpoint,
                    "x-minio-deployment-id": "DEP1",
                },
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key, "size": 1024},
                },
            }
        ],
    }


class TestObjectKeyFromUrl:
    def test_extracts_key_for_matching_bucket(self):
        url = "http://minio:9000/viduploads/videos/vid1/final cut.mp4"
        assert object_key_from_url(url, "viduploads") == "videos/vid1/final cut.mp4"

    def test_returns_none_for_other_bucket(self):
        url = "http://minio:9000/manifest/videos/vid1/file.mp4"
        assert object_key_from_url(url, "viduploads") is None

    def test_returns_none_for_url_without_key(self):
        assert object_key_from_url("http://minio:9000/viduploads", "viduploads") is None

    def test_returns_none_for_non_string(self):
        assert object_key_from_url(None, "viduploads") is None


class TestObjectKeyFromEvent:
    def test_extracts_and_decodes_key(self):
        assert object_key_from_event(_event(key="videos/vid1/a%20b.mp4")) == "videos/vid1/a b.mp4"

    def test_returns_none_when_records_missing(self):
        assert object_key_from_event({}) is None

    def test_returns_none_for_empty_key(self):
        assert object_key_from_event(_event(key="")) is None


class TestExistingHelpers:
    def test_build_object_url(self):
        assert build_object_url(_event()) == "http://minio:9000/viduploads/videos/vid1/file.mp4"

    def test_extract_video_id(self):
        assert extract_video_id(_event(key="videos/vid1/file.mp4")) == "vid1"
        assert extract_video_id(_event(key="other/file.mp4")) is None
