"""Human review: AI prepares, people decide. No claim-related money moves until a case is approved.

Depth follows risk: low = one reviewer; medium = one reviewer plus a video call; high (or cash aid
over $1,000) = two independent reviewers, and a supervisor settles any disagreement. Reviewers are
assigned at random, never to a household they belong to or vouched for, and 5% of approvals get a
random audit.
"""

import logging
import random
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, ledger, trust
from app.agents import sentinel
from app.models import Case, CaseAssignment, CaseReview, Donation, Household, Registry, Role, User, now
from app.paypal import orders, payouts

log = logging.getLogger(__name__)
AUDIT_RATE = 0.05
TWO_REVIEWERS_OVER = Decimal("1000.00")
DECISIONS = {"approve", "reject", "request_info"}


class ReviewError(ValueError):
    pass


def _depth(tier: str, kind: str, amount: Decimal) -> tuple[int, bool]:
    two = tier == "high" or (kind == "cash_aid" and amount > TWO_REVIEWERS_OVER)
    return (2 if two else 1), tier in {"medium", "high"}


def eligible_reviewers(db: Session, home: Household, role: Role = Role.REVIEWER) -> list[User]:
    """Never the household's own members, and never the caseworker who vouched for it."""
    users = db.scalars(select(User).where(User.role == role))
    return [u for u in users if u.household_id != home.id and u.id != home.vouched_by_user_id]


def _assign(db: Session, case: Case, role: Role, count: int, rng: random.Random) -> None:
    taken = {a.reviewer_user_id for a in case.assignments}
    pool = [u for u in eligible_reviewers(db, case.household, role) if u.id not in taken]
    if len(pool) < count:
        raise ReviewError(f"Not enough eligible {role}s to review this case")
    for user in rng.sample(pool, count):
        case.assignments.append(CaseAssignment(reviewer_user_id=user.id, role=str(role)))


def _assign_auditor(db: Session, case: Case, rng: random.Random) -> None:
    """Random after-the-fact audit by someone not involved in the case. Never blocks the decision."""
    involved = {a.reviewer_user_id for a in case.assignments}
    pool = [
        u
        for role in (Role.SUPERVISOR, Role.ORG_ADMIN)
        for u in eligible_reviewers(db, case.household, role)
        if u.id not in involved
    ]
    auditor = rng.choice(pool) if pool else None
    if auditor is not None:
        case.assignments.append(CaseAssignment(reviewer_user_id=auditor.id, role="auditor"))
    audit.record(
        db,
        action="case.random_audit",
        subject_type="case",
        subject_id=case.id,
        data={"auditor": auditor.id if auditor else None},
    )


def open_case(
    db: Session,
    home: Household,
    *,
    kind: str,
    title: str,
    amount: Decimal = Decimal(0),
    note: str = "",
    actor_user_id: int | None = None,
    rng: random.Random | None = None,
    explain: bool = True,  # False for seeding: rule messages instead of an AI call
) -> Case:
    rng = rng or random.Random()
    flags = trust.sentinel_flags(db, home, amount)
    score, tier = trust.risk(flags)
    facts = {
        "case": kind,
        "amount_requested": str(amount),
        "household": home.name,
        "town": f"{home.city}, {home.state}",
        "verification_level": trust.verification_level(db, home),
        "household_note": note,
    }
    explained = (
        sentinel.explain(facts, flags)
        if explain
        else sentinel.SentinelNote(
            summary=" ".join(f.message for f in flags) or "No warning signs were found.",
            questions=[],
            recommendation="escalate" if flags else "approve",
        )
    )
    required, video = _depth(tier, kind, amount)
    case = Case(
        household_id=home.id,
        kind=kind,
        title=title,
        note=note,
        amount_requested=amount,
        risk_score=score,
        risk_tier=tier,
        flags=trust.flags_json(flags),
        sentinel_summary=explained.summary[:1500],
        sentinel_questions=explained.questions,
        sentinel_recommendation=explained.recommendation,
        required_reviews=required,
        video_call_required=video,
        random_audit=rng.random() < AUDIT_RATE,
        household=home,
    )
    db.add(case)
    _assign(db, case, Role.REVIEWER, required, rng)
    db.flush()
    audit.record(
        db,
        actor_user_id=actor_user_id,
        action="case.opened",
        subject_type="case",
        subject_id=case.id,
        data={
            "kind": kind,
            "amount": amount,
            "risk": score,
            "flags": [f.code for f in flags],
            "reviewers": [a.reviewer_user_id for a in case.assignments],
        },
    )
    db.commit()
    return case


def is_assigned(case: Case, user: User) -> bool:
    return any(a.reviewer_user_id == user.id for a in case.assignments)


