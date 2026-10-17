# Hearthline Public API v1 and MCP server

The public API is for partners, donors' apps and AI agents. No login is needed. Preparing a gift never
charges anyone: it returns a PayPal approval link, and the person approves the payment on PayPal. After
approving, PayPal sends them to Hearthline's `/paid` page, which completes the payment (the PayPal webhook
does it if they close the tab first).

| File | What it is |
|---|---|
| `hearthline-v1.openapi.json` | The OpenAPI 3.1 contract for `/v1`. APIMatic generates the SDKs and API portal from it. |
| `hearthline-v1.postman_collection.json` | The same operations as a Postman collection (`baseUrl` variable). |

Both files are generated from the code: `cd backend && uv run python -m scripts.export_api`. A test fails if
they're out of date.

## Operations

| Method | Path | Does |
|---|---|---|
| GET | `/v1/disasters` | Disasters Hearthline is responding to |
| GET | `/v1/registries?q=` | Verified families' registries, most still needed first |
| GET | `/v1/registries/{slug}` | A registry with every item and what it still needs |
| POST | `/v1/registries/{slug}/donations` | Prepare a gift; returns a PayPal approval link |
| GET | `/v1/donations/{id}` | Where the gift went: paid, bought, shipped, delivered |
| GET | `/v1/reopen-funds` | Local businesses selling gift cards to reopen |
| GET | `/v1/reopen-funds/{slug}` | One Reopen Fund and what its money pays for |
| POST | `/v1/reopen-funds/{slug}/gift-cards` | Prepare a gift card; returns a PayPal approval link |
| GET | `/v1/gift-cards/{code}` | A card's balance and whether it can be spent yet |
| GET | `/v1/price-watch?status=gouging` | Essential prices against their pre-disaster baseline |

## MCP server

The same operations are tools on an MCP server (Streamable HTTP) at `/mcp`: `find_registries`, `get_registry`,
`prepare_donation`, `donation_status`, `find_reopen_funds`, `prepare_gift_card` and `price_watch`.
Its instructions tell the agent to always show the PayPal link and never ask for payment details.

Add it to an MCP client, for example Claude Code:

```bash
claude mcp add --transport http hearthline https://hearthline-api.onrender.com/mcp
```

or any client that takes JSON config:

```json
{ "mcpServers": { "hearthline": { "type": "http", "url": "https://hearthline-api.onrender.com/mcp" } } }
```

Locally, use `http://localhost:8000/mcp`.

`examples/donor_agent.py` is a small agent that uses these tools to turn a donor's wish into a prepared gift.

## SDKs with APIMatic

Import `hearthline-v1.openapi.json` into APIMatic to generate SDKs (Python, TypeScript, Java, C#, Go, Ruby,
PHP) and an API portal. The operation ids (`findRegistries`, `prepareDonation`, ...) become the SDK method names.
PayPal's own Python Server SDK, which Hearthline uses for Orders, refunds and captures, is also APIMatic-generated.
