# Phoenix

**Disaster recovery for the people who live through it.** Phoenix helps a family document their home *before* a disaster, get help that can't be stolen or diverted *during* it, rebuild with contractors who are paid only for verified work, and helps local businesses reopen with support from their regulars.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com) on the PayPal developer platform (sandbox) with Claude, AG Grid, Bryntum, Channel3, APIMatic and Render.

> Status: **Week 0 (setup)**. See [PLAN.md](PLAN.md) for the full product and build plan.

## Repository layout

```
backend/    Python 3.12 · FastAPI API, arq worker, agents, PayPal/Channel3 integrations
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
uv run uvicorn app.main:app --reload     # http://localhost:8000/health

# Web
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Tests: `cd backend && uv run pytest`

## License

[MIT](LICENSE)
