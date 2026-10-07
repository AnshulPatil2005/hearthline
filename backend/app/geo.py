"""Disaster zones and geocoding.

Zones are GeoJSON geometries, so any disaster type works: fire perimeters, flood extents,
hurricane wind fields or earthquake shaking areas.
"""

import json
from functools import lru_cache

import httpx
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DisasterEvent

CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


@lru_cache(maxsize=64)
def _geometry(zone_json: str) -> BaseGeometry:
    return shape(json.loads(zone_json))


def in_zone(zone: dict, lat: float, lng: float) -> bool:
    # covers(): a point exactly on the boundary counts as inside.
    return _geometry(json.dumps(zone, sort_keys=True)).covers(Point(lng, lat))


def event_for_point(db: Session, lat: float, lng: float) -> DisasterEvent | None:
    events = db.scalars(select(DisasterEvent).where(DisasterEvent.status == "active"))
    return next((e for e in events if in_zone(e.zone, lat, lng)), None)


def geocode(address: str) -> tuple[float, float] | None:
    """US address -> (lat, lng) with the free Census geocoder. None if not found or unreachable."""
    try:
        r = httpx.get(
            CENSUS_GEOCODER,
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            timeout=15,
        )
        r.raise_for_status()
        matches = r.json()["result"]["addressMatches"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    if not matches:
        return None
    coords = matches[0]["coordinates"]
    return coords["y"], coords["x"]
