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
| `command_center.py` | The org admin lands on the Command Center; 2,000+ households load block by block from the server-side AG Grid, sorted by unmet need, with help sparklines; dragging Damage into the group bar groups on the server with counts and summed totals; then batch cash aid: the admin filters to destroyed, level-2 homes, previews (who is paid, who is left out and why) and sends the batch for approval; he can't approve it himself; a supervisor approves it and one PayPal Payouts call pays everyone (or, with a low sandbox balance, the batch is marked "Not sent" and nothing moves); the batch row expands to its payments (needs a freshly seeded database) |
| `crews.py` | Crew dispatch in Bryntum Scheduler Pro: crews load with each job's travel-time buffer; the org admin drags a job from "Not assigned yet" onto a crew and the assignment is saved (needs a freshly seeded database) |
| `ask_grid.py` | "Ask the grid": a question becomes grid state through AG Grid's AI Toolkit schema and the server's checks; a second question groups by street with totals; "Reset view" restores the default (uses two AI calls) |
| `reopen_fund.py` | Reopen Fund: the public page shows the bakery's progress, plan and Gantt; choosing PayPal creates a gift-card order and opens the sandbox checkout; the owner asks for a step's money; a supervisor verifies a new business and releases the step through Payouts; the owner marks the bakery reopened and takes $12.50 from a card; the card page shows the new balance and its QR code; the outfitter that missed its date shows as refunded (needs a freshly seeded database) |
| `price_watch.py` | Price Watch: the public report lists tracked essential prices against their pre-disaster baseline, with sparklines and the ones over the 10% limit in red |
| `impact.py` | Impact: the donor's page shows each gift's journey (paid, bought, shipped, delivered) at once, then the Funds agent's note; the org admin downloads the grant report PDF (uses up to two AI calls) |
| `insurance.py` | Policy agent: the household uploads the sample policy (fictional); the agent reads limits, sub-limits and deadlines; the page shows the jewelry over its sub-limit and the suit deadline as a date; a question is answered with a quote from the policy (uses two AI calls; needs a freshly seeded database) |

Screenshots land in `e2e/screenshots/` (git-ignored).
