"""Policy agent: reads a household's insurance policy and answers questions about it.

It extracts what the policy says (limits, sub-limits, deductible, deadlines) with structured output.
Code, not the AI, then compares those numbers with the household's inventory. Read-only: it never files a
claim or talks to the insurer, and it isn't legal advice.
"""

import io
import logging
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app import ai
from app.agents.inventory import CATEGORIES

log = logging.getLogger(__name__)
MAX_CHARS = 60_000  # a homeowners policy with endorsements; more is trimmed


class NotAPolicy(ValueError):
    pass


class Coverage(BaseModel):
    name: str = Field(description='As the policy names it, e.g. "Coverage C - Personal Property"')
    kind: Literal["dwelling", "other_structures", "contents", "loss_of_use", "liability", "medical", "other"]
    limit: float | None = Field(description="US dollars; null if the policy gives none")
    notes: str = Field(description="One short line, e.g. 'replacement cost' or '24 months'")


class SubLimit(BaseModel):
    what: str = Field(description='e.g. "Jewelry, watches and furs (theft)"')
    limit: float
    keywords: list[str] = Field(
        description="8-15 lower-case words found in the names of such items, including specific item types "
        "(for jewelry: ring, necklace, earring, bracelet, pearl, diamond, gold, watch)"
    )
    categories: list[str] = Field(description=f"Inventory categories it applies to, from: {CATEGORIES}")


class Deadline(BaseModel):
    what: str = Field(description='e.g. "Sign and send a proof of loss"')
    days_after_loss: int | None = Field(
        description="Only when the policy counts from the date of loss; null if the clock starts from something "
        "else (such as the insurer's request)"
    )
    text: str = Field(description="The policy's own words, shortened")


class PolicySummary(BaseModel):
    insurer: str
    policy_number: str | None
    policy_type: Literal["homeowners", "renters", "condo", "dwelling_fire", "other"]
    period: str | None
    deductible: float | None
    contents_settlement: Literal["replacement_cost", "actual_cash_value", "unknown"]
    extended_replacement_percent: int | None = Field(description="Extra dwelling coverage above the limit, in %")
    coverages: list[Coverage]
    sub_limits: list[SubLimit]
    deadlines: list[Deadline]
    plain_summary: str = Field(description="Three short sentences for the family, in plain words")


class PolicyAnswer(BaseModel):
    answer: str = Field(description="2-4 sentences in plain words")
    quote: str | None = Field(description="The policy text the answer rests on, word for word")
    in_policy: bool = Field(description="False if the policy doesn't say")


READ_SYSTEM = f"""You read a family's insurance policy after their home was damaged in a disaster.
Extract exactly what the policy says; copy dollar amounts exactly; never guess. If something isn't in the
text, use null or an empty list. Sub-limits are the special lower limits for kinds of property (jewelry,
money, firearms, silverware, business property, ...): for each, give specific words that would appear in the
names of such items in a household inventory, and inventory categories from this list: {CATEGORIES}.
Deadlines are the duties after a loss with a number of
days (notice, proof of loss, inventory, suit); convert months to days (1 month = 30 days). This loss was
caused by a wildfire in a declared state of emergency: where the policy has rules for that, use them.
plain_summary: three short sentences a stressed family can
understand: what is covered (never say "fully covered": limits apply), how contents are paid
(replacement cost or actual cash value), what to do first."""

ASK_SYSTEM = """You answer a family's question about their own insurance policy, using only the policy text
given. Quote the exact sentence your answer rests on. If the policy doesn't answer it, say so and suggest
asking the insurer's adjuster. Explain what the policy says; don't promise what the insurer will pay. Don't
add disclaimers about not being a lawyer: the page already shows one."""


def pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except (PdfReadError, ValueError, KeyError) as e:
        raise NotAPolicy("That file isn't a readable PDF") from e
    text = " ".join(text.split())  # PDF text comes with ragged spacing
    if len(text) < 200:
        raise NotAPolicy("This PDF has no readable text (is it a scan?). Upload the policy PDF from your insurer.")
    return text[:MAX_CHARS]


def read(text: str) -> PolicySummary:
    return ai.parse(PolicySummary, system=READ_SYSTEM, content=[ai.text_part(text)], max_tokens=4000)


def ask(text: str, question: str) -> PolicyAnswer:
    return ai.parse(
        PolicyAnswer,
        system=ASK_SYSTEM,
        content=[ai.text_part(f"POLICY:\n{text}\n\nQUESTION: {question}")],
        max_tokens=1000,
    )
