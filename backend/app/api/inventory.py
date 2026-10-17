"""Prepare: rooms, photo scans, the household inventory and its summary."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.households import MyHousehold
from app.db import get_db
from app.media import InvalidImage, media_token_valid, media_url, prepare_image
from app.models import EvidenceLevel, Household, Item, Media, Room, Scan
from app.scans import process_scan
from app.schemas import ORM, Money

router = APIRouter(tags=["inventory"])
DB = Annotated[Session, Depends(get_db)]
MAX_PHOTOS_PER_SCAN = 12


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RoomOut(ORM):
    id: int
    name: str


class ScanOut(ORM):
    id: int
    room_id: int
    status: str
    error: str | None
    photo_count: int = 0
    item_count: int = 0


class ItemOut(ORM):
    id: int
    room_id: int | None
    room_name: str | None = None
    name: str
    category: str
    quantity: int
    brand: str | None
    condition: str | None
    ai_confidence: float | None
    unit_price: Money | None
    price_low: Money | None
    price_high: Money | None
    total_value: Money | None
    price_source: str | None
    match_title: str | None
    match_url: str | None
    retailer: str | None
    offers_considered: int
    evidence_level: str
    confirmed: bool
    user_edited: bool
    photo_url: str | None = None


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    room_id: int | None = None
    category: str = "other"
    quantity: int = Field(default=1, ge=1)
    unit_price: Money | None = Field(default=None, ge=0)


class ItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    room_id: int | None = None
    category: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    unit_price: Money | None = Field(default=None, ge=0)
    confirmed: bool | None = None


class RoomTotal(BaseModel):
    room_id: int | None
    room_name: str
    item_count: int
    total_value: Money


class InventorySummary(BaseModel):
    item_count: int
    confirmed_count: int
    unpriced_count: int
    total_value: Money
    insured_contents_value: Money | None
    coverage_gap: Money | None  # how much more the contents are worth than the policy covers
    by_room: list[RoomTotal]


def item_out(item: Item) -> ItemOut:
    out = ItemOut.model_validate(item)
    out.room_name = item.room.name if item.room else None
    out.photo_url = media_url(item.media_id) if item.media_id else None
    return out


def own_room(db: Session, home: Household, room_id: int) -> Room:
    room = db.get(Room, room_id)
    if room is None or room.household_id != home.id:
        raise HTTPException(404, "Room not found")
    return room


def own_item(db: Session, home: Household, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.household_id != home.id:
        raise HTTPException(404, "Item not found")
    return item


def scan_out(scan: Scan, db: Session) -> ScanOut:
    out = ScanOut.model_validate(scan)
    out.photo_count = len(scan.media)
    out.item_count = len(list(db.scalars(select(Item.id).where(Item.scan_id == scan.id))))
    return out


@router.get("/households/me/rooms", response_model=list[RoomOut])
def list_rooms(home: MyHousehold) -> list[Room]:
    return sorted(home.rooms, key=lambda r: r.id)


@router.post("/households/me/rooms", response_model=RoomOut, status_code=201)
def create_room(body: RoomIn, home: MyHousehold, db: DB) -> Room:
    room = Room(household_id=home.id, name=body.name.strip())
    db.add(room)
    db.commit()
    return room


@router.post("/households/me/rooms/{room_id}/scans", response_model=ScanOut, status_code=202)
async def create_scan(
    room_id: int, files: list[UploadFile], home: MyHousehold, db: DB, background: BackgroundTasks
) -> ScanOut:
    """Upload photos (or video frames extracted in the browser) of one room. Items appear when
    the scan's status becomes `done`; poll GET /scans/{id}."""
    room = own_room(db, home, room_id)
    if not 1 <= len(files) <= MAX_PHOTOS_PER_SCAN:
        raise HTTPException(422, f"Send between 1 and {MAX_PHOTOS_PER_SCAN} photos per scan")
    scan = Scan(household_id=home.id, room_id=room.id)
    db.add(scan)
    db.flush()
    for upload in files:
        try:
            img = prepare_image(await upload.read())
        except InvalidImage as e:
            raise HTTPException(422, f"{upload.filename}: {e}") from None
        db.add(
            Media(
                household_id=home.id,
                room_id=room.id,
                scan_id=scan.id,
                content_type="image/jpeg",
                data=img.jpeg,
                width=img.width,
                height=img.height,
                sha256=img.sha256,
                phash=img.phash,
                captured_at=img.captured_at,
            )
        )
    db.commit()
    background.add_task(process_scan, scan.id)
    return scan_out(scan, db)


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: int, home: MyHousehold, db: DB) -> ScanOut:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.household_id != home.id:
        raise HTTPException(404, "Scan not found")
    return scan_out(scan, db)


