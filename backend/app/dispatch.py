"""The dispatch agent: tomorrow's crew plan, proposed for a person to accept.

Code does everything that has a right answer: which crews can do a job (the right kind), when they're free (working
hours, the jobs they already have, the plan so far), how long it takes to get there (distance between stops), and how
urgent each request is. The agent chooses among those options, following the coordinator's own instructions (most
urgent first, nearby stops together, crews kept even) and explains each pick in a sentence. Code re-checks every pick
in the agent's order before it becomes a proposal, and again when a person accepts it; nothing moves until then.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, audit
from app.models import Crew, CrewJob, DispatchPlan, DispatchProposal, Household, User, now

SITE = ZoneInfo("America/Los_Angeles")  # Sablewood's clock
DAY_START, DAY_END = 8, 18  # crews work daylight hours
DEPOT = (38.709, -120.627)  # the relief center, where a crew's day starts
JOB_CREW = {  # the kind of crew each job needs
    "debris_removal": "debris",
    "tarp_roof": "tarp",
    "water": "delivery",
    "food": "delivery",
    "cleanup": "cleanup",
    "wellness": "wellness",
}


class DispatchError(ValueError):
    pass


@dataclass
class Stop:
    start: datetime  # when the work starts (the drive there comes before it)
    end: datetime
    at: tuple[float, float]


@dataclass
class Request:
    job: CrewJob
    urgency: int
    why: list[str]
    minutes: int
    crews: list[int] = field(default_factory=list)  # the crews of the right kind


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def travel_minutes(a: tuple[float, float], b: tuple[float, float]) -> int:
    """Driving time between two stops in town: 5 minutes to get going, then about 30 km/h, in 5-minute steps."""
    km = math.dist((a[0] * 111, a[1] * 87), (b[0] * 111, b[1] * 87))  # degrees to km at this latitude
    return max(10, int(math.ceil((5 + km / 30 * 60) / 5) * 5))


def _where(h: Household) -> tuple[float, float]:
    return (h.lat, h.lng) if h.lat is not None and h.lng is not None else DEPOT


def urgency(job: CrewJob, at: datetime) -> tuple[int, list[str]]:
    """A score and its reasons, in plain words: needs that can't wait come first."""
    h, needs = job.household, set(job.household.needs or [])
    score, why = 0, []
    if "medical" in needs:
        score, why = score + 30, [*why, "a medical need"]
    if job.kind in ("water", "food"):
        score, why = score + 20, [*why, "basic supplies"]
    if job.kind == "tarp_roof":
        score, why = score + 15, [*why, "a roof open to the weather"]
    if h.damage_level == "destroyed":
        score, why = score + 15, [*why, "home destroyed"]
    elif h.damage_level == "major":
        score, why = score + 8, [*why, "major damage"]
    if h.household_size >= 5:
        score, why = score + 8, [*why, f"{h.household_size} people"]
    waited = (at - _aware(job.requested_at)).days
    if waited >= 1:
        score, why = score + 5 * min(waited, 6), [*why, f"waiting {waited} day{'s' if waited > 1 else ''}"]
    return score, why


def _window(day: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, time(DAY_START), SITE).astimezone(UTC),
        datetime.combine(day, time(DAY_END), SITE).astimezone(UTC),
    )


def _stops(db: Session, crew: Crew, day: date) -> list[Stop]:
    start, end = _window(day)
    jobs = db.scalars(
        select(CrewJob).where(
            CrewJob.crew_id == crew.id,
            CrewJob.status != "cancelled",
            CrewJob.ends_at > start,
            CrewJob.starts_at < end,
        )
    )
    return sorted(
        (Stop(_aware(j.starts_at), _aware(j.ends_at), _where(j.household)) for j in jobs),
        key=lambda s: s.start,
    )


