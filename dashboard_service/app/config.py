from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@dashboard-db:5432/dashboard_db"
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 4
    kafka_bootstrap_servers: str = "kafka:29092"
    kafka_dlq_topic: str = "video.DLQ"
    kafka_retry_topic: str = "video.retry"
    kafka_consumer_group_id: str = "meridian-dashboard-consumer-group"
    kafka_auto_offset_reset: str = "earliest"
    log_level: str = "info"
    jwt_secret: str = "test-secret"
    proxy_secret: str = "test-proxy-secret"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
