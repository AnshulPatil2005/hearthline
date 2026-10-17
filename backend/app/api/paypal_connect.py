"""Connect your PayPal account (Log in with PayPal): where the money you receive goes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import paypal_connect
from app.auth import CurrentUser
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/paypal/connect", tags=["paypal-connect"])
DB = Annotated[Session, Depends(get_db)]


class ReceivesOut(BaseModel):
    what: str
    current: str | None


class ConnectionOut(BaseModel):
    connected: bool
    name: str | None = None
    email: str | None = None  # the signed-in person's own address, shown to them in full
    verified_account: bool | None = None
    connected_at: datetime | None = None
    receives: list[ReceivesOut]
    available: bool  # PayPal credentials are configured on this server


def _status(db: Session, user) -> ConnectionOut:
    link = paypal_connect.link_for(db, user)
    receives = [ReceivesOut(what=r.what, current=r.current) for r in paypal_connect.receives(db, user)]
    available = get_settings().paypal_configured
    if link is None:
        return ConnectionOut(connected=False, receives=receives, available=available)
    return ConnectionOut(
        connected=True,
        name=link.name,
        email=link.email,
        verified_account=link.verified_account,
        connected_at=link.connected_at,
        receives=receives,
        available=available,
    )


@router.get("", response_model=ConnectionOut)
def connection(user: CurrentUser, db: DB) -> ConnectionOut:
    return _status(db, user)


class Started(BaseModel):
    authorize_url: str


@router.post("/start", response_model=Started)
def start(user: CurrentUser, db: DB) -> Started:
    if not paypal_connect.receives(db, user):
        raise HTTPException(409, "Only households, contractors and businesses receive money through Hearthline.")
    if not get_settings().paypal_configured:
        raise HTTPException(503, "PayPal isn't configured on this server")
    return Started(authorize_url=paypal_connect.start(user))


class Finish(BaseModel):
    code: str = Field(min_length=4, max_length=2000)
    state: str = Field(min_length=10, max_length=2000)


@router.post("/finish", response_model=ConnectionOut)
def finish(body: Finish, user: CurrentUser, db: DB) -> ConnectionOut:
    """PayPal's return page posts the code here; the account becomes where this person's money goes."""
    try:
        paypal_connect.finish(db, user, body.code, body.state)
    except paypal_connect.ConnectError as e:
        raise HTTPException(400, str(e)) from e
    return _status(db, user)
