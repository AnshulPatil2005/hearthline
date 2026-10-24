"""Showing a family's needs in a giver's own currency: family and friends abroad give in pesos, Philippine pesos,
euros, Canadian dollars or pounds through PayPal, and the family receives dollars.

The rates here are estimates for display: the European Central Bank's daily reference rates, through Frankfurter
(free, no key). PayPal converts at its own rate when it captures the payment, and the books use that rate, from the
capture. In the sandbox PayPal's rate ran about 3% from the reference rate, so estimates allow for it.
"""

import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

import httpx

FRANKFURTER = "https://api.frankfurter.dev/v1/latest"
CURRENCIES = {
    "MXN": "Mexican peso",
    "PHP": "Philippine peso",
    "EUR": "Euro",
    "CAD": "Canadian dollar",
    "GBP": "British pound",
}
PAYPAL_SPREAD = Decimal("1.03")  # PayPal's conversion runs about 3% from the reference rate
FALLBACK = {"MXN": "18.78", "PHP": "63.64", "EUR": "0.893", "CAD": "1.400", "GBP": "0.748"}  # Oct 23, 2026
CACHE_SECONDS = 3600
CENT = Decimal("0.01")

_cache: dict[str, tuple[float, "Rates"]] = {}


@dataclass(frozen=True)
class Rates:
    per_usd: dict[str, Decimal]  # units of each currency for one US dollar
    as_of: str  # the reference rates' date
    source: str  # ecb (today's reference rates) | fallback (saved ones, when Frankfurter didn't answer)


def rates() -> Rates:
    hit = _cache.get("rates")
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        r = httpx.get(FRANKFURTER, params={"base": "USD", "symbols": ",".join(CURRENCIES)}, timeout=10)
        r.raise_for_status()
        data = r.json()
        found = Rates({c: Decimal(str(data["rates"][c])) for c in CURRENCIES}, data["date"], "ecb")
    except (httpx.HTTPError, KeyError, ValueError):
        found = Rates({c: Decimal(v) for c, v in FALLBACK.items()}, "2026-10-23", "fallback")
    _cache["rates"] = (time.monotonic(), found)
    return found


def giver_pays(usd: Decimal, currency: str) -> Decimal:
    """About what someone pays in `currency` for the family to get `usd` (rounded up to a whole unit)."""
    return (usd * rates().per_usd[currency] * PAYPAL_SPREAD).quantize(Decimal("1"), rounding=ROUND_CEILING)


def family_gets(amount: Decimal, currency: str) -> Decimal:
    """About how many dollars `amount` in `currency` becomes once PayPal converts it."""
    return (amount / rates().per_usd[currency] / PAYPAL_SPREAD).quantize(CENT)
