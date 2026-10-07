"""Core data model. Later weeks add ledger, registry, review and contractor tables."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, LargeBinary, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(12, 2)


def now() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    HOUSEHOLD = "household"
    DONOR = "donor"
    CONTRACTOR = "contractor"
    REVIEWER = "reviewer"
    SUPERVISOR = "supervisor"
    ORG_ADMIN = "org_admin"
    BUSINESS = "business"


class DisasterKind(StrEnum):
    WILDFIRE = "wildfire"
    FLOOD = "flood"
    HURRICANE = "hurricane"
    EARTHQUAKE = "earthquake"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class EvidenceLevel(StrEnum):
    """How strongly an item's existence is proven, strongest first."""

    PRE_DISASTER_SCAN = "pre_disaster_scan"
    PHOTO = "photo"
    RECEIPT = "receipt"
    MEMORY = "memory"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(200))  # one-line description shown on persona cards
    locale: Mapped[str] = mapped_column(String(10), default="en")
    is_demo: Mapped[bool] = mapped_column(default=False)
    household_id: Mapped[int | None] = mapped_column(ForeignKey("households.id"))
    created_at: Mapped[datetime] = mapped_column(default=now)

    household: Mapped["Household | None"] = relationship(back_populates="members")


class DisasterEvent(Base):
    __tablename__ = "disaster_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[DisasterKind] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="active")
    declared_at: Mapped[datetime] = mapped_column(default=now)
    # GeoJSON Polygon or MultiPolygon geometry of the affected area.
    zone: Mapped[dict] = mapped_column(JSON)
    is_fictional: Mapped[bool] = mapped_column(default=False)


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address_line: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    postal_code: Mapped[str] = mapped_column(String(10))
    lat: Mapped[float | None]
    lng: Mapped[float | None]
    insured_contents_value: Mapped[Decimal | None] = mapped_column(Money)
    verification_level: Mapped[int] = mapped_column(default=0)
    disaster_event_id: Mapped[int | None] = mapped_column(ForeignKey("disaster_events.id"))
    created_at: Mapped[datetime] = mapped_column(default=now)

    members: Mapped[list[User]] = relationship(back_populates="household")
    rooms: Mapped[list["Room"]] = relationship(back_populates="household", cascade="all, delete-orphan")
    items: Mapped[list["Item"]] = relationship(back_populates="household", cascade="all, delete-orphan")
    disaster_event: Mapped[DisasterEvent | None] = relationship()


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))

    household: Mapped[Household] = relationship(back_populates="rooms")


class Media(Base):
    """An uploaded photo or a frame extracted from a walkthrough video.

    Stored in the database while Hearthline runs on free hosting (no object storage)."""

    __tablename__ = "media"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"))
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    content_type: Mapped[str] = mapped_column(String(40))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    width: Mapped[int]
    height: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    captured_at: Mapped[datetime | None]
    uploaded_at: Mapped[datetime] = mapped_column(default=now)


class Scan(Base):
    """One batch of photos for a room, turned into items by the Inventory and Valuation agents."""

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    status: Mapped[ScanStatus] = mapped_column(String(20), default=ScanStatus.QUEUED)
    error: Mapped[str | None] = mapped_column(String(500))
    ai_model: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]

    media: Mapped[list[Media]] = relationship()
    household: Mapped[Household] = relationship()
    room: Mapped[Room] = relationship()


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"))
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))
    media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))

    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), default="other")
    quantity: Mapped[int] = mapped_column(default=1)
    brand: Mapped[str | None] = mapped_column(String(80))
    condition: Mapped[str | None] = mapped_column(String(40))
    ai_confidence: Mapped[float | None]
    search_query: Mapped[str | None] = mapped_column(String(200))

    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    price_low: Mapped[Decimal | None] = mapped_column(Money)  # range across the offers considered
    price_high: Mapped[Decimal | None] = mapped_column(Money)
    price_source: Mapped[str | None] = mapped_column(String(20))  # channel3 | user
    channel3_product_id: Mapped[str | None] = mapped_column(String(40))
    match_title: Mapped[str | None] = mapped_column(String(300))
    match_url: Mapped[str | None] = mapped_column(String(600))
    retailer: Mapped[str | None] = mapped_column(String(120))
    offers_considered: Mapped[int] = mapped_column(default=0)

    evidence_level: Mapped[EvidenceLevel] = mapped_column(String(30), default=EvidenceLevel.PHOTO)
    confirmed: Mapped[bool] = mapped_column(default=False)
    user_edited: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)

    household: Mapped[Household] = relationship(back_populates="items")
    room: Mapped[Room | None] = relationship()

    @property
    def total_value(self) -> Decimal | None:
        return self.unit_price * self.quantity if self.unit_price is not None else None
