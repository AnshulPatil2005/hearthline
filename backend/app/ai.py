"""Shared Claude client. Every agent calls Claude through here so model choice and
refusal fallbacks are configured in one place."""

from functools import lru_cache
from typing import Any

import anthropic
from pydantic import BaseModel

from app.config import get_settings

# Re-runs a request declined by safety classifiers on Anthropic's recommended fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeRefusal(RuntimeError):
    pass


@lru_cache
def client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def parse[T: BaseModel](
    output_format: type[T], *, system: str, content: list[dict[str, Any]], max_tokens: int = 16000
) -> T:
    """Single structured-output call: returns a validated `output_format` instance."""
    response = client().messages.parse(
        model=get_settings().anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=output_format,
        extra_headers={"anthropic-beta": FALLBACK_BETA},
        extra_body={"fallbacks": "default"},
    )
    if response.stop_reason == "refusal":
        raise ClaudeRefusal(str(response.stop_details))
    return response.parsed_output
