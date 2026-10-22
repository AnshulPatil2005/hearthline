"""PayPal Vault for giving mandates, through APIMatic's PayPal Python SDK (`paypal`): a donor saves their PayPal account
once, Hearthline gives from it with no checkout (merchant-initiated orders), and revoking deletes it at PayPal.

Written from the contract sheet in paypal-plan.md (Part 2), following APIMatic's PayPal Context Plugin workflow. Uses
the app's one long-lived client (`reporting.client()`). Retries keep the SDK's default policy, which never repeats a
`POST` or `DELETE`; a gift whose outcome is unknown is settled by resending with the same `PayPal-Request-Id`, which
PayPal answers with the same order.
"""

import functools
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import httpx2
from paypal.core import ApiError, OAuthProviderError, RawError, Success, UnsetType
from paypal.models import Error, Money
from pydantic import ValidationError

from app.paypal.reporting import client

USAGE_PATTERN = "UNSCHEDULED_PREPAID"  # gifts are made when a disaster calls for them, not on a schedule


class VaultError(Exception):
    """A PayPal Vault call failed. The message is safe to show; `outcome_unknown` means a payment may have happened."""

    def __init__(self, status_code: int, message: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True)
class Setup:
    setup_id: str
    approve_url: str  # where the donor approves saving their PayPal account


@dataclass(frozen=True)
class SavedAccount:
    token_id: str  # the vault id that payments use
    customer_id: str | None
    email: str | None
    payer_id: str | None


@dataclass(frozen=True)
class Payment:
    order_id: str
    capture_id: str
    status: str
    amount: Decimal
    fee: Decimal


def _value[T](field: T | UnsetType) -> T | None:
    return None if isinstance(field, UnsetType) else field


def _money(field: Money | UnsetType) -> Decimal:
    money = _value(field)
    return Decimal(money.value) if money is not None else Decimal(0)


def _detail(error: object) -> str:
    if isinstance(error, Error):
        details = _value(error.details) or []
        issue = _value(details[0].issue) if details else None
        return str(issue or _value(error.message) or error.name)
    return "unknown"


def _failure(status: int, error: object, what: str) -> VaultError:
    """One mapping for every failure, keyed on the status and the decoded error body."""
    match (status, error):
        case (401 | 403, _) | (_, OAuthProviderError()):
            return VaultError(502, "PayPal refused our credentials for saved accounts")
        case (422, _):
            return VaultError(402, f"PayPal declined {what} ({_detail(error)})")
        case (s, Error() | RawError()) if 400 <= s < 500:
            return VaultError(400, f"PayPal rejected {what} ({_detail(error)})")
        case _:
            return VaultError(502, "PayPal's vault service is unavailable")


def _guard[**P, R](what: str, *, pays: bool = False) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Run a vault call inside the one error boundary. For a payment, a request that may have reached PayPal without
    an answer is `outcome_unknown`; one that was never sent is a plain failure."""

    def wrap(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return fn(*args, **kwargs)
            except ApiError as e:
                raise _failure(e.status_code, e.error, what) from e
            except ValidationError as e:
                raise VaultError(502, f"PayPal's answer about {what} couldn't be read") from e
            except (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout, httpx2.ProxyError) as e:
                raise VaultError(502, "Couldn't reach PayPal") from e
            except httpx2.RequestError as e:
                raise VaultError(504, "PayPal didn't answer in time", outcome_unknown=pays) from e

        return inner

    return wrap


@_guard("saving the PayPal account")
def start_saving(description: str, return_url: str, cancel_url: str, brand: str = "Hearthline") -> Setup:
    """A setup token for the donor to approve at PayPal ("Save and Continue")."""
    setup = client().vault.create_setup_token(
        {
            "payment_source": {
                "paypal": {
                    "description": description[:120],
                    "usage_type": "MERCHANT",
                    "customer_type": "CONSUMER",
                    "usage_pattern": USAGE_PATTERN,
                    "experience_context": {"brand_name": brand, "return_url": return_url, "cancel_url": cancel_url},
                }
            }
        }
    )
    setup_id = _value(setup.id)
    approve = next((link.href for link in _value(setup.links) or [] if link.rel == "approve"), None)
    if not setup_id or not approve:
        raise VaultError(502, "PayPal didn't return a page to approve saving the account")
    return Setup(setup_id=setup_id, approve_url=approve)


@_guard("saving the PayPal account")
def setup_approved(setup_id: str) -> bool:
    status = _value(client().vault.get_setup_token(setup_id).status)
    return status == "APPROVED"


@_guard("saving the PayPal account")
def finish_saving(setup_id: str) -> SavedAccount:
    """Turn the approved setup token into a saved account (a payment token)."""
    token = client().vault.create_payment_token({"payment_source": {"token": {"id": setup_id, "type_": "SETUP_TOKEN"}}})
    token_id = _value(token.id)
    if not token_id:
        raise VaultError(502, "PayPal didn't return the saved account")
    customer = _value(token.customer)
    source = _value(token.payment_source)
    paypal = _value(source.paypal) if source is not None else None
    return SavedAccount(
        token_id=token_id,
        customer_id=_value(customer.id) if customer is not None else None,
        email=_value(paypal.email_address) if paypal is not None else None,
        payer_id=_value(paypal.payer_id) if paypal is not None else None,
    )


@_guard("the gift", pays=True)
def give(token_id: str, amount: Decimal, custom_id: str, description: str, request_id: str) -> Payment:
    """Charge the saved account with no buyer present. `request_id` must be derived from what the gift is for: PayPal
    requires it for an order with a saved account, and a resend with the same one returns the same order."""
    order = client().orders.create_order(
        {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {"currency_code": "USD", "value": f"{amount:.2f}"},
                    "custom_id": custom_id,
                    "description": description[:127],
                }
            ],
            "payment_source": {
                "paypal": {
                    "vault_id": token_id,
                    "stored_credential": {
                        "payment_initiator": "MERCHANT",
                        "usage": "SUBSEQUENT",
                        "usage_pattern": USAGE_PATTERN,
                    },
                }
            },
        },
        pay_pal_request_id=request_id,
        prefer="return=representation",
    )
    order_id = _value(order.id) or ""
    units = _value(order.purchase_units) or []
    payments = _value(units[0].payments) if units else None
    captures = (_value(payments.captures) if payments is not None else None) or []
    capture = captures[0] if captures else None
    capture_id = _value(capture.id) if capture is not None else None
    if _value(order.status) != "COMPLETED" or capture is None or not capture_id:
        raise VaultError(402, f"PayPal didn't complete the gift (order {order_id or 'not created'})")
    breakdown = _value(capture.seller_receivable_breakdown)
    return Payment(
        order_id=order_id,
        capture_id=capture_id,
        status=str(_value(capture.status) or ""),
        amount=_money(capture.amount),
        fee=_money(breakdown.paypal_fee) if breakdown is not None else Decimal(0),
    )


@_guard("removing the saved account")
def revoke(token_id: str) -> None:
    """Delete the saved account at PayPal. One that is already gone counts as removed."""
    try:
        result = client().vault.with_raw_response.delete_payment_token(token_id)
    except ValidationError:
        return  # PayPal's not-found body for a deleted token doesn't decode (paypal-plan.md, Part 2)
    if isinstance(result, Success) or result.status_code == 404:
        return
    raise _failure(result.status_code, result.error, "removing the saved account")
