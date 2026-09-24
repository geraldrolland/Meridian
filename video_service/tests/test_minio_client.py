import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_module(name: str) -> MagicMock:
    mod = MagicMock()
    mod.__name__ = name
    mod.__package__ = name
    return mod


@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    """Mock heavy dependencies so minio_client module can be imported."""
    mock_modules = {
        "app.config": _make_mock_module("app.config"),
        "minio": _make_mock_module("minio"),
        "minio.datatypes": _make_mock_module("minio.datatypes"),
    }

    for mod_name, mock_mod in mock_modules.items():
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, mock_mod)

    import app.config as cfg_mod
    cfg_mod.settings = MagicMock()
    cfg_mod.settings.minio_endpoint = "minio:9000"
    cfg_mod.settings.minio_access_key = "minioadmin"
    cfg_mod.settings.minio_secret_key = "minioadmin"
    cfg_mod.settings.minio_secure = False
    cfg_mod.settings.minio_bucket = "viduploads"


class TestGenerateUploadData:
    def test_returns_correct_structure(self, _mock_heavy_deps):
        from minio.datatypes import PostPolicy

        fake_form_data = {
            "x-amz-algorithm": "AWS4-HMAC-SHA256",
            "policy": "eyJleHBpcmF0aW9uIjog...",
            "x-amz-signature": "abc123",
        }

        mock_minio_client = MagicMock()
        mock_minio_client.presigned_post_policy.return_value = fake_form_data

        with patch("app.minio_client.presign_client", mock_minio_client), \
             patch("app.minio_client.settings", sys.modules["app.config"].settings):
            from app.minio_client import generate_upload_data
            result = generate_upload_data("vid-123", "test.mp4", "video/mp4")

        assert "url" in result
        assert "fields" in result
        assert isinstance(result["url"], str)
        assert isinstance(result["fields"], dict)
        assert result["fields"]["key"] == "videos/vid-123/test.mp4"
        assert "x-amz-algorithm" in result["fields"]
        assert "policy" in result["fields"]
        assert "x-amz-signature" in result["fields"]

    def test_sets_content_type_condition(self, _mock_heavy_deps):
        mock_policy = MagicMock()
        fake_form_data = {"policy": "...", "x-amz-signature": "..."}

        mock_minio_client = MagicMock()
        mock_minio_client.presigned_post_policy.return_value = fake_form_data

        with patch("app.minio_client.presign_client", mock_minio_client), \
             patch("app.minio_client.settings", sys.modules["app.config"].settings), \
             patch("app.minio_client.PostPolicy", return_value=mock_policy):
            from app.minio_client import generate_upload_data
            generate_upload_data("vid-123", "test.mp4", "video/mp4")

        mock_policy.add_equals_condition.assert_called_once_with("key", "videos/vid-123/test.mp4")
        mock_policy.add_starts_with_condition.assert_called_once_with("Content-Type", "video/")
