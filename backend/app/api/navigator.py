"""The recovery navigator for the signed-in household: its next steps, the AI's explanation, and questions."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import navigator
from app.api.households import MyHousehold
from app.db import get_db

router = APIRouter(prefix="/households/me/navigator", tags=["navigator"])
DB = Annotated[Session, Depends(get_db)]


class StepOut(BaseModel):
    id: str
    key: str
    params: dict
    due: str | None
    link: str
    kind: str
    manual: bool
    done: bool


class NoteOut(BaseModel):
    text: str
    lang: str
    created_at: datetime


class PlanOut(BaseModel):
    steps: list[StepOut]
    note: NoteOut | None  # the explanation for the steps as they are now, in the asked language


class LangIn(BaseModel):
    lang: str = Field(pattern="^(en|es|zh|tl|vi)$")


class AskIn(LangIn):
    question: str = Field(min_length=3, max_length=500)


class AnswerOut(BaseModel):
    answer: str
    steps: list[str]


class DoneIn(BaseModel):
    done: bool


def _plan(db: Session, home, lang: str) -> PlanOut:
    note = navigator.current_note(db, home, lang)
    return PlanOut(
        steps=[StepOut(**navigator.step_dict(s)) for s in navigator.steps(db, home)],
        note=NoteOut(text=note.text, lang=note.lang, created_at=note.created_at) if note else None,
    )


@router.get("", response_model=PlanOut)
def plan(home: MyHousehold, db: DB, lang: str = "en") -> PlanOut:
    return _plan(db, home, lang if lang in navigator.LANGUAGES else "en")


@router.post("/explain", response_model=NoteOut)
def explain(body: LangIn, home: MyHousehold, db: DB) -> NoteOut:
    """The AI explains the steps in the family's language (once per language until the steps change)."""
    try:
        note = navigator.explain(db, home, body.lang)
    except navigator.NavigatorError as e:
        raise HTTPException(503, str(e)) from None
    return NoteOut(text=note.text, lang=note.lang, created_at=note.created_at)


@router.post("/ask", response_model=AnswerOut)
def ask(body: AskIn, home: MyHousehold, db: DB) -> AnswerOut:
    try:
        answer = navigator.ask(db, home, body.lang, body.question)
    except navigator.NavigatorError as e:
        raise HTTPException(503, str(e)) from None
    return AnswerOut(answer=answer.answer, steps=answer.steps)


@router.post("/steps/{step_id}", response_model=PlanOut)
def mark(step_id: str, body: DoneIn, home: MyHousehold, db: DB, lang: str = "en") -> PlanOut:
    try:
        navigator.mark(db, home, step_id, body.done)
    except navigator.NavigatorError as e:
        raise HTTPException(409, str(e)) from None
    return _plan(db, home, lang if lang in navigator.LANGUAGES else "en")
