"""Spike 1: can Claude vision + Channel3 turn room photos into a priced inventory?

Usage (from backend/):  uv run python -m spikes.s1_vision_inventory [photo_dir]
Put 3-5 real room photos (jpg/png/webp) in spikes/samples/ first.
Writes results to spikes/out/s1_<photo>.json.
"""

import base64
import io
import json
import sys
import time
from pathlib import Path

from channel3_sdk import Channel3
from PIL import Image
from pydantic import BaseModel

from app import ai
from app.config import get_settings

MAX_EDGE = 1568  # Claude's recommended long edge; larger images only add tokens.
OUT_DIR = Path(__file__).parent / "out"

SYSTEM = """You catalogue household contents for insurance claims after a disaster.
List every distinct physical item visible in the photo that has replacement value:
furniture, electronics, appliances, decor, kitchenware, clothing, books, toys, tools.
Skip fixtures that belong to the building (walls, windows, built-in cabinets).
Group identical items into one entry with a quantity. Prefer specific names
("55-inch flat-screen TV", "3-seat grey fabric sofa") over generic ones.
For search_query, write what you would type into a shopping site to buy a comparable
replacement new today."""


class Item(BaseModel):
    name: str
    category: str
    quantity: int
    brand: str | None
    condition: str
    search_query: str
    confidence: float


class RoomInventory(BaseModel):
    room_type: str
    items: list[Item]


def load_jpeg_b64(path: Path) -> str:
    img = Image.open(path)
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def cheapest_new_offer(product) -> tuple[float | None, str | None]:
    offers = [o for o in (product.offers or []) if o.price and o.availability == "InStock"]
    if not offers:
        return None, None
    best = min(offers, key=lambda o: o.price.amount)
    return best.price.amount, best.domain


def run(photo: Path, c3: Channel3) -> dict:
    b64 = load_jpeg_b64(photo)

    t0 = time.perf_counter()
    inventory = ai.parse(
        RoomInventory,
        system=SYSTEM,
        content=[
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text", "text": "Catalogue this room."},
        ],
    )
    claude_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    priced = []
    for item in inventory.items:
        results = c3.products.search(query=item.search_query, limit=3)
        product = results.products[0] if results.products else None
        price, domain = cheapest_new_offer(product) if product else (None, None)
        priced.append(
            {
                **item.model_dump(),
                "match_title": product.title if product else None,
                "match_id": product.id if product else None,
                "unit_price": price,
                "retailer": domain,
            }
        )
    search_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    scene = c3.experimental.find_products_in_image(base64image=b64)
    scene_s = time.perf_counter() - t0
    scene_things = [{"thing": t.thing, "top_match": t.matches[0].title if t.matches else None} for t in scene.things]

    total = sum((p["unit_price"] or 0) * p["quantity"] for p in priced)
    print(f"\n=== {photo.name}: {inventory.room_type} - {len(priced)} items, ~${total:,.0f}")
    print(f"    Claude {claude_s:.1f}s | Channel3 text search {search_s:.1f}s | find-in-image {scene_s:.1f}s")
    for p in priced:
        price = f"${p['unit_price']:,.2f}" if p["unit_price"] else "no price"
        print(f"  {p['quantity']:>2} x {p['name'][:40]:<40} {price:>12}  <- {(p['match_title'] or '-')[:45]}")
    print("  Channel3 find-in-image saw:", ", ".join(t["thing"] for t in scene_things) or "nothing")

    return {
        "photo": photo.name,
        "room_type": inventory.room_type,
        "estimated_total": total,
        "timings_s": {"claude": claude_s, "channel3_search": search_s, "find_in_image": scene_s},
        "items": priced,
        "find_in_image": scene_things,
    }


def main() -> None:
    s = get_settings()
    if not (s.anthropic_api_key and s.channel3_api_key):
        sys.exit("Set ANTHROPIC_API_KEY and CHANNEL3_API_KEY in backend/.env")

    photo_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "samples"
    photos = sorted(p for p in photo_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if not photos:
        sys.exit(f"No photos in {photo_dir}")

    c3 = Channel3(api_key=s.channel3_api_key)
    OUT_DIR.mkdir(exist_ok=True)
    for photo in photos:
        result = run(photo, c3)
        (OUT_DIR / f"s1_{photo.stem}.json").write_text(json.dumps(result, indent=2))
    print(f"\nSaved results to {OUT_DIR}. Check: are names specific, prices plausible, anything missed?")


if __name__ == "__main__":
    main()
