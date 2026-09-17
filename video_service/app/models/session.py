from pydantic import BaseModel


class SessionData(BaseModel):
    """User session data extracted from the ``session`` cookie set by the API gateway."""

    userId: int
    role: str
    email: str
