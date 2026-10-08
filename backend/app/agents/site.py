"""Site agent: checks a contractor's milestone photos against what "done" should look like.

It only reports what it sees. A homeowner (and for large amounts, a human reviewer) decides
whether the contractor gets paid.
"""

import base64
import logging

from pydantic import BaseModel

from app import ai

log = logging.getLogger(__name__)

SYSTEM = """You inspect construction progress photos for a homeowner rebuilding after a disaster.
You get the milestone the contractor says is finished, a description of what "done" looks like,
and photos. Report only what the photos show.
verdict: "matches" if the photos clearly show the work as described, "partial" if some of it is
visible but parts are missing or unclear, "does_not_match" if the photos don't show this work
(or show a different site, stock photos, or unrelated rooms).
observations: up to 4 short factual notes about what is visible.
concerns: anything the homeowner should ask about (missing items, quality, safety). Empty if none.
confidence is 0-1."""


class SiteCheck(BaseModel):
    verdict: str
    confidence: float
    observations: list[str]
    concerns: list[str]


def check(milestone_title: str, done_looks_like: str, jpegs: list[bytes]) -> SiteCheck:
    content = [ai.image_part(base64.standard_b64encode(j).decode()) for j in jpegs]
    content.append(ai.text_part(f"Milestone: {milestone_title}\nDone looks like: {done_looks_like}"))
    try:
        result = ai.parse(SiteCheck, system=SYSTEM, content=content, max_tokens=1500)
    except Exception:  # without the AI the homeowner and reviewers still see the photos
        log.exception("Site check failed")
        return SiteCheck(
            verdict="unchecked", confidence=0.0, observations=[], concerns=["Automatic photo check unavailable"]
        )
    if result.verdict not in {"matches", "partial", "does_not_match"}:
        result.verdict = "partial"
    result.confidence = min(max(result.confidence, 0.0), 1.0)
    return result
