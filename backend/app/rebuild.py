"""Contractor projects paid by milestone out of escrow.

- The deposit is capped by California law: 10% of the price or $1,000, whichever is less.
- Accepting a plan moves the full price from the household's fund into the project's escrow.
- A milestone is paid only after the contractor submits photos, the Site agent checks them, and the
  homeowner approves. Large amounts, weak photo checks and disputes go to human review.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app import audit, ledger, trust
from app.agents import site
from app.models import Media, Milestone, RebuildProject, User, now
from app.paypal import payouts
from app.paypal.rest import PayPalError

DEPOSIT_PERCENT = Decimal("0.10")
DEPOSIT_MAX = Decimal("1000.00")
AUTO_PAY_LIMIT = Decimal("10000.00")
AUTO_PAY_MIN_CONFIDENCE = 0.7


class RebuildError(ValueError):
    pass


def deposit_cap(total: Decimal) -> Decimal:
    return min((total * DEPOSIT_PERCENT).quantize(Decimal("0.01")), DEPOSIT_MAX)


def escrow_account(project_id: int) -> str:
    return f"liabilities:escrow:project:{project_id}"


def escrow_balance(db: Session, project_id: int) -> Decimal:
    return -ledger.balance(db, escrow_account(project_id))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def submit_plan(db: Session, project: RebuildProject, milestones: list[dict], actor: User) -> RebuildProject:
    if project.status not in {"awaiting_plan", "plan_submitted"}:
        raise RebuildError(f"The project is {project.status}")
    if not milestones:
        raise RebuildError("A plan needs at least one milestone")
    total = sum((Decimal(str(m["amount"])) for m in milestones), Decimal(0))
    deposits = [m for m in milestones if m.get("is_deposit")]
    if len(deposits) > 1:
        raise RebuildError("Only one deposit is allowed")
    if deposits and Decimal(str(deposits[0]["amount"])) > deposit_cap(total):
        raise RebuildError(
            f"California caps a home-improvement deposit at 10% or $1,000, whichever is less: ${deposit_cap(total)}"
        )
    project.milestones.clear()
    db.flush()
    for seq, m in enumerate(milestones, start=1):
        if _aware(m["end_date"]) < _aware(m["start_date"]):
            raise RebuildError(f"Milestone {seq} ends before it starts")
        project.milestones.append(
            Milestone(
                seq=seq,
                title=m["title"],
                done_looks_like=m.get("done_looks_like", ""),
                amount=Decimal(str(m["amount"])),
                is_deposit=bool(m.get("is_deposit")),
                start_date=_aware(m["start_date"]),
                end_date=_aware(m["end_date"]),
            )
        )
    project.total_price = total
    project.status = "plan_submitted"
    audit.record(
        db,
        actor_user_id=actor.id,
        action="project.plan_submitted",
        subject_type="project",
        subject_id=project.id,
        data={"total": total, "milestones": len(milestones)},
    )
    db.commit()
    return project


def accept_plan(db: Session, project: RebuildProject, actor: User) -> RebuildProject:
    if project.status != "plan_submitted":
        raise RebuildError(f"The project is {project.status}")
    if not project.contractor.license_verified:
        raise RebuildError("This contractor's license hasn't been verified yet")
    available = ledger.household_available(db, project.household_id)
    if available < project.total_price:
        raise RebuildError(f"The project costs ${project.total_price} but ${available} is available")
    ledger.post(
        db,
        kind="escrow",
        description=f"Escrow for {project.title}",
        household_id=project.household_id,
        paypal_ref=f"escrow-{project.id}",
        meta={"project_id": project.id},
        lines={
            ledger.household_fund(project.household_id): project.total_price,
            escrow_account(project.id): -project.total_price,
        },
    )
    project.status = "active"
    audit.record(
        db,
        actor_user_id=actor.id,
        action="project.accepted",
        subject_type="project",
        subject_id=project.id,
        data={"escrow": project.total_price},
    )
    db.commit()
    return project


def _metadata_concerns(milestone: Milestone, media: list[Media]) -> list[str]:
    concerns = []
    start = _aware(milestone.start_date)
    stale = [m for m in media if m.captured_at and _aware(m.captured_at) < start]
    if stale:
        concerns.append(f"{len(stale)} photo(s) were taken before this milestone started")
    if media and all(m.captured_at is None for m in media):
        concerns.append("None of the photos has a capture date")
    return concerns


def submit_milestone(db: Session, milestone: Milestone, media: list[Media], actor: User) -> Milestone:
    if milestone.project.status != "active":
        raise RebuildError("The project isn't active")
    if milestone.status not in {"pending"}:
        raise RebuildError(f"This milestone is {milestone.status}")
    if not media and not milestone.is_deposit:
        raise RebuildError("Add photos of the finished work")
    result = (
        site.check(milestone.title, milestone.done_looks_like, [m.data for m in media])
        if media
        else site.SiteCheck(
            verdict="matches", confidence=1.0, observations=["Deposit: no work to photograph"], concerns=[]
        )
    )
    milestone.site_check = result.model_dump() | {"metadata_concerns": _metadata_concerns(milestone, media)}
    milestone.photo_media_ids = [m.id for m in media]
    milestone.status = "submitted"
    milestone.submitted_at = now()
    audit.record(
        db,
        actor_user_id=actor.id,
        action="milestone.submitted",
        subject_type="milestone",
        subject_id=milestone.id,
        data={"verdict": result.verdict, "confidence": result.confidence},
    )
    db.commit()
    return milestone


def needs_human_review(milestone: Milestone) -> bool:
    check = milestone.site_check or {}
    return (
        milestone.amount > AUTO_PAY_LIMIT
        or check.get("verdict") != "matches"
        or check.get("confidence", 0) < AUTO_PAY_MIN_CONFIDENCE
        or bool(check.get("metadata_concerns"))
    )


def site_check_flags(milestone: Milestone) -> list[trust.Flag]:
    """What the photo check found, as warning signs for the reviewer (they set the case's risk and review depth)."""
    check = milestone.site_check or {}
    verdict, confidence = check.get("verdict"), float(check.get("confidence", 0))
    evidence = {"milestone_id": milestone.id, "concerns": check.get("concerns", [])}
    flags = []
    if verdict == "does_not_match":
        flags.append(
            trust.Flag(
                "site_photos_mismatch",
                "high",
                f"The photo check says these photos don't show the finished work ({confidence:.0%} sure).",
                evidence,
            )
        )
    elif verdict == "partial":
        flags.append(
            trust.Flag(
                "site_photos_partial", "medium", "The photo check says the work looks only partly done.", evidence
            )
        )
    elif verdict == "unchecked":
        flags.append(
            trust.Flag(
                "site_photos_unchecked",
                "medium",
                "The photos couldn't be checked automatically; look at them closely.",
                evidence,
            )
        )
    elif confidence < AUTO_PAY_MIN_CONFIDENCE and not milestone.is_deposit:
        flags.append(
            trust.Flag(
                "site_photos_low_confidence",
                "low",
                f"The photo check matched the work but is only {confidence:.0%} sure.",
                evidence,
            )
        )
    if check.get("metadata_concerns"):
        flags.append(
            trust.Flag(
                "site_photo_dates",
                "medium",
                "; ".join(check["metadata_concerns"]) + ".",
                {"milestone_id": milestone.id},
            )
        )
    return flags


def _milestone_context(milestone: Milestone) -> dict:
    check = milestone.site_check or {}
    return {
        "milestone": milestone.title,
        "done_looks_like": milestone.done_looks_like,
        "contractor": milestone.project.contractor.business_name,
        "photo_check_verdict": check.get("verdict"),
        "photo_check_observations": check.get("observations", []),
    }


def approve_milestone(db: Session, milestone: Milestone, homeowner: User) -> Milestone:
    """The homeowner signs off. Clean, smaller milestones pay now; the rest go to a human reviewer."""
    from app import review  # avoid an import cycle (review pays milestones when cases are approved)

    if milestone.status != "submitted":
        raise RebuildError(f"This milestone is {milestone.status}")
    audit.record(
        db,
        actor_user_id=homeowner.id,
        action="milestone.homeowner_approved",
        subject_type="milestone",
        subject_id=milestone.id,
    )
    if not needs_human_review(milestone):
        return pay_milestone(db, milestone, homeowner)
    project = milestone.project
    case = review.open_case(
        db,
        project.household,
        kind="milestone_payment",
        title=f"Milestone {milestone.seq}: {milestone.title} ({project.contractor.business_name})",
        amount=milestone.amount,
        actor_user_id=homeowner.id,
        extra_flags=site_check_flags(milestone),
        context=_milestone_context(milestone),
    )
    milestone.case_id = case.id
    milestone.status = "under_review"
    db.commit()
    return milestone


def dispute_milestone(db: Session, milestone: Milestone, homeowner: User, reason: str) -> Milestone:
    from app import review

    if milestone.status not in {"submitted", "pending"}:
        raise RebuildError(f"This milestone is {milestone.status}")
    project = milestone.project
    case = review.open_case(
        db,
        project.household,
        kind="contractor_dispute",
        title=f"Dispute: milestone {milestone.seq} with {project.contractor.business_name}",
        amount=milestone.amount,
        note=reason,
        actor_user_id=homeowner.id,
        extra_flags=site_check_flags(milestone),
        context=_milestone_context(milestone),
    )
    milestone.case_id = case.id
    milestone.status = "disputed"
    audit.record(
        db,
        actor_user_id=homeowner.id,
        action="milestone.disputed",
        subject_type="milestone",
        subject_id=milestone.id,
        data={"reason": reason},
    )
    db.commit()
    return milestone


def pay_milestone(db: Session, milestone: Milestone, approved_by: User) -> Milestone:
    project = milestone.project
    try:
        result = payouts.send_payouts(
            [
                (
                    project.contractor.payout_email,
                    milestone.amount,
                    f"Hearthline milestone {milestone.seq}: {milestone.title}",
                    f"milestone-{milestone.id}",
                )
            ],
            batch_id=payouts.batch_id_for("milestone", milestone.id, project.created_at),
            subject=f"Milestone payment for {project.title}",
        )
    except PayPalError as e:
        raise RebuildError(payouts.failure_reason(e)) from e
    ledger.post(
        db,
        kind="milestone_payment",
        description=f"{project.contractor.business_name}: {milestone.title}",
        household_id=project.household_id,
        paypal_ref=result.batch_id,
        meta={"project_id": project.id, "milestone_id": milestone.id},
        lines={escrow_account(project.id): milestone.amount, ledger.CASH: -milestone.amount},
    )
    milestone.status = "paid"
    milestone.paid_at = now()
    milestone.paypal_ref = result.batch_id
    if all(m.status == "paid" for m in project.milestones):
        project.status = "completed"
    audit.record(
        db,
        actor_user_id=approved_by.id,
        action="milestone.paid",
        subject_type="milestone",
        subject_id=milestone.id,
        data={"amount": milestone.amount, "payout_batch": result.batch_id},
    )
    db.commit()
    return milestone


def release_back_to_household(db: Session, milestone: Milestone, reason: str, decided_by: User) -> Milestone:
    """A reviewer sided with the homeowner in a dispute: the milestone's money returns to the family's fund."""
    project = milestone.project
    ledger.post(
        db,
        kind="escrow_release",
        description=f"Returned from escrow: {milestone.title}",
        household_id=project.household_id,
        paypal_ref=f"escrow-release-{milestone.id}",
        meta={"milestone_id": milestone.id, "reason": reason[:200]},
        lines={
            escrow_account(project.id): milestone.amount,
            ledger.household_fund(project.household_id): -milestone.amount,
        },
    )
    milestone.status = "refunded"
    audit.record(
        db,
        actor_user_id=decided_by.id,
        action="milestone.refunded",
        subject_type="milestone",
        subject_id=milestone.id,
        data={"amount": milestone.amount, "reason": reason},
    )
    return milestone
