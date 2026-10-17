"""Hearthline Public API v1: what partners, donors' apps and AI agents use. No login needed.

Preparing a gift returns a PayPal approval link; a person approves the payment there and nothing is
charged before that. The same operations are available as tools on the MCP server at /mcp.
"""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from paypalserversdk.exceptions.error_exception import ErrorException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import public_api as svc
from app.api.registry import paypal_reason
from app.db import get_db

router = APIRouter(prefix="/v1", tags=["Public API v1"])
DB = Annotated[Session, Depends(get_db)]


class Problem(BaseModel):
    """Why a request failed."""

    detail: str = Field(description="A sentence you can show to the person", examples=["Registry not found"])


def errors(*codes: int) -> dict:
    meaning = {
        404: "Not found",
        409: "Not possible right now (for example, the registry or fund isn't taking gifts)",
        502: "PayPal couldn't start the payment; nothing was charged",
    }
    return {code: {"model": Problem, "description": meaning[code]} for code in codes}


RegistrySlug = Annotated[str, Path(description="The registry's slug", examples=["rivera-family"])]
FundSlug = Annotated[str, Path(description="The Reopen Fund's slug", examples=["morenos-bakery"])]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.PublicError as e:
        raise HTTPException(e.status, str(e)) from None
    except ErrorException as e:
        raise HTTPException(502, f"PayPal couldn't start the payment: {paypal_reason(e)}") from None


class DonationRequest(BaseModel):
    """A gift to a family: toward one item, or to the household fund."""

    amount: Decimal = Field(gt=0, le=10000, description="USD", examples=[50])
    item_id: int | None = Field(default=None, description="A registry item; omit to give to the household fund")
    donor_name: str | None = Field(default=None, max_length=80, description="Shown to the family")
    message: str = Field(default="", max_length=280, description="A note for the family")


class GiftCardRequest(BaseModel):
    """A gift card bought ahead from a closed business; it's worth the bonus percent more in the shop."""

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
    limit: Annotated[int, Query(ge=1, le=100, description="At most this many registries")] = 20,
) -> list[svc.RegistrySummary]:
    """Families' verified Rebuild Registries, those that still need the most first."""
    return svc.find_registries(db, q, limit)


@router.get("/registries/{slug}", response_model=svc.RegistryDetail, operation_id="getRegistry", responses=errors(404))
def get_registry(slug: RegistrySlug, db: DB) -> svc.RegistryDetail:
    """A registry with every item and what it still needs."""
    return run(svc.registry_detail, db, slug)


@router.post(
    "/registries/{slug}/donations",
    response_model=svc.Checkout,
    status_code=201,
    operation_id="prepareDonation",
    responses=errors(404, 409, 502),
)
def prepare_donation(slug: RegistrySlug, body: DonationRequest, db: DB) -> svc.Checkout:
    """Prepare a gift to a family. Returns a PayPal link the donor opens to approve it."""
    return run(svc.start_donation, db, slug, body.amount, body.item_id, body.donor_name, body.message)


@router.get(
    "/donations/{donation_id}", response_model=svc.DonationStatus, operation_id="getDonation", responses=errors(404)
)
def get_donation(donation_id: Annotated[int, Path(description="From `Checkout.id`")], db: DB) -> svc.DonationStatus:
    """Where a gift went: paid, item bought, shipped, delivered."""
    return run(svc.donation_status, db, donation_id)


@router.get("/reopen-funds", response_model=list[svc.ReopenFund], operation_id="listReopenFunds")
def list_reopen_funds(
    db: DB,
    include_closed: Annotated[bool, Query(description="Also list funds that reopened, refunded or closed")] = False,
) -> list[svc.ReopenFund]:
    """Local businesses selling gift cards to pay for reopening."""
    return svc.reopen_funds(db, include_closed)


@router.get("/reopen-funds/{slug}", response_model=svc.ReopenFund, operation_id="getReopenFund", responses=errors(404))
def get_reopen_fund(slug: FundSlug, db: DB) -> svc.ReopenFund:
    """A business's Reopen Fund: its plan, what's raised and which steps' money staff have released."""
    return run(svc.reopen_fund, db, slug)


@router.post(
    "/reopen-funds/{slug}/gift-cards",
    response_model=svc.Checkout,
    status_code=201,
    operation_id="prepareGiftCard",
    responses=errors(404, 409, 502),
)
def prepare_gift_card(slug: FundSlug, body: GiftCardRequest, db: DB) -> svc.Checkout:
    """Prepare a gift card purchase. Returns a PayPal link the buyer opens to approve it."""
    return run(svc.start_gift_card, db, slug, body.amount, body.buyer_name)


@router.get("/gift-cards/{code}", response_model=svc.GiftCardStatus, operation_id="getGiftCard", responses=errors(404))
def get_gift_card(code: Annotated[str, Path(description="The card's code")], db: DB) -> svc.GiftCardStatus:
    """A gift card's balance and whether it can be spent yet."""
    return run(svc.gift_card, db, code)


@router.get("/price-watch", response_model=list[svc.PriceReport], operation_id="getPriceWatch")
def price_watch(
    db: DB,
    status: Annotated[
        Literal["ok", "gouging", "no_baseline", "unknown"] | None, Query(description="Only prices with this status")
    ] = None,
    category: Annotated[str | None, Query(description="Only this kind of essential, e.g. water or fuel")] = None,
) -> list[svc.PriceReport]:
    """Essential prices against their pre-disaster baseline (California's 10% limit)."""
    return svc.price_report(db, status, category)
