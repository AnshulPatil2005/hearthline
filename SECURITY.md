# Security

Hearthline moves money to people right after a disaster, which is when scammers show up too: fake fundraisers,
copied photos, made-up losses, inflated prices. This page sets out what we protect, who we protect it from, where
the trust boundaries are and what holds each one. It also lists, plainly, what we haven't done.

The hosted demo runs entirely on the **PayPal sandbox**. No real money moves.

## The rule everything follows

**AI proposes, code checks, people decide.** No model output moves money on its own say-so.

- Every AI answer is structured output that has to fit a schema ([`app/ai.py`](backend/app/ai.py) `parse`). If it
  doesn't fit, it's retried and then dropped. Free text never reaches a payment.
- What an agent can choose from is narrowed by code first. The Shopper picks among candidates code has already
  filtered; the giving agent picks among needs code has already found eligible; the dispatcher's proposals are
  re-checked against the real schedule before anyone can accept them.
- Who gets paid is never chosen by a model. Payees come from records people approved or from an allowlist
  ([`app/policy.py`](backend/app/policy.py)).
- Sentinel, the fraud agent, can only *raise* the level of review. It never approves or rejects anything
  ([`app/trust.py`](backend/app/trust.py), [`app/agents/sentinel.py`](backend/app/agents/sentinel.py)).

## What we protect

| Asset | Why it matters |
| --- | --- |
| Relief money held for families | Donations wait in Hearthline's PayPal account until they are spent on a family's needs. |
| Cash-aid and contractor payouts | PayPal Payouts sent from the relief fund. |
| Donors' saved PayPal accounts | Giving mandates charge them without a checkout (PayPal Vault). |
| Families' personal data | Addresses, damage photos, insurance policies, inventories. |
| The record of who decided what | The audit log and the double-entry ledger, which Books checks against PayPal. |

## Who uses it

| Actor | Can | Can't |
| --- | --- | --- |
| Anyone (public) | Browse approved registries and Reopen Funds, give through PayPal, use the Public API and MCP server | See addresses, see an unreviewed registry, move money without approving it on PayPal |
| Household | Manage its own inventory, registry and cases; approve large Shopper purchases | See other households; review its own case |
| Donor | Give, set up a giving mandate with limits, pause or revoke it | Change what a mandate may buy beyond its limits |
| Reviewer | Decide cases assigned to them at random | Review a household they belong to or vouched for |
| Supervisor / org admin | Prepare and approve aid batches, settle reviewer disagreements, run Books | Approve a batch they prepared |
| Contractor, business | Their own projects, plans and Reopen Fund | Release their own milestone payments |
| AI agents (ours) | Propose, explain, draft | Pay anyone, choose a payee, approve a case |
| Outside AI agents (MCP) | Find needs and prepare a gift | Complete a payment: a person approves every one on PayPal |

## Trust boundaries

1. **Browser to API.** The browser is untrusted. Every role check happens on the server
   ([`app/auth.py`](backend/app/auth.py) `require_role`). Batches are built from a filter on the server; the browser
   never sends a list of households or amounts ([`app/aid_batches.py`](backend/app/aid_batches.py)). CORS allows only
   localhost and the Render site ([`app/config.py`](backend/app/config.py)).
2. **API to AI models.** Everything a model reads can contain hostile text: a registry story, a photo, a policy PDF.
   Model output is treated as untrusted input to code, never as an instruction.
3. **API to PayPal.** Every payment is created and captured on the server. A webhook is acted on only when PayPal
   confirms its signature ([`app/paypal/webhooks.py`](backend/app/paypal/webhooks.py) `verify_signature`).
4. **Public API and MCP to the outside world.** These can prepare a gift and return a PayPal approval link, and
   nothing more ([`app/public_api.py`](backend/app/public_api.py), [`app/mcp_server.py`](backend/app/mcp_server.py)).

## Threats and what stops them

### Fraud and scams