def fit(stops: list[Stop], day: date, place: tuple[float, float], minutes: int) -> list[tuple[datetime, int]]:
    """Every gap in a crew's day where a job of `minutes` fits, driving there from the stop before and on to the
    stop after in time for it: (start time, travel minutes) for the earliest start in each gap."""
    day_start, day_end = _window(day)
    found = []
    previous_end, previous_at = day_start, DEPOT
    for stop in [*stops, Stop(day_end, day_end, DEPOT)]:  # the day's end works like a stop at the depot
        travel = travel_minutes(previous_at, place)
        begin = previous_end + timedelta(minutes=travel)
        finish = begin + timedelta(minutes=minutes)
        after = 0 if stop.start == day_end else travel_minutes(place, stop.at)
        if finish + timedelta(minutes=after) <= stop.start and finish <= day_end:
            found.append((begin, travel))
        previous_end, previous_at = max(previous_end, stop.end), stop.at
    return found


def fits_at(stops: list[Stop], day: date, place: tuple[float, float], start: datetime, minutes: int) -> int | None:
    """Whether a job can still start at `start`: no overlap, the drive from the stop before ends in time, and the work
    ends in time for the drive on to the stop after, all inside the working day. The drive there in minutes, or None.
    (Proposals can be accepted in any order, so this checks the time itself, not just the earliest start in a gap.)"""
    day_start, day_end = _window(day)
    end = start + timedelta(minutes=minutes)
    if any(st.start < end and st.end > start for st in stops) or end > day_end:
        return None
    before = max(
        (st for st in stops if st.end <= start), key=lambda st: st.end, default=Stop(day_start, day_start, DEPOT)
    )
    after = min((st for st in stops if st.start >= end), key=lambda st: st.start, default=None)
    travel = travel_minutes(before.at, place)
    if before.end + timedelta(minutes=travel) > start:
        return None
    if after and end + timedelta(minutes=travel_minutes(place, after.at)) > after.start:
        return None
    return travel


