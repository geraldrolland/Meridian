from app.models.video import (
    Video,
    VideoStatus,
    UploadRequest,
    PresignedPostUpload,
    MultipartUpload,
    UploadPartUrl,
    UploadPartResult,
)


class TestVideoStatusEnum:
    def test_queued_exists(self):
        assert hasattr(VideoStatus, "QUEUED")
        assert VideoStatus.QUEUED.value == "QUEUED"

    def test_all_statuses(self):
        expected = {"AWAITING_UPLOAD", "QUEUED", "PROCESSING", "GENERATING_MANIFEST", "COMPLETED", "FAILED", "RETRY"}
        actual = {s.value for s in VideoStatus}
        assert actual == expected


class TestVideoModel:
    def test_default_status_is_awaiting_upload(self):
        video = Video(filename="test.mp4")
        assert video.status == VideoStatus.AWAITING_UPLOAD.value

    def test_size_defaults_to_none(self):
        video = Video(filename="test.mp4")
        assert video.size is None

    def test_size_can_be_set(self):
        video = Video(filename="test.mp4", size=1024)
        assert video.size == 1024

    def test_user_id_defaults_to_none(self):
        video = Video(filename="test.mp4")
        assert video.user_id is None

    def test_user_id_can_be_set(self):
        video = Video(filename="test.mp4", user_id=42)
        assert video.user_id == 42

    def test_multipart_upload_id_defaults_to_none(self):
        video = Video(filename="test.mp4")
        assert video.multipart_upload_id is None

    def test_total_parts_defaults_to_none(self):
        video = Video(filename="test.mp4")
        assert video.total_parts is None

    def test_num_of_retries_defaults_to_zero(self):
        video = Video(filename="test.mp4")
        assert video.num_of_retries == 0

    def test_num_of_retries_can_be_set(self):
        video = Video(filename="test.mp4", num_of_retries=3)
        assert video.num_of_retries == 3

    def test_published_defaults_to_false(self):
        video = Video(filename="test.mp4")
        assert video.published is False

    def test_published_can_be_set(self):
        video = Video(filename="test.mp4", published=True)
        assert video.published is True

    def test_notif_reference_id_defaults_to_none(self):
        video = Video(filename="test.mp4")
        assert video.notif_reference_id is None

    def test_notif_reference_id_can_be_set(self):
        video = Video(filename="test.mp4", notif_reference_id="req123deploy456")
        assert video.notif_reference_id == "req123deploy456"


class TestUploadRequestModel:
    def test_upload_request_schema(self):
        body = UploadRequest(filename="test.mp4")
        assert body.filename == "test.mp4"

    def test_upload_request_defaults_content_type(self):
        body = UploadRequest(filename="test.mp4")
        assert body.content_type == "video/mp4"

    def test_upload_request_custom_content_type(self):
        body = UploadRequest(filename="test.webm", content_type="video/webm")
        assert body.content_type == "video/webm"

    def test_upload_request_file_size_default(self):
        body = UploadRequest(filename="test.mp4")
        assert body.file_size == 0

    def test_upload_request_file_size(self):
        body = UploadRequest(filename="test.mp4", file_size=1024 * 1024)
        assert body.file_size == 1024 * 1024


class TestPresignedPostUploadModel:
    def test_presigned_post_upload_validates(self):
        data = PresignedPostUpload(url="http://minio:9000/bucket", fields={"key": "test"})
        assert data.mode == "presigned_post"
        assert data.url == "http://minio:9000/bucket"
        assert data.fields == {"key": "test"}


class TestMultipartUploadModel:
    def test_multipart_upload_validates(self):
        data = MultipartUpload(
            video_id="vid-123",
            upload_id="upload-id-123",
            part_size=5 * 1024 * 1024,
            total_parts=10,
            parts=[UploadPartUrl(part_number=1, url="http://minio/part1")],
        )
        assert data.mode == "multipart"
        assert data.video_id == "vid-123"
        assert data.upload_id == "upload-id-123"
        assert data.total_parts == 10
        assert len(data.parts) == 1
