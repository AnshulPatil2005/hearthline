"""Inventory agent: photos of one room -> list of distinct household items.

All photos of a scan go into a single model call. That saves free-tier requests and lets
the model merge the same sofa seen from three angles into one item.
"""

import base64

from pydantic import BaseModel

from app import ai

CATEGORIES = (
    "furniture, electronics, appliance, lighting, bedding, decor, kitchenware, "
    "clothing, books, toys, tools, sports, musical, other"
)

SYSTEM = f"""You catalogue household contents for insurance claims after a disaster.
You receive one or more photos of the same room. List every distinct physical item that has
replacement value: furniture, electronics, appliances, lighting, bedding, decor, kitchenware,
clothing, books, toys, tools. Photos may overlap: list each physical item once, with a quantity
for identical items. Skip fixtures that belong to the building (walls, windows, built-in cabinets,
ceiling fans wired into the house) and skip people.
Use specific names ("55-inch flat-screen TV", "3-seat grey fabric sofa"), not generic ones.
category must be one of: {CATEGORIES}.
search_query is what you would type into a shopping site to buy a comparable replacement new today.
photo_index is the 0-based index of the photo where the item is most clearly visible.
confidence is 0-1: how sure you are the item is really there and correctly named."""


class DetectedItem(BaseModel):
    name: str
    category: str
    quantity: int
    brand: str | None
    condition: str
    search_query: str
    confidence: float
    photo_index: int


class RoomInventory(BaseModel):
    room_type: str
    items: list[DetectedItem]


def detect_items(jpegs: list[bytes], room_name: str) -> RoomInventory:
    content = [ai.image_part(base64.standard_b64encode(j).decode()) for j in jpegs]
    content.append(ai.text_part(f"These {len(jpegs)} photo(s) show the room the household calls '{room_name}'."))
    inventory = ai.parse(RoomInventory, system=SYSTEM, content=content)
    for item in inventory.items:
        item.quantity = max(1, item.quantity)
        item.photo_index = min(max(0, item.photo_index), len(jpegs) - 1)
        item.confidence = min(max(0.0, item.confidence), 1.0)
    return inventory
