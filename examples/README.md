# Examples

## Donor agent (`donor_agent.py`)

An AI agent that gives on a donor's behalf through Hearthline's MCP server. It finds a verified family's
registry (or a local Reopen Fund), picks one specific thing that fits the donor's wish and budget, and prepares
the gift. It cannot pay: it ends with a PayPal link the donor opens to approve the payment.

```bash
cd backend
uv run python ../examples/donor_agent.py "I'd like to help a family with kids get ready for winter. About \$100."
```

A run against the demo data:

```
-> find_registries({"query": "kids"})
-> get_registry({"slug": "rivera-family"})
-> prepare_donation({"slug": "rivera-family", "item_id": 7, "amount": 95, ...})
Agent: ...their winter jackets have already been funded, so this gift covers a crate and bed for their
dog Pepper ($95). Approve it here: https://www.sandbox.paypal.com/checkoutnow?token=... Nothing is
charged until you approve it there.
```

`HEARTHLINE_MCP` points it at another server (default `http://localhost:8000/mcp`). The model is the first
entry in `AI_MODELS` (any OpenAI-compatible provider with tool calling).
