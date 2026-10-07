"""Shared LLM client. Every provider is reached through its OpenAI-compatible API.

Every agent calls the model through here, so providers, the model fallback list and
structured-output handling live in one place. Agents build message content with
`text_part` / `image_part` and never touch provider-specific formats.

AI_MODELS is a comma-separated fallback list of `provider:model` entries, e.g.
`gemini:gemini-flash-lite-latest,openrouter:openrouter/free`. Providers without a key are skipped.
"""

import json
import re
from functools import lru_cache
from typing import Any

from openai import APIConnectionError, APITimeoutError, InternalServerError, NotFoundError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from app.config import get_settings


class AIError(RuntimeError):
    pass


# Errors that mean "this model is unavailable right now": try the next one.
UNAVAILABLE = (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError, NotFoundError)


def _provider_config(provider: str) -> tuple[str, str | None]:
    s = get_settings()
    return {
        "openrouter": (s.openrouter_base_url, s.openrouter_api_key),
        "gemini": (s.gemini_base_url, s.gemini_api_key),
    }[provider]


@lru_cache
def client(provider: str) -> OpenAI:
    base_url, api_key = _provider_config(provider)
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={"X-Title": "Hearthline"},
        max_retries=1,  # parse() moves on to the next model instead of hammering a busy one
        timeout=90,
    )


def models() -> list[tuple[str, str]]:
    """(provider, model) pairs from AI_MODELS, skipping providers that have no API key."""
    pairs = []
    for entry in get_settings().ai_models.split(","):
        provider, _, model = entry.strip().partition(":")
        if provider and model and _provider_config(provider)[1]:
            pairs.append((provider, model))
    return pairs


def configured() -> bool:
    return bool(models())


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def image_part(b64: str, media_type: str = "image/jpeg") -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}}


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits $defs/$ref; several providers reject refs in tool parameters."""
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _strip_fences(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return match.group(1) if match else text


def parse[T: BaseModel](
    output_format: type[T], *, system: str, content: list[dict[str, Any]], max_tokens: int = 8000
) -> T:
    """One structured-output call. The model must answer by calling a `submit` tool whose
    parameters are the output schema; this works on any tool-capable model, unlike JSON-schema
    response modes. Models in AI_MODELS are tried in order when one is unavailable (free models
    are often rate-limited upstream); each gets one retry if its arguments don't fit the schema."""
    tool = {
        "type": "function",
        "function": {
            "name": "submit",
            "description": "Submit the final result.",
            "parameters": _inline_refs(output_format.model_json_schema()),
        },
    }
    base_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system + "\n\nAlways answer by calling the submit tool."},
        {"role": "user", "content": content},
    ]
    errors: list[str] = []
    for provider, model in models():
        messages = list(base_messages)
        for _ in range(2):
            try:
                response = client(provider).chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "function", "function": {"name": "submit"}},
                    max_tokens=max_tokens,
                )
            except UNAVAILABLE as e:
                errors.append(f"{model}: {type(e).__name__}")
                break
            if not response.choices:  # OpenRouter can return 200 with only an error body
                errors.append(f"{model}: {getattr(response, 'error', None) or 'empty response'}")
                break
            message = response.choices[0].message
            if message.tool_calls:
                raw = message.tool_calls[0].function.arguments
            else:
                raw = _strip_fences(message.content or "")
            try:
                return output_format.model_validate_json(raw)
            except (ValidationError, json.JSONDecodeError) as e:
                errors.append(f"{model}: invalid output")
                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"That did not match the schema: {e}. Call submit again."},
                ]
    raise AIError(f"No valid {output_format.__name__}. Attempts: {'; '.join(errors)}")
