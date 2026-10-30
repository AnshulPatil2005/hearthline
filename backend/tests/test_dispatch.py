"""The dispatch agent: code finds each crew's free time, the drives and how urgent each request is; the AI (stubbed)
only picks a crew and an order and explains; code packs the times, and nothing moves until a person accepts."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from app import ai, dispatch, seed_command
from app.db import SessionLocal
from app.models import Crew, CrewJob, DispatchProposal
from tests.helpers import client, login_as

PLAN = "/command/dispatch/plan"
DAY = (datetime.now(dispatch.SITE) + timedelta(days=1)).date()  # the seed books crews around today
HERE, NEAR, FAR = (38.709, -120.627), (38.712, -120.63), (38.80, -120.40)


def utc(s: str) -> datetime:
    return dispatch._aware(datetime.fromisoformat(s))


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=dispatch.SITE).astimezone(UTC)


@pytest.fixture
def sam(monkeypatch):
    headers = login_as("Sam Whitfield")
    monkeypatch.setattr(seed_command, "COUNT", 150)
    with SessionLocal() as db:
        seed_command.seed_command_center(db)
        seed_command.seed_crews(db)
    return headers


@pytest.fixture
def agent(monkeypatch):
    """The AI picks the first crew it's offered for every job, in the order given; tests can change a pick."""
    seen: list[dict] = []
    changes: dict[int, int | None] = {}

    def parse(output_format, *, system, content, max_tokens=8000):
        facts = json.loads(content[0]["text"])
        seen.append(facts)
        picks = [
            dispatch.Pick(
                job_id=j["job_id"], crew_id=changes.get(j["job_id"], j["crews"][0]), reason=f"Job {j['job_id']}"
            )
            for j in facts["jobs"]
        ]
        return dispatch.Choice(
            summary="Medical needs first.", picks=[*picks, dispatch.Pick(job_id=999999, crew_id=1, reason="made up")]
        )

    monkeypatch.setattr(ai, "parse", parse)
    return seen, changes


def test_drives_and_urgency():
    assert dispatch.travel_minutes(HERE, HERE) == 10  # getting going takes time even next door
    assert dispatch.travel_minutes(HERE, FAR) % 5 == 0 and dispatch.travel_minutes(HERE, FAR) > 30


def test_fit_leaves_room_for_the_drive_before_and_after():
    morning = [dispatch.Stop(at(8, 20), at(12), HERE)]
    # the earliest start after the morning job is noon plus the drive; the work must also end by 6 pm
    starts = dispatch.fit(morning, DAY, NEAR, 60)
    assert starts == [(at(12, 10), 10)]
    # a job right after lunch leaves too little time to drive to it from the morning job
    lunch = [*morning, dispatch.Stop(at(13, 10), at(17), FAR)]
    assert dispatch.fit(lunch, DAY, NEAR, 60) == []
    assert dispatch.fit([], DAY, HERE, 11 * 60) == []  # longer than the working day


def test_fits_at_checks_the_time_itself_whatever_order_people_accept_in():
    stops = [dispatch.Stop(at(8, 20), at(12), HERE)]
    # a proposal planned after another proposal still fits on its own once the first is rejected
    assert dispatch.fits_at(stops, DAY, NEAR, at(14), 60) == 10
    assert dispatch.fits_at(stops, DAY, NEAR, at(11), 60) is None  # overlaps
    assert dispatch.fits_at(stops, DAY, FAR, at(12, 5), 60) is None  # can't drive there in 5 minutes
    assert dispatch.fits_at([*stops, dispatch.Stop(at(15, 5), at(16), FAR)], DAY, NEAR, at(14), 60) is None
    assert dispatch.fits_at(stops, DAY, NEAR, at(17, 30), 60) is None  # past the working day


def _crew_days(db, day: date) -> dict[int, list[tuple[datetime, datetime]]]:
    return {c.id: [(s.start, s.end) for s in dispatch._crew_stops(db, c.id, day)] for c in db.query(Crew)}


def test_the_agent_picks_and_code_packs_the_times(sam, agent):
    seen, _ = agent
    r = client.post(PLAN, headers=sam, json={"day": DAY.isoformat(), "instructions": "Medical needs first."})
    assert r.status_code == 201
    plan = r.json()
    facts = seen[0]
    assert facts["coordinator_instructions"] == "Medical needs first." and facts["day"] == DAY.isoformat()
    # the jobs come most urgent first, with the reasons in words
    urgencies = [j["urgency"] for j in facts["jobs"]]
    assert urgencies == sorted(urgencies, reverse=True) and all(j["crews"] for j in facts["jobs"])
    assert plan["by_ai"] and plan["summary"] == "Medical needs first."
    assert len(plan["proposals"]) == len(facts["jobs"])  # the made-up job is ignored
    placed = [p for p in plan["proposals"] if p["status"] == "proposed"]
    assert placed and all(p["crew"] and p["reason"].endswith(f"Job {p['job_id']}") for p in placed)
    # every proposal is inside the working day, and no crew is booked twice
    with SessionLocal() as db:
        busy = _crew_days(db, DAY)
    day_start, day_end = dispatch._window(DAY)
    for p in placed:
        start, end = utc(p["starts_at"]), utc(p["ends_at"])
        assert day_start < start and end <= day_end
        busy[p["crew_id"]].append((start, end))
    for spans in busy.values():
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))
    # nothing moved yet
    with SessionLocal() as db:
        assert all(db.get(CrewJob, p["job_id"]).crew_id is None for p in placed)


