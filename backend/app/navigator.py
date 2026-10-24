"""Recovery navigator: each family's next steps, soonest first.

Code reads where the household stands (verification, PayPal, aid requests, the registry, purchases and rebuild
steps waiting for them, the insurance policy and its deadlines, FEMA's application window, crew visits and calls)
and lists what is open, each step with its date and the page that does it. The AI only explains that list in the
family's language and answers questions from it; it never adds a step, a date or a rule.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, claims
from app.agents import policy_agent
from app.models import (
    Appointment,
    Case,
    CrewJob,
    Household,
    InsuranceClaim,
    InsurancePolicy,
    Item,
    Milestone,
    NavigatorCheck,
    NavigatorNote,
    Purchase,
    RebuildProject,
    Registry,
    RegistryItem,
)

FEMA_DAYS = 60  # FEMA Individual Assistance: apply within 60 days of a major disaster declaration
FEMA_URL = "https://www.disasterassistance.gov"
LANGUAGES = {"en": "English", "es": "Spanish", "zh": "Simplified Chinese", "tl": "Tagalog", "vi": "Vietnamese"}
MANUAL = {"fema_apply", "ca_advance", "policy_deadline"}  # only the family can say these are done
# Waiting on the family now, whatever the date; and how close a date has to be to count as now
NOW = {
    "case_needs_info",
    "approve_purchase",
    "approve_milestone",
    "verify_address",
    "confirm_residence",
    "connect_paypal",
}
SOON_DAYS = 7

# What each step says, in English, for the AI's facts (the page shows its own translations of the same keys)
WORDS = {
    "verify_address": "Confirm your home address is inside the disaster area",
    "confirm_residence": "Upload proof of residence (a bill or lease) or ask a caseworker to vouch for you",
    "connect_paypal": "Connect your PayPal account so cash aid and claims can reach you",
    "case_needs_info": "A reviewer needs something from you about: {title}",
    "approve_purchase": "Approve the Shopper's purchase: {title} ({total})",
    "approve_milestone": "Approve the rebuild step: {title} ({amount}), after checking the contractor's photos",
    "fema_apply": "Apply for FEMA disaster assistance at DisasterAssistance.gov",
    "upload_policy": "Upload your insurance policy so Hearthline can read its limits and deadlines",
    "policy_deadline": "Insurance deadline: {what}",
    "prepare_claim": "Send your insurer your contents claim, built from your inventory",
    "ca_advance": "Ask your insurer for the advance payments California requires after a total loss",
    "list_needs": "List what your family needs on your Rebuild Registry",
    "crew_visit": "Crew visit: {title}",
    "video_call": "Video call with a reviewer about your case",
}


class NavigatorError(ValueError):
    pass


@dataclass
class Step:
    key: str
    params: dict = field(default_factory=dict)
    due: date | None = None
    link: str = "/home"
    kind: str = "task"  # task (something to do) | event (something coming up)
    manual: bool = False  # the family marks it done themselves
    done: bool = False

    @property
    def id(self) -> str:
        """Stable across visits, so a step marked done stays done."""
        suffix = self.params.get("ref") or self.params.get("what") or ""
        return f"{self.key}:{suffix}" if suffix else self.key

    def words(self) -> str:
        return WORDS[self.key].format(**{k: v for k, v in self.params.items() if k != "ref"})


def _money(value) -> str:
    return f"${value:,.2f}"


def _when(dt: datetime) -> date:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).date()


def steps(db: Session, home: Household, today: date | None = None) -> list[Step]:
    today = today or date.today()
    out: list[Step] = []
    level = home.verification_level
    if level == 0:
        out.append(Step("verify_address", link="/aid"))
    elif level == 1:
        out.append(Step("confirm_residence", link="/aid"))
    if not home.payout_email:
        out.append(Step("connect_paypal", link="/aid"))

    for case in db.scalars(select(Case).where(Case.household_id == home.id, Case.status == "needs_info")):
        out.append(Step("case_needs_info", {"title": case.title, "ref": f"case-{case.id}"}, link="/aid"))
    for p in db.scalars(
        select(Purchase).where(Purchase.household_id == home.id, Purchase.status == "awaiting_approval")
    ):
        out.append(
            Step(
                "approve_purchase",
                {"title": p.title[:80], "total": _money(p.total), "ref": f"purchase-{p.id}"},
                link="/registry",
            )
        )
    waiting = db.scalars(
        select(Milestone)
        .join(RebuildProject, RebuildProject.id == Milestone.project_id)
        .where(RebuildProject.household_id == home.id, Milestone.status == "submitted")
    )
    for m in waiting:
        out.append(
            Step(
                "approve_milestone",
                {"title": m.title, "amount": _money(m.amount), "ref": f"milestone-{m.id}"},
                link="/rebuild",
            )
        )

    event = home.disaster_event
    if event is not None and event.status == "active":
        out.append(
            Step(
                "fema_apply",
                {"ref": f"event-{event.id}"},
                due=_when(event.declared_at) + timedelta(days=FEMA_DAYS),
                link=FEMA_URL,
                manual=True,
            )
        )

    policy = db.scalar(
        select(InsurancePolicy)
        .where(InsurancePolicy.household_id == home.id, InsurancePolicy.summary.is_not(None))
        .order_by(InsurancePolicy.id.desc())
    )
    claim = db.scalar(select(InsuranceClaim).where(InsuranceClaim.household_id == home.id))
    if policy is None:
        out.append(Step("upload_policy", link="/insurance"))
    else:
        summary = policy_agent.PolicySummary.model_validate(policy.summary)
        items = list(db.scalars(select(Item).where(Item.household_id == home.id)))
        for d in claims.check(summary, home, items, today).deadlines:
            if d.due is not None:
                out.append(
                    Step(
                        "policy_deadline",
                        {"what": d.what[:120], "text": d.text[:200]},
                        due=d.due,
                        link="/insurance",
                        manual=True,
                    )
                )
        if claim is None:
            out.append(Step("prepare_claim", link="/insurance"))
        if home.state == "CA" and home.damage_level == "destroyed":
            out.append(Step("ca_advance", link="/insurance", manual=True))

    registry = db.scalar(select(Registry).where(Registry.household_id == home.id))
    if registry is not None and not db.scalar(select(RegistryItem.id).where(RegistryItem.registry_id == registry.id)):
        out.append(Step("list_needs", link="/registry"))

    soon = datetime.now(UTC) - timedelta(hours=2)
    job = db.scalar(
        select(CrewJob)
        .where(CrewJob.household_id == home.id, CrewJob.status == "scheduled", CrewJob.starts_at >= soon)
        .order_by(CrewJob.starts_at)
    )
    if job is not None:
        out.append(
            Step("crew_visit", {"title": job.title, "ref": f"job-{job.id}"}, due=_when(job.starts_at), kind="event")
        )
    call = db.scalar(
        select(Appointment)
        .join(Case, Case.id == Appointment.case_id)
        .where(Case.household_id == home.id, Appointment.status == "scheduled", Appointment.starts_at >= soon)
        .order_by(Appointment.starts_at)
    )
    if call is not None:
        out.append(Step("video_call", {"ref": f"call-{call.id}"}, due=_when(call.starts_at), kind="event", link="/aid"))

    checked = set(db.scalars(select(NavigatorCheck.step_id).where(NavigatorCheck.household_id == home.id)))
    for s in out:
        s.done = s.manual and s.id in checked

    def rank(s: Step) -> tuple:
        if s.done:
            return (3, date.max)
        if s.key in NOW or (s.due is not None and (s.due - today).days <= SOON_DAYS):
            return (0, s.due or today)
        return (1, s.due) if s.due else (2, date.max)

    return sorted(out, key=rank)


def mark(db: Session, home: Household, step_id: str, done: bool) -> None:
    """The family says a step only they can see is done (or not)."""
    if step_id.split(":", 1)[0] not in MANUAL:
        raise NavigatorError("This step is done when Hearthline sees it done")
    existing = db.scalar(
        select(NavigatorCheck).where(NavigatorCheck.household_id == home.id, NavigatorCheck.step_id == step_id)
    )
    if done and existing is None:
        db.add(NavigatorCheck(household_id=home.id, step_id=step_id[:160]))
    elif not done and existing is not None:
        db.delete(existing)
    db.commit()


# --- The AI's part: explaining, answering -----------------------------------------------------------------------------


class Explanation(BaseModel):
    summary: str = Field(description="3 to 5 short sentences for the family, in the requested language")


class Answer(BaseModel):
    answer: str = Field(description="A short answer in the requested language, from the facts only")
    steps: list[str] = Field(description="The ids of the steps the answer is about, from the facts")


def facts(db: Session, home: Household, today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "today": today.isoformat(),
        "household": {
            "size": home.household_size,
            "damage": home.damage_level,
            "state": home.state,
            "verification_level": home.verification_level,
            "paypal_connected": bool(home.payout_email),
            "disaster": home.disaster_event.name if home.disaster_event else None,
        },
        "steps": [
            {
                "id": s.id,
                "what": s.words(),
                "due": s.due.isoformat() if s.due else None,
                "days_left": (s.due - today).days if s.due else None,
                "kind": s.kind,
                "done": s.done,
                **({"policy_words": s.params["text"]} if "text" in s.params else {}),
            }
            for s in steps(db, home, today)
        ],
    }


SYSTEM = (
    "You are Hearthline's recovery navigator, helping a family after a disaster. You get FACTS: the family's open "
    "steps with dates, computed by Hearthline. Use only these facts. Never add a step, a date, an amount or a rule "
    "that isn't in them; if something isn't covered, say a caseworker can help. This is not legal or financial "
    "advice. Write warmly and plainly, like a caseworker who respects the family's time, in {language}."
)


def _language(lang: str) -> str:
    if lang not in LANGUAGES:
        raise NavigatorError("Unknown language")
    return LANGUAGES[lang]


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps({**data, "today": None}, sort_keys=True).encode()).hexdigest()[:32]


def current_note(db: Session, home: Household, lang: str, data: dict | None = None) -> NavigatorNote | None:
    """The explanation written for the household's steps as they are now, if there is one."""
    digest = _digest(data if data is not None else facts(db, home))
    return db.scalar(
        select(NavigatorNote).where(
            NavigatorNote.household_id == home.id, NavigatorNote.lang == lang, NavigatorNote.facts_hash == digest
        )
    )


