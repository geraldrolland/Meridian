import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_module(name: str) -> MagicMock:
    mod = MagicMock()
    mod.__name__ = name
    mod.__package__ = name
    return mod


@pytest.fixture(autouse=True)
def _mock_deps(monkeypatch):
    for key in list(sys.modules):
        if key in ("app.lock", "app.database", "app.routes.ready"):
            monkeypatch.delitem(sys.modules, key, raising=False)

    mock_modules = {
        "app.config": _make_mock_module("app.config"),
        "app.database": _make_mock_module("app.database"),
        "app.lock": _make_mock_module("app.lock"),
        "app.minio_client": _make_mock_module("app.minio_client"),
        "kombu": _make_mock_module("kombu"),
    }

    for mod_name, mock_mod in mock_modules.items():
        monkeypatch.setitem(sys.modules, mod_name, mock_mod)

    import app.config as cfg
    cfg.settings = MagicMock()
    cfg.settings.minio_bucket = "vid_uploads"
    cfg.settings.celery_broker_url = "amqp://guest:guest@localhost:5672//"


def _make_async_conn(execute_side_effect=None):
    """Create a mock that behaves as an async context manager returning itself."""
    mock_conn = AsyncMock()
    if execute_side_effect:
        mock_conn.execute.side_effect = execute_side_effect
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    return mock_conn


def _setup_mocks(ready_mod, *, redis_ping_side_effect=None, db_execute_side_effect=None, minio_bucket_side_effect=None, rabbitmq_side_effect=None):
    """Helper to create and patch all four dependency mocks."""
    mock_redis = MagicMock()
    if redis_ping_side_effect:
        mock_redis.ping.side_effect = redis_ping_side_effect
    else:
        mock_redis.ping.return_value = True

    mock_conn = _make_async_conn(execute_side_effect=db_execute_side_effect)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    mock_minio = MagicMock()
    if minio_bucket_side_effect:
        mock_minio.bucket_exists.side_effect = minio_bucket_side_effect
    else:
        mock_minio.bucket_exists.return_value = True

    mock_kombu_conn = MagicMock()
    mock_kombu_conn.__enter__ = MagicMock(return_value=mock_kombu_conn)
    mock_kombu_conn.__exit__ = MagicMock(return_value=False)
    if rabbitmq_side_effect:
        mock_kombu_conn.connect.side_effect = rabbitmq_side_effect
    else:
        mock_kombu_conn.connect.return_value = True

    return mock_redis, mock_engine, mock_minio, mock_kombu_conn


class TestReadyEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200_when_all_healthy(self, _mock_deps):
        from app.routes import ready as ready_mod
        from fastapi import Response

        mock_redis, mock_engine, mock_minio, mock_kombu_conn = _setup_mocks(ready_mod)

        with patch.object(ready_mod, "redis_client", mock_redis), \
             patch.object(ready_mod, "db_engine", mock_engine), \
             patch.object(ready_mod, "minio_client", mock_minio), \
             patch.object(ready_mod, "Connection", MagicMock(return_value=mock_kombu_conn)):
            response = Response()
            result = await ready_mod.ready(response=response)

        assert response.status_code == 200
        assert result == {"status": "ok", "redis": "ok", "db": "ok", "minio": "ok", "rabbitmq": "ok"}

    @pytest.mark.asyncio
    async def test_returns_500_when_redis_down(self, _mock_deps):
        from app.routes import ready as ready_mod
        from fastapi import Response

        mock_redis, mock_engine, mock_minio, mock_kombu_conn = _setup_mocks(
            ready_mod, redis_ping_side_effect=Exception("Connection refused")
        )

        with patch.object(ready_mod, "redis_client", mock_redis), \
             patch.object(ready_mod, "db_engine", mock_engine), \
             patch.object(ready_mod, "minio_client", mock_minio), \
             patch.object(ready_mod, "Connection", MagicMock(return_value=mock_kombu_conn)):
            response = Response()
            result = await ready_mod.ready(response=response)

        assert response.status_code == 500
        assert result["redis"] == "unreachable"
        assert result["db"] == "ok"
        assert result["minio"] == "ok"
        assert result["rabbitmq"] == "ok"

    @pytest.mark.asyncio
    async def test_returns_500_when_db_down(self, _mock_deps):
        from app.routes import ready as ready_mod
        from fastapi import Response

        mock_redis, mock_engine, mock_minio, mock_kombu_conn = _setup_mocks(
            ready_mod, db_execute_side_effect=Exception("Connection refused")
        )

        with patch.object(ready_mod, "redis_client", mock_redis), \
             patch.object(ready_mod, "db_engine", mock_engine), \
             patch.object(ready_mod, "minio_client", mock_minio), \
             patch.object(ready_mod, "Connection", MagicMock(return_value=mock_kombu_conn)):
            response = Response()
            result = await ready_mod.ready(response=response)

        assert response.status_code == 500
        assert result["redis"] == "ok"
        assert result["db"] == "unreachable"
        assert result["minio"] == "ok"
        assert result["rabbitmq"] == "ok"

    @pytest.mark.asyncio
    async def test_returns_500_when_minio_down(self, _mock_deps):
        from app.routes import ready as ready_mod
        from fastapi import Response

        mock_redis, mock_engine, mock_minio, mock_kombu_conn = _setup_mocks(
            ready_mod, minio_bucket_side_effect=Exception("Connection refused")
        )

        with patch.object(ready_mod, "redis_client", mock_redis), \
             patch.object(ready_mod, "db_engine", mock_engine), \
             patch.object(ready_mod, "minio_client", mock_minio), \
             patch.object(ready_mod, "Connection", MagicMock(return_value=mock_kombu_conn)):
            response = Response()
            result = await ready_mod.ready(response=response)

        assert response.status_code == 500
        assert result["redis"] == "ok"
        assert result["db"] == "ok"
        assert result["minio"] == "unreachable"
        assert result["rabbitmq"] == "ok"

    @pytest.mark.asyncio
    async def test_returns_500_when_rabbitmq_down(self, _mock_deps):
        from app.routes import ready as ready_mod
        from fastapi import Response

        mock_redis, mock_engine, mock_minio, mock_kombu_conn = _setup_mocks(
            ready_mod, rabbitmq_side_effect=Exception("Connection refused")
        )

        with patch.object(ready_mod, "redis_client", mock_redis), \
             patch.object(ready_mod, "db_engine", mock_engine), \
             patch.object(ready_mod, "minio_client", mock_minio), \
             patch.object(ready_mod, "Connection", MagicMock(return_value=mock_kombu_conn)):
            response = Response()
            result = await ready_mod.ready(response=response)

        assert response.status_code == 500
        assert result["redis"] == "ok"
        assert result["db"] == "ok"
        assert result["minio"] == "ok"
        assert result["rabbitmq"] == "unreachable"

    @pytest.mark.asyncio
    async def test_returns_500_when_all_down(self, _mock_deps):
        from app.routes import ready as ready_mod
        from fastapi import Response

        mock_redis, mock_engine, mock_minio, mock_kombu_conn = _setup_mocks(
            ready_mod,
            redis_ping_side_effect=Exception("Connection refused"),
            db_execute_side_effect=Exception("Connection refused"),
            minio_bucket_side_effect=Exception("Connection refused"),
            rabbitmq_side_effect=Exception("Connection refused"),
        )

        with patch.object(ready_mod, "redis_client", mock_redis), \
             patch.object(ready_mod, "db_engine", mock_engine), \
             patch.object(ready_mod, "minio_client", mock_minio), \
             patch.object(ready_mod, "Connection", MagicMock(return_value=mock_kombu_conn)):
            response = Response()
            result = await ready_mod.ready(response=response)

        assert response.status_code == 500
        assert result["redis"] == "unreachable"
        assert result["db"] == "unreachable"
        assert result["minio"] == "unreachable"
        assert result["rabbitmq"] == "unreachable"
