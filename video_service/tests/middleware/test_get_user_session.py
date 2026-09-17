import json
import pytest
from unittest.mock import MagicMock
from urllib.parse import quote


@pytest.fixture
def make_request():
    def _make(cookies=None):
        request = MagicMock()
        request.cookies = cookies or {}
        return request
    return _make


@pytest.mark.asyncio
async def test_valid_session_cookie(make_request):
    from app.middleware.get_user_session import get_user_session

    session_data = {"userId": 1, "role": "admin", "email": "a@b.com"}
    cookie = quote(json.dumps(session_data))
    request = make_request(cookies={"session": cookie})

    result = await get_user_session(request)

    assert result is not None
    assert result.userId == 1
    assert result.role == "admin"
    assert result.email == "a@b.com"


@pytest.mark.asyncio
async def test_missing_session_cookie(make_request):
    from app.middleware.get_user_session import get_user_session

    request = make_request(cookies={})

    result = await get_user_session(request)

    assert result is None


@pytest.mark.asyncio
async def test_invalid_session_cookie(make_request):
    from app.middleware.get_user_session import get_user_session

    request = make_request(cookies={"session": "%ZZinvalid"})

    result = await get_user_session(request)

    assert result is None
