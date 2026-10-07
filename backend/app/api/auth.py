from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, issue_token
from app.db import get_db
from app.models import User
from app.schemas import DemoLoginIn, TokenOut, UserOut

router = APIRouter(tags=["auth"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/auth/personas", response_model=list[UserOut])
def list_personas(db: DB) -> list[User]:
    """Demo accounts judges can sign in as with one click."""
    return list(db.scalars(select(User).where(User.is_demo).order_by(User.id)))


@router.post("/auth/demo-login", response_model=TokenOut)
def demo_login(body: DemoLoginIn, db: DB) -> TokenOut:
    user = db.get(User, body.user_id)
    if user is None or not user.is_demo:
        raise HTTPException(404, "No such demo persona")
    return TokenOut(token=issue_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
