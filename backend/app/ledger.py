"""Double-entry ledger: every money movement is a balanced set of postings.

Accounts (all USD):
- `assets:paypal`               cash in Hearthline's PayPal account
- `liabilities:household:<id>`  money held on behalf of a household (donations not yet spent)
- `expenses:paypal_fees`        PayPal processing fees (absorbed by the platform, not the family)

A donation debits cash and credits the household; a purchase or payout does the reverse.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LedgerAccount, LedgerPosting, LedgerTransaction

CASH = "assets:paypal"
FEES = "expenses:paypal_fees"
CASH_AID = "expenses:cash_aid"

ACCOUNT_DEFAULTS = {
    CASH: ("PayPal balance", "asset"),
    FEES: ("PayPal fees", "expense"),
    CASH_AID: ("Cash aid paid by the relief organization", "expense"),
}


class UnbalancedTransaction(ValueError):
    pass


def household_fund(household_id: int) -> str:
    return f"liabilities:household:{household_id}"


def account(db: Session, code: str) -> LedgerAccount:
    acct = db.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
    if acct is None:
        if code.startswith("liabilities:household:"):
            household_id = int(code.rsplit(":", 1)[1])
            name, kind = f"Funds held for household {household_id}", "liability"
        elif code.startswith("liabilities:escrow:project:"):
            name, kind = f"Escrow for rebuild project {code.rsplit(':', 1)[1]}", "liability"
            household_id = None
        else:
            name, kind = ACCOUNT_DEFAULTS[code]
            household_id = None
        acct = LedgerAccount(code=code, name=name, kind=kind, household_id=household_id)
        db.add(acct)
        db.flush()
    return acct


def post(
    db: Session,
    *,
    kind: str,
    description: str,
    lines: dict[str, Decimal],
    household_id: int | None = None,
    paypal_ref: str | None = None,
    meta: dict | None = None,
) -> LedgerTransaction:
    """Record one balanced transaction. `lines` maps account code -> signed amount (debit +, credit -).
    Posting the same `paypal_ref` twice returns the existing transaction (webhooks are retried)."""
    if paypal_ref:
        existing = db.scalar(select(LedgerTransaction).where(LedgerTransaction.paypal_ref == paypal_ref))
        if existing is not None:
            return existing
    if sum(lines.values(), Decimal(0)) != 0:
        raise UnbalancedTransaction(f"{kind}: postings sum to {sum(lines.values())}, not 0")
    txn = LedgerTransaction(
        kind=kind, description=description, household_id=household_id, paypal_ref=paypal_ref, meta=meta or {}
    )
    for code, amount in lines.items():
        if amount != 0:
            txn.postings.append(LedgerPosting(account=account(db, code), amount=amount))
    db.add(txn)
    db.flush()
    return txn


def record_donation(
    db: Session, *, household_id: int, gross: Decimal, fee: Decimal, capture_id: str, description: str, meta: dict
) -> LedgerTransaction:
    """Donor pays `gross`; PayPal keeps `fee`; the household's fund is credited the full gross."""
    return post(
        db,
        kind="donation",
        description=description,
        household_id=household_id,
        paypal_ref=capture_id,
        meta=meta,
        lines={CASH: gross - fee, FEES: fee, household_fund(household_id): -gross},
    )


def record_spend(
    db: Session, *, kind: str, household_id: int, amount: Decimal, paypal_ref: str, description: str, meta: dict
) -> LedgerTransaction:
    """Money leaves Hearthline on the household's behalf (a purchase or a payout)."""
    return post(
        db,
        kind=kind,
        description=description,
        household_id=household_id,
        paypal_ref=paypal_ref,
        meta=meta,
        lines={household_fund(household_id): amount, CASH: -amount},
    )


def balance(db: Session, code: str) -> Decimal:
    """Debit-positive balance. A household fund (a liability) is negative while it holds money."""
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerPosting.amount), 0)).join(LedgerAccount).where(LedgerAccount.code == code)
    )
    return Decimal(total).quantize(Decimal("0.01"))


def household_available(db: Session, household_id: int) -> Decimal:
    """Money currently held for a household, as a positive number."""
    return -balance(db, household_fund(household_id))