def test_a_crew_of_the_wrong_kind_or_a_skip(sam, agent):
    _, changes = agent
    with SessionLocal() as db:
        found = dispatch.requests(db)
        wellness = next(c.id for c in db.query(Crew).filter_by(kind="wellness"))
    water = next(r for r in found if r.job.kind == "water")
    tarp = next(r for r in found if r.job.kind == "tarp_roof")
    changes[water.job.id] = wellness  # not a crew that can deliver water
    changes[tarp.job.id] = None  # the agent leaves it for another day
    plan = client.post(PLAN, headers=sam, json={"day": DAY.isoformat()}).json()
    by_job = {p["job_id"]: p for p in plan["proposals"]}
    assert by_job[water.job.id]["status"] == "proposed" and by_job[water.job.id]["crew_id"] in water.crews
    assert by_job[tarp.job.id]["status"] == "skipped" and by_job[tarp.job.id]["reason"] == f"Job {tarp.job.id}"


def test_without_the_ai_it_plans_by_urgency(sam, monkeypatch):
    def down(*a, **k):
        raise ai.AIError("down")

    monkeypatch.setattr(ai, "parse", down)
    plan = client.post(PLAN, headers=sam, json={"day": DAY.isoformat()}).json()
    assert not plan["by_ai"] and plan["summary"] == dispatch.FALLBACK_SUMMARY
    urgencies = [p["urgency"] for p in plan["proposals"]]
    assert urgencies == sorted(urgencies, reverse=True)
    assert all(p["reason"].startswith("Urgent") for p in plan["proposals"] if p["status"] == "proposed")


def test_people_accept_and_reject_in_any_order(sam, agent):
    plan = client.post(PLAN, headers=sam, json={"day": DAY.isoformat()}).json()
    open_ = [p for p in plan["proposals"] if p["status"] == "proposed"]
    last, first = open_[-1], open_[0]
    # accept the last one first, reject the first; accept the rest
    r = client.post(f"/command/dispatch/proposals/{last['id']}/accept", headers=sam)
    assert r.status_code == 200
    assert client.post(f"/command/dispatch/proposals/{last['id']}/accept", headers=sam).status_code == 409
    client.post(f"/command/dispatch/proposals/{first['id']}/reject", headers=sam)
    after = client.post(f"/command/dispatch/plans/{plan['id']}/accept-all", headers=sam).json()
    assert after["counts"]["accepted"] == len(open_) - 1 and after["counts"]["rejected"] == 1
    assert "stale" not in after["counts"] and "proposed" not in after["counts"]
    with SessionLocal() as db:
        job = db.get(CrewJob, last["job_id"])
        assert job.crew_id == last["crew_id"] and dispatch._aware(job.starts_at) == utc(last["starts_at"])
        assert db.get(CrewJob, first["job_id"]).crew_id is None
    assert client.get(PLAN, headers=sam).json()["id"] == plan["id"]


def test_a_proposal_that_no_longer_fits_goes_stale(sam, agent):
    plan = client.post(PLAN, headers=sam, json={"day": DAY.isoformat()}).json()
    p = next(p for p in plan["proposals"] if p["status"] == "proposed")
    with SessionLocal() as db:  # someone books the crew over that time by hand
        busy = db.query(CrewJob).filter(CrewJob.crew_id == p["crew_id"]).first()
        busy.starts_at, busy.ends_at = utc(p["starts_at"]), utc(p["ends_at"])
        db.commit()
    r = client.post(f"/command/dispatch/proposals/{p['id']}/accept", headers=sam)
    assert r.status_code == 409 and "no longer fits" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.get(DispatchProposal, p["id"]).status == "stale"
        assert db.get(CrewJob, p["job_id"]).crew_id is None


def test_open_proposals_are_ghosts_on_the_scheduler(sam, agent):
    plan = client.post(PLAN, headers=sam, json={"day": DAY.isoformat()}).json()
    open_ = [p for p in plan["proposals"] if p["status"] == "proposed"]
    data = client.get("/bryntum/crews/load", headers=sam).json()
    ghosts = [e for e in data["events"]["rows"] if e.get("proposal")]
    assert len(ghosts) == len(open_)
    assert all(g["id"].startswith("p") and not g["draggable"] and g["cls"] == "job-proposal" for g in ghosts)
    links = {a["eventId"]: a["resourceId"] for a in data["assignments"]["rows"]}
    assert all(links[f"p{p['id']}"] == p["crew_id"] for p in open_)
    # a ghost dragged by mistake changes nothing
    g = ghosts[0]
    r = client.post(
        "/bryntum/crews/sync",
        headers=sam,
        json={
            "events": {"updated": [{"id": g["id"], "startDate": at(9).isoformat()}]},
            "assignments": {"updated": [{"id": g["id"], "eventId": g["id"], "resourceId": 1}]},
        },
    ).json()
    assert r["success"] and r["events"]["rows"] == [] and r["assignments"]["rows"] == []


def test_only_dispatchers(sam):
    assert client.post(PLAN, headers=login_as("Priya Nair"), json={}).status_code == 403
    assert client.get(PLAN, headers=login_as("Dana Okafor")).status_code == 403
    assert client.get(PLAN, headers=sam).json() is None


def test_nothing_to_plan(sam, agent):
    with SessionLocal() as db:
        for job in db.query(CrewJob).filter(CrewJob.crew_id.is_(None)):
            job.crew_id = 1
        db.commit()
    r = client.post(PLAN, headers=sam, json={"day": (DAY + timedelta(days=1)).isoformat()})
    assert r.status_code == 409
