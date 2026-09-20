import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import init_db, close_db
from app.consumer import start_dlq_consumer
from app.routes import router as routes_router
from app.routes import start_pubsub_listener

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    consumer_task = asyncio.create_task(start_dlq_consumer())
    pubsub_task = asyncio.create_task(start_pubsub_listener())
    logger.info("Dashboard service started")
    yield
    consumer_task.cancel()
    pubsub_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    try:
        await pubsub_task
    except asyncio.CancelledError:
        pass
    await close_db()
    logger.info("Dashboard service stopped")


app = FastAPI(
    title="Dashboard Service",
    description="Consumes DLQ events, serves dashboard via WebSocket",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(routes_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
