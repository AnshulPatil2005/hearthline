"""Price-gouging guard.

California Penal Code 396: once an emergency is declared, sellers may not raise the price of essentials
(food, water, emergency and medical supplies, building materials, tools, ...) more than 10% above what
they charged just before the declaration. It applies for 30 days and is often extended locally.

The baseline is the median price in the 30 days before the declaration (one sale day shouldn't make a
normal price look like gouging). Channel3's price history supplies it for online products; the
Shopper refuses offers over the limit, and the public Price Watch shows every tracked price.
"""

import logging
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DisasterEvent, PriceSnapshot, PriceWatch, now

log = logging.getLogger(__name__)

LIMIT_PERCENT = 10.0
BASELINE_DAYS = 30
CENT = Decimal("0.01")


@dataclass
class Verdict:
    status: str  # ok | gouging | no_baseline | unknown
    baseline: Decimal | None
    current: Decimal | None
    markup_percent: float | None

    @property
    def gouging(self) -> bool:
        return self.status == "gouging"

    def explain(self) -> str:
        if self.baseline is None or self.current is None:
            return "no price history from before the declaration"
        return f"${self.current:,.2f} now vs ${self.baseline:,.2f} before the declaration ({self.markup_percent:+.0f}%)"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def protection_active(event: DisasterEvent | None, at: datetime | None = None) -> bool:
    if event is None:
        return False
    at = at or now()
    until = event.price_protection_until or _aware(event.declared_at) + timedelta(days=30)
    return _aware(event.declared_at) <= at <= _aware(until)


def judge(history: list[tuple[date, Decimal]], declared: datetime, current: Decimal | None = None) -> Verdict:
    """Compare the current price (or the latest observed one) with the pre-declaration median."""
    start = (_aware(declared) - timedelta(days=BASELINE_DAYS)).date()
    before = [price for day, price in history if start <= day < _aware(declared).date()]
    latest = current if current is not None else (max(history)[1] if history else None)
    if latest is None:
        return Verdict("unknown", None, None, None)
    if not before:
        return Verdict("no_baseline", None, latest, None)
    baseline = Decimal(str(statistics.median(before))).quantize(CENT)
    markup = float((latest - baseline) / baseline * 100) if baseline > 0 else 0.0
    return Verdict("gouging" if markup > LIMIT_PERCENT else "ok", baseline, latest, round(markup, 1))


def _channel3_history(product_id: str, days: int) -> list[tuple[date, Decimal]]:
    from app.agents.valuation import channel3  # optional dependency at call time (tests fake this)

    response = channel3().price_tracking.retrieve_history(product_id, days=days)
    out = []
    for point in response.history or []:
        stamp = (
            point.timestamp if isinstance(point.timestamp, datetime) else datetime.fromisoformat(str(point.timestamp))
        )
        out.append((stamp.date(), Decimal(str(point.price)).quantize(CENT)))
    return out


def _start_tracking(product_id: str) -> None:
    """Ask Channel3 to keep tracking the product's price (best effort; history works either way)."""
    try:
        from app.agents.valuation import channel3

        channel3().price_tracking.start(canonical_product_id=product_id)
    except Exception:
        log.info("Channel3 price tracking not started for %s", product_id)


def history_for(product_id: str, event: DisasterEvent) -> list[tuple[date, Decimal]]:
    days = (now() - _aware(event.declared_at)).days + BASELINE_DAYS + 2
    try:
        return _channel3_history(product_id, min(max(days, BASELINE_DAYS + 2), 365))
    except Exception:  # no history is "no baseline", never a crash in the Shopper
        log.exception("Channel3 price history failed for %s", product_id)
        return []


def watch_offer(
    db: Session,
    event: DisasterEvent,
    *,
    product_id: str,
    title: str,
    seller: str,
    url: str,
    category: str,
    price: Decimal,
) -> tuple[PriceWatch, Verdict]:
    """Track an online offer (Channel3) and judge its current price."""
    watch = db.scalar(
        select(PriceWatch).where(PriceWatch.channel3_product_id == product_id, PriceWatch.disaster_event_id == event.id)
    )
    if watch is None:
        watch = PriceWatch(
            disaster_event_id=event.id,
            channel3_product_id=product_id,
            title=title[:300],
            seller=seller,
            url=url[:600],
            category=category,
        )
        db.add(watch)
        db.flush()
        _start_tracking(product_id)
    history = history_for(product_id, event)
    _store(db, watch, history)
    verdict = judge(history, event.declared_at, price)
    _apply(watch, verdict)
    return watch, verdict


def _store(db: Session, watch: PriceWatch, history: list[tuple[date, Decimal]]) -> None:
    have = {s.observed_on for s in watch.snapshots}
    for day, price in history:
        if day not in have:
            watch.snapshots.append(PriceSnapshot(observed_on=day, price=price))
            have.add(day)


def _apply(watch: PriceWatch, verdict: Verdict) -> None:
    watch.baseline_price, watch.current_price = verdict.baseline, verdict.current
    watch.markup_percent, watch.status, watch.checked_at = verdict.markup_percent, verdict.status, now()


def rejudge(watch: PriceWatch, event: DisasterEvent) -> Verdict:
    verdict = judge([(s.observed_on, s.price) for s in watch.snapshots], event.declared_at)
    _apply(watch, verdict)
    return verdict


def refresh(db: Session, event: DisasterEvent, limit: int = 40) -> int:
    """Pull fresh Channel3 history for tracked online products (on demand: no cron on Render's free plan)."""
    watches = list(
        db.scalars(
            select(PriceWatch)
            .where(PriceWatch.disaster_event_id == event.id, PriceWatch.source == "channel3")
            .order_by(PriceWatch.checked_at.is_(None).desc(), PriceWatch.checked_at)
            .limit(limit)
        )
    )
    for watch in watches:
        _store(db, watch, history_for(watch.channel3_product_id, event))
        rejudge(watch, event)
    db.commit()
    return len(watches)
