import logging

from aiokafka import TopicPartition, ConsumerRebalanceListener

logger = logging.getLogger(__name__)


class AppRebalanceListener(ConsumerRebalanceListener):
    """Logs Kafka partition rebalance events for the video consumer group."""

    async def on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        logger.info("Partitions revoked: %s", revoked)

    async def on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        logger.info("Partitions assigned: %s", assigned)
