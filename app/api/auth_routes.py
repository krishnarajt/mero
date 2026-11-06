from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.api.schemas import CredentialsRequest, TokenResponse, UserOut
from app.db.database import get_db
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user_id: int, username: str) -> TokenResponse:
    return TokenResponse(token=auth_service.make_token(user_id, username), user=UserOut(id=user_id, username=username))


@router.post("/register", response_model=TokenResponse)
async def register(body: CredentialsRequest, db: AsyncSession = Depends(get_db)):
    username = body.username.strip().lower()
    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Username required")
    # scrypt is deliberately slow; keep it off the event loop.
    password_hash = await run_in_threadpool(auth_service.hash_password, body.password)
    user = await auth_service.create_user(db, username, password_hash)
    if user is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")
    return _token_response(user.id, username)


@router.post("/login", response_model=TokenResponse)
async def login(body: CredentialsRequest, db: AsyncSession = Depends(get_db)):
    username = body.username.strip().lower()
    user = await auth_service.get_user_by_username(db, username)
    if user is None or not await run_in_threadpool(auth_service.verify_password, body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    return _token_response(user.id, username)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username)
