"""A donor's AI agent that gives through Hearthline's MCP server.

It reads what the donor wants to do, finds a verified family's registry or a local Reopen Fund with the MCP
tools, picks something specific, and prepares the gift. It cannot pay: the last step is a PayPal link the
donor opens to approve the payment.

    cd backend
    uv run python ../examples/donor_agent.py "I'd like to help a family with kids get ready for winter. About $100."

Set HEARTHLINE_MCP to another server (default http://localhost:8000/mcp). The model comes from AI_MODELS in
backend/.env (any OpenAI-compatible provider with tool calling).
"""

import asyncio
import json
import os
import sys

from mcp import Client

from app import ai

MCP_URL = os.environ.get("HEARTHLINE_MCP", "http://localhost:8000/mcp")
MAX_STEPS = 8
SYSTEM = """You are a donor's personal assistant. Use the Hearthline tools to turn the donor's wish into one
specific, well-chosen gift: find registries or Reopen Funds, read the details, choose something that fits the
wish and budget, then prepare it once. Explain the choice in two or three sentences and give the donor the
PayPal approval link, saying that nothing is charged until they approve it there."""


def tool_spec(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or "")[:1000],
            "parameters": ai._inline_refs(dict(tool.input_schema or {"type": "object", "properties": {}})),
        },
    }


def result_text(result) -> str:
    if getattr(result, "structured_content", None) is not None:
        return json.dumps(result.structured_content)[:6000]
    return "\n".join(getattr(c, "text", "") for c in result.content)[:6000]


async def run(wish: str) -> None:
    provider, model = ai.models()[0]
    llm = ai.client(provider)
    async with Client(MCP_URL) as hearthline:
        tools = [tool_spec(t) for t in (await hearthline.list_tools()).tools]
        print(f"Connected to {MCP_URL}: {', '.join(t['function']['name'] for t in tools)}\n")
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": wish}]
        for _ in range(MAX_STEPS):
            reply = llm.chat.completions.create(model=model, messages=messages, tools=tools, max_tokens=1500)
            message = reply.choices[0].message
            if not message.tool_calls:
                print(f"\nAgent: {message.content}")
                return
            messages.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                print(f"-> {call.function.name}({json.dumps(args)})")
                result = await hearthline.call_tool(call.function.name, args)
                text = result_text(result)
                print(f"   {text[:160]}{'...' if len(text) > 160 else ''}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
        print("\nAgent: stopped after too many steps without preparing a gift.")


if __name__ == "__main__":
    asyncio.run(run(" ".join(sys.argv[1:]) or "I'd like to help a family with kids get ready for winter. About $100."))
