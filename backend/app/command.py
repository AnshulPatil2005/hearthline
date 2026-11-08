"""Command Center: every household in the disaster, served to AG Grid's server-side row model.

AG Grid sends filter, sort, grouping and aggregation requests; `rows()` turns them into one SQL query
so 2,000+ households never have to be sent to the browser at once. "Help received" is read from the
ledger, so the grid always matches the books.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, String, and_, case, cast, false, func, not_, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app import ledger
from app.models import (
    AidBatch,
    AidBatchItem,
    Business,
    Crew,
    CrewJob,
    DisasterEvent,
    Household,
    LedgerAccount,
    LedgerPosting,
    LedgerTransaction,
    RapidAidTrigger,
)

# What counts as help for a household: gifts and insurance credited to its fund, and cash aid paid to it.
HELP_KINDS = ("donation", "insurance_payment")
SPARK_WEEKS = 8
GROUPABLE = {"street", "damage_level", "verification_level", "household_size", "payout_ready"}
AGG_FUNCS = {"sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max, "count": func.count}


def _help_amount() -> ColumnElement:
    """The help one posting represents (0 for postings that aren't help)."""
    return case(
        (LedgerAccount.code == ledger.CASH_AID, LedgerPosting.amount),
        (
            and_(LedgerAccount.household_id.is_not(None), LedgerTransaction.kind.in_(HELP_KINDS)),
            -LedgerPosting.amount,
        ),
        else_=0,
    )


def _help_postings():
    return (
        select(LedgerTransaction.household_id, LedgerTransaction.created_at, _help_amount().label("amount"))
        .join(LedgerPosting, LedgerPosting.transaction_id == LedgerTransaction.id)
        .join(LedgerAccount, LedgerAccount.id == LedgerPosting.account_id)
        .where(LedgerTransaction.household_id.is_not(None))
    )


def _households():
    """One row per household with every column the grid can show, filter, sort or group by."""
    postings = _help_postings().subquery()
    helped = (
        select(postings.c.household_id, func.sum(postings.c.amount).label("help_received"))
        .group_by(postings.c.household_id)
        .subquery()
    )
    help_received = func.coalesce(helped.c.help_received, 0)
    loss = func.coalesce(Household.estimated_loss, 0)
    gap = loss - help_received
    return (
        select(
            Household.id.label("id"),
            Household.name.label("name"),
            Household.address_line.label("address_line"),
            Household.street.label("street"),
            Household.damage_level.label("damage_level"),
            Household.household_size.label("household_size"),
            Household.verification_level.label("verification_level"),
            Household.needs.label("needs"),
            Household.estimated_loss.label("estimated_loss"),
            help_received.label("help_received"),
            case((gap > 0, gap), else_=0).label("unmet_need"),
            (Household.payout_email.is_not(None)).label("payout_ready"),
            Household.created_at.label("registered"),
        )
        .outerjoin(helped, helped.c.household_id == Household.id)
        .subquery("hh")
    )


# --- AG Grid filter models -> SQL -------------------------------------------------------------


def _text(col: ColumnElement, m: dict) -> ColumnElement:
    value = str(m.get("filter") or "").lower()
    low = func.lower(cast(col, String))
    return {
        "contains": low.contains(value, autoescape=True),
        "notContains": not_(low.contains(value, autoescape=True)),
        "equals": low == value,
        "notEqual": low != value,
        "startsWith": low.startswith(value, autoescape=True),
        "endsWith": low.endswith(value, autoescape=True),
        "blank": or_(col.is_(None), cast(col, String) == ""),
        "notBlank": and_(col.is_not(None), cast(col, String) != ""),
    }[m.get("type", "contains")]


def _value(v: Any) -> float:
    if v is None or v == "":
        raise ValueError("a number is required")
    return float(v)


def _number(col: ColumnElement, m: dict) -> ColumnElement:
    kind = m.get("type", "equals")
    if kind == "blank":
        return col.is_(None)
    if kind == "notBlank":
        return col.is_not(None)
    a = _value(m.get("filter"))
    if kind == "inRange":
        return col.between(a, _value(m.get("filterTo")))
    return {
        "equals": col == a,
        "notEqual": col != a,
        "greaterThan": col > a,
        "greaterThanOrEqual": col >= a,
        "lessThan": col < a,
        "lessThanOrEqual": col <= a,
    }[kind]


def _date(col: ColumnElement, m: dict) -> ColumnElement:
    def day(v: str) -> date:
        return date.fromisoformat(v[:10])

    kind, d = m.get("type", "equals"), cast(col, Date)
    if kind == "blank":
        return col.is_(None)
    if kind == "notBlank":
        return col.is_not(None)
    a = day(m["dateFrom"])  # KeyError/TypeError if missing: reported as a bad filter
    if kind == "inRange":
        return d.between(a, day(m["dateTo"]))
    return {"equals": d == a, "notEqual": d != a, "greaterThan": d > a, "lessThan": d < a}[kind]


def _set(name: str, col: ColumnElement, m: dict) -> ColumnElement:
    values = m.get("values") or []
    if name == "needs":  # a JSON list: match households that have any of the chosen needs
        return or_(*(cast(col, String).contains(f'"{v}"', autoescape=True) for v in values)) if values else false()
    if name == "payout_ready":
        wanted = {str(v).lower() == "true" for v in values}
        return true() if wanted == {True, False} else (col.is_(True) if True in wanted else col.is_(False))
    if name == "verification_level":
        values = [int(v) for v in values if v is not None]
    present = [v for v in values if v is not None]
    clause = col.in_(present) if present else false()
    return or_(clause, col.is_(None)) if None in values else clause


def _filter(name: str, col: ColumnElement, m: dict) -> ColumnElement:
    if "conditions" in m:  # two conditions joined with AND / OR
        parts = [_filter(name, col, {**c, "filterType": m.get("filterType")}) for c in m["conditions"]]
        return and_(*parts) if m.get("operator", "AND") == "AND" else or_(*parts)
    kind = m.get("filterType")
    if kind == "set":
        return _set(name, col, m)
    if kind == "number":
        return _number(col, m)
    if kind == "date":
        return _date(col, m)
    return _text(col, m)


class BadRequest(ValueError):
    pass


def _where(hh, filter_model: dict | None) -> list[ColumnElement]:
    clauses = []
    for name, model in (filter_model or {}).items():
        if name not in hh.c:
            raise BadRequest(f"Unknown column {name}")
        try:
            clauses.append(_filter(name, hh.c[name], model))
        except (KeyError, ValueError, TypeError) as e:
            raise BadRequest(f"Can't filter {name}: {e}") from None
    return clauses


def _group_key(name: str, key: Any) -> Any:
    if key is None:
        return None
    if name in {"verification_level", "household_size"}:
        try:
            return int(key)
        except (TypeError, ValueError):
            raise BadRequest(f"Not a group of {name}: {key!r}") from None
    if name == "payout_ready":
        return str(key).lower() == "true"
    return key


def rows(db: Session, req: dict) -> dict:
    """Answer one AG Grid server-side request: {startRow, endRow, rowGroupCols, groupKeys, valueCols,
    filterModel, sortModel}. Returns {rows, lastRow}."""
    hh = _households()
    try:
        start, end = max(0, int(req.get("startRow") or 0)), int(req.get("endRow") or 100)
    except (TypeError, ValueError):
        raise BadRequest("startRow and endRow must be numbers") from None
    limit = max(1, min(end - start, 500))
    where = _where(hh, req.get("filterModel"))
    groups = [g["field"] for g in req.get("rowGroupCols") or []]
    keys = req.get("groupKeys") or []
    if any(g not in GROUPABLE for g in groups):
        raise BadRequest("That column can't be grouped")
    for field, key in zip(groups, keys, strict=False):
        value = _group_key(field, key)
        where.append(hh.c[field].is_(None) if value is None else hh.c[field] == value)
    sort_model = req.get("sortModel") or []
    # How many households match the filters, whatever the grouping (shown above the grid).
    matching = db.scalar(select(func.count()).select_from(select(hh.c.id).where(*where).subquery()))

    if len(keys) < len(groups):  # a level of group rows with aggregates
        field = groups[len(keys)]
        g = hh.c[field]
        aggs = []
        for vc in req.get("valueCols") or []:
            fn = AGG_FUNCS.get(vc.get("aggFunc") or "sum")
            if fn is None or vc["field"] not in hh.c:
                raise BadRequest("Unsupported aggregation")
            aggs.append(fn(hh.c[vc["field"]]).label(vc["field"]))
        q = select(g.label(field), func.count().label("childCount"), *aggs).where(*where).group_by(g)
        labels = {field, "childCount", *(a.name for a in aggs)}
        order = [
            (q.selected_columns[s["colId"]].desc() if s.get("sort") == "desc" else q.selected_columns[s["colId"]])
            for s in sort_model
            if s.get("colId") in labels
        ] or [g]
        total = db.scalar(select(func.count()).select_from(q.subquery()))
        result = db.execute(q.order_by(*order).offset(start).limit(limit)).mappings().all()
        return {"rows": [_clean(dict(r)) for r in result], "lastRow": total, "matching": matching}

    q = select(hh).where(*where)
    order = [
        (hh.c[s["colId"]].desc() if s.get("sort") == "desc" else hh.c[s["colId"]])
        for s in sort_model
        if s.get("colId") in hh.c
    ]
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    result = [dict(r) for r in db.execute(q.order_by(*order, hh.c.id).offset(start).limit(limit)).mappings()]
    trends = help_trends(db, [r["id"] for r in result])
    for r in result:
        r["help_trend"] = trends.get(r["id"], [0] * SPARK_WEEKS)
    return {"rows": [_clean(r) for r in result], "lastRow": total, "matching": matching}


def help_trends(db: Session, household_ids: list[int], weeks: int = SPARK_WEEKS) -> dict[int, list[float]]:
    """Help received per week for the last `weeks` weeks (oldest first), for the grid's sparklines."""
    if not household_ids:
        return {}
    since = datetime.now(UTC) - timedelta(weeks=weeks)
    p = (
        _help_postings()
        .where(LedgerTransaction.household_id.in_(household_ids), LedgerTransaction.created_at >= since)
        .subquery()
    )
    out: dict[int, list[float]] = defaultdict(lambda: [0.0] * weeks)
    for hid, created, amount in db.execute(select(p.c.household_id, p.c.created_at, p.c.amount)):
        if not amount:
            continue
        created = created if created.tzinfo else created.replace(tzinfo=UTC)
        week = min(weeks - 1, max(0, (created - since).days // 7))
        out[hid][week] += float(amount)
    return dict(out)


def set_values(db: Session, field: str) -> list:
    """Distinct values for a set filter."""
    if field == "needs":
        seen: set[str] = set()
        for (needs,) in db.execute(select(Household.needs)):
            seen.update(needs or [])
        return sorted(seen)
    if field == "payout_ready":
        return [True, False]
    if field not in {"street", "damage_level", "verification_level", "household_size"}:
        raise BadRequest("No set filter for that column")
    col = getattr(Household, field)
    return [v for (v,) in db.execute(select(col).distinct().order_by(col))]


def summary(db: Session) -> dict:
    hh = _households()
    row = db.execute(
        select(
            func.count().label("households"),
            func.sum(case((hh.c.damage_level == "destroyed", 1), else_=0)).label("destroyed"),
            func.sum(case((hh.c.verification_level >= 2, 1), else_=0)).label("verified"),
            func.sum(hh.c.help_received).label("help_received"),
            func.sum(hh.c.unmet_need).label("unmet_need"),
        )
    ).one()
    return _clean(dict(row._mapping))


def _clean(row: dict) -> dict:
    """JSON-friendly values: money as strings with cents, booleans as booleans."""
    out = {}
    for k, v in row.items():
        if k == "payout_ready" and v is not None:
            out[k] = bool(v)  # SQLite returns 0/1
        elif isinstance(v, Decimal):
            out[k] = f"{v:.2f}"
        elif isinstance(v, float) and k in {"estimated_loss", "help_received", "unmet_need"}:
            out[k] = f"{v:.2f}"
        else:
            out[k] = v
    return out


# --- The map: the same households as the grid, with everything that has a place ----------------------------------


def map_data(db: Session, filter_model: dict | None) -> dict:
    """Households matching the grid's filters (as compact rows), first-72-hours payments, upcoming crew visits,
    verified local businesses and the open disasters' zones."""
    hh = _households()
    found = db.execute(
        select(hh.c.id, Household.lat, Household.lng, hh.c.damage_level, hh.c.verification_level, hh.c.unmet_need)
        .join(Household, Household.id == hh.c.id)
        .where(Household.lat.is_not(None), Household.lng.is_not(None), *_where(hh, filter_model))
        .order_by(hh.c.id)
    ).all()
    paid = db.execute(
        select(AidBatchItem.household_id, AidBatchItem.amount, AidBatch.decided_at)
        .join(AidBatch, AidBatch.id == AidBatchItem.batch_id)
        .join(RapidAidTrigger, RapidAidTrigger.aid_batch_id == AidBatch.id)
        .where(AidBatchItem.status.not_in(("queued", "skipped")))
    ).all()
    jobs = db.execute(
        select(CrewJob.id, CrewJob.household_id, Household.lat, Household.lng, Crew.name, CrewJob.title)
        .join(Household, Household.id == CrewJob.household_id)
        .outerjoin(Crew, Crew.id == CrewJob.crew_id)
        .where(CrewJob.status == "scheduled", Household.lat.is_not(None))
        .order_by(CrewJob.starts_at)
        .limit(300)
    ).all()
    businesses = db.scalars(
        select(Business).where(Business.verification == "verified", Business.lat.is_not(None)).order_by(Business.id)
    )
    events = db.scalars(select(DisasterEvent).where(DisasterEvent.status == "active").order_by(DisasterEvent.id))
    return {
        # [id, lat, lng, damage, verification level, unmet need in whole dollars]: 2,000 rows stay small
        "households": [
            [r.id, round(r.lat, 5), round(r.lng, 5), r.damage_level, r.verification_level, int(r.unmet_need or 0)]
            for r in found
        ],
        "paid": [{"household_id": h, "amount": f"{a:.2f}", "at": at.isoformat() if at else None} for h, a, at in paid],
        "jobs": [
            {"id": j.id, "household_id": j.household_id, "lat": j.lat, "lng": j.lng, "crew": j.name, "title": j.title}
            for j in jobs
        ],
        "businesses": [
            {"id": b.id, "name": b.name, "kind": b.kind, "lat": b.lat, "lng": b.lng, "status": _business_status(b)}
            for b in businesses
        ],
        "zones": [{"id": e.id, "name": e.name, "is_fictional": e.is_fictional, "zone": e.zone} for e in events],
    }


def _business_status(b: Business) -> str:
    """open (never closed, or reopened) | raising (closed, raising its Reopen Fund) | closed (missed its date)."""
    last = b.campaigns[-1].status if b.campaigns else None
    return {"live": "raising", "refunded": "closed", "closed": "closed"}.get(last or "", "open")


def household_card(db: Session, household_id: int) -> dict | None:
    """What a map pin shows when it's clicked."""
    hh = _households()
    row = db.execute(select(hh).where(hh.c.id == household_id)).first()
    return _clean(dict(row._mapping)) if row else None
