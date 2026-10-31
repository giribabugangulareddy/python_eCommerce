import re
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from src.core.database import get_next_id, get_users
from src.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from src.schemas.commerce import TokenResponse, UserCreate, UserLogin, UserResponse

router = APIRouter(tags=["authentication"])
bearer_scheme = HTTPBearer(auto_error=False)
Users = Annotated[Collection, Depends(get_users)]


def _public_user(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["id"],
        "email": document["email"],
        "name": document["name"],
        "role": document["role"],
        "created_at": document["created_at"],
    }


@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: UserCreate, users: Users) -> dict[str, Any]:
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    document = {
        "id": get_next_id("users"),
        "email": email,
        "name": payload.name.strip(),
        "password_hash": hash_password(payload.password),
        "role": "customer",
        "active": True,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        users.insert_one(document)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        ) from error
    return _public_user(document)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: UserLogin, users: Users) -> dict[str, Any]:
    email = payload.email.strip().lower()
    user = users.find_one({"email": email, "active": True})
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "access_token": create_access_token(user["id"], user["role"]),
        "user": _public_user(user),
    }


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    users: Users,
) -> dict[str, Any]:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
        raise unauthorized from error
    user = users.find_one({"id": user_id, "active": True})
    if user is None or claims.get("role") != user.get("role"):
        raise unauthorized
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def require_admin(user: CurrentUser) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


AdminUser = Annotated[dict[str, Any], Depends(require_admin)]


@router.get("/auth/me", response_model=UserResponse)
def get_profile(user: CurrentUser) -> dict[str, Any]:
    return _public_user(user)
