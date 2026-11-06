"""Username + password accounts with stateless signed tokens.

Everything here is stdlib: scrypt for the password hash and an HMAC-signed
token, so there is no session table to hit on every request or socket.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    # Fine for a local run; in a deployment every restart would log everyone out.
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("SECRET_KEY not set: using a random one, tokens die on restart")

TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(365 * 24 * 3600)))

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt_hex), n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _sign(payload: str) -> str:
    mac = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def make_token(user_id: int, username: str) -> str:
    name = base64.urlsafe_b64encode(username.encode()).rstrip(b"=").decode()
    payload = f"{user_id}.{name}.{int(time.time()) + TOKEN_TTL_SECONDS}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> tuple[int, str] | None:
    """Returns (user_id, username) for a valid token, else None."""
    try:
        uid, name, exp, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(f"{uid}.{name}.{exp}")):
            return None
        if int(exp) < time.time():
            return None
        username = base64.urlsafe_b64decode(name + "=" * (-len(name) % 4)).decode()
        return int(uid), username
    except (ValueError, UnicodeDecodeError):
        return None


async def create_user(db: AsyncSession, username: str, password_hash: str) -> User | None:
    """The new user, or None if the username is taken."""
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
