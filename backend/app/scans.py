"""Turns a scan's photos into priced items. Runs as a FastAPI background task (in-process on
Render's free tier), so it opens its own database session and records failures on the scan."""

import logging

from app import ai
from app.agents import inventory, valuation
from app.db import SessionLocal
from app.models import EvidenceLevel, Item, Media, Scan, ScanStatus, now

log = logging.getLogger(__name__)


AI_BUSY = "ai_busy"  # the page shows a translated "try again in a minute"


def process_scan(scan_id: int) -> None:
    with SessionLocal() as db:
        scan = db.get(Scan, scan_id)
        scan.status = ScanStatus.PROCESSING
        db.commit()
        try:
            media: list[Media] = sorted(scan.media, key=lambda m: m.id)
            household = scan.household
            detected = inventory.detect_items([m.data for m in media], scan.room.name)
            prices = valuation.value_items([d.search_query for d in detected.items])
            # A scan made before the household was caught in a disaster is the strongest evidence.
            evidence = EvidenceLevel.PHOTO if household.disaster_event_id else EvidenceLevel.PRE_DISASTER_SCAN
            for found, price in zip(detected.items, prices, strict=True):
                db.add(
                    Item(
                        household_id=household.id,
                        room_id=scan.room_id,
                        scan_id=scan.id,
                        media_id=media[found.photo_index].id,
                        name=found.name,
                        category=found.category,
                        quantity=found.quantity,
                        brand=found.brand,
                        condition=found.condition,
                        ai_confidence=found.confidence,
                        search_query=found.search_query,
                        evidence_level=evidence,
                        **(
                            {
                                "unit_price": price.unit_price,
                                "price_low": price.price_low,
                                "price_high": price.price_high,
                                "price_source": "channel3",
                                "channel3_product_id": price.product_id,
                                "match_title": price.title[:300],
                                "match_url": price.url[:600],
                                "retailer": price.retailer,
                                "offers_considered": price.offers_considered,
                            }
                            if price
                            else {}
                        ),
                    )
                )
            scan.status = ScanStatus.DONE
        except Exception as e:  # a background job has no caller to raise to; record it on the scan
            log.exception("Scan %s failed", scan_id)
            db.rollback()
            scan = db.get(Scan, scan_id)
            scan.status = ScanStatus.FAILED
            scan.error = AI_BUSY if isinstance(e, ai.AIError) else str(e)[:500]
        scan.finished_at = now()
        db.commit()
