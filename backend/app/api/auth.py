from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo_reset
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


class ResetStatus(BaseModel):
    running: bool
    available_in_seconds: int
    error: str | None


@router.get("/demo/reset", response_model=ResetStatus)
def demo_reset_status() -> dict:
    return demo_reset.status()


@router.post("/demo/reset", response_model=ResetStatus, status_code=202)
def reset_demo() -> dict:
    """Put every persona's data back to the start, for everyone. At most once every ten minutes."""
    try:
        demo_reset.start()
    except demo_reset.TooSoon as e:
        raise HTTPException(429, str(e)) from e
    return demo_reset.status()
