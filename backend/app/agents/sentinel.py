"""Sentinel agent: explains a case's warning signs in plain English for the human reviewer.

It never approves or rejects anything. If the AI is unavailable, reviewers still get the rule
messages verbatim.
"""

import json
import logging

from pydantic import BaseModel

from app import ai
from app.trust import Flag

log = logging.getLogger(__name__)

SYSTEM = """You help human reviewers at a disaster relief organization check aid claims for fraud.
You receive the facts about one household's claim and the automated warning signs.
Write for a busy caseworker: plain words, no jargon, no accusations. Real disaster victims often
lose documents and photos, so a warning sign is a reason to ask, not proof of fraud.
summary: 2-3 sentences on what stands out and how serious it looks.
questions: up to 3 specific questions the reviewer could ask the household to resolve the warnings.
recommendation: one of "approve", "ask_for_evidence", "escalate"."""


class SentinelNote(BaseModel):
    summary: str
    questions: list[str]
    recommendation: str


def explain(case_facts: dict, flags: list[Flag]) -> SentinelNote:
    if not flags:
        return SentinelNote(summary="No warning signs were found.", questions=[], recommendation="approve")
    payload = {"facts": case_facts, "warning_signs": [{"severity": f.severity, "what": f.message} for f in flags]}
    try:
        note = ai.parse(
            SentinelNote, system=SYSTEM, content=[ai.text_part(json.dumps(payload, default=str))], max_tokens=1200
        )
    except Exception:  # the review must work without the AI
        log.exception("Sentinel explanation failed; using rule messages")
        return SentinelNote(summary=" ".join(f.message for f in flags), questions=[], recommendation="escalate")
    if note.recommendation not in {"approve", "ask_for_evidence", "escalate"}:
        note.recommendation = "escalate"
    note.questions = note.questions[:3]
    return note
