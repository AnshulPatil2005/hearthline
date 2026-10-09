# Hearthline

**Disaster recovery for the people who live through it.** Hearthline helps a family document their home *before* a disaster, get help that can't be stolen or diverted *during* it, rebuild with contractors who are paid only for verified work, and helps local businesses reopen with support from their regulars.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com) on the PayPal developer platform (sandbox) with Google Gemini (via its OpenAI-compatible API, with OpenRouter as a fallback), AG Grid, Bryntum, Channel3, APIMatic and Render.

> Status: **in development** (core features built; demo polish, README and video come in the final week). See [PLAN.md](PLAN.md) for the full product and build plan.

## Repository layout

```
backend/    Python 3.12 · FastAPI API, agents, PayPal/Channel3 integrations, Alembic migrations
  spikes/   Week-0 experiments that de-risk the design (see backend/spikes/README.md)
frontend/   React + TypeScript (Vite) · AG Grid and Bryntum UIs
render.yaml Render Blueprint for the whole stack
PLAN.md     Product scope, architecture and week-by-week plan
```

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/), Node.js 20+.

```bash
# API
cd backend
cp .env.example .env        # then fill in your keys
uv sync
uv run alembic upgrade head              # creates backend/hearthline.db (SQLite)
uv run python -m app.seed                # the fictional Sablewood wildfire demo (personas, households, payments)
uv run uvicorn app.main:app              # http://localhost:8000/health

# Web
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Tests: `cd backend && uv run pytest`. Browser checks: see [e2e/README.md](e2e/README.md).

## Deploy (Render)

`render.yaml` deploys the API, the web app and Postgres on Render's free plans; enter the secrets marked
`sync: false` in the Render dashboard. Then point PayPal's webhooks at the API (subscribes to every event
Hearthline handles) and put the printed id in `PAYPAL_WEBHOOK_ID`:

```bash
cd backend
uv run python -m scripts.paypal_webhook https://<your-api-host>
```

## License

[MIT](LICENSE)
