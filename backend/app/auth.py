"""Bearer-token auth. Tokens are signed JWTs carrying the user id.

Bearer tokens (not cookies) because the web app and API live on different onrender.com
subdomains, which browsers treat as different sites.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, User

ALGORITHM = "HS256"
LOGIN = "login"  # the `purpose` of a sign-in token; other tokens signed with the same key carry their own
bearer = HTTPBearer(auto_error=False)


def issue_token(user: User) -> str:
    s = get_settings()
    expires = datetime.now(UTC) + timedelta(hours=s.token_ttl_hours)
    return jwt.encode({"sub": str(user.id), "purpose": LOGIN, "exp": expires}, s.secret_key, algorithm=ALGORITHM)


def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    try:
        claims = jwt.decode(creds.credentials, get_settings().secret_key, algorithms=[ALGORITHM])
        if claims.get("purpose", LOGIN) != LOGIN:  # tokens issued before purposes existed are sign-ins
            raise ValueError("not a sign-in token")
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def optional_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """The signed-in user if a valid token was sent, else None (for public pages like registries)."""
    if creds is None:
        return None
    try:
        return current_user(creds, db)
    except HTTPException:
        return None


OptionalUser = Annotated[User | None, Depends(optional_user)]


def require_role(*roles: Role) -> Callable[[User], User]:
    def check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return check
