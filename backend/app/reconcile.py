"""Our books against PayPal's: since the books were opened (the last demo reset), at most 31 days back.

- Every payout PayPal made must trace to a decision people approved in Hearthline: a cash-aid case, a contractor
  milestone, a Reopen step, a Shopper purchase or a batch aid payment (the payout item's `custom_field` is our
  sender_item_id), for the same amount.
- Every payment PayPal received must be a gift, gift card, regular's payment or insurance claim payment in our records,
  for the same amount;
  refunds must point at a payment we refunded.
- Anything we recorded that PayPal doesn't show is missing, unless it's newer than PayPal's report (up to 3 hours).
Seeded demo records (DEMO- ids) never touched PayPal and are left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AidBatch,
    AidBatchItem,
    AuditEvent,
    Case,
    Donation,
    GiftCard,
    GiftCardPayment,
    InsuranceClaim,
    Milestone,
    Purchase,
    ReadinessPayment,
    ReopenTranche,
    now,
)
from app.paypal import reporting

MAX_DAYS = 31
PAYOUT_SENT = "T0001"
REFUND = "T1107"


@dataclass
class Expected:
    """Something our books say moved through PayPal."""

    key: str  # PayPal transaction id (money in) or sender_item_id (payouts)
    direction: str  # in | out
    amount: Decimal
    at: datetime | None
    what: str  # a person-readable description
    currency: str = "USD"


@dataclass
class Line:
    status: str  # matched | amount_differs | not_in_books | missing_at_paypal | waiting | info
    direction: str  # in | out | refund | other
    amount: Decimal
    at: datetime | None
    paypal_id: str | None
    hearthline: str | None
    note: str
    currency: str = "USD"


@dataclass
class Report:
    start: datetime
    end: datetime
    paypal_refreshed_at: datetime | None
    lines: list[Line] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for line in self.lines if line.status == status)


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def books_opened(db: Session) -> datetime | None:
    seeded = db.scalar(
        select(AuditEvent.created_at).where(AuditEvent.action == "demo.seeded").order_by(AuditEvent.id.desc())
    )
    return _aware(seeded)


def window(db: Session, end: datetime | None = None) -> tuple[datetime, datetime]:
    end = end or now()
    earliest = end - timedelta(days=MAX_DAYS) + timedelta(minutes=5)
    opened = books_opened(db)
    return (max(opened, earliest) if opened else earliest), end


def _real(ref: str | None) -> bool:
    """A record that went through PayPal (seeded demo records carry DEMO- references). A payout's reference is
    PayPal's own batch id, so it says nothing about what was paid: the PayPal side is matched by our item id."""
    return bool(ref) and not ref.startswith("DEMO-")


