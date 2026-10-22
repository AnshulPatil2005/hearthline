"""Real disasters: open a disaster FEMA declared (OpenFEMA) or a severe National Weather Service warning in Hearthline.

The zone is the declaration's counties (or the warning's own polygon, else its counties), drawn from the Census
Bureau's TIGERweb county shapes. Opening one is a staff decision. Households whose address falls inside join it, and
a declaration (or a qualifying warning) proposes first-72-hours aid for the ones that prepared. The demo stays the
fictional Sablewood Fire; real disasters are opened on top of it and can be closed again.
"""

import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Any

import httpx
from shapely import make_valid
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union
from shapely.prepared import prep
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, rapid_aid
from app.alerts import HEADERS, NWS_ALERTS
from app.models import DisasterEvent, DisasterKind, Household, RapidAidTrigger, User, now

OPENFEMA = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer"
STATES_LAYER, COUNTIES_LAYER = 0, 1
CACHE_SECONDS = 600
DAYS = 120  # declarations made in the last four months
SIMPLIFY = 0.002  # degrees (about 200 m): small enough to keep a house on the right side of a county line
CLOSE_GAPS = 0.004  # degrees: wider than the gaps the generalized county shapes leave between neighbours
PRICE_PROTECTION_DAYS = 30  # California Penal Code 396, after a declared emergency

FEMA_KINDS = {
    "Fire": DisasterKind.WILDFIRE,
    "Flood": DisasterKind.FLOOD,
    "Dam/Levee Break": DisasterKind.FLOOD,
    "Tsunami": DisasterKind.FLOOD,
    "Hurricane": DisasterKind.HURRICANE,
    "Typhoon": DisasterKind.HURRICANE,
    "Tropical Storm": DisasterKind.HURRICANE,
    "Tropical Depression": DisasterKind.HURRICANE,
    "Earthquake": DisasterKind.EARTHQUAKE,
    "Severe Storm": DisasterKind.STORM,
    "Severe Storm(s)": DisasterKind.STORM,
    "Coastal Storm": DisasterKind.STORM,
    "Straight-Line Winds": DisasterKind.STORM,
    "Mud/Landslide": DisasterKind.STORM,
    "Tornado": DisasterKind.TORNADO,
    "Winter Storm": DisasterKind.WINTER_STORM,
    "Snowstorm": DisasterKind.WINTER_STORM,
    "Severe Ice Storm": DisasterKind.WINTER_STORM,
    "Freezing": DisasterKind.WINTER_STORM,
}
# NWS event names, by the first word that matches
NWS_KINDS = [
    ("Fire", DisasterKind.WILDFIRE),
    ("Red Flag", DisasterKind.WILDFIRE),
    ("Evacuation", DisasterKind.WILDFIRE),
    ("Flood", DisasterKind.FLOOD),
    ("Tsunami", DisasterKind.FLOOD),
    ("Hurricane", DisasterKind.HURRICANE),
    ("Tropical", DisasterKind.HURRICANE),
    ("Storm Surge", DisasterKind.HURRICANE),
    ("Typhoon", DisasterKind.HURRICANE),
    ("Tornado", DisasterKind.TORNADO),
    ("Blizzard", DisasterKind.WINTER_STORM),
    ("Winter", DisasterKind.WINTER_STORM),
    ("Ice", DisasterKind.WINTER_STORM),
    ("Snow", DisasterKind.WINTER_STORM),
    ("Earthquake", DisasterKind.EARTHQUAKE),
    ("Wind", DisasterKind.STORM),
    ("Storm", DisasterKind.STORM),
    ("Thunderstorm", DisasterKind.STORM),
]
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
FIPS = re.compile(r"\d{5}")


class RealDisasterError(ValueError):
    pass


class Unavailable(RealDisasterError):
    """A public service (OpenFEMA, the NWS, the Census Bureau) didn't answer."""


@dataclass(frozen=True)
class Declaration:
    number: int
    code: str  # e.g. DR-4949-WI: DR major disaster, EM emergency, FM fire management
    state: str
    declared_at: datetime
    incident: str  # FEMA's incident type: Fire, Flood, Hurricane, ...
    title: str
    areas: list[str]  # FEMA's designated areas, e.g. "Winnebago (County)"
    counties: list[str] = field(default_factory=list)  # 5-digit FIPS; "SS000" means the whole state
    unmapped: list[str] = field(default_factory=list)  # tribal lands and other areas with no county shape