| Threat | What stops it | Where |
| --- | --- | --- |
| A fake fundraiser using a real family's story | New registries stay hidden (404 to the public) and can't take gifts until a person approves the verification case. Rejecting one refunds every donor. | [`api/registry.py`](backend/app/api/registry.py) `view_registry`, [`review.py`](backend/app/review.py) |
| Copied damage photos | Perceptual hashes compared across households; a match is a high-severity Sentinel flag | [`trust.py`](backend/app/trust.py) `duplicate_photos` |
| Address outside the disaster | Verification level 0 outside the zone; cash aid needs level 2 | [`trust.py`](backend/app/trust.py) `verification_level` |
| Prove one home, then move the address to unlock aid elsewhere | Changing the address clears the residence proof and the vouch; the new one has to be proven again | [`api/households.py`](backend/app/api/households.py) |
| One person, many households | Households sharing a PayPal account are left out of batches; Sentinel flags shared payout emails | [`aid_batches.py`](backend/app/aid_batches.py), [`trust.py`](backend/app/trust.py) |
| A reviewer approving a friend's case | Random assignment from the OS's randomness, never to a member or the caseworker who vouched; two reviewers for high risk or over $1,000; 5% of approvals randomly audited | [`review.py`](backend/app/review.py) |
| One staff member paying out alone | The person who prepares a batch can't approve it; eligibility is checked again at approval | [`aid_batches.py`](backend/app/aid_batches.py) |
| Price gouging after the disaster | Purchases more than 10% over the pre-disaster price are blocked while price protection lasts | [`gouging.py`](backend/app/gouging.py) |

### The Shopper agent spending donated money

Every proposal passes nine checks in plain code before anything is paid: funds held, within what was donated for
the item, $1,000 per purchase, $2,500 per day, blocked categories (gift cards, cash equivalents, alcohol and so
on), allowlisted retailers only, at most 1.5 times the median of comparable offers, ships only to an address that
is in the zone *and* proven to be the family's home, and the gouging guard. Above $300, or when the model is
unsure, the family approves first ([`app/policy.py`](backend/app/policy.py), [`app/shopping.py`](backend/app/shopping.py)).

### Giving mandates

A mandate charges a donor's saved PayPal account without a checkout, by design. Limits are set by the donor and
capped in code ($500 per gift, $2,000 a month). Each gift is claimed once per mandate and item (a unique row) before
PayPal is called, so a retry can't give twice. The donor can pause or revoke at any time; revoking deletes the saved
account at PayPal ([`app/mandates.py`](backend/app/mandates.py)).

### Accounts and sessions

| Threat | What stops it | Where |
| --- | --- | --- |
| Weak or default signing key in production | The API refuses to start in production with the development key or one shorter than 32 characters; Render generates a random one | [`config.py`](backend/app/config.py), [`render.yaml`](render.yaml) |
| Another token signed with the same key used to sign in | Sign-in tokens carry `purpose: login`; the PayPal-connect state token can't be used as one | [`auth.py`](backend/app/auth.py) |
| Replaying a PayPal sign-in code into someone else's account | The OAuth `state` is signed, short-lived and tied to the signed-in user | [`paypal_connect.py`](backend/app/paypal_connect.py) |
| Guessing photo URLs | Media links are signed per item | [`media.py`](backend/app/media.py) |
| Collecting other people's gift-card codes (a code is what spends a card) | The capture and sync that answer with a card's code need a token signed for its buyer, given when the card is started and in PayPal's return link; a guessed id gets a 404 | [`reopen.py`](backend/app/reopen.py) `buyer_token` |
| Live PayPal by accident | The API refuses to start against live PayPal unless `ALLOW_LIVE_PAYPAL=true` is set on purpose | [`config.py`](backend/app/config.py) |

### Money and records

| Threat | What stops it | Where |
| --- | --- | --- |
| Forged PayPal webhooks | Signature checked with PayPal; an unverified event is stored but not acted on, and gets a 401 so PayPal redelivers a genuine one | [`api/webhooks.py`](backend/app/api/webhooks.py) |
| A webhook processed twice | Events are stored by PayPal's id and processed once | [`paypal/webhooks.py`](backend/app/paypal/webhooks.py) |
| Money leaving with no decision behind it | Books matches every PayPal payout and payment to an approved record, for the same amount, and lists anything unmatched | [`reconcile.py`](backend/app/reconcile.py) |
| A gift counted twice, or an item bought twice | A capture re-reads the gift under a row lock, so the donor's browser and PayPal's webhook can't both add it; one purchase per item at a time, re-checked at approval; a payout with no answer is retried as the same batch, which PayPal never pays twice | [`registry.py`](backend/app/registry.py), [`shopping.py`](backend/app/shopping.py) |
| Quietly editing who approved what | The audit log is a hash chain: each event's hash covers its content and the previous hash. Staff can re-check the whole chain on the Books page | [`audit.py`](backend/app/audit.py), `GET /command/books/audit` |
| Unbalanced books | Every posting set must balance before it's written | [`ledger.py`](backend/app/ledger.py) |

