from datetime import datetime

import pytest

from app import seed_command
from app.db import SessionLocal
from app.models import Crew, CrewJob
from tests.helpers import client, login_as

LOAD, SYNC = "/bryntum/crews/load", "/bryntum/crews/sync"


@pytest.fixture
def sam(monkeypatch):
    headers = login_as("Sam Whitfield")
    monkeypatch.setattr(seed_command, "COUNT", 150)
    with SessionLocal() as db:
        seed_command.seed_command_center(db)
        seed_command.seed_crews(db)
    return headers


def test_load_has_crews_jobs_and_one_assignment_per_job(sam):
    data = client.get(LOAD, headers=sam, params={"data": '{"requestId": 7}'}).json()
    assert data["success"] and data["requestId"] == 7
    ids = [r["id"] for r in data["resources"]["rows"]]
    assert ids[0] == "unassigned" and len(ids) == 9
    events, assignments = data["events"]["rows"], data["assignments"]["rows"]
    assert len(events) == len(assignments) > 20
    assert {a["eventId"] for a in assignments} == {e["id"] for e in events}
    assert any(a["resourceId"] == "unassigned" for a in assignments)
    done = [e for e in events if e["status"] == "done"]
    assert done and all(not e["draggable"] and e["eventColor"] == "gray" for e in done)
    assert all(e["preamble"] == "20 minutes" for e in events)


def _a_job(status: str = "scheduled", assigned: bool = False) -> CrewJob:
    with SessionLocal() as db:
        q = db.query(CrewJob).filter(CrewJob.status == status)
        q = q.filter(CrewJob.crew_id.is_not(None)) if assigned else q.filter(CrewJob.crew_id.is_(None))
        job = q.first()
        db.expunge(job)
        return job


def test_dispatcher_assigns_and_reschedules_a_job(sam):
    job = _a_job()
    with SessionLocal() as db:
        tarp = db.query(Crew).filter_by(name="Tarp Team").one().id
    body = {
        "requestId": 3,
        "events": {"updated": [{"id": job.id, "startDate": "2026-10-20T16:00:00Z", "endDate": "2026-10-20T19:00:00Z"}]},
        "assignments": {"updated": [{"id": job.id, "resourceId": tarp}]},
    }
    r = client.post(SYNC, headers=sam, json=body).json()
    assert r["success"] and r["events"]["rows"] == [{"id": job.id}]
    with SessionLocal() as db:
        saved = db.get(CrewJob, job.id)
        assert saved.crew_id == tarp and saved.starts_at.replace(tzinfo=None) == datetime(2026, 10, 20, 16)


def test_marking_done_and_done_jobs_stay_put(sam):
    job = _a_job(assigned=True)
    r = client.post(SYNC, headers=sam, json={"events": {"updated": [{"id": job.id, "status": "done"}]}}).json()
    assert r["success"] and r["events"]["rows"][0]["eventColor"] == "gray"
    moved = client.post(
        SYNC, headers=sam, json={"events": {"updated": [{"id": job.id, "startDate": "2026-10-21T16:00:00Z"}]}}
    ).json()
    assert moved["success"] is False and "already done" in moved["message"]


def test_jobs_cannot_be_created_or_deleted_or_given_to_unknown_crews(sam):
    job = _a_job()
    added = client.post(SYNC, headers=sam, json={"events": {"added": [{"$PhantomId": "x", "name": "New"}]}}).json()
    removed = client.post(SYNC, headers=sam, json={"events": {"removed": [{"id": job.id}]}}).json()
    unknown = client.post(
        SYNC, headers=sam, json={"assignments": {"updated": [{"id": job.id, "resourceId": 999}]}}
    ).json()
    backwards = client.post(
        SYNC,
        headers=sam,
        json={
            "events": {
                "updated": [{"id": job.id, "startDate": "2026-10-21T16:00:00Z", "endDate": "2026-10-21T15:00:00Z"}]
            }
        },
    ).json()
    assert [x["success"] for x in (added, removed, unknown, backwards)] == [False] * 4
    with SessionLocal() as db:
        assert db.get(CrewJob, job.id).crew_id is None


def test_only_dispatchers(sam):
    assert client.get(LOAD, headers=login_as("Priya Nair")).status_code == 403
    assert client.post(SYNC, headers=login_as("Dana Okafor"), json={}).status_code == 403
    assert client.get(LOAD, headers=login_as("Grace Alvarez")).status_code == 200
