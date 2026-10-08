import pytest

from app import ai, ask_grid, seed_command
from app.db import SessionLocal
from tests.helpers import client, login_as

GRID_SCHEMA = {
    "type": "object",
    "properties": {"filter": {"$ref": "#/$defs/filter"}},
    "$defs": {"filter": {"type": ["object", "null"]}},
}


@pytest.fixture
def sam(monkeypatch):
    headers = login_as("Sam Whitfield")
    monkeypatch.setattr(seed_command, "COUNT", 60)
    with SessionLocal() as db:
        seed_command.seed_command_center(db)
    return headers


def answering(monkeypatch, answer: dict) -> dict:
    """Fake model: records what it was sent, then runs the real answer check on `answer`."""
    seen = {}

    def fake(parameters, check, *, system, content, max_tokens):
        seen.update(parameters=parameters, system=system, question=content[0]["text"])
        return check(answer)

    monkeypatch.setattr(ai, "parse_json", fake)
    return seen


def ask(headers, question="destroyed homes that can get cash aid"):
    return client.post("/command/ask", headers=headers, json={"question": question, "grid_schema": GRID_SCHEMA})


def test_a_question_becomes_checked_grid_state(sam, monkeypatch):
    seen = answering(
        monkeypatch,
        {
            "explanation": "Destroyed homes with PayPal ready, biggest need first.",
            "state": {
                "filter": {
                    "filterModel": {
                        "damage_level": {"filterType": "set", "values": ["destroyed"]},
                        "payout_ready": {"filterType": "set", "values": ["true"]},
                        "name": None,  # columns the request didn't mention come back null
                    }
                },
                "sort": None,
                "rowGroup": None,
                "aggregation": None,
                "columnVisibility": None,
            },
        },
    )
    r = ask(sam)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["state"]["filter"]["filterModel"]) == {"damage_level", "payout_ready"}
    assert body["state"]["sort"] == {"sortModel": [{"colId": "unmet_need", "sort": "desc"}]}  # the default
    assert body["state"]["rowGroup"] == {"groupColIds": []}
    assert body["matching"] > 0 and body["explanation"].startswith("Destroyed")
    # AG Grid's schema is sent as the `state` argument, with its $defs moved to the root so refs resolve.
    assert seen["parameters"]["properties"]["state"]["properties"] == GRID_SCHEMA["properties"]
    assert "filter" in seen["parameters"]["$defs"] and "Juniper Lane" in seen["system"]


def test_answers_the_query_cannot_run_are_sent_back_to_the_model(sam):
    with pytest.raises(ValueError, match="group by"):
        ask_grid._check({"explanation": "x", "state": {"rowGroup": {"groupColIds": ["name"]}}})
    with pytest.raises(ValueError, match="Bad filter"):
        ask_grid._check(
            {"explanation": "x", "state": {"filter": {"filterModel": {"payout_email": {"filterType": "text"}}}}}
        )
    with pytest.raises(ValueError, match="explanation"):
        ask_grid._check({"state": {}})


def test_grouping_and_sorting_pass_through(sam, monkeypatch):
    answering(
        monkeypatch,
        {
            "explanation": "Total still needed by street.",
            "state": {
                "filter": None,
                "sort": {"sortModel": [{"colId": "unmet_need", "sort": "desc"}, {"colId": "bogus", "sort": "asc"}]},
                "rowGroup": {"groupColIds": ["street"]},
                "aggregation": {"aggregationModel": [{"colId": "unmet_need", "aggFunc": "sum"}]},
                "columnVisibility": None,
            },
        },
    )
    body = ask(sam, "total still needed by street").json()
    assert body["state"]["rowGroup"] == {"groupColIds": ["street"]}
    assert body["state"]["sort"]["sortModel"] == [{"colId": "unmet_need", "sort": "desc"}]
    assert body["state"]["aggregation"]["aggregationModel"][0]["colId"] == "unmet_need"
    assert body["matching"] == 61


def test_when_no_model_can_answer(sam, monkeypatch):
    def down(*a, **k):
        raise ai.AIError("all busy")

    monkeypatch.setattr(ai, "parse_json", down)
    r = ask(sam)
    assert r.status_code == 503 and "column filters" in r.json()["detail"]


def test_only_organization_staff_can_ask(sam):
    assert ask(login_as("Priya Nair")).status_code == 403
