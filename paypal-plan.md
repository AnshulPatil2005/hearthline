# PayPal SDK plan: books-vs-PayPal reconciliation (Part 1) and giving mandates (Part 2)

Written while following APIMatic's **PayPal Context Plugin** for Claude Code (`paypal@context-plugins` 0.4.1,
installed with `npx context-plugins install paypal`): its `python-integrate-paypal` workflow, the
`python-getting-started` lookup layer, and the companion skills listed under *Required reading*. Every SDK fact below
comes from the SDK map (`sdk-map.md`, `map/operations/transaction_search.md`) or the installed package's own modules,
not from memory.

## Scope

1. **PayPal balance** (`transaction_search.search_balances`): staff see what the relief fund holds at PayPal, and the
   batch cash-aid preview warns when the batch is larger than the balance (payouts failed for exactly this reason
   during development).
2. **Books vs PayPal** (`transaction_search.search_transactions`): since the books were opened (the last demo reset),
   every payout PayPal reports must trace to an approved Hearthline decision (`case-N`, `milestone-N`, `tranche-N`,
   `purchase-N`, `aidbatch-B-H` in the payout item's `custom_field`), every payment received must be in the ledger,
   and amounts must agree. Anything else is listed for a person to look at. Read-only.

Out of scope: the existing Orders integration on `paypal-server-sdk` stays as it is.

## SDK identity (from `python-getting-started`, verified against the installed package)

| Fact | Value |
| --- | --- |
| Distribution / import root | `paypal` / `paypal` (from source: `git+https://github.com/context-plugins/paypal-python-sdk.git@main`, locked to commit `143e57f`) |
| Version | 2.29 (`pyproject.toml` of the clone the map was read from is the same commit) |
| Client | `PaypalClient` (sync), keyword-only constructor |
| Auth | `oauth2=ClientCredentials(client_id=..., client_secret=...)` from `paypal.core`; token fetched lazily and cached on the client |
| Base URL | only `https://api-m.sandbox.paypal.com` by default: **pass `base_url` explicitly** from `PAYPAL_ENVIRONMENT` (sandbox / `https://api-m.paypal.com` live) |

## Decisions

- **Sync client.** The service layer is synchronous (SQLAlchemy sessions, FastAPI `def` routes in the thread pool);
  the sync client is thread-safe. One long-lived client, built lazily on first use and closed in the app's lifespan
  shutdown (`python-client-initialization`).
- **Timeout** 20 s per wait (default 30 s). Whole-call budget: none in sync code.
- **Retries: keep the default policy.** Both operations are `GET`, which the default retries on
  408/429/5xx and connection failures (`max_retries` 3, backoff 1 s × 2, capped at 60 s). Tests use `retry_options=0`.
- **Response mode:** parsed calls (both operations return a body), wrapped in one error boundary.
- **Duplicate claims:** none. Both operations only read.

## Contract sheet

### `client.transaction_search.search_balances`

- `GET /v1/reporting/balances`, auth `oauth2`
- `search_balances(*, as_of_time: str | None = None, currency_code: str | None = None, request_options=None) -> BalancesResponse`
- Call: `search_balances(currency_code="USD")`
- Returns `BalancesResponse` (`paypal/models/balances_response.py`): `balances: Optional[list[BalanceInformation]]`,
  `last_refresh_time: Optional[str]`, `as_of_time: Optional[str]`, `account_id: Optional[str]`
- `BalanceInformation` (`paypal/models/balance_information.py`): `currency: str` (required),
  `total_balance: Money` (required), `available_balance: Optional[Money]`, `withheld_balance: Optional[Money]`,
  `primary: Optional[bool]`
- `Money` (`paypal/models/money.py`): `currency_code: str`, `value: str` (both required)
- Error: `ApiError` with `.error: SearchBalancesErrorBody` = `DefaultError` [400, 403, 500] | `RawError`
  (`DefaultError` in `paypal/models/default_error.py`: `name`, `message`, `debug_id`)
- Semantics (docstring): balances take up to **3 hours** to refresh; without `as_of_time` it returns the last
  refreshed balance, so the UI shows `last_refresh_time` beside the number.

### `client.transaction_search.search_transactions`

- `GET /v1/reporting/transactions`, auth `oauth2`
- `search_transactions(start_date: str, end_date: str, *, transaction_id=None, transaction_type=None,
  transaction_status=None, transaction_amount=None, transaction_currency=None, payment_instrument_type=None,
  store_id=None, terminal_id=None, fields: str | None = "transaction_info",
  balance_affecting_records_only: str | None = "Y", page_size: int | None = 100, page: int | None = 1,
  request_options=None) -> SearchResponse`
- Positional: `start_date`, `end_date` (RFC 3339 with seconds, e.g. `2026-10-19T09:00:00Z`); everything else by name.
- Call: `search_transactions(start, end, fields="transaction_info", balance_affecting_records_only="Y",
  page_size=500, page=n)` for n = 1 .. `total_pages`. Defaults are passed explicitly: `fields` defaults to
  `transaction_info` only and `balance_affecting_records_only` to `Y` (`python-calling-endpoints`: non-`None` defaults
  narrow the response).
- Returns `SearchResponse` (`paypal/models/search_response.py`): `transaction_details:
  Optional[list[TransactionDetails]]`, `total_pages: Optional[int]`, `total_items: Optional[int]`,
  `last_refreshed_datetime: Optional[str]`
- `TransactionDetails.transaction_info: Optional[TransactionInformation]`
- `TransactionInformation` (`paypal/models/transaction_information.py`), members used: `transaction_id`,
  `paypal_reference_id`, `transaction_event_code`, `transaction_initiation_date`, `transaction_amount: Optional[Money]`,
  `fee_amount: Optional[Money]`, `transaction_status`, `custom_field` (all `Optional[...]`, no wire aliases)
- Error: **Case B**, `ApiError.error` is always `RawError` (smoke test: a 59-day range answers 400
  `INVALID_REQUEST`).
- Semantics (docstring): **at most 31 days** per request; transactions take up to **3 hours** to appear; status
  `S` success, `P` pending, `D` denied, `V` reversed.

### Shared

- `Optional[T]` is `T | UnsetType` (`paypal/core/optionality.py`), not `typing.Optional`; `UNSET` is falsy and a
  singleton. Narrow with `isinstance(value, UnsetType)`.
- Failures that are not `ApiError` (`python-error-handling`): a failed token fetch raises `ApiError` whose `.error` is
  `OAuthProviderError`; a decode failure raises `pydantic.ValidationError`; transport failures arrive as `httpx2`
  exceptions (`ConnectError`/`ConnectTimeout`/`PoolTimeout`/`ProxyError`: never sent; other `RequestError`: no reply).
  All map to one `ReportingError(status, message)` in `app/paypal/reporting.py`:
  401/403 or OAuth → 502 "PayPal refused our credentials" · 429 → 503 · other 4xx → 400 with our message ·
  5xx/unreadable/transport → 502/504. Reads have no side effects, so `outcome_unknown` is not needed.

## Code layout

- `app/paypal/reporting.py`: the client's lifetime, `balance()`, `transactions(start, end)` with paging, the error
  boundary. Exemplar for style: `app/paypal/payouts.py`.
- `app/reconcile.py`: the books-vs-PayPal report (window since the last `demo.seeded` audit event, at most 31 days).
- `app/api/books.py`: staff endpoints. Frontend: `pages/Books.tsx` (AG Grid, Excel export).
- `app/aid_batches.py` preview: PayPal balance beside the batch total.

## Assumptions and blockers

- Transaction Search and the Balances API are enabled on the app (smoke test passed on 2026-10-19).
- Data lags up to 3 hours, so ledger entries newer than PayPal's `last_refreshed_datetime` are "waiting for PayPal",
  not "missing".
- No blockers.

## Required reading (all loaded before coding)

- MUST load `python-getting-started` (lookup layer) and `python-integrate-paypal` (this workflow)
- MUST load `python-client-initialization`: sync client, lifetime, explicit `base_url`
- MUST load `python-authentication`: the OAuth failure path raises from the operation call
- MUST load `python-calling-endpoints`: positional vs keyword-only, defaults that narrow responses
- MUST load `python-models`: `Optional` is `T | UnsetType`
- MUST load `python-error-handling`: one boundary, distinct failure kinds
- MUST load `python-configuration-resilience`: retries on by default for `GET`
- MUST load `python-testing`: stub transport, token response first, `retry_options=0`

---

# Part 2: giving mandates (PayPal Vault and merchant-initiated payments)

Added 2026-10-22, following the same workflow and lookup layer as Part 1. Every fact below comes from
`map/operations/vault.md`, `map/operations/orders.md`, the installed package's modules, or the sandbox smoke tests run
from the scratchpad on 2026-10-22 (noted as *smoke*).

## Scope

A donor saves their PayPal account once and gives Hearthline's giving agent a standing instruction (where, how much
per gift and per month, which kinds of needs). When needs match, the agent gives within those limits with no checkout;
the donor can pause or revoke at any time, and revoking deletes the saved account at PayPal.

