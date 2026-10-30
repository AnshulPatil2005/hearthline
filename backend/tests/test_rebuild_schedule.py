"""Rebuild what-if: steps wait for the steps before them (or the ones the plan names); a late step moves every step
that waits for it, no earlier than planned; move-in waits for the last steps. The server's arithmetic matches Bryntum
Gantt's engine (startnoearlierthan + finish-to-start), so what the contractor previews is what the homeowner is told."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import navigator, rebuild_schedule
from app.db import SessionLocal
from app.models import Household, Milestone, RebuildProject
from tests.helpers import client, login_as
from tests.test_rebuild import START, fund_household, new_project

DAY0 = datetime(2026, 11, 2, 8, tzinfo=UTC)

# (title, status, start day, length in days, after): the Riveras' plan, with the rough-in alongside the roof
RIVERA = [
    ("Deposit", "paid", 0, 3, None),
    ("Demolition", "submitted", 6, 16, None),
    ("Foundation", "pending", 25, 14, None),
    ("Framing", "pending", 40, 21, None),
    ("Roofing", "pending", 62, 10, None),
    ("Rough-in", "pending", 62, 14, [4]),
]


def project(rows=RIVERA, status="active") -> RebuildProject:
    p = RebuildProject(id=1, title="Rebuild", status=status)
    for seq, (title, st, start, length, after) in enumerate(rows, start=1):
        p.milestones.append(
            Milestone(
                id=seq,
                project_id=1,
                seq=seq,
                title=title,
                amount=D("1000"),
                status=st,
                start_date=DAY0 + timedelta(days=start),
                end_date=DAY0 + timedelta(days=start + length),
                after=after,
            )
        )
    return p


def at(iso: str) -> datetime:
    """The API's times, with or without a zone (SQLite drops it), as UTC."""
    return rebuild_schedule._aware(datetime.fromisoformat(iso.replace("Z", "+00:00")))


def step(p: RebuildProject, title: str) -> Milestone:
    return next(m for m in p.milestones if m.title == title)


def test_dependencies_move_in_and_days_to_spare():
    p = project()
    ms = p.milestones
    assert [rebuild_schedule.predecessors(m) for m in ms] == [[], [1], [2], [3], [4], [4]]
    assert [m.title for m in rebuild_schedule.last_steps(ms)] == ["Roofing", "Rough-in"]
    assert rebuild_schedule.move_in(ms) == DAY0 + timedelta(days=76)  # the rough-in ends last
    spare = {m.title: rebuild_schedule.slack(ms)[m.id] for m in ms if m.status == "pending"}
    # the roof has 4 days before the rough-in sets move-in; framing 1 (the gap before both); foundation 2
    assert spare == {"Foundation": 2, "Framing": 1, "Roofing": 4, "Rough-in": 0}


@pytest.mark.parametrize(
    ("title", "days", "move_in_days", "moved"),
    [
        ("Roofing", 3, 0, ["Roofing"]),  # within its days to spare
        ("Roofing", 7, 3, ["Roofing"]),  # 4 of the 7 absorbed
        ("Foundation", 2, 0, ["Foundation", "Framing"]),  # framing moves a day into its gap; move-in doesn't
        ("Foundation", 10, 8, ["Foundation", "Framing", "Roofing", "Rough-in"]),
        ("Framing", 14, 13, ["Framing", "Roofing", "Rough-in"]),
    ],
)
def test_what_if(title, days, move_in_days, moved):
    p = project()
    before = {m.id: (m.start_date, m.end_date) for m in p.milestones}
    result = rebuild_schedule.what_if(p, step(p, title), days)
    assert result.move_in_days == move_in_days
    assert [mv.milestone.title for mv in result.moves] == moved
    late = next(mv for mv in result.moves if mv.milestone.title == title)
    assert late.end_after - late.start_after == late.end_before - late.start_before + timedelta(days=days)
    for mv in result.moves:  # a step that waits never starts before what it waits for ends
        for s in rebuild_schedule.predecessors(mv.milestone):
            prev = next((x for x in result.moves if x.milestone.seq == s), None)
            prev_end = prev.end_after if prev else p.milestones[s - 1].end_date
            assert mv.start_after >= prev_end
    assert {m.id: (m.start_date, m.end_date) for m in p.milestones} == before  # nothing saved


def test_what_if_refuses():
    p = project()
    with pytest.raises(rebuild_schedule.ScheduleError, match="hasn't been submitted"):
        rebuild_schedule.what_if(p, step(p, "Demolition"), 3)
    with pytest.raises(rebuild_schedule.ScheduleError, match="1 to 120"):
        rebuild_schedule.what_if(p, step(p, "Framing"), 0)
    done = project(status="completed")
    with pytest.raises(rebuild_schedule.ScheduleError, match="completed"):
        rebuild_schedule.what_if(done, step(done, "Framing"), 3)


def test_overlapping_steps_in_a_plan_run_side_by_side():
    rows = [
        ("Demolition", "pending", 0, 7, None),
        ("Permits", "pending", 3, 5, None),  # planned to overlap demolition
        ("Foundation", "pending", 8, 7, None),
    ]
    p = project(rows)
    rebuild_schedule.infer_after(p.milestones)
    assert [m.after for m in p.milestones] == [[], [], [2]]
    assert rebuild_schedule.violations(p.milestones) == []