@router.get("/households/me/items", response_model=list[ItemOut])
def list_items(home: MyHousehold, db: DB) -> list[ItemOut]:
    items = db.scalars(select(Item).where(Item.household_id == home.id).order_by(Item.room_id, Item.id))
    return [item_out(i) for i in items]


@router.post("/households/me/items", response_model=ItemOut, status_code=201)
def add_item(body: ItemIn, home: MyHousehold, db: DB) -> ItemOut:
    """Add an item from memory (no photo). It carries the weakest evidence level."""
    if body.room_id is not None:
        own_room(db, home, body.room_id)
    item = Item(
        household_id=home.id,
        **body.model_dump(),
        price_source="user" if body.unit_price is not None else None,
        evidence_level=EvidenceLevel.MEMORY,
        user_edited=True,
        confirmed=True,
    )
    db.add(item)
    db.commit()
    return item_out(item)


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(item_id: int, body: ItemPatch, home: MyHousehold, db: DB) -> ItemOut:
    item = own_item(db, home, item_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("room_id") is not None:
        own_room(db, home, changes["room_id"])
    if "unit_price" in changes:
        item.price_source = "user"
    for key, value in changes.items():
        setattr(item, key, value)
    if changes.keys() - {"confirmed"}:
        item.user_edited = True
    db.commit()
    return item_out(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, home: MyHousehold, db: DB) -> Response:
    db.delete(own_item(db, home, item_id))
    db.commit()
    return Response(status_code=204)


@router.get("/households/me/inventory-summary", response_model=InventorySummary)
def inventory_summary(home: MyHousehold, db: DB) -> InventorySummary:
    items = list(db.scalars(select(Item).where(Item.household_id == home.id)))
    rooms: dict[int | None, RoomTotal] = {}
    for item in items:
        bucket = rooms.setdefault(
            item.room_id,
            RoomTotal(
                room_id=item.room_id,
                room_name=item.room.name if item.room else "Unassigned",
                item_count=0,
                total_value=Decimal(0),
            ),
        )
        bucket.item_count += 1
        bucket.total_value += item.total_value or 0
    total = sum((i.total_value or Decimal(0) for i in items), Decimal(0))
    insured = home.insured_contents_value
    return InventorySummary(
        item_count=len(items),
        confirmed_count=sum(i.confirmed for i in items),
        unpriced_count=sum(i.unit_price is None for i in items),
        total_value=total,
        insured_contents_value=insured,
        coverage_gap=max(total - insured, Decimal(0)) if insured is not None else None,
        by_room=sorted(rooms.values(), key=lambda r: r.total_value, reverse=True),
    )


@router.get("/media/{media_id}", include_in_schema=False)
def get_media(media_id: int, t: str, db: DB) -> Response:
    """Signed-URL image access, so plain <img> tags work without an Authorization header."""
    media = db.get(Media, media_id)
    if media is None or not media_token_valid(media_id, t):
        raise HTTPException(404, "Not found")
    return Response(media.data, media_type=media.content_type, headers={"Cache-Control": "private, max-age=86400"})