### Cost and abuse

| Threat | What stops it | Where |
| --- | --- | --- |
| Running up the AI bill | In production, AI routes are limited per client (40 per 10 minutes) and in total (600 per 10 minutes) | [`rate_limit.py`](backend/app/rate_limit.py) |
| Flooding sign-in or the Public API | The same, with higher limits | [`rate_limit.py`](backend/app/rate_limit.py) |
| Huge uploads | 15 MB per photo or PDF, 12 photos per scan; images are re-encoded and shrunk | [`media.py`](backend/app/media.py), [`api/inventory.py`](backend/app/api/inventory.py) |
| Resetting the shared demo over and over | At most once every ten minutes | [`demo_reset.py`](backend/app/demo_reset.py) |

## What the demo relaxes on purpose

- **One-click sign-in.** Judges sign in as any demo persona without a password (`POST /auth/demo-login`, demo
  accounts only). A real deployment would put this behind an identity provider; the role checks behind it stay
  the same.
- **Anyone can reset the demo** (once every ten minutes), so each judge can start from the beginning.
- **First-72-hours aid needs one approval**, not two. Speed is the point within hours of a warning, so it's limited
  instead: only households that prepared before the disaster (level 3) with a PayPal account, Sentinel holds back
  anyone with warning signs, and payment goes through the same batch path with its re-checks
  ([`app/rapid_aid.py`](backend/app/rapid_aid.py)).
- **Sandbox only.** Payouts go to sandbox accounts, and the Shopper pays a stand-in retailer account.

## Known limitations

We'd rather say these than have someone find them.

- **No identity verification.** Residence is proven with a document a caseworker checks or by a caseworker's vouch.
  There is no KYC, and a determined fraudster with a forged bill could reach level 2. Two-person review and Books
  are the backstop.
- **The rate limits are in memory** on the one API instance, and a restart forgets them. Clients are told apart
  by the address Cloudflare (in front of Render) reports, which a client can't fake, and every limit also has a
  total. They are there to stop floods and runaway cost, not a determined attacker with many addresses.
- **The audit chain is checked on demand**, in tests and from the Books page, not continuously. Events are
  appended without a database lock, so two writes at the same moment could link to the same previous event. That
  would show as a break, not hide one. The time of each event isn't part of its hash.
- **Ledger balance is enforced in application code**, not by a database constraint.
- **Prompt injection is contained, not prevented.** A model can be talked into a bad proposal; the code checks
  and the human approvals above are what stop it from paying for one.
- **No penetration test or external audit** has been done.

## Secrets

Keys live only in environment variables: `backend/.env` locally (gitignored) and Render's environment in
production. The repository holds no keys. The PayPal sandbox buyer login shown in the README and on the sign-in
page is a sandbox test account, published on purpose so judges can pay with it.

## Tests that hold these lines

The backend test suite runs on every push ([CI](.github/workflows/ci.yml)). Among others:
[`test_review.py`](backend/tests/test_review.py) (independent review, hidden registries, refunds),
[`test_aid_batches.py`](backend/tests/test_aid_batches.py) (two people, re-checks),
[`test_policy.py`](backend/tests/test_policy.py) and [`test_shopping.py`](backend/tests/test_shopping.py) (every
spending rule can block), [`test_ledger_audit_webhooks.py`](backend/tests/test_ledger_audit_webhooks.py)
(balanced books, tamper detection, forged webhooks),
[`test_auth.py`](backend/tests/test_auth.py) (token purpose, live PayPal guard),
[`test_households.py`](backend/tests/test_households.py) (re-proving a new address) and
[`test_rate_limit.py`](backend/tests/test_rate_limit.py).

## Reporting a problem

Please report a vulnerability privately through GitHub's **Report a vulnerability** button on this repository's
Security tab, not in a public issue.