def free_minutes(stops: list[Stop], day: date) -> int:
    """How much of the working day a crew has left (travel between new stops comes out of it)."""
    day_start, day_end = _window(day)
    busy = sum(
        (min(st.end, day_end) - max(st.start, day_start)).total_seconds() // 60
        for st in stops
        if st.end > day_start and st.start < day_end
    )
    return int((day_end - day_start).total_seconds() // 60 - busy)


def requests(db: Session) -> list[Request]:
    """Every job without a crew, with its urgency and the crews that can do it."""
    at = now()
    crews = list(db.scalars(select(Crew).order_by(Crew.id)))
    jobs = db.scalars(
        select(CrewJob).where(CrewJob.crew_id.is_(None), CrewJob.status == "scheduled").order_by(CrewJob.id)
    )
    out = []
    for job in jobs:
        score, why = urgency(job, at)
        minutes = int((_aware(job.ends_at) - _aware(job.starts_at)).total_seconds() // 60)
        able = [c.id for c in crews if c.kind == JOB_CREW.get(job.kind)]
        out.append(Request(job, score, why, minutes, able))
    return sorted(out, key=lambda r: -r.urgency)


# --- The agent's part -------------------------------------------------------------------------------------------------


class Pick(BaseModel):
    job_id: int
    crew_id: int | None = Field(description="One of the job's crew ids, or null to leave it for another day")
    reason: str = Field(description="One short sentence for the coordinator: why this job goes to this crew now")


class Choice(BaseModel):
    summary: str = Field(description="Two sentences for the coordinator about the plan as a whole")
    picks: list[Pick] = Field(description="Every job, in the order to schedule them: most urgent first")


SYSTEM = (
    "You are Hearthline's dispatch agent for a disaster relief organization. You plan one day of crew visits to "
    "households. You get each crew's free time that day and each job with its urgency (with reasons), its length and "
    "the crews that can do it. For each job choose one of its crews, or null to leave it for another day, and list the "
    "jobs in the order to schedule them. Code then fits each job into its crew's free time in your order, adding the "
    "drive from the stop before, so a crew can take several jobs while its free time lasts; it will not overbook. Put "
    "the most urgent needs first, give a crew stops on the same or nearby streets (less driving), spread work across "
    "crews, and follow the coordinator's instructions unless they conflict with basic or medical needs. Never invent "
    "a job or crew. Write each reason in plain words, under 25 words."
)


def _facts(day: date, found: list[Request], free: dict[int, int], names: dict[int, str], instructions: str) -> str:
    return json.dumps(
        {
            "day": day.isoformat(),
            "working_hours": f"{DAY_START}:00-{DAY_END}:00",
            "coordinator_instructions": instructions or "(none)",
            "crews": [{"crew_id": c, "name": names[c], "free_minutes": m} for c, m in free.items()],
            "jobs": [
                {
                    "job_id": r.job.id,
                    "job": r.job.title,
                    "minutes": r.minutes,
                    "household": r.job.household.name,
                    "street": r.job.household.street,
                    "urgency": r.urgency,
                    "why": r.why,
                    "crews": r.crews,
                }
                for r in found
            ],
        },
        indent=1,
    )


FALLBACK_SUMMARY = (
    "The AI wasn't available, so Hearthline planned by urgency: the most urgent requests first, each with the crew "
    "that can start it soonest."
)


def _place(
    db: Session, day: date, request: Request, crew_id: int, taken: dict[int, list[Stop]]
) -> tuple[datetime, int] | None:
    """The earliest start for the job in the crew's day, after what the plan already gave it."""
    stops = sorted([*_crew_stops(db, crew_id, day), *taken.get(crew_id, [])], key=lambda st: st.start)
    places = fit(stops, day, _where(request.job.household), request.minutes)
    return places[0] if places else None


def plan(db: Session, staff: User, day: date, instructions: str = "") -> DispatchPlan:
    """Ask the agent for a plan, fit every pick in its order, and save the proposals for a person to decide."""
    found = requests(db)
    if not found:
        raise DispatchError("Every job already has a crew")
    crews = {c.id: c for c in db.scalars(select(Crew).order_by(Crew.id))}
    free = {c: free_minutes(_crew_stops(db, c, day), day) for c in crews}
    by_ai = True
    try:
        choice = ai.parse(
            Choice,
            system=SYSTEM,
            content=[ai.text_part(_facts(day, found, free, {c: crews[c].name for c in crews}, instructions))],
            max_tokens=4000,
        )
    except ai.AIError:
        by_ai = False
        choice = Choice(summary=FALLBACK_SUMMARY, picks=[Pick(job_id=r.job.id, crew_id=None, reason="") for r in found])
    by_job = {r.job.id: r for r in found}
    ordered = list(dict.fromkeys(p.job_id for p in choice.picks if p.job_id in by_job))
    ordered += [r.job.id for r in found if r.job.id not in ordered]  # anything the agent left out, by urgency
    picks = {p.job_id: p for p in reversed(choice.picks)}  # the first pick for a job wins
    taken: dict[int, list[Stop]] = {}
    plan_ = DispatchPlan(created_by_user_id=staff.id, day=day, instructions=instructions[:500], by_ai=by_ai)
    for rank, job_id in enumerate(ordered):
        request, pick = by_job[job_id], picks.get(job_id)
        proposal = DispatchProposal(
            job_id=job_id, rank=rank, urgency=request.urgency, reason=(pick.reason if pick else "")
        )
        wanted = pick.crew_id if pick and pick.crew_id in request.crews else None
        skipped_by_agent = by_ai and pick is not None and pick.crew_id is None
        placed = None
        if not skipped_by_agent:
            # The agent's crew if it has room; otherwise (or without the AI) the crew that can start soonest
            tries = [wanted] if wanted else []
            options = [(c, _place(db, day, request, c, taken)) for c in request.crews if c != wanted]
            tries += [c for c, at in sorted((o for o in options if o[1]), key=lambda o: o[1][0])]
            for crew_id in tries:
                at = _place(db, day, request, crew_id, taken)
                if at:
                    placed = (crew_id, *at)
                    break
        if placed:
            crew_id, start, travel = placed
            proposal.crew_id, proposal.starts_at, proposal.travel_minutes = crew_id, start, travel
            proposal.ends_at = start + timedelta(minutes=request.minutes)
            taken.setdefault(crew_id, []).append(Stop(start, proposal.ends_at, _where(request.job.household)))
            if not by_ai:
                proposal.reason = f"Urgent: {', '.join(request.why) or 'no special need'}. The soonest free crew."
            elif wanted and crew_id != wanted:
                proposal.reason = f"{crews[wanted].name} had no room left, so {crews[crew_id].name}. {proposal.reason}"
        else:
            proposal.status = "skipped"
            if not skipped_by_agent:
                proposal.reason = "No crew of the right kind has room that day."
        proposal.reason = (proposal.reason or "Left for another day.")[:400]
        plan_.proposals.append(proposal)
    placed_count = sum(1 for p in plan_.proposals if p.status == "proposed")
    plan_.summary = choice.summary[:1000]
    db.add(plan_)
    db.flush()
    audit.record(
        db,
        actor_user_id=staff.id,
        action="dispatch.planned",
        subject_type="dispatch_plan",
        subject_id=plan_.id,
        data={
            "day": day.isoformat(),
            "proposed": placed_count,
            "skipped": len(plan_.proposals) - placed_count,
            "by_ai": by_ai,
        },
    )
    db.commit()
    return plan_


def _crew_stops(db: Session, crew_id: int, day: date) -> list[Stop]:
    crew = db.get(Crew, crew_id)
    return _stops(db, crew, day) if crew else []


# --- A person decides -------------------------------------------------------------------------------------------------


def accept(db: Session, proposal: DispatchProposal, staff: User) -> DispatchProposal:
    """Give the job to the crew at the proposed time, if it still fits (the schedule may have changed since)."""
    if proposal.status != "proposed":
        raise DispatchError(f"This proposal is already {proposal.status}")
    job = proposal.job
    if job.crew_id is not None or job.status != "scheduled":
        proposal.status = "stale"
        db.commit()
        raise DispatchError("This job was already given a crew or closed")
    start, end = _aware(proposal.starts_at), _aware(proposal.ends_at)
    day = start.astimezone(SITE).date()
    minutes = int((end - start).total_seconds() // 60)
    travel = fits_at(_crew_stops(db, proposal.crew_id, day), day, _where(job.household), start, minutes)
    if travel is None:
        proposal.status = "stale"
        db.commit()
        raise DispatchError("The crew's day changed and this no longer fits; plan again")
    job.crew_id, job.starts_at, job.ends_at, job.travel_minutes = proposal.crew_id, start, end, travel
    proposal.status, proposal.decided_by_user_id, proposal.decided_at = "accepted", staff.id, now()
    audit.record(
        db,
        actor_user_id=staff.id,
        action="dispatch.accepted",
        subject_type="crew_job",
        subject_id=job.id,
        data={"proposal": proposal.id, "crew_id": proposal.crew_id, "start": start.isoformat()},
    )
    db.commit()
    return proposal


def reject(db: Session, proposal: DispatchProposal, staff: User) -> DispatchProposal:
    if proposal.status != "proposed":
        raise DispatchError(f"This proposal is already {proposal.status}")
    proposal.status, proposal.decided_by_user_id, proposal.decided_at = "rejected", staff.id, now()
    audit.record(
        db, actor_user_id=staff.id, action="dispatch.rejected", subject_type="dispatch_proposal", subject_id=proposal.id
    )
    db.commit()
    return proposal


def accept_all(db: Session, plan_: DispatchPlan, staff: User) -> tuple[int, int]:
    """Accept every open proposal in the agent's order; ones that no longer fit are marked stale. (accepted, stale)"""
    accepted = stale = 0
    for proposal in plan_.proposals:
        if proposal.status != "proposed":
            continue
        try:
            accept(db, proposal, staff)
            accepted += 1
        except DispatchError:
            stale += 1
    return accepted, stale


def latest(db: Session) -> DispatchPlan | None:
    return db.scalar(select(DispatchPlan).order_by(DispatchPlan.id.desc()))
