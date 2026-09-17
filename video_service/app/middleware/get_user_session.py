import json
import logging
from urllib.parse import unquote

from fastapi import Request

from app.models.session import SessionData

logger = logging.getLogger(__name__)


async def get_user_session(request: Request) -> SessionData | None:
    """FastAPI dependency that extracts session data from the ``session`` cookie.

    The API gateway serializes ``SessionData`` as URI-encoded JSON in a
    ``session`` cookie on every proxied request.

    Returns ``None`` if the cookie is missing (allows unauthenticated access).
    Raises no exception on invalid cookie — logs and returns ``None``.
    """
    session_cookie = request.cookies.get("session")
    if not session_cookie:
        return None

    try:
        session = SessionData.model_validate_json(unquote(session_cookie))
        return session
    except Exception:
        logger.warning("Invalid session cookie")
        return None
