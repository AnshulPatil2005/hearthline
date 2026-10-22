"""The household's money trail: every ledger transaction that touched its fund."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ledger
from app.api.households import MyHousehold
from app.db import get_db
from app.models import AidBatch, AidBatchItem, LedgerAccount, LedgerPosting, LedgerTransaction
from app.schemas import Money

router = APIRouter(tags=["ledger"])
DB = Annotated[Session, Depends(get_db)]


class PostingOut(BaseModel):
    account_code: str
    account_name: str
    amount: Money  # debit positive, credit negative


class LedgerRowOut(BaseModel):
    id: int
    kind: str
    description: str
    created_at: datetime
    paypal_ref: str | None
    amount: Money  # effect on the household's fund: + money in, - money out
    balance: Money  # household fund after this transaction
    postings: list[PostingOut]


@router.get("/households/me/ledger", response_model=list[LedgerRowOut])
def household_ledger(home: MyHousehold, db: DB) -> list[LedgerRowOut]:
    fund_code = ledger.household_fund(home.id)
    # A subquery, not DISTINCT: Postgres can't compare the JSON `meta` column, so DISTINCT over the rows fails there.
    touching = select(LedgerPosting.transaction_id).join(LedgerAccount).where(LedgerAccount.code == fund_code)
    txns = db.scalars(
        select(LedgerTransaction).where(LedgerTransaction.id.in_(touching)).order_by(LedgerTransaction.id)
    )
    rows, balance = [], Decimal(0)
    for txn in txns:
        effect = -sum((p.amount for p in txn.postings if p.account.code == fund_code), Decimal(0))
        balance += effect
        rows.append(
            LedgerRowOut(
                id=txn.id,
                kind=txn.kind,
                description=txn.description,
                created_at=txn.created_at,
                paypal_ref=txn.paypal_ref,
                amount=effect,
                balance=balance,
                postings=[
                    PostingOut(account_code=p.account.code, account_name=p.account.name, amount=p.amount)
                    for p in txn.postings
                ],
            )
        )
    return list(reversed(rows))  # newest first


class BatchAidOut(BaseModel):
    id: int
    title: str
    amount: Money
    status: str  # PayPal's payout status: PENDING, SUCCESS, UNCLAIMED, ... (or failed if the batch wasn't sent)
    receiver: str
    first_72_hours: bool
    sent_at: datetime | None


@router.get("/households/me/batch-aid", response_model=list[BatchAidOut])
def household_batch_aid(home: MyHousehold, db: DB) -> list[BatchAidOut]:
    """Cash aid paid straight to the household's PayPal account in a batch (it never passes through the fund)."""
    items = db.scalars(
        select(AidBatchItem)
        .join(AidBatch)
        .where(AidBatchItem.household_id == home.id, AidBatchItem.status.not_in(("queued", "skipped")))
        .order_by(AidBatchItem.id.desc())
    )
    return [
        BatchAidOut(
            id=i.id,
            title=i.batch.title,
            amount=i.amount,
            status=i.status,
            receiver=i.receiver,
            first_72_hours="rapid_aid_trigger" in (i.batch.rule or {}),
            sent_at=i.batch.decided_at,
        )
        for i in items
    ]