def expected(db: Session, start: datetime) -> list[Expected]:
    """What our records say went through PayPal since `start`."""
    out: list[Expected] = []

    def since(at: datetime | None) -> bool:
        at = _aware(at)
        return at is not None and at >= start

    for d in db.scalars(select(Donation).where(Donation.paypal_capture_id.is_not(None))):
        if _real(d.paypal_capture_id) and since(d.captured_at):
            if d.currency != "USD" and d.currency_amount is not None:  # PayPal reports it in the giver's currency
                what = f"Gift #{d.id} to a registry, from abroad (${d.amount} for the family)"
                at = _aware(d.captured_at)
                out.append(Expected(d.paypal_capture_id, "in", d.currency_amount, at, what, d.currency))
                continue
            out.append(
                Expected(d.paypal_capture_id, "in", d.amount, _aware(d.captured_at), f"Gift #{d.id} to a registry")
            )
    for c in db.scalars(select(GiftCard).where(GiftCard.paypal_capture_id.is_not(None))):
        if _real(c.paypal_capture_id) and since(c.activated_at):
            out.append(Expected(c.paypal_capture_id, "in", c.amount_paid, _aware(c.activated_at), f"Gift card #{c.id}"))
    for p in db.scalars(select(GiftCardPayment)):
        if _real(p.paypal_sale_id) and since(p.created_at):
            out.append(Expected(p.paypal_sale_id, "in", p.amount, _aware(p.created_at), f"Regular's payment #{p.id}"))
    for r in db.scalars(select(ReadinessPayment)):
        if _real(r.paypal_sale_id) and since(r.paid_at):
            what = f"Monthly gift #{r.id} to the readiness fund"
            out.append(Expected(r.paypal_sale_id, "in", r.amount, _aware(r.paid_at), what))

    for claim in db.scalars(select(InsuranceClaim).where(InsuranceClaim.paypal_capture_id.is_not(None))):
        if _real(claim.paypal_capture_id) and since(claim.paid_at):
            what = f"Insurance claim #{claim.id} paid by {claim.insurer} (adjuster {claim.adjuster_name})"
            out.append(
                Expected(
                    claim.paypal_capture_id, "in", claim.approved_amount or Decimal(0), _aware(claim.paid_at), what
                )
            )
            if claim.payout_status == "sent" and _real(claim.payout_ref):
                what = f"Insurance claim #{claim.id} passed on to the household's PayPal account"
                out.append(
                    Expected(
                        f"claim-{claim.id}", "out", claim.approved_amount or Decimal(0), _aware(claim.paid_at), what
                    )
                )

    for case in db.scalars(select(Case).where(Case.paypal_ref.is_not(None))):
        if _real(case.paypal_ref) and since(case.decided_at):
            what = f"Cash aid, case #{case.id} (approved by reviewers)"
            out.append(Expected(f"case-{case.id}", "out", case.amount_requested, _aware(case.decided_at), what))
    for m in db.scalars(select(Milestone).where(Milestone.paypal_ref.is_not(None))):
        if _real(m.paypal_ref) and since(m.paid_at):
            what = f"Contractor milestone #{m.id} (homeowner approved)"
            out.append(Expected(f"milestone-{m.id}", "out", m.amount, _aware(m.paid_at), what))
    for t in db.scalars(select(ReopenTranche).where(ReopenTranche.paypal_ref.is_not(None))):
        if _real(t.paypal_ref) and since(t.released_at):
            what = f"Reopen step #{t.id}: {t.title} (staff released)"
            out.append(Expected(f"tranche-{t.id}", "out", t.amount, _aware(t.released_at), what))
    for p in db.scalars(select(Purchase).where(Purchase.paypal_ref.is_not(None))):
        if _real(p.paypal_ref) and since(p.paid_at):
            what = f"Shopper purchase #{p.id}: {p.title[:60]}"
            out.append(Expected(f"purchase-{p.id}", "out", p.total, _aware(p.paid_at), what))
    for item, batch in db.execute(select(AidBatchItem, AidBatch).join(AidBatch, AidBatchItem.batch_id == AidBatch.id)):
        if batch.paypal_batch_id and item.status not in ("queued", "skipped") and since(batch.decided_at):
            what = f"Batch cash aid #{batch.id}, household #{item.household_id} (two people approved)"
            out.append(Expected(item.sender_item_id, "out", item.amount, _aware(batch.decided_at), what))
    return out


def _refunded_payment(db: Session, capture_id: str | None) -> str | None:
    if not capture_id:
        return None
    gift = db.scalar(select(Donation).where(Donation.paypal_capture_id == capture_id))
    if gift is not None:
        return f"Refund of gift #{gift.id}"
    card = db.scalar(select(GiftCard).where(GiftCard.paypal_capture_id == capture_id))
    if card is not None:
        return f"Refund of gift card #{card.id}"
    payment = db.scalar(select(GiftCardPayment).where(GiftCardPayment.paypal_sale_id == capture_id))
    return f"Refund of regular's payment #{payment.id}" if payment is not None else None


