import json
import logging
import uuid

from kafka import KafkaProducer as SyncKafkaProducer
from kafka.errors import NoBrokersAvailable

from app.config import settings

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Singleton sync Kafka producer."""

    _instance: "KafkaProducer | None" = None
    _producer: SyncKafkaProducer | None = None

    def __new__(cls) -> "KafkaProducer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self) -> None:
        """Initialize the underlying SyncKafkaProducer. Safe to call multiple times."""
        if self._producer is not None:
            return
        self._producer = SyncKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
        )
        logger.info("Kafka producer initialized")

    def stop(self) -> None:
        """Close the producer."""
        if self._producer is not None:
            self._producer.close()
            self._producer = None
            KafkaProducer._instance = None
            logger.info("Kafka producer stopped")

    def publish(self, topic: str, payload: dict) -> None:
        from datetime import datetime, timezone
        """Publish a message to Kafka synchronously. Raises NoBrokersAvailable if broker is offline."""
        if self._producer is None:
            raise RuntimeError("Kafka producer not initialized")
        payload["event_id"] = uuid.uuid4().hex
        payload["timestamp"] = datetime.now(timezone.utc).timestamp()
        self._producer.send(topic, payload)
        self._producer.flush()
        logger.info("Published event to topic=%s", topic)


kafka_producer = KafkaProducer()
