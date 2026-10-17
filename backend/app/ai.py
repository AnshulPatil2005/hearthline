"""Shared LLM client. Every provider is reached through its OpenAI-compatible API.

Every agent calls the model through here, so providers, the model fallback list and
structured-output handling live in one place. Agents build message content with
`text_part` / `image_part` and never touch provider-specific formats.

AI_MODELS is a comma-separated fallback list of `provider:model` entries, e.g.
`gemini:gemini-flash-lite-latest,openrouter:openrouter/free`. Providers without a key are skipped.
"""

import json
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.config import get_settings


class AIError(RuntimeError):
    pass


# Errors that mean "this model can't answer right now" (busy, down, or it rejects the request): try the next.
UNAVAILABLE = (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError, NotFoundError, BadRequestError)


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
    return _submit(
        _inline_refs(output_format.model_json_schema()),
        output_format.model_validate_json,
        output_format.__name__,
        system=system,
        content=content,
        max_tokens=max_tokens,
    )


def parse_json(
    schema: dict[str, Any],
    check: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    system: str,
    content: list[dict[str, Any]],
    max_tokens: int = 8000,
) -> dict[str, Any]:
    """Like parse(), for a JSON schema that arrives at runtime (e.g. from AG Grid's AI Toolkit).
    `check` validates the answer and raises ValueError with a reason the model can fix."""

    def validate(raw: str) -> dict[str, Any]:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("The answer must be a JSON object")
        return check(data)

    return _submit(_inline_refs(schema), validate, "answer", system=system, content=content, max_tokens=max_tokens)


def chat(messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, max_tokens: int = 1500) -> Any:
    """One turn of a tool-using agent: the assistant message (text or tool calls). Models in AI_MODELS are tried
    in order when one is unavailable; the conversation is stateless, so a turn can move to the next model."""
    errors: list[str] = []
    for provider, model in models():
        try:
            response = client(provider).chat.completions.create(
                model=model, messages=messages, tools=tools or None, max_tokens=max_tokens
            )
        except UNAVAILABLE as e:
            errors.append(f"{model}: {type(e).__name__}")
            continue
        if not response.choices:
            errors.append(f"{model}: {getattr(response, 'error', None) or 'empty response'}")
            continue
        return response.choices[0].message
    raise AIError("No AI model could answer: " + "; ".join(errors or ["none configured"]))


def _submit[T](
    parameters: dict[str, Any],
    validate: Callable[[str], T],
    name: str,
    *,
    system: str,
    content: list[dict[str, Any]],
    max_tokens: int,
) -> T:
    tool = {
        "type": "function",
        "function": {"name": "submit", "description": "Submit the final result.", "parameters": parameters},
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
                return validate(raw)
            except (ValidationError, ValueError) as e:  # JSONDecodeError is a ValueError
                errors.append(f"{model}: invalid output")
                messages += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"That did not match the schema: {e}. Call submit again."},
                ]
    raise AIError(f"No valid {name}. Attempts: {'; '.join(errors)}")
