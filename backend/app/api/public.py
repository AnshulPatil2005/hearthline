"""Hearthline Public API v1: what partners, donors' apps and AI agents use. No login needed.

Preparing a gift returns a PayPal approval link; a person approves the payment there and nothing is
charged before that. The same operations are available as tools on the MCP server at /mcp.
"""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from paypalserversdk.exceptions.error_exception import ErrorException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import public_api as svc
from app.api.registry import paypal_reason
from app.db import get_db

router = APIRouter(prefix="/v1", tags=["Public API v1"])
DB = Annotated[Session, Depends(get_db)]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.PublicError as e:
        raise HTTPException(e.status, str(e)) from None
    except ErrorException as e:
        raise HTTPException(502, f"PayPal couldn't start the payment: {paypal_reason(e)}") from None


class DonationRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=10000, description="USD", examples=[50])
    item_id: int | None = Field(default=None, description="A registry item; omit to give to the household fund")
    donor_name: str | None = Field(default=None, max_length=80, description="Shown to the family")
    message: str = Field(default="", max_length=280)


class GiftCardRequest(BaseModel):
    amount: Decimal = Field(ge=10, le=500, description="USD", examples=[50])
    buyer_name: str | None = Field(default=None, max_length=80, description="Shown as a supporter")


@router.get("/disasters", response_model=list[svc.Disaster], operation_id="listDisasters")
def list_disasters(db: DB) -> list[svc.Disaster]:
    """Disasters Hearthline is responding to."""
    return svc.disasters(db)


@router.get("/registries", response_model=list[svc.RegistrySummary], operation_id="findRegistries")
def find_registries(
    db: DB,
    q: Annotated[str | None, Query(description="Words in the title, story or items, e.g. 'mattress'")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[svc.RegistrySummary]:
    """Families' verified Rebuild Registries, those that still need the most first."""
    return svc.find_registries(db, q, limit)


@router.get("/registries/{slug}", response_model=svc.RegistryDetail, operation_id="getRegistry")
def get_registry(slug: str, db: DB) -> svc.RegistryDetail:
    """A registry with every item and what it still needs."""
    return run(svc.registry_detail, db, slug)


@router.post(
    "/registries/{slug}/donations", response_model=svc.Checkout, status_code=201, operation_id="prepareDonation"
)
def prepare_donation(slug: str, body: DonationRequest, db: DB) -> svc.Checkout:
    """Prepare a gift to a family. Returns a PayPal link the donor opens to approve it."""
    return run(svc.start_donation, db, slug, body.amount, body.item_id, body.donor_name, body.message)


@router.get("/donations/{donation_id}", response_model=svc.DonationStatus, operation_id="getDonation")
def get_donation(donation_id: int, db: DB) -> svc.DonationStatus:
    """Where a gift went: paid, item bought, shipped, delivered."""
    return run(svc.donation_status, db, donation_id)


@router.get("/reopen-funds", response_model=list[svc.ReopenFund], operation_id="listReopenFunds")
def list_reopen_funds(db: DB, include_closed: bool = False) -> list[svc.ReopenFund]:
    """Local businesses selling gift cards to pay for reopening."""
    return svc.reopen_funds(db, include_closed)


@router.get("/reopen-funds/{slug}", response_model=svc.ReopenFund, operation_id="getReopenFund")
def get_reopen_fund(slug: str, db: DB) -> svc.ReopenFund:
    return run(svc.reopen_fund, db, slug)


@router.post(
    "/reopen-funds/{slug}/gift-cards", response_model=svc.Checkout, status_code=201, operation_id="prepareGiftCard"
)
def prepare_gift_card(slug: str, body: GiftCardRequest, db: DB) -> svc.Checkout:
    """Prepare a gift card purchase. Returns a PayPal link the buyer opens to approve it."""
    return run(svc.start_gift_card, db, slug, body.amount, body.buyer_name)


@router.get("/gift-cards/{code}", response_model=svc.GiftCardStatus, operation_id="getGiftCard")
def get_gift_card(code: str, db: DB) -> svc.GiftCardStatus:
    return run(svc.gift_card, db, code)


@router.get("/price-watch", response_model=list[svc.PriceReport], operation_id="getPriceWatch")
def price_watch(
    db: DB,
    status: Literal["ok", "gouging", "no_baseline", "unknown"] | None = None,
    category: str | None = None,
) -> list[svc.PriceReport]:
    """Essential prices against their pre-disaster baseline (California's 10% limit)."""
    return svc.price_report(db, status, category)