def explain(db: Session, home: Household, lang: str) -> NavigatorNote:
    """The plan in a few sentences, made once per language for the same facts (the AI isn't asked again until
    something changes)."""
    language = _language(lang)
    data = facts(db, home)
    note = current_note(db, home, lang, data)
    if note is not None:
        return note
    try:
        result = ai.parse(
            Explanation,
            system=SYSTEM.format(language=language),
            content=[
                ai.text_part(
                    "Explain the family's plan: the most urgent steps first, with their dates.\n\n"
                    f"FACTS:\n{json.dumps(data, indent=1)}"
                )
            ],
            max_tokens=1200,
        )
    except ai.AIError as e:
        raise NavigatorError("The navigator can't explain right now; your steps are still listed") from e
    note = NavigatorNote(household_id=home.id, lang=lang, facts_hash=_digest(data), text=result.summary[:2000])
    db.add(note)
    db.commit()
    return note


def ask(db: Session, home: Household, lang: str, question: str) -> Answer:
    language = _language(lang)
    data = facts(db, home)
    try:
        answer = ai.parse(
            Answer,
            system=SYSTEM.format(language=language),
            content=[ai.text_part(f"FACTS:\n{json.dumps(data, indent=1)}\n\nThe family asks: {question}")],
            max_tokens=1000,
        )
    except ai.AIError as e:
        raise NavigatorError("The navigator can't answer right now. Try again in a minute.") from e
    known = {s["id"] for s in data["steps"]}
    answer.steps = [s for s in answer.steps if s in known]  # only steps that exist
    return answer


def step_dict(s: Step, today: date | None = None) -> dict:
    today = today or date.today()
    data = asdict(s)
    data["id"] = s.id
    data["due"] = s.due.isoformat() if s.due else None
    data["days_left"] = (s.due - today).days if s.due else None
    return data