1. **Save the account**: `vault.create_setup_token` → the donor approves at PayPal → `vault.get_setup_token` (status) →
   `vault.create_payment_token`.
2. **Give**: `orders.create_order` with the saved account (`payment_source.paypal.vault_id`) as a merchant-initiated
   payment. *Smoke*: the order comes back `COMPLETED` with its capture; no `capture_order` call is needed.
3. **Revoke**: `vault.delete_payment_token`.
4. **Read back** (the donor's page shows the PayPal email it gives from): `vault.get_payment_token`.

Out of scope: card vaulting, Venmo vaulting, `list_customer_payment_tokens`.

## Decisions

- **Sync client, the same one.** `app.paypal.reporting.client()` is the app's one long-lived `PaypalClient`; the vault
  code uses it (no second client). Service code is sync and runs in FastAPI's thread pool.
- **Retries: keep the default policy, which never repeats a `POST` or `DELETE`.** `create_setup_token`,
  `create_payment_token` and `create_order` are `POST` and `delete_payment_token` is `DELETE`; only the `GET`s retry.
  A gift whose outcome is unknown is resolved by resending with the **same** `PayPal-Request-Id` (PayPal returns the
  same order: *smoke*), never by a retry loop of our own.
- **Response mode:** parsed calls everywhere except `delete_payment_token`, which returns `None`; it is called through
  `client.vault.with_raw_response.delete_payment_token` to see the status (`Success`, 204 in the *smoke*).
- **Base URL:** the client's explicit `base_url` from `PAYPAL_ENVIRONMENT` (Part 1).
- **Who decides what:** code computes the eligible needs and the money left (per gift, per month); the AI only
  chooses among them and explains; code checks the AI's plan against the limits before any call.

## Contract sheet

### `client.vault.create_setup_token`
- `POST /v3/vault/setup-tokens` · `create_setup_token(body: SetupTokenRequest | SetupTokenRequestDict, *,
  pay_pal_request_id: str | None = None, request_options=None) -> SetupTokenResponse`
- Body (`SetupTokenRequest`): `payment_source` **required** (`SetupTokenRequestPaymentSource`), `customer` UNSET.
  `payment_source.paypal` (`VaultPayPalWalletRequest`, `paypal/models/vault_pay_pal_wallet_request.py`):
  `description` (str), `usage_type` = `"MERCHANT"` (`PayPalPaymentTokenUsageType`: MERCHANT | PLATFORM),
  `customer_type` = `"CONSUMER"` (CONSUMER | BUSINESS), `usage_pattern` = `"UNSCHEDULED_PREPAID"` (`UsagePattern`),
  `permit_multiple_payment_tokens` (bool, default False), `experience_context` (`VaultExperienceContext`):
  `brand_name`, `return_url`, `cancel_url` (all str; a `http://localhost` return URL is accepted: *smoke*).
- Returns `SetupTokenResponse`: `id`, `status` (`PaymentTokenStatus`: CREATED | PAYER_ACTION_REQUIRED | APPROVED |
  VAULTED | TOKENIZED; *smoke*: `PAYER_ACTION_REQUIRED`), `customer.id`, `links`. The approval URL is the link with
  `rel == "approve"` (`https://www.sandbox.paypal.com/agreements/approve?approval_session_id=<id>`). All members are
  `Optional[...]`: assert `id` and the approve link are present.
- PayPal sends the donor back to `return_url?approval_token_id=<setup id>&approval_session_id=<setup id>` (*smoke*);
  the consent button reads **"Save and Continue"**.
- Error: `CreateSetupTokenErrorBody` = `Error` [400, 403, 422, 500] | `RawError`.

### `client.vault.get_setup_token`
- `GET /v3/vault/setup-tokens/{id}` · `get_setup_token(id_: str, *, request_options=None) -> SetupTokenResponse`
- After approval `status` is `APPROVED` and `payment_source.paypal` carries `email_address` and `payer_id` (*smoke*).
- Error: `GetSetupTokenErrorBody` = `Error` [403, 404, 422, 500] | `RawError`.

### `client.vault.create_payment_token`
- `POST /v3/vault/payment-tokens` · `create_payment_token(body: PaymentTokenRequest | PaymentTokenRequestDict, *,
  pay_pal_request_id: str | None = None, request_options=None) -> PaymentTokenResponse`
- Body: `payment_source` **required** (`PaymentTokenRequestPaymentSource`) with `token` (`VaultTokenRequest`):
  `id` (str, required) and `type_`, wire alias **`type`**, = `"SETUP_TOKEN"` (`VaultTokenRequestType`, its only member).
- Returns `PaymentTokenResponse`: `id` (the vault id), `customer.id` (`CustomerResponse`), `payment_source.paypal`
  (`PayPalPaymentToken`): `email_address`, `payer_id`. All `Optional[...]`: assert `id`.
- Error: `CreatePaymentTokenErrorBody` = `Error` [400, 403, 404, 422, 500] | `RawError`.

### `client.orders.create_order` (merchant-initiated, with the saved account)
- `POST /v2/checkout/orders` · `create_order(body: OrderRequest | OrderRequestDict, *, pay_pal_request_id: str | None =
  None, prefer: str | None = "return=minimal", ...) -> Order`
- Body (`OrderRequest`): `intent` = `"CAPTURE"` (required), `purchase_units` (required, one `PurchaseUnitRequest`:
  `amount` required with `currency_code` and `value`; `custom_id` = `donation:<id>`; `description`),
  `payment_source.paypal` (`PayPalWallet`): `vault_id`, and `stored_credential` (`PayPalWalletStoredCredential`):
  `payment_initiator` **required** = `"MERCHANT"` (`PaymentInitiator`: CUSTOMER | MERCHANT), `usage` = `"SUBSEQUENT"`
  (`StoredPaymentSourceUsageType`: FIRST | SUBSEQUENT | DERIVED), `usage_pattern` = `"UNSCHEDULED_PREPAID"`.
- ⚠ **`pay_pal_request_id` is required in practice**: without it PayPal answers 400 `INVALID_REQUEST` /
  `PAYPAL_REQUEST_ID_REQUIRED` for an order with a `payment_source` (*smoke*). It is also PayPal's dedup key: a second
  `create_order` with the same id returns the same order with one capture (*smoke*). We derive it from the gift's row:
  `hearthline-gift-<gift id>`.
- `prefer="return=representation"`, so the reply carries the capture.
- Returns `Order`: `status` (*smoke*: `COMPLETED`), `purchase_units[0].payments.captures[0]` (`OrdersCapture`): `id`,
  `status`, `amount.value`, `seller_receivable_breakdown.paypal_fee.value`, `final_capture`. All `Optional[...]`:
  assert `status == "COMPLETED"` and a capture `id`; anything else is a failed gift, not a crash.
- Error: `CreateOrderErrorBody` = `Error` [400, 401, 422] | `RawError`. A declined or closed account answers 422.

### `client.vault.get_payment_token`
- `GET /v3/vault/payment-tokens/{id}` · `get_payment_token(id_: str, *, request_options=None) -> PaymentTokenResponse`
- ⚠ After the token is deleted, PayPal's error body does not decode as `Error`: the call raises
  **`pydantic.ValidationError`, not `ApiError`** (*smoke*). Treat it like a 404.
- Error: `GetPaymentTokenErrorBody` = `Error` [403, 404, 422, 500] | `RawError`.

### `client.vault.delete_payment_token`
- `DELETE /v3/vault/payment-tokens/{id}` · `delete_payment_token(id_: str, *, request_options=None) -> None`
- Called as `client.vault.with_raw_response.delete_payment_token(token_id)` → `ApiResult[None,
  DeletePaymentTokenErrorBody]`; a `Success` with `status_code` 204 (*smoke*). A token already gone counts as revoked.
- Error: `DeletePaymentTokenErrorBody` = `Error` [400, 403, 500] | `RawError`.

### Shared (adds to Part 1's)
- Keyword-only boundary: every operation takes its path id or body positionally and everything else by name; every
  keyword has a real default, so no defensive `None`s.
- Errors map to one `VaultError(message, outcome_unknown=False)` in `app/paypal/vault.py`: `ApiError` (any arm), a
  decode `ValidationError`, and `httpx2.ConnectError`/`ConnectTimeout`/`PoolTimeout`/`ProxyError` are known failures;
  any other `httpx2.RequestError` on `create_order` sets `outcome_unknown=True` (the gift stays "checking" and is
  resolved by resending with the same request id).

## DUPLICATE CLAIMS

| Write | Where the claim is stored | What rejects the second one | Where that rejection is caught | Where in the code |
| --- | --- | --- | --- | --- |
| A gift from a mandate to one registry item (`create_order`) | a `mandate_gifts` row, inserted before the call, unique on (`mandate_id`, `registry_item_id`) and on `paypal_request_id` | the database's unique constraint (`IntegrityError` on flush) | `except IntegrityError` in the claim | TBD |
| Turning an approved setup token into a payment token (`create_payment_token`); the return page can load twice | `giving_mandates.status`, moved `pending` → `saving` by one conditional `UPDATE ... WHERE status = 'pending'` | the conditional update matching no row (`rowcount == 0`) | the `rowcount` check in the claim | TBD |
| Revoking (`delete_payment_token`) | `giving_mandates.status`, moved to `revoked` by a conditional update | the conditional update matching no row | the `rowcount` check in the claim | TBD |

`create_setup_token` has no row: an unused setup token is harmless and expires on its own.

## Code layout

- `app/paypal/vault.py`: the calls above and the error boundary (exemplar for style: `app/paypal/reporting.py`).
- `app/mandates.py`: mandates, eligibility, the monthly budget, the claims, and giving: a `Donation` per gift, applied
  with `registry.apply_capture`, so funding, the Shopper, the ledger and Books work as for any gift.
- `app/agents/giving.py`: the AI's choice among eligible needs, checked by code.
- `app/api/mandates.py`, and `frontend/src/components/GivingMandate.tsx` on the donor's Giving page.
- Tests: `tests/test_mandates.py` through `tests/paypal_stub.py`'s routing transport.

## Assumptions and blockers

- Vaulting PayPal accounts is enabled on the sandbox app (*smoke*: setup token, approval, payment token, a $5 and a
  $3 merchant-initiated order, and deletes all succeeded on 2026-10-22).
- No blockers.

## Required reading (loaded before coding Part 2)

- MUST load `python-getting-started` and `python-integrate-paypal` (again, for the Vault and Orders pages)
- MUST load `python-error-handling`: decode failures are not `ApiError`; which transport failures were never sent
- MUST load `python-configuration-resilience`: retries never repeat a `POST`; *the same operation arriving twice*
- MUST load `python-calling-endpoints`: `with_raw_response` for the operation that returns `None`
- MUST load `python-models`: `Optional` is `T | UnsetType`; `type_` has the wire alias `type`
- MUST load `python-client-initialization`: one long-lived client, reused
- MUST load `python-testing`: the stub transport routes by path; check the method on the shared payment-token path
