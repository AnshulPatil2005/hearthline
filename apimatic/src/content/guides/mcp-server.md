# Use it from an AI agent (MCP)

The same operations are tools on an MCP server (Streamable HTTP) at `/mcp`: `find_registries`, `get_registry`,
`prepare_donation`, `donation_status`, `find_reopen_funds`, `prepare_gift_card` and `price_watch`.

The server's instructions tell the agent to always show the PayPal link to the person and never ask for payment
details, so an agent can find a need and prepare the gift, but a person approves every payment.

Add it to an MCP client, for example Claude Code:

```bash
claude mcp add --transport http hearthline https://hearthline-api.onrender.com/mcp
```

Then ask, for example: "Find a family affected by the Sablewood Fire who still needs bedding, and prepare a $40
gift for their mattresses."
