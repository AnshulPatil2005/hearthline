# End-to-end checks

Browser checks that drive the real app with Playwright. Start the API (`backend/`) and the web app (`frontend/`) first, then:

```bash
cd backend
uv run --with playwright python -m playwright install chromium   # once
uv run --with playwright python ../e2e/registry_checkout.py
```

| Script | Checks |
|---|---|
| `registry_checkout.py` | The public registry loads; "Fund this" opens the donation panel; PayPal, Venmo and Pay Later buttons render; clicking PayPal creates a donation and opens the PayPal sandbox checkout |

Screenshots land in `e2e/screenshots/` (git-ignored).