@dataclass(frozen=True)
class Warning:
    id: str
    event: str
    severity: str
    headline: str
    area: str
    sent: datetime
    expires: datetime | None
    geometry: dict | None  # the warning's own polygon, when the NWS drew one
    counties: list[str]  # 5-digit FIPS from the alert's SAME codes
    first_72_hours: bool  # qualifies for first-72-hours aid


@dataclass(frozen=True)
class Zone:
    geometry: dict
    households: int  # households already on file inside it and not in another open disaster


# --- Fetching, with a short cache (the public lists change slowly; the services ask clients not to hammer them) -------

_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def _cached(key: str, fetch: Any) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fetch()
    _cache[key] = (time.monotonic(), value)
    while len(_cache) > 64:
        _cache.popitem(last=False)
    return value


def _get(url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> Any:
    try:
        r = httpx.get(url, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        host = httpx.URL(url).host
        raise Unavailable(f"{host} didn't answer; try again in a minute") from e


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def title_case(text: str) -> str:
    """FEMA writes titles in capitals: "SEVERE STORMS AND FLOODING" -> "Severe Storms and Flooding"."""
    words = text.strip().lower().split()
    return " ".join(
        w if (i and w in SMALL_WORDS) else "-".join(part[:1].upper() + part[1:] for part in w.split("-"))
        for i, w in enumerate(words)
    )


# --- FEMA declarations ------------------------------------------------------------------------------------------------

FEMA_FIELDS = (
    "femaDeclarationString,disasterNumber,state,declarationDate,incidentType,declarationTitle,designatedArea,"
    "fipsStateCode,fipsCountyCode"
)


def _declarations_from(rows: list[dict]) -> list[Declaration]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(int(row["disasterNumber"]), []).append(row)
    out = []
    for number, group in grouped.items():
        first = group[0]
        counties, unmapped = [], []
        for row in group:
            state, county, area = row.get("fipsStateCode") or "", row.get("fipsCountyCode") or "", row["designatedArea"]
            if county != "000" and FIPS.fullmatch(state + county):
                counties.append(state + county)
            elif area == "Statewide" and FIPS.fullmatch(state + "000"):
                counties.append(state + "000")
            else:
                unmapped.append(area)
        out.append(
            Declaration(
                number=number,
                code=first["femaDeclarationString"],
                state=first["state"],
                declared_at=_when(first["declarationDate"]) or datetime.now(UTC),
                incident=first["incidentType"],
                title=title_case(first["declarationTitle"]),
                areas=sorted({row["designatedArea"] for row in group}),
                counties=sorted(set(counties)),
                unmapped=sorted(set(unmapped)),
            )
        )
    return out


def declarations(days: int = DAYS) -> list[Declaration]:
    """Disasters FEMA declared in the last `days` days, newest first, one entry per declaration."""

    def fetch() -> list[Declaration]:
        since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
        data = _get(
            OPENFEMA,
            {
                "$filter": f"declarationDate ge '{since}'",
                "$orderby": "declarationDate desc",
                "$top": "10000",
                "$select": FEMA_FIELDS,
            },
        )
        return _declarations_from(data.get("DisasterDeclarationsSummaries", []))

    return _cached(f"fema:{days}", fetch)


def declaration(number: int) -> Declaration:
    def fetch() -> list[Declaration]:
        data = _get(OPENFEMA, {"$filter": f"disasterNumber eq {int(number)}", "$top": "1000", "$select": FEMA_FIELDS})
        return _declarations_from(data.get("DisasterDeclarationsSummaries", []))

    found = _cached(f"fema-one:{number}", fetch)
    if not found:
        raise RealDisasterError(f"FEMA has no declaration numbered {number}")
    return found[0]


# --- National Weather Service warnings --------------------------------------------------------------------------------


def _warning(feature: dict) -> Warning:
    props = feature.get("properties") or {}
    same = (props.get("geocode") or {}).get("SAME") or []
    counties = sorted({code[1:] for code in same if len(code) == 6 and FIPS.fullmatch(code[1:])})
    return Warning(
        id=props["id"],
        event=props.get("event") or "Warning",
        severity=props.get("severity") or "Unknown",
        headline=(props.get("headline") or props.get("event") or "")[:500],
        area=(props.get("areaDesc") or "")[:500],
        sent=_when(props.get("sent") or props.get("effective")) or datetime.now(UTC),
        expires=_when(props.get("ends") or props.get("expires")),
        geometry=feature.get("geometry"),
        counties=counties,
        first_72_hours=rapid_aid.qualifies(props),
    )


def nws_kind(event: str) -> DisasterKind:
    return next((k for word, k in NWS_KINDS if word in event), DisasterKind.OTHER)


def warnings() -> list[Warning]:
    """Active severe and extreme NWS warnings across the country, most serious and newest first."""

    def fetch() -> list[Warning]:
        data = _get(NWS_ALERTS, {"status": "actual", "severity": "Extreme,Severe"}, HEADERS)
        found = [_warning(f) for f in data.get("features", []) if (f.get("properties") or {}).get("id")]
        return sorted(found, key=lambda w: (w.first_72_hours, w.severity == "Extreme", w.sent), reverse=True)

    return _cached("nws", fetch)


def warning(alert_id: str) -> Warning:
    if not alert_id.startswith("urn:oid:"):
        raise RealDisasterError("That isn't a National Weather Service alert id")
    data = _cached(f"nws-one:{alert_id}", lambda: _get(f"{NWS_ALERTS[: -len('/active')]}/{alert_id}", None, HEADERS))
    return _warning(data)


# --- Zones ------------------------------------------------------------------------------------------------------------


def _shapes(layer: int, where: str) -> list:
    data = _get(
        f"{TIGERWEB}/{layer}/query",
        {
            "where": where,
            "outFields": "GEOID",
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryPrecision": "4",
            "maxAllowableOffset": "0.002",
            "f": "geojson",
        },
    )
    return [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]


def county_zone(counties: list[str]) -> dict:
    """The union of the counties' shapes (5-digit FIPS; "SS000" is the whole state) as a GeoJSON geometry."""
    codes = sorted({c for c in counties if FIPS.fullmatch(c)})
    if not codes:
        raise RealDisasterError("No county to draw the zone from")

    def fetch() -> dict:
        by_state: dict[str, list[str]] = {}
        for code in codes:
            by_state.setdefault(code[:2], []).append(code[2:])
        parts = []
        for state, in_state in by_state.items():
            if "000" in in_state:
                parts += _shapes(STATES_LAYER, f"STATE='{state}'")
                continue
            for chunk in batched(in_state, 40):
                parts += _shapes(COUNTIES_LAYER, f"STATE='{state}' AND COUNTY IN ({','.join(repr(c) for c in chunk)})")
        if not parts:
            raise RealDisasterError("The Census Bureau has no shape for these counties")
        # Each county is generalized on its own, so neighbours don't quite meet: grow them a little, merge, then
        # shrink back (closing the slivers between them). make_valid repairs shapes that touch themselves.
        grown = [make_valid(part).buffer(CLOSE_GAPS, join_style="mitre") for part in parts]
        union = unary_union(grown).buffer(-CLOSE_GAPS, join_style="mitre")
        return mapping(make_valid(union.simplify(SIMPLIFY, preserve_topology=True)))

    return _cached("zone:" + ",".join(codes), fetch)


def warning_zone(w: Warning) -> dict:
    if w.geometry:
        return w.geometry
    return county_zone(w.counties)


def households_inside(db: Session, zone: dict) -> list[Household]:
    """Households on file inside the zone that aren't part of another open disaster."""
    area = shape(zone)
    west, south, east, north = area.bounds
    inside = prep(area)
    homes = db.scalars(select(Household).where(Household.lat.between(south, north), Household.lng.between(west, east)))
    return [
        h
        for h in homes
        if (h.disaster_event is None or h.disaster_event.status != "active") and inside.covers(Point(h.lng, h.lat))
    ]


def preview_declaration(db: Session, number: int) -> tuple[Declaration, Zone]:
    d = declaration(number)
    zone = county_zone(d.counties)
    return d, Zone(zone, len(households_inside(db, zone)))


def preview_warning(db: Session, alert_id: str) -> tuple[Warning, Zone]:
    w = warning(alert_id)
    zone = warning_zone(w)
    return w, Zone(zone, len(households_inside(db, zone)))


# --- Opening and closing ----------------------------------------------------------------------------------------------


def _open(
    db: Session,
    staff: User,
    *,
    source: str,
    external_id: str,
    slug: str,
    name: str,
    kind: DisasterKind,
    zone: dict,
    declared_at: datetime,
    price_protection: bool,
) -> DisasterEvent:
    event = db.scalar(select(DisasterEvent).where(DisasterEvent.external_id == external_id))
    if event is not None and event.status == "active":
        raise RealDisasterError(f"{event.name} is already open")
    if event is None:
        event = DisasterEvent(external_id=external_id, slug=slug[:80], source=source, is_fictional=False)
        db.add(event)
    event.name, event.kind, event.zone, event.declared_at, event.status = name[:120], kind, zone, declared_at, "active"
    event.opened_by = staff.name
    event.price_protection_until = declared_at + timedelta(days=PRICE_PROTECTION_DAYS) if price_protection else None
    db.flush()
    joined = households_inside(db, zone)
    for home in joined:
        home.disaster_event = event
    audit.record(
        db,
        actor_user_id=staff.id,
        action="disaster.opened",
        subject_type="disaster_event",
        subject_id=event.id,
        data={"source": source, "external_id": external_id, "name": event.name, "households": len(joined)},
    )
    db.commit()
    return event


def open_declaration(db: Session, number: int, staff: User) -> DisasterEvent:
    """Open a FEMA declaration with its counties as the zone, and propose first-72-hours aid for it."""
    d, zone = preview_declaration(db, number)
    event = _open(
        db,
        staff,
        source="fema",
        external_id=d.code,
        slug=f"fema-{d.code.lower()}",
        name=f"{d.title} ({d.state})",
        kind=FEMA_KINDS.get(d.incident, DisasterKind.OTHER),
        zone=zone.geometry,
        declared_at=d.declared_at,
        price_protection=d.state == "CA",
    )
    rapid_aid.declared(db, event, d.code, d.title)
    return event


def open_warning(db: Session, alert_id: str, staff: User) -> DisasterEvent:
    """Open a NWS warning with its polygon (or counties) as the zone; a qualifying one proposes first-72-hours aid."""
    w, zone = preview_warning(db, alert_id)
    kind = nws_kind(w.event)
    area = w.area.split(";")[0].strip()
    event = _open(
        db,
        staff,
        source="nws",
        external_id=w.id,
        slug=f"nws-{re.sub(r'[^a-z0-9]+', '-', w.id.lower())[-60:]}",
        name=f"{w.event}: {area}" if area else w.event,
        kind=kind,
        zone=zone.geometry,
        declared_at=w.sent,
        price_protection=False,
    )
    if w.first_72_hours:
        rapid_aid.warned(
            db, event, alert_id=w.id, event_name=w.event, headline=w.headline, severity=w.severity, sent=w.sent
        )
    return event


def close(db: Session, event: DisasterEvent, staff: User) -> DisasterEvent:
    if event.is_fictional:
        raise RealDisasterError("The demo disaster stays open")
    if event.status != "active":
        raise RealDisasterError(f"{event.name} is already closed")
    event.status = "closed"
    waiting = db.scalars(
        select(RapidAidTrigger).where(
            RapidAidTrigger.disaster_event_id == event.id, RapidAidTrigger.status == "proposed"
        )
    )
    for trigger in waiting:  # nothing is paid for a disaster that's closed
        trigger.status, trigger.decided_at, trigger.note = "dismissed", now(), "The disaster was closed"
        trigger.decided_by_user_id = staff.id
    audit.record(
        db,
        actor_user_id=staff.id,
        action="disaster.closed",
        subject_type="disaster_event",
        subject_id=event.id,
        data={"name": event.name},
    )
    db.commit()
    return event
