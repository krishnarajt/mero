from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from app.services.auth_service import read_token


@dataclass
class CurrentUser:
    id: int
    username: str


async def get_current_user(authorization: str = Header(default="")) -> CurrentUser:
    """Resolve the bearer token to a user, or 401.

    The token is signed and carries the username, so this never touches the
    database.
    """
    token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    parsed = read_token(token) if token else None
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not logged in",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(*parsed)