def contract(after_roof: list[int] | None = None) -> tuple[dict, dict, dict]:
    """A four-step plan, accepted: demolition, framing, then roof and rough-in side by side."""
    fund_household("40000")
    elena = login_as("Elena Rivera")
    p = new_project(elena)
    dana = login_as("Dana Okafor")
    steps = [("Demolition", 0, 7, None), ("Framing", 7, 14, None), ("Roof", 21, 7, None), ("Rough-in", 21, 10, [2])]
    body = {
        "milestones": [
            {
                "title": t,
                "amount": "5000",
                "done_looks_like": f"{t} done",
                "start_date": (START + timedelta(days=s)).isoformat(),
                "end_date": (START + timedelta(days=s + n)).isoformat(),
                **({"after": after} if after else {}),
            }
            for t, s, n, after in steps
        ]
    }
    assert client.put(f"/projects/{p['id']}/plan", headers=dana, json=body).status_code == 200
    accepted = client.post(f"/projects/{p['id']}/accept", headers=elena).json()
    return accepted, elena, dana


def test_contractor_previews_then_tells_the_homeowner():
    p, elena, dana = contract()
    roof, framing = p["milestones"][2], p["milestones"][1]
    assert at(p["move_in"]) == at(p["planned_move_in"]) and roof["slack_days"] == 3 and roof["after"] == [2]
    assert all(at(m["baseline_end"]) == at(m["end_date"]) for m in p["milestones"])

    preview = client.post(f"/projects/{p['id']}/what-if", headers=dana, json={"milestone_id": roof["id"], "days": 2})
    assert preview.json()["move_in_days"] == 0 and preview.json()["slack_days"] == 3
    preview = client.post(f"/projects/{p['id']}/what-if", headers=dana, json={"milestone_id": framing["id"], "days": 5})
    assert preview.json()["move_in_days"] == 5 and [m["title"] for m in preview.json()["moved"]] == [
        "Framing",
        "Roof",
        "Rough-in",
    ]
    assert client.get(f"/projects/{p['id']}", headers=elena).json()["move_in"] == p["move_in"]  # nothing saved

    # only the project's contractor, with a reason
    body = {"milestone_id": framing["id"], "days": 5, "reason": "Lumber is two weeks late"}
    assert client.post(f"/projects/{p['id']}/delays", headers=elena, json=body).status_code == 403
    short = client.post(f"/projects/{p['id']}/delays", headers=dana, json={**body, "reason": "x"})
    assert short.status_code == 422
    saved = client.post(f"/projects/{p['id']}/delays", headers=dana, json=body)
    assert saved.status_code == 201 and saved.json()["milestone_title"] == "Framing"

    after = client.get(f"/projects/{p['id']}", headers=elena).json()
    change = after["changes"][0]
    assert change["reason"] == "Lumber is two weeks late" and len(change["moved"]) == 3
    assert at(after["planned_move_in"]) == at(p["planned_move_in"])  # the baseline stays the accepted plan
    assert at(after["move_in"]) - at(p["move_in"]) == timedelta(days=5)
    moved_framing = after["milestones"][1]
    assert at(moved_framing["baseline_end"]) == at(framing["end_date"]) != at(moved_framing["end_date"])

    # the Gantt shows the new dates with the accepted plan as the baseline
    loaded = client.get(f"/bryntum/gantt/{p['id']}/load", headers=elena).json()
    task = next(c for c in loaded["tasks"]["rows"][0]["children"] if c["id"] == framing["id"])
    assert at(task["baselines"][0]["endDate"]) == at(framing["end_date"]) != at(task["endDate"])

    # the family's navigator says why move-in moved, dated the new move-in day
    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        found = [s for s in navigator.steps(db, home, date(2026, 10, 30)) if s.key == "move_in_moved"]
    assert found and found[0].params["days"] == 5 and found[0].due == at(after["move_in"]).date()
    assert "Lumber is two weeks late" in found[0].words()


def test_paid_work_and_strangers():
    p, elena, dana = contract()
    first = p["milestones"][0]
    with SessionLocal() as db:
        db.get(Milestone, first["id"]).status = "paid"
        db.commit()
    paid = client.post(
        f"/projects/{p['id']}/delays", headers=dana, json={"milestone_id": first["id"], "days": 3, "reason": "Rain"}
    )
    assert paid.status_code == 409
    other = client.post(f"/projects/{p['id']}/what-if", headers=dana, json={"milestone_id": 999999, "days": 3})
    assert other.status_code == 404


def test_a_plan_can_say_what_a_step_waits_for():
    fund_household("40000")
    elena = login_as("Elena Rivera")
    p = new_project(elena)
    dana = login_as("Dana Okafor")
    body = {
        "milestones": [
            {
                "title": "Framing",
                "amount": "5000",
                "start_date": START.isoformat(),
                "end_date": (START + timedelta(days=10)).isoformat(),
            },
            {
                "title": "Roof",
                "amount": "5000",
                "start_date": (START + timedelta(days=5)).isoformat(),  # before framing ends
                "end_date": (START + timedelta(days=12)).isoformat(),
                "after": [1],
            },
        ]
    }
    r = client.put(f"/projects/{p['id']}/plan", headers=dana, json=body)
    assert r.status_code == 409 and "Roof can't start before Framing ends" in r.json()["detail"]
    body["milestones"][1]["after"] = [2]  # only earlier steps
    assert client.put(f"/projects/{p['id']}/plan", headers=dana, json=body).status_code == 409
