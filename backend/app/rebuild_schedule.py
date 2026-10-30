"""A rebuild's schedule: which steps wait for which, what moves when one runs late, and when the family moves in.

Bryntum Gantt's scheduling engine draws the same rules in the browser: steps not yet submitted are scheduled
automatically, no earlier than their planned start and not before the steps they wait for end (finish-to-start).
This module is the server's own copy of those rules, so a delay is saved from the server's arithmetic, not from
whatever a browser sent, and the homeowner is told exactly which steps and payments moved.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app import audit
from app.models import Milestone, RebuildProject, ScheduleChange, User

MAX_DELAY_DAYS = 120


class ScheduleError(ValueError):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _days(td: timedelta) -> int:
    return int(td.total_seconds() // 86400)


def predecessors(m: Milestone) -> list[int]:
    """The steps (by seq) this one waits for: the step before it, unless the plan says otherwise. Only earlier steps
    count, so going through the plan in order always sees a step's predecessors first."""
    if m.after is not None:
        return sorted({s for s in m.after if isinstance(s, int) and 0 < s < m.seq})
    return [m.seq - 1] if m.seq > 1 else []


def last_steps(milestones: list[Milestone]) -> list[Milestone]:
    """The steps nothing else waits for: the family moves in when all of them are done."""
    waited = {s for m in milestones for s in predecessors(m)}
    return [m for m in milestones if m.seq not in waited]


def move_in(milestones: list[Milestone], baseline: bool = False) -> datetime | None:
    ends = [m.baseline_end if baseline else m.end_date for m in last_steps(milestones)]
    found = [_aware(e) for e in ends if e is not None]
    return max(found) if found else None


def slack(milestones: list[Milestone]) -> dict[int, int]:
    """For each step not yet submitted, how many days it can run late before the move-in date moves."""
    end_all = move_in(milestones)
    if end_all is None:
        return {}
    last = {m.seq for m in last_steps(milestones)}
    waiting: dict[int, list[Milestone]] = {m.seq: [] for m in milestones}  # the steps that wait for each step
    for m in milestones:
        for s in predecessors(m):
            if s in waiting:
                waiting[s].append(m)
    out: dict[int, int] = {}
    for m in sorted(milestones, key=lambda m: -m.seq):  # the steps that wait for it come first
        if m.status != "pending":
            continue
        end = _aware(m.end_date)
        # the gap before each step that waits for it, plus that step's own room; the last steps have until move-in
        room = [_aware(n.start_date) - end + timedelta(days=out.get(n.id, 0)) for n in waiting[m.seq]]
        if m.seq in last:
            room.append(end_all - end)
        out[m.id] = max(0, _days(min(room)))
    return out


@dataclass
class Move:
    milestone: Milestone
    start_before: datetime
    end_before: datetime
    start_after: datetime
    end_after: datetime

    def as_dict(self) -> dict:
        m = self.milestone
        return {
            "milestone_id": m.id,
            "seq": m.seq,
            "title": m.title,
            "amount": str(m.amount),
            "start_before": self.start_before.isoformat(),
            "end_before": self.end_before.isoformat(),
            "start_after": self.start_after.isoformat(),
            "end_after": self.end_after.isoformat(),
        }


@dataclass
class WhatIf:
    milestone: Milestone
    days: int
    moves: list[Move]
    move_in_before: datetime
    move_in_after: datetime

    @property
    def move_in_days(self) -> int:
        return _days(self.move_in_after - self.move_in_before)


def what_if(project: RebuildProject, milestone: Milestone, days: int) -> WhatIf:
    """The schedule if `milestone` takes `days` longer than planned. Nothing is saved."""
    if milestone.project_id != project.id:
        raise ScheduleError("That step isn't part of this project")
    if project.status != "active":
        raise ScheduleError(f"The project is {project.status}")
    if milestone.status != "pending":
        raise ScheduleError("Only a step that hasn't been submitted yet can run late")
    if not 1 <= days <= MAX_DELAY_DAYS:
        raise ScheduleError(f"A delay is 1 to {MAX_DELAY_DAYS} days")
    milestones = list(project.milestones)
    new: dict[int, tuple[datetime, datetime]] = {}
    for m in sorted(milestones, key=lambda m: m.seq):
        start, end = _aware(m.start_date), _aware(m.end_date)
        if m.status == "pending":  # submitted and paid work stays where it is
            length = end - start + (timedelta(days=days) if m.id == milestone.id else timedelta())
            ready = max((new[s][1] for s in predecessors(m) if s in new), default=start)
            start = max(start, ready)
            end = start + length
        new[m.seq] = (start, end)
    moves = [
        Move(m, _aware(m.start_date), _aware(m.end_date), *new[m.seq])
        for m in milestones
        if new[m.seq] != (_aware(m.start_date), _aware(m.end_date))
    ]
    before = move_in(milestones)
    after = max(new[m.seq][1] for m in last_steps(milestones))
    return WhatIf(milestone, days, moves, before, after)


def record_delay(
    db: Session, project: RebuildProject, milestone: Milestone, days: int, reason: str, actor: User
) -> ScheduleChange:
    """Save a delay: the late step and every step after it move, the plan the homeowner accepted stays as the
    baseline, and the change (with the contractor's reason) is kept for the homeowner to see."""
    reason = reason.strip()
    if len(reason) < 3:
        raise ScheduleError("Say why the step is late")
    result = what_if(project, milestone, days)
    for mv in result.moves:
        mv.milestone.start_date, mv.milestone.end_date = mv.start_after, mv.end_after
    change = ScheduleChange(
        project_id=project.id,
        milestone_id=milestone.id,
        days=days,
        reason=reason[:300],
        moved=[mv.as_dict() for mv in result.moves],
        move_in_before=result.move_in_before,
        move_in_after=result.move_in_after,
        created_by_user_id=actor.id,
    )
    db.add(change)
    db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        action="project.delayed",
        subject_type="project",
        subject_id=project.id,
        data={
            "milestone_id": milestone.id,
            "days": days,
            "moved": [mv.milestone.id for mv in result.moves],
            "move_in_before": result.move_in_before.isoformat(),
            "move_in_after": result.move_in_after.isoformat(),
        },
    )
    db.commit()
    return change


def violations(milestones: list[Milestone]) -> list[str]:
    """Steps not yet submitted that would start before a step they wait for ends."""
    by_seq = {m.seq: m for m in milestones}
    out = []
    for m in milestones:
        if m.status != "pending":
            continue
        for s in predecessors(m):
            before = by_seq.get(s)
            if before is not None and _aware(m.start_date) < _aware(before.end_date):
                out.append(f"{m.title} can't start before {before.title} ends")
    return out


def infer_after(milestones: list[Milestone]) -> None:
    """For steps whose plan doesn't say what they wait for: the step before, if it ends by the time this one starts;
    otherwise the latest earlier step that does (steps planned to overlap run side by side). The contractor's dates
    stay exactly as planned."""
    ordered = sorted(milestones, key=lambda m: m.seq)
    for i, m in enumerate(ordered):
        if m.after is not None:
            continue
        ready = [p for p in ordered[:i] if _aware(p.end_date) <= _aware(m.start_date)]
        if i and ordered[i - 1] in ready:
            m.after = [ordered[i - 1].seq]
        else:
            m.after = [max(ready, key=lambda p: _aware(p.end_date)).seq] if ready else []


def set_baseline(project: RebuildProject) -> None:
    """The plan the homeowner accepts becomes the baseline later changes are measured against."""
    for m in project.milestones:
        m.baseline_start, m.baseline_end = _aware(m.start_date), _aware(m.end_date)