def decide(
    db: Session, case: Case, reviewer: User, decision: str, reason: str, rng: random.Random | None = None
) -> Case:
    rng = rng or random.Random()
    if decision not in DECISIONS:
        raise ReviewError("Unknown decision")
    if decision != "approve" and len(reason.strip()) < 5:
        raise ReviewError("Explain the decision so the household and the audit log know why")
    if not is_assigned(case, reviewer):
        raise ReviewError("This case isn't assigned to you")
    if reviewer.household_id == case.household_id or reviewer.id == case.household.vouched_by_user_id:
        raise ReviewError("You have a conflict of interest with this household")
    supervisor_turn = case.status == "escalated" and reviewer.role == Role.SUPERVISOR
    if case.status not in {"in_review", "escalated"} or (case.status == "escalated" and not supervisor_turn):
        raise ReviewError(f"This case is {case.status}")
    if any(r.reviewer_user_id == reviewer.id for r in case.reviews) and not supervisor_turn:
        raise ReviewError("You've already reviewed this case")

    case.reviews.append(
        CaseReview(reviewer_user_id=reviewer.id, role=str(reviewer.role), decision=decision, reason=reason.strip())
    )
    audit.record(
        db,
        actor_user_id=reviewer.id,
        action=f"case.review.{decision}",
        subject_type="case",
        subject_id=case.id,
        data={"reason": reason.strip()},
    )

    if supervisor_turn or decision == "request_info":
        final = None if decision == "request_info" else decision
        if decision == "request_info":
            case.status = "needs_info"
            case.decision_note = reason.strip()
    else:
        votes = [r.decision for r in case.reviews if r.role == Role.REVIEWER and r.decision != "request_info"]
        final = None
        if len(votes) >= case.required_reviews:
            if len(set(votes[-case.required_reviews :])) == 1:
                final = votes[-1]
            else:
                case.status = "escalated"
                _assign(db, case, Role.SUPERVISOR, 1, rng)
                audit.record(
                    db, action="case.escalated", subject_type="case", subject_id=case.id, data={"votes": votes}
                )
    if final:
        apply_decision(db, case, final, reason.strip(), reviewer, rng)
    db.commit()
    return case


def respond(db: Session, case: Case, note: str, actor_user_id: int) -> Case:
    """The household answers a request for more information; the case goes back to review."""
    if case.status != "needs_info":
        raise ReviewError(f"This case is {case.status}")
    case.note = f"{case.note}\n\nHousehold reply: {note}".strip()[:1000]
    case.status = "in_review"
    # Earlier "request_info" reviews no longer count; each assigned reviewer reviews again.
    for review in [r for r in case.reviews if r.decision == "request_info"]:
        case.reviews.remove(review)
    audit.record(
        db,
        actor_user_id=actor_user_id,
        action="case.household_replied",
        subject_type="case",
        subject_id=case.id,
        data={"note": note},
    )
    db.commit()
    return case


def apply_decision(db: Session, case: Case, decision: str, reason: str, decided_by: User, rng: random.Random) -> None:
    case.status = "approved" if decision == "approve" else "rejected"
    case.decided_at = now()
    case.decision_note = reason or None
    home = case.household
    if case.kind == "cash_aid" and decision == "approve":
        _send_cash_aid(db, case, home)
    elif case.kind == "registry_verification":
        reg = db.scalar(select(Registry).where(Registry.household_id == home.id))
        if reg is not None:
            if decision == "approve":
                reg.status = "active"
                home.residence_verified = True
            else:
                reg.status = "closed"
                refund_registry(db, reg, reason)
        trust.refresh_level(db, home)
    if decision == "approve" and case.random_audit:
        _assign_auditor(db, case, rng)
    audit.record(
        db,
        actor_user_id=decided_by.id,
        action=f"case.{case.status}",
        subject_type="case",
        subject_id=case.id,
        data={"kind": case.kind, "amount": case.amount_requested, "paypal": case.paypal_ref},
    )


def _send_cash_aid(db: Session, case: Case, home: Household) -> None:
    if not home.payout_email:
        raise ReviewError("This household hasn't connected a PayPal account to receive cash aid")
    result = payouts.send_payouts(
        [(home.payout_email, case.amount_requested, "Cash aid from the Sablewood Relief Network", f"case-{case.id}")],
        batch_id=f"hearthline-case-{case.id}",
        subject="You have received disaster cash aid",
    )
    case.paypal_ref = result.batch_id
    ledger.post(
        db,
        kind="payout",
        description=f"Cash aid for {home.name}",
        household_id=home.id,
        paypal_ref=result.batch_id,
        meta={"case_id": case.id},
        lines={ledger.CASH_AID: case.amount_requested, ledger.CASH: -case.amount_requested},
    )


def refund_registry(db: Session, reg: Registry, reason: str) -> int:
    """Refund every captured donation to a registry that reviewers rejected. Returns how many."""
    refunded = 0
    donations = db.scalars(select(Donation).where(Donation.registry_id == reg.id, Donation.status == "captured"))
    for d in donations:
        if d.paypal_capture_id and not d.paypal_capture_id.startswith("DEMO-"):
            try:
                orders.refund_capture(d.paypal_capture_id)
            except Exception:  # keep going; the failure is visible in the audit log
                log.exception("Refund failed for donation %s", d.id)
                audit.record(db, action="donation.refund_failed", subject_type="donation", subject_id=d.id)
                continue
        d.status = "refunded"
        if d.item is not None:
            d.item.funded_amount -= d.amount
        ledger.post(
            db,
            kind="refund",
            description=f"Refund: registry rejected ({reason[:80]})",
            household_id=reg.household_id,
            paypal_ref=f"refund-{d.paypal_capture_id or d.id}",
            meta={"donation_id": d.id},
            lines={ledger.household_fund(reg.household_id): d.amount, ledger.CASH: -d.amount},
        )
        audit.record(
            db,
            action="donation.refunded",
            subject_type="donation",
            subject_id=d.id,
            data={"amount": d.amount, "capture_id": d.paypal_capture_id},
        )
        refunded += 1
    return refunded
