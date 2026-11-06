from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError, RateLimitError
from pydantic import BaseModel

from app import ai


class Answer(BaseModel):
    word: str


def provider_error(cls, status: int):
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return cls("refused", response=httpx.Response(status, request=request), body=None)


def answering(arguments: str):
    call = SimpleNamespace(function=SimpleNamespace(name="submit", arguments=arguments))
    message = SimpleNamespace(tool_calls=[call], content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])


def fake_clients(monkeypatch, behaviours: dict[str, object]) -> None:
    def create(model, **kwargs):
        outcome = behaviours[model]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(ai, "client", lambda provider: fake)
    monkeypatch.setattr(ai, "models", lambda: [("gemini", m) for m in behaviours])


def test_a_key_the_provider_refuses_moves_on_to_the_next_model(monkeypatch):
    fake_clients(
        monkeypatch,
        {"revoked": provider_error(AuthenticationError, 401), "spare": answering('{"word": "ok"}')},
    )
    assert ai.parse(Answer, system="s", content=[ai.text_part("q")]).word == "ok"


def test_when_no_model_answers_callers_get_an_ai_error(monkeypatch):
    fake_clients(
        monkeypatch,
        {"busy": provider_error(RateLimitError, 429), "revoked": provider_error(AuthenticationError, 401)},
    )
    with pytest.raises(ai.AIError, match="busy: RateLimitError; revoked: AuthenticationError"):
        ai.parse(Answer, system="s", content=[ai.text_part("q")])
