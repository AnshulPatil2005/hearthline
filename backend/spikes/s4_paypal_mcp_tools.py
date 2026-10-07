"""Spike 4: connect to PayPal's sandbox MCP server from Python and list its tools.

Usage (from backend/):  uv run python -m spikes.s4_paypal_mcp_tools [--call TOOL_NAME '{"json": "args"}']
"""

import asyncio
import json
import sys

from mcp import Client
from mcp.client.sse import sse_client

from app.paypal.rest import PayPalREST


async def main() -> None:
    async with PayPalREST.from_settings() as pp:
        token = await pp.access_token()
        mcp_url = pp.mcp_url

    transport = sse_client(mcp_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with Client(transport, mode="legacy") as client:
        tools = (await client.list_tools()).tools
        print(f"{len(tools)} tools from {mcp_url}:")
        for t in sorted(tools, key=lambda t: t.name):
            print(f"  {t.name:<40} {(t.description or '').splitlines()[0][:70]}")

        if len(sys.argv) >= 3 and sys.argv[1] == "--call":
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
            result = await client.call_tool(sys.argv[2], args)
            print(f"\n{sys.argv[2]} ->")
            for block in result.content:
                print(getattr(block, "text", block))


if __name__ == "__main__":
    asyncio.run(main())
