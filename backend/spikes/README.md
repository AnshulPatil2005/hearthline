# Week 0 spikes

Each spike answers one question that shapes the design. Run them from `backend/` once `backend/.env` is filled in (see `.env.example`).

| # | Question | Command | Result |
|---|---|---|---|
| 1 | Do a vision LLM (via OpenRouter) + Channel3 produce a usable priced inventory from room photos? | `uv run python -m spikes.s1_vision_inventory` | **PASS** (Gemini `gemini-flash-lite-latest` + Channel3). 8-10 specific items per photo in 4-6 s; Channel3 priced each item (~11 s sequential, parallelize later). Prices need guarding: outliers like a $7,240 display cabinet and a tablet matched to a replacement screen. Use the median of several offers, filter parts/accessories, keep human confirmation. Free OpenRouter vision models were all rate-limited upstream, so Gemini's free tier is primary. |
| 2 | Can the Shopper pay with a vaulted wallet, no buyer present? Can the payee be a different merchant? | `uv run python -m spikes.s2_vault_agent_order` | _pending_: needs you to approve a $1 payment in the browser as a US sandbox personal account |
| 3 | Does a Payouts batch to several receivers succeed in the sandbox? | `uv run python -m spikes.s3_payouts_batch` | **PASS** with the US "hackathon" app: batch SUCCESS in ~30 s; unknown receivers come back UNCLAIMED as expected. (The first app was on a non-US account and got `PAYOUT_NOT_AVAILABLE`.) |
| 4 | Can Python reach PayPal's sandbox MCP server, and which tools does it expose? | `uv run python -m spikes.s4_paypal_mcp_tools` | **PASS**: 46 tools over SSE at `https://mcp.sandbox.paypal.com/sse` (the documented `/http` endpoint returns 404). Covers orders, invoices, disputes, subscriptions, shipment tracking, refunds, transactions. |
| 5 | Can a sandbox dispute be settled through the API? | `uv run python -m spikes.s5_disputes` | API works (0 disputes listed). Settling still needs a dispute opened by a sandbox buyer. |
| 6 | Can PayPal hold escrow funds (multiparty delayed disbursement)? | Manual: needs partner onboarding | _pending_ (default: Hearthline holds funds and releases them with Payouts) |

## Before running

1. **PayPal sandbox app**: in the [developer dashboard](https://developer.paypal.com/dashboard/applications/sandbox), create an app, then turn on **Vault**, **Payouts** and **Log in with PayPal** in its settings. Copy the client ID and secret.
2. **Sandbox accounts** ([accounts page](https://developer.paypal.com/dashboard/accounts)): you need a *business* account for Hearthline (the app owner), a second *business* account as the stand-in retailer, and personal accounts for the household, donor and volunteer. Put the retailer email in `PAYPAL_SANDBOX_RETAILER_EMAIL` and personal emails in `PAYPAL_SANDBOX_PAYOUT_RECEIVERS`.
3. **Photos for spike 1**: drop 3-5 real room photos into `spikes/samples/` (they are git-ignored).

## Recording results

Replace each _pending_ with PASS/FAIL and one line on what you learned. A failed spike means switching to its fallback in `PLAN.md` section 14.
