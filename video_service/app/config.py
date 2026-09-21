"""Centralized configuration for the video service.

All settings are loaded from environment variables via pydantic-settings.
Falls back to sensible defaults for local development.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings sourced from environment variables.

    Attributes:
        kafka_bootstrap_servers: Comma-separated Kafka broker addresses.
        kafka_topic: Topic for MinIO bucket notification events.
        kafka_consumer_group_id: Consumer group ID for the Kafka consumer.
        kafka_auto_offset_reset: Where to start reading when no committed offset exists.
        database_url: SQLAlchemy async database connection string.
        minio_endpoint: MinIO (S3-compatible) endpoint address.
        minio_access_key: MinIO access key.
        minio_secret_key: MinIO secret key.
        minio_bucket: Bucket name for video uploads.
        minio_secure: Whether to use HTTPS for MinIO connections.
        celery_broker_url: RabbitMQ broker URL for Celery task dispatch.
        celery_result_backend: Redis URL for Celery result storage.
        redis_host: Redis host for general use.
        redis_port: Redis port.
        redis_db: Redis database number for pub/sub.
        jwt_secret: JWT signing secret for WebSocket auth.
        proxy_secret: Shared HMAC-SHA256 secret for API gateway proxy signature verification.
        allowed_video_extensions: File extensions accepted for upload (without dot).
        multipart_threshold: File size in bytes above which multipart upload is used (100 MB).
        default_part_size: Part size in bytes for multipart uploads (5 MB).
        log_level: Python logging level.
    """
    kafka_bootstrap_servers: str = "kafka:29092"
    kafka_topic: str = "bucketnotifications"
    kafka_consumer_group_id: str = "meridian-video-consumer-group"
    kafka_auto_offset_reset: str = "earliest"
    kafka_processing_topic: str = "video.processing"
    kafka_processing_consumer_group_id: str = "meridian-video-processing-consumer-group"
    kafka_job_failed_topic: str = "job.failed"
    kafka_manifest_failed_topic: str = "manifest.failed"
    kafka_failure_consumer_group_id: str = "meridian-video-failure-consumer-group"
    kafka_manifest_generating_topic: str = "manifest.generating"
    kafka_manifest_generating_consumer_group_id: str = "meridian-video-manifest-generating-consumer-group"
    kafka_manifest_completed_topic: str = "manifest.completed"
    kafka_manifest_completed_consumer_group_id: str = "meridian-video-manifest-completed-consumer-group"
    database_url: str = "postgresql+asyncpg://postgres:postgres@video-db:5432/video_db"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "viduploads"
    minio_secure: bool = False
    celery_broker_url: str = "amqp://guest:guest@rabbitmq:5672//"
    celery_result_backend: str = "redis://redis:6379/1"
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 3
    jwt_secret: str = "test-secret"
    proxy_secret: str = "change-me-in-production"
    allowed_video_extensions: list[str] = ["mp4", "mov", "avi", "mkv", "webm", "flv", "wmv"]
    multipart_threshold: int = 100 * 1024 * 1024  # 100MB -- files larger than this use multipart
    default_part_size: int = 5 * 1024 * 1024      # 5MB -- chunk size for each part
    outbox_max_retry: int = 5
    bucketnotification_max_retry: int = 5
    log_level: str = "info"

    @property
    def db_dsn(self) -> str:
        return self.database_url

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
