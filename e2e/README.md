# End-to-end checks

Browser checks that drive the real app with Playwright. Start the API (`backend/`) and the web app (`frontend/`) first, then:

```bash
cd backend
uv run --with playwright python -m playwright install chromium   # once
uv run --with playwright python ../e2e/registry_checkout.py
```

| Script | Checks |
|---|---|
| `registry_checkout.py` | The public registry loads; "Fund this" opens the donation panel; PayPal, Venmo and Pay Later buttons render; clicking PayPal creates a donation and opens the PayPal sandbox checkout; with the sandbox buyer login, the buyer signs in inside the popup, pays, and the page thanks them (a real sandbox capture) |
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
| `disputes.py` | Payment disputes desk: the org admin answers the three seeded PayPal disputes the way the rules recommend: messages the bakery card buyer about their share of the escrow, refunds the gift to the copycat registry (confirmed first), and sends proof of refund for the outfitter card; each answer starts from the Funds agent's draft. Then "Ask PayPal": the Funds agent answers from PayPal's own MCP server (read-only tools) and refuses a refund request (uses about eight AI calls; needs a freshly seeded database) |
| `connect_paypal.py` | Log in with PayPal: the household's Aid page, the contractor portal and the business home show where each person's money goes and a "Log in with PayPal" button that opens PayPal's sign-in page for the app; a cancelled return changes nothing (finishing the sign-in needs the return URL set in the PayPal developer dashboard) |
| `demo_reset.py` | Reset the demo: after shared state was changed (a dispute answered, a registry closed), "Put it back to the start" on the sign-in page restores the seeded data for everyone; a second reset right away is refused |
| `books.py` | Books and PayPal: the reconciliation of the ledger against PayPal's Transaction Search loads with the PayPal balance, the counts and the grid; the batch cash-aid preview says whether that balance covers the batch |
| `insurance_claim.py` | Insurers pay claims through PayPal: Elena prepares her contents claim from the pre-disaster inventory and her policy; the adjuster opens the private link, sees each item's evidence and the policy math (sub-limits, contents limit, deductible), pays with PayPal in the popup (the sandbox buyer stands in for the insurer), and Hearthline passes the money on to Elena's PayPal account (uses one AI call if the policy isn't read yet) |
| `local_first.py` | The Shopper buys local first: a donor finishes funding Pepper's dog crate with a real sandbox payment; the Shopper checks Sablewood Mercantile (reopened after the fire) before web stores and buys there, paying the store's PayPal account; Elena sees the local purchase; Rosa sees the order with the family's contact and marks it delivered (uses up to two AI calls; needs a freshly seeded database) |
| `video_tour.py` | Not a check: records the demo video's scenes (PLAN.md §13) as captioned 1280×720 clips with a visible cursor, cuts out the waiting (AI calls, the Shopper, PayPal loading), splices PayPal's checkout window in where it opened, and writes one mp4 per scene plus `rough_cut.mp4` to `e2e/video/` (git-ignored). Real sandbox payments; run on a freshly seeded database with `--with imageio-ffmpeg` (pass scene names to record only those) |

Scripts that sign in at PayPal use the sandbox buyer account from `backend/.env` (`PAYPAL_SANDBOX_BUYER_EMAIL`,
`PAYPAL_SANDBOX_BUYER_PASSWORD`); `paypal_sandbox.py` holds the sign-in steps for PayPal's sandbox pages, and
reopens PayPal's window through its "Click to Continue" overlay when headless Chromium loses the first one.

To check another stack (for example the API on Postgres), point the scripts at it: `E2E_WEB` (web app, default
`http://localhost:5173`), `E2E_API` (API, default `http://localhost:8000`) and `DATABASE_URL` (the API's database,
read by `reopen_fund.py`). Most scripts expect a freshly seeded database.

Screenshots land in `e2e/screenshots/` (git-ignored).
