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
| `video_calls.py` | A reviewer books a video call on the medium-risk case; it appears in Bryntum Calendar; Bryntum TaskBoard shows the case pipeline |
| `cash_aid.py` | The household requests cash aid on the Aid page; the randomly assigned reviewer approves it; a real PayPal sandbox payout is sent; the household sees "Approved" (uses one AI call) |
| `review_scam.py` | Two reviewers open the seeded impersonation registry from their queues and reject it with reasons; the registry closes and its donations are refunded (needs a freshly seeded database) |
| `rebuild_milestones.py` | The contractor drags a milestone in Bryntum Gantt and the new date is saved; the homeowner approves the seeded demolition milestone (paid from escrow through Payouts, or a plain "balance can't cover" message if the sandbox account is low); the contractor submits photos, the Site agent checks them (one AI call), and the mismatch opens a high-risk case for two reviewers that shows the photos and the check (needs a freshly seeded database) |

Screenshots land in `e2e/screenshots/` (git-ignored).
