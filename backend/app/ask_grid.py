"""Ask the grid: a question in plain language becomes Command Center grid state.

The browser sends AG Grid's own description of its state (the AI Toolkit's `getStructuredSchema()`).
The model fills it in; this module checks the answer against what the households query really supports
before the browser applies it with `api.setState()`. The model never sees household data.
"""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, command
from app.models import Household

MAX_SCHEMA_CHARS = 60_000
FEATURES = ("filter", "sort", "rowGroup", "aggregation", "columnVisibility")

SYSTEM = """You help relief-organization staff explore the households affected by the Sablewood Fire
(a fictional wildfire) in a data grid. Turn the request into grid state and call submit with:
- explanation: one short sentence, in the same language as the request, saying what the grid now shows.
- state: the grid state, following the schema.

Rules for state:
- filter: exactly the filters the request asks for. Leave out every column it doesn't mention; never
  add a placeholder filter. A combined filter (operator + conditions) may have one condition.
- sort: what the request asks for; otherwise sort by unmet_need descending (biggest need first).
- rowGroup: only when the request asks to group or break down by something; otherwise no grouping.
- aggregation and columnVisibility: null unless the request asks about totals or showing/hiding columns.

Columns:
- name: household name, e.g. "Garcia household". address_line: e.g. "214 Juniper Lane".
- street: one of {streets}.
- damage_level: destroyed, major, minor, affected or unknown.
- verification_level: "0" (outside the burn area or unverified), "1" (address inside the burn area),
  "2" (residence confirmed; can receive cash aid), "3" (also has an inventory scanned before the fire).
  "Verified" means "2" or "3".
- household_size: number of people.
- needs: shelter, food, water, clothing, medical, transport, childcare, pet_care, mental_health
  (counseling), repairs, cleanup. A household can have several; a needs filter matches households with
  ANY of the chosen needs, so say "or" in the explanation when you choose more than one.
- estimated_loss, help_received, unmet_need: US dollars. unmet_need is what they still need
  ("still needed", "gap", "shortfall"). help_received is gifts, insurance and cash aid so far.
- payout_ready: true when the household has a PayPal account to receive cash aid.
- registered: the date the household signed up (YYYY-MM-DD). Today is {today}."""


class Unsupported(ValueError):
    pass


def _check(answer: dict[str, Any]) -> dict[str, Any]:
    """Keep only what the households query can do; raise with a reason the model can fix."""
    state = answer.get("state")
    if not isinstance(state, dict) or not isinstance(answer.get("explanation"), str):
        raise ValueError("Submit an object with `explanation` (text) and `state` (the grid state)")
    hh = command._households()
    allowed = set(hh.c.keys())

    filters = {
        k: v
        for k, v in ((state.get("filter") or {}).get("filterModel") or {}).items()
        if v and not (v.get("filterType") == "set" and not v.get("values"))  # an empty set filter matches nobody
    }
    try:
        command._where(hh, filters)
    except command.BadRequest as e:
        raise ValueError(f"Bad filter: {e}") from None

    sort = [
        {"colId": s["colId"], "sort": "desc" if s.get("sort") == "desc" else "asc"}
        for s in ((state.get("sort") or {}).get("sortModel") or [])
        if isinstance(s, dict) and s.get("colId") in allowed
    ] or [{"colId": "unmet_need", "sort": "desc"}]

    groups = list((state.get("rowGroup") or {}).get("groupColIds") or [])
    bad = [g for g in groups if g not in command.GROUPABLE]
    if bad:
        raise ValueError(f"Can't group by {', '.join(bad)}; group by one of {', '.join(sorted(command.GROUPABLE))}")

    out: dict[str, Any] = {
        "filter": {"filterModel": filters},
        "sort": {"sortModel": sort},
        "rowGroup": {"groupColIds": groups},
    }
    if state.get("aggregation"):
        out["aggregation"] = state["aggregation"]
    if (state.get("columnVisibility") or {}).get("hiddenColIds"):  # an empty list would unhide every column
        out["columnVisibility"] = state["columnVisibility"]
    return {"explanation": answer["explanation"].strip()[:300], "state": out}


def _relax(node: Any) -> Any:
    """AG Grid writes its schema for strict structured output: every filter column is required (but
    nullable) and a combined filter has exactly two conditions. Given that as a function schema, models
    fill the required slots with placeholder filters ("help received equals 0"). Let them leave columns
    out and use a single condition instead."""
    if isinstance(node, list):
        return [_relax(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: _relax(v) for k, v in node.items()}
    if isinstance(out.get("filterModel"), dict):
        out["filterModel"].pop("required", None)
    if out.get("type") == "array" and out.get("minItems") == 2:
        out["minItems"] = 1
    return out


def ask(db: Session, question: str, grid_schema: dict[str, Any]) -> dict[str, Any]:
    if len(str(grid_schema)) > MAX_SCHEMA_CHARS:
        raise Unsupported("That grid description is too large")
    schema = _relax(grid_schema)
    defs = schema.pop("$defs", {})
    parameters = {
        "type": "object",
        "required": ["explanation", "state"],
        "additionalProperties": False,
        "properties": {
            "explanation": {"type": "string", "description": "One short sentence: what the grid now shows."},
            "state": schema,
        },
        "$defs": defs,  # AG Grid's references point at the root
    }
    streets = sorted({s for (s,) in db.execute(select(Household.street).distinct()) if s})
    system = SYSTEM.format(streets=", ".join(streets), today=date.today().isoformat())
    result = ai.parse_json(parameters, _check, system=system, content=[ai.text_part(question)], max_tokens=4000)
    matching = command.rows(db, {"filterModel": result["state"]["filter"]["filterModel"], "startRow": 0, "endRow": 1})
    return {**result, "matching": matching["matching"]}