def _other(code: str) -> str:
    if code.startswith("T15") or code == "T1105":
        return "PayPal holds money while a payout is processed, then releases it"
    if code.startswith("T19") or code.startswith("T03") or code.startswith("T04"):
        return "Money added to or taken from the account outside Hearthline (a top-up or correction)"
    if code.startswith("T12"):
        return "A chargeback or dispute adjustment; see the Disputes desk"
    if code.startswith("T02"):
        return "PayPal converted a payment from abroad into dollars"
    return f"PayPal transaction type {code}"


def build(db: Session, end: datetime | None = None) -> Report:
    start, end = window(db, end)
    found, refreshed = reporting.transactions(start, end)
    report = Report(start=start, end=end, paypal_refreshed_at=refreshed)
    books = expected(db, start)
    by_key = {e.key: e for e in books}
    seen: set[str] = set()

    for t in sorted(found, key=lambda t: t.at or start):
        if t.event_code == PAYOUT_SENT:
            exp = by_key.get(t.custom or "")
            if exp is None:
                report.lines.append(
                    Line(
                        "not_in_books",
                        "out",
                        t.amount,
                        t.at,
                        t.id,
                        None,
                        f"A payout ({t.custom or 'no reference'}) with no approved decision behind it in Hearthline",
                    )
                )
                continue
            seen.add(exp.key)
            same = abs(t.amount) == exp.amount
            report.lines.append(
                Line(
                    "matched" if same else "amount_differs",
                    "out",
                    t.amount,
                    t.at,
                    t.id,
                    exp.what,
                    "" if same else f"Hearthline approved {exp.amount}",
                )
            )
        elif t.event_code == REFUND:
            refunded = _refunded_payment(db, t.reference_id)
            report.lines.append(
                Line(
                    "matched" if refunded else "not_in_books",
                    "refund",
                    t.amount,
                    t.at,
                    t.id,
                    refunded,
                    "" if refunded else "A refund of a payment Hearthline has no record of",
                )
            )
        elif t.event_code.startswith("T00") and t.amount > 0:
            exp = by_key.get(t.id)
            if exp is None:
                report.lines.append(
                    Line(
                        "not_in_books",
                        "in",
                        t.amount,
                        t.at,
                        t.id,
                        None,
                        f"Money received that isn't in Hearthline's books ({t.custom or 'no reference'})",
                        t.currency,
                    )
                )
                continue
            seen.add(exp.key)
            same = t.amount == exp.amount and t.currency == exp.currency
            report.lines.append(
                Line(
                    "matched" if same else "amount_differs",
                    "in",
                    t.amount,
                    t.at,
                    t.id,
                    exp.what,
                    "" if same else f"Hearthline recorded {exp.amount} {exp.currency}",
                    t.currency,
                )
            )
        else:
            report.lines.append(Line("info", "other", t.amount, t.at, t.id, None, _other(t.event_code), t.currency))

    for exp in books:
        if exp.key in seen:
            continue
        recent = refreshed is None or (exp.at is not None and exp.at > refreshed)
        report.lines.append(
            Line(
                "waiting" if recent else "missing_at_paypal",
                exp.direction,
                exp.amount if exp.direction == "in" else -exp.amount,
                exp.at,
                None,
                exp.what,
                "Newer than PayPal's latest report (it can take up to 3 hours)"
                if recent
                else "In Hearthline's books but not in PayPal's report",
                exp.currency,
            )
        )
    report.lines.sort(key=lambda line: line.at or start, reverse=True)
    return report


def funds_check(needed: Decimal) -> dict:
    """Whether PayPal's latest balance covers a payout of `needed`. A warning, not a gate: the balance lags."""
    try:
        bal = reporting.balance()
    except reporting.ReportingError as e:
        return {"available": None, "as_of": None, "covers": None, "error": str(e)}
    return {
        "available": f"{bal.available:.2f}",
        "as_of": bal.as_of.isoformat() if bal.as_of else None,
        "covers": bal.available >= needed,
        "error": None,
    }
