"""Core data model. Later weeks add ledger, registry, review and contractor tables."""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, LargeBinary, Numeric, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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
    STORM = "storm"
    TORNADO = "tornado"
    WINTER_STORM = "winter_storm"
    OTHER = "other"


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

    household: Mapped["Household | None"] = relationship(back_populates="members", foreign_keys=[household_id])


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
    # Where it came from: demo (the fictional scenario), fema (a disaster declaration from OpenFEMA) or nws (a National
    # Weather Service warning); external_id is the FEMA declaration code (e.g. DR-4949-WI) or the alert's id.
    source: Mapped[str] = mapped_column(String(20), default="demo", server_default="demo")
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    opened_by: Mapped[str | None] = mapped_column(String(120))  # who opened a real one (the audit log has their id)
    # California Penal Code 396: for 30 days after a declaration, prices of essentials may rise at most 10%.
    # Local governments often extend it; this is the date the protection ends.
    price_protection_until: Mapped[datetime | None]


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
    # PayPal account that receives cash aid (set by Log in with PayPal; seeded for the demo).
    payout_email: Mapped[str | None] = mapped_column(String(255), index=True)
    residence_verified: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )  # proof accepted by a reviewer
    # Plain id (no FK): users already reference households, and the audit log records who vouched.
    vouched_by_user_id: Mapped[int | None]
    vouch_note: Mapped[str | None] = mapped_column(String(500))
    disaster_event_id: Mapped[int | None] = mapped_column(ForeignKey("disaster_events.id"))
    # Damage assessment and needs (from intake or a field visit); the Command Center sorts and groups by these.
    damage_level: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    household_size: Mapped[int] = mapped_column(default=1, server_default="1")
    estimated_loss: Mapped[Decimal | None] = mapped_column(Money)
    needs: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    street: Mapped[str | None] = mapped_column(String(120), index=True)  # derived from address_line
    created_at: Mapped[datetime] = mapped_column(default=now)

    members: Mapped[list[User]] = relationship(back_populates="household", foreign_keys="User.household_id")
    rooms: Mapped[list["Room"]] = relationship(back_populates="household", cascade="all, delete-orphan")
    items: Mapped[list["Item"]] = relationship(back_populates="household", cascade="all, delete-orphan")
    disaster_event: Mapped[DisasterEvent | None] = relationship()

    @validates("address_line")
    def _derive_street(self, _key: str, value: str) -> str:
        self.street = street_of(value)
        return value


def street_of(address_line: str) -> str:
    """'214 Juniper Lane, Apt 2' -> 'Juniper Lane'."""
    first = address_line.split(",")[0].strip()
    return re.sub(r"^\d+[A-Za-z]?\s+", "", first) or first


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
    phash: Mapped[str | None] = mapped_column(String(16), index=True)  # perceptual hash: survives resizing
    # photo | document | site_photo
    kind: Mapped[str] = mapped_column(String(20), default="photo", server_default="photo")
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


class Alert(Base):
    """A hazard alert for a household: from the National Weather Service, or simulated for demos."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # nws | simulated
    external_id: Mapped[str] = mapped_column(String(200))
    event: Mapped[str] = mapped_column(String(120))
    headline: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(4000), default="")
    instruction: Mapped[str] = mapped_column(String(2000), default="")
    effective: Mapped[datetime | None]
    expires: Mapped[datetime | None]
    dismissed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)


class LedgerAccount(Base):
    """Chart of accounts. `code` examples: `assets:paypal`, `liabilities:household:7`, `expenses:paypal_fees`."""

    __tablename__ = "ledger_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # asset | liability | income | expense
    household_id: Mapped[int | None] = mapped_column(ForeignKey("households.id", ondelete="SET NULL"))


class LedgerTransaction(Base):
    """One business event (a donation, a purchase, a payout) as balanced postings."""

    __tablename__ = "ledger_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # donation | purchase | payout | refund | fee | adjustment
    description: Mapped[str] = mapped_column(String(300))
    household_id: Mapped[int | None] = mapped_column(ForeignKey("households.id", ondelete="SET NULL"), index=True)
    paypal_ref: Mapped[str | None] = mapped_column(
        String(80), unique=True
    )  # capture/payout id; makes posting idempotent
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=now)

    postings: Mapped[list["LedgerPosting"]] = relationship(back_populates="transaction", cascade="all, delete-orphan")


class LedgerPosting(Base):
    """Signed amount on one account: positive = debit, negative = credit. Postings of a transaction sum to zero."""

    __tablename__ = "ledger_postings"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("ledger_transactions.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)

    transaction: Mapped[LedgerTransaction] = relationship(back_populates="postings")
    account: Mapped[LedgerAccount] = relationship()


class AuditEvent(Base):
    """Append-only, hash-chained record of every money and review decision."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class WebhookEvent(Base):
    """Every PayPal webhook delivery, stored once (PayPal retries) before it is processed."""

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # PayPal event id
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    resource: Mapped[dict] = mapped_column(JSON)
    verified: Mapped[bool]
    received_at: Mapped[datetime] = mapped_column(default=now)
    processed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(String(500))


class Registry(Base):
    """A household's public Rebuild Registry: specific things donors can pay for."""

    __tablename__ = "registries"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    story: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # pending_review | active | paused | closed
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=now)

    household: Mapped[Household] = relationship()
    items: Mapped[list["RegistryItem"]] = relationship(
        back_populates="rebuild_registry", cascade="all, delete-orphan", order_by="RegistryItem.priority"
    )


class RegistryItem(Base):
    __tablename__ = "registry_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int] = mapped_column(ForeignKey("registries.id", ondelete="CASCADE"), index=True)
    inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(60), default="other")
    quantity: Mapped[int] = mapped_column(default=1)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    priority: Mapped[int] = mapped_column(default=100)  # lower = more urgent
    channel3_product_id: Mapped[str | None] = mapped_column(String(40))
    match_url: Mapped[str | None] = mapped_column(String(600))
    retailer: Mapped[str | None] = mapped_column(String(120))
    funded_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | funded | purchased | delivered
    created_at: Mapped[datetime] = mapped_column(default=now)

    rebuild_registry: Mapped[Registry] = relationship(back_populates="items")

    @property
    def target_amount(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def remaining(self) -> Decimal:
        return max(self.target_amount - self.funded_amount, Decimal("0"))


class Donation(Base):
    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int] = mapped_column(ForeignKey("registries.id", ondelete="CASCADE"), index=True)
    registry_item_id: Mapped[int | None] = mapped_column(ForeignKey("registry_items.id", ondelete="SET NULL"))
    donor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    donor_name: Mapped[str | None] = mapped_column(String(80))  # None = anonymous
    message: Mapped[str] = mapped_column(String(280), default="")
    amount: Mapped[Decimal] = mapped_column(Money)  # US dollars (for another currency: PayPal's conversion)
    fee: Mapped[Decimal | None] = mapped_column(Money)
    payment_method: Mapped[str] = mapped_column(String(20), default="paypal")  # paypal | venmo | paylater
    # A gift from abroad: what the giver paid, in their currency, and PayPal's rate to dollars (set at capture)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    currency_amount: Mapped[Decimal | None] = mapped_column(Money)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    paypal_order_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="created")  # created | captured | refunded | failed
    created_at: Mapped[datetime] = mapped_column(default=now)
    captured_at: Mapped[datetime | None]

    rebuild_registry: Mapped[Registry] = relationship()
    item: Mapped[RegistryItem | None] = relationship()


class Purchase(Base):
    """Something the Shopper agent proposed or bought for a household, with the rule checks it passed."""

    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    registry_item_id: Mapped[int | None] = mapped_column(ForeignKey("registry_items.id", ondelete="SET NULL"))
    channel3_product_id: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    retailer: Mapped[str] = mapped_column(String(120))
    url: Mapped[str | None] = mapped_column(String(600))
    unit_price: Mapped[Decimal] = mapped_column(Money)
    quantity: Mapped[int] = mapped_column(default=1)
    total: Mapped[Decimal] = mapped_column(Money)
    # proposed | awaiting_approval | approved | paid | shipped | delivered | blocked | rejected | failed
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    policy_checks: Mapped[list] = mapped_column(JSON, default=list)
    # Offers the Shopper refused because they were priced more than the gouging limit above their pre-disaster price.
    refused_offers: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # The Shopper's talk with local stores' pricing agents: quotes, a counter-offer, the answer (shown to the family)
    negotiation: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    ai_reasoning: Mapped[str] = mapped_column(String(1000), default="")
    ai_confidence: Mapped[float | None]
    candidates_considered: Mapped[int] = mapped_column(default=0)
    payment_rail: Mapped[str] = mapped_column(String(20), default="payouts")  # payouts | vault
    # Bought from a local business that reopened after the disaster (paid to its PayPal account), not a web store.
    local_business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id", ondelete="SET NULL"))
    paypal_ref: Mapped[str | None] = mapped_column(String(80))
    carrier: Mapped[str | None] = mapped_column(String(40))
    tracking_number: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now)
    paid_at: Mapped[datetime | None]

    registry_item: Mapped[RegistryItem | None] = relationship()
    household: Mapped[Household] = relationship()


class Case(Base):
    """Something a human must approve before money moves: cash aid, a new registry, a contents claim."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # cash_aid | registry_verification | contents_claim
    title: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(1000), default="")
    amount_requested: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    # submitted | in_review | needs_info | escalated | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="in_review")
    risk_score: Mapped[int] = mapped_column(default=0)
    risk_tier: Mapped[str] = mapped_column(String(10), default="low")
    flags: Mapped[list] = mapped_column(JSON, default=list)
    sentinel_summary: Mapped[str] = mapped_column(String(1500), default="")
    sentinel_questions: Mapped[list] = mapped_column(JSON, default=list)
    sentinel_recommendation: Mapped[str | None] = mapped_column(String(20))
    required_reviews: Mapped[int] = mapped_column(default=1)
    video_call_required: Mapped[bool] = mapped_column(default=False)
    random_audit: Mapped[bool] = mapped_column(default=False)
    decision_note: Mapped[str | None] = mapped_column(String(1000))
    paypal_ref: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None]

    household: Mapped[Household] = relationship()
    assignments: Mapped[list["CaseAssignment"]] = relationship(cascade="all, delete-orphan")
    reviews: Mapped[list["CaseReview"]] = relationship(cascade="all, delete-orphan", order_by="CaseReview.id")


class CaseAssignment(Base):
    __tablename__ = "case_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="reviewer")  # reviewer | supervisor | auditor
    assigned_at: Mapped[datetime] = mapped_column(default=now)

    reviewer: Mapped[User] = relationship()


class CaseReview(Base):
    __tablename__ = "case_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="reviewer")
    decision: Mapped[str] = mapped_column(String(20))  # approve | reject | request_info
    reason: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(default=now)

    reviewer: Mapped[User] = relationship()


class Appointment(Base):
    """A video-verification call between a reviewer and a household (shown in Bryntum Calendar)."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | completed | cancelled
    created_at: Mapped[datetime] = mapped_column(default=now)

    case: Mapped[Case] = relationship()
    reviewer: Mapped[User] = relationship()


class Contractor(Base):
    __tablename__ = "contractors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    business_name: Mapped[str] = mapped_column(String(160))
    license_number: Mapped[str] = mapped_column(String(40))
    license_state: Mapped[str] = mapped_column(String(2), default="CA")
    license_verified: Mapped[bool] = mapped_column(default=False)  # a reviewer checked the state license board
    payout_email: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=now)

    user: Mapped[User] = relationship()


class RebuildProject(Base):
    """A contractor job for a household. The full price sits in escrow; milestones release it."""

    __tablename__ = "rebuild_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    contractor_id: Mapped[int] = mapped_column(ForeignKey("contractors.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    # awaiting_plan | plan_submitted | active | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="awaiting_plan")
    total_price: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(default=now)

    household: Mapped[Household] = relationship()
    contractor: Mapped[Contractor] = relationship()
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Milestone.seq"
    )


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("rebuild_projects.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int]
    title: Mapped[str] = mapped_column(String(160))
    done_looks_like: Mapped[str] = mapped_column(String(1000), default="")  # what the Site agent checks photos against
    amount: Mapped[Decimal] = mapped_column(Money)
    is_deposit: Mapped[bool] = mapped_column(default=False)
    start_date: Mapped[datetime]
    end_date: Mapped[datetime]
    # pending | submitted | under_review | paid | disputed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    photo_media_ids: Mapped[list] = mapped_column(JSON, default=list)
    site_check: Mapped[dict | None] = mapped_column(JSON)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    paypal_ref: Mapped[str | None] = mapped_column(String(80))
    submitted_at: Mapped[datetime | None]
    paid_at: Mapped[datetime | None]

    project: Mapped[RebuildProject] = relationship(back_populates="milestones")


class AidBatch(Base):
    """Cash aid to many households in one PayPal Payouts call. One person prepares it; a different
    supervisor or admin must approve it before any money moves."""

    __tablename__ = "aid_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    # awaiting_approval | sent | rejected | failed (PayPal refused; the approver can retry)
    status: Mapped[str] = mapped_column(String(20), default="awaiting_approval")
    rule: Mapped[dict] = mapped_column(JSON, default=dict)  # the filter and amounts it was built from
    total_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(String(500))
    paypal_batch_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None]

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_user_id])
    items: Mapped[list["AidBatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="AidBatchItem.id"
    )


class AidBatchItem(Base):
    __tablename__ = "aid_batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("aid_batches.id", ondelete="CASCADE"), index=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    receiver: Mapped[str] = mapped_column(String(255))  # payout email at the time the batch was built
    # queued | skipped (no longer eligible at approval) | then PayPal's status: PENDING, SUCCESS, UNCLAIMED, ...
    status: Mapped[str] = mapped_column(String(20), default="queued")
    note: Mapped[str | None] = mapped_column(String(200))
    payout_item_id: Mapped[str | None] = mapped_column(String(80))

    batch: Mapped[AidBatch] = relationship(back_populates="items")
    household: Mapped[Household] = relationship()

    @property
    def sender_item_id(self) -> str:
        return f"aidbatch-{self.batch_id}-{self.household_id}"


class Crew(Base):
    """A volunteer crew or vehicle the relief organization dispatches (debris, deliveries, tarps, visits)."""

    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))  # debris | delivery | tarp | cleanup | wellness
    lead_name: Mapped[str] = mapped_column(String(120), default="")
    size: Mapped[int] = mapped_column(default=4)


class CrewJob(Base):
    """One visit to a household, scheduled in Bryntum Scheduler Pro. No crew means not assigned yet."""

    __tablename__ = "crew_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int | None] = mapped_column(ForeignKey("crews.id", ondelete="SET NULL"), index=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # debris_removal | water | food | tarp_roof | cleanup | wellness
    title: Mapped[str] = mapped_column(String(160))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    travel_minutes: Mapped[int] = mapped_column(default=20)  # shown as a buffer before the job
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | done | cancelled
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)

    crew: Mapped[Crew | None] = relationship()
    household: Mapped[Household] = relationship()


class Business(Base):
    """A local business closed by the disaster, raising its Reopen Fund through gift-card pre-sales."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(30), default="other")  # bakery | restaurant | retail | services | other
    address_line: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    lat: Mapped[float | None]
    lng: Mapped[float | None]
    license_number: Mapped[str] = mapped_column(String(40))  # city business license, checked by staff
    story: Mapped[str] = mapped_column(String(2000), default="")
    payout_email: Mapped[str | None] = mapped_column(String(255))
    # pending | verified | rejected. Staff check the license and that the shop is in the disaster area.
    verification: Mapped[str] = mapped_column(String(20), default="pending")
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verification_note: Mapped[str | None] = mapped_column(String(500))
    # The owner's instructions to the store's pricing agent, in their own words (it never goes below an item's floor).
    agent_note: Mapped[str] = mapped_column(String(280), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(default=now)

    owner: Mapped[User] = relationship(foreign_keys=[owner_user_id])
    campaigns: Mapped[list["ReopenCampaign"]] = relationship(back_populates="business", order_by="ReopenCampaign.id")


class ReopenCampaign(Base):
    """Gift cards sold now, redeemable once the business reopens. The money waits in escrow and is
    released in tranches that staff approve; if the business misses its reopen date, buyers are refunded."""

    __tablename__ = "reopen_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    goal_amount: Mapped[Decimal] = mapped_column(Money)
    bonus_percent: Mapped[int] = mapped_column(default=0)  # a $50 card with 20% bonus is worth $60 in the shop
    reopen_by: Mapped[datetime]
    # live | reopened | refunded | closed
    status: Mapped[str] = mapped_column(String(20), default="live")
    raised: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    # "Regulars" pre-pay monthly (PayPal Subscriptions); each payment adds to their gift card.
    regular_monthly: Mapped[Decimal] = mapped_column(Money, default=Decimal("20.00"), server_default="20.00")
    regular_months: Mapped[int] = mapped_column(default=6, server_default="6")
    paypal_plan_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    reopened_at: Mapped[datetime | None]
    refunded_at: Mapped[datetime | None]

    business: Mapped[Business] = relationship(back_populates="campaigns")
    tranches: Mapped[list["ReopenTranche"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="ReopenTranche.seq"
    )
    cards: Mapped[list["GiftCard"]] = relationship(back_populates="campaign", order_by="GiftCard.id")


class ReopenTranche(Base):
    __tablename__ = "reopen_tranches"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("reopen_campaigns.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int]
    title: Mapped[str] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Money)
    start_date: Mapped[datetime]
    end_date: Mapped[datetime]
    # pending | requested | released | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    request_note: Mapped[str | None] = mapped_column(String(500))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    paypal_ref: Mapped[str | None] = mapped_column(String(80))
    released_at: Mapped[datetime | None]

    campaign: Mapped[ReopenCampaign] = relationship(back_populates="tranches")


class GiftCard(Base):
    __tablename__ = "gift_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("reopen_campaigns.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(24), unique=True)  # printed as a QR code; whoever has it can spend it
    buyer_name: Mapped[str | None] = mapped_column(String(120))
    buyer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    amount_paid: Mapped[Decimal] = mapped_column(Money)
    face_value: Mapped[Decimal] = mapped_column(Money)
    balance: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    # pending (checkout not finished) | active | refunded | failed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payment_method: Mapped[str] = mapped_column(String(20), default="paypal")
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(64))
    refunded_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(default=now)
    activated_at: Mapped[datetime | None]

    campaign: Mapped[ReopenCampaign] = relationship(back_populates="cards")
    redemptions: Mapped[list["GiftCardRedemption"]] = relationship(back_populates="card")
    payments: Mapped[list["GiftCardPayment"]] = relationship(order_by="GiftCardPayment.id")


class GiftCardRedemption(Base):
    __tablename__ = "gift_card_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    gift_card_id: Mapped[int] = mapped_column(ForeignKey("gift_cards.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    redeemed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=now)

    card: Mapped[GiftCard] = relationship(back_populates="redemptions")


class PriceWatch(Base):
    """A product or local seller whose price is checked against its price before the disaster."""

    __tablename__ = "price_watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    disaster_event_id: Mapped[int] = mapped_column(ForeignKey("disaster_events.id"), index=True)
    channel3_product_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    seller: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40), default="other")
    source: Mapped[str] = mapped_column(String(20), default="channel3")  # channel3 | local_survey
    url: Mapped[str | None] = mapped_column(String(600))
    baseline_price: Mapped[Decimal | None] = mapped_column(Money)
    current_price: Mapped[Decimal | None] = mapped_column(Money)
    markup_percent: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(20), default="unknown")  # ok | gouging | no_baseline | unknown
    checked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now)

    snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="watch", cascade="all, delete-orphan", order_by="PriceSnapshot.observed_on"
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (UniqueConstraint("watch_id", "observed_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("price_watches.id", ondelete="CASCADE"), index=True)
    observed_on: Mapped[date]
    price: Mapped[Decimal] = mapped_column(Money)

    watch: Mapped[PriceWatch] = relationship(back_populates="snapshots")


class InsurancePolicy(Base):
    """A household's insurance policy PDF and what the Policy agent read in it (the latest upload counts)."""

    __tablename__ = "insurance_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    text: Mapped[str] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=now)


class GiftCardPayment(Base):
    """One payment that added value to a card: a regular's monthly subscription payment (a PayPal sale)."""

    __tablename__ = "gift_card_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    gift_card_id: Mapped[int] = mapped_column(ForeignKey("gift_cards.id", ondelete="CASCADE"), index=True)
    paypal_sale_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    refunded_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(default=now)


class ReopenRegular(Base):
    """A customer who pre-pays a closed business every month through a PayPal subscription."""

    __tablename__ = "reopen_regulars"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("reopen_campaigns.id", ondelete="CASCADE"), index=True)
    gift_card_id: Mapped[int] = mapped_column(ForeignKey("gift_cards.id", ondelete="CASCADE"))
    buyer_name: Mapped[str | None] = mapped_column(String(120))
    buyer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    paypal_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # pending (waiting for approval) | active | cancelled | expired
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=now)
    activated_at: Mapped[datetime | None]

    card: Mapped[GiftCard] = relationship()
    campaign: Mapped[ReopenCampaign] = relationship()


class PaymentDispute(Base):
    """A payer's PayPal dispute about a donation or a gift card. The Funds agent drafts a response from Hearthline's
    records; a staff member decides whether to send evidence or refund."""

    __tablename__ = "payment_disputes"

    id: Mapped[int] = mapped_column(primary_key=True)
    paypal_dispute_id: Mapped[str] = mapped_column(String(64), unique=True)
    reason: Mapped[str] = mapped_column(String(60), default="OTHER")
    # OPEN | WAITING_FOR_SELLER_RESPONSE | WAITING_FOR_BUYER_RESPONSE | UNDER_REVIEW | RESOLVED | OTHER
    status: Mapped[str] = mapped_column(String(40), default="OPEN")
    stage: Mapped[str] = mapped_column(String(30), default="INQUIRY")  # INQUIRY | CHARGEBACK | PRE_ARBITRATION | ...
    amount: Mapped[Decimal] = mapped_column(Money)
    transaction_id: Mapped[str | None] = mapped_column(String(64), index=True)  # the seller transaction (capture/sale)
    payer_message: Mapped[str] = mapped_column(String(2000), default="")
    respond_by: Mapped[datetime | None]
    outcome: Mapped[str | None] = mapped_column(String(60))
    # What PayPal allows now, from the dispute's links: provide_evidence, accept_claim, send_message, ...
    actions: Mapped[list] = mapped_column(JSON, default=list)
    donation_id: Mapped[int | None] = mapped_column(ForeignKey("donations.id", ondelete="SET NULL"))
    gift_card_id: Mapped[int | None] = mapped_column(ForeignKey("gift_cards.id", ondelete="SET NULL"))
    gift_card_payment_id: Mapped[int | None] = mapped_column(ForeignKey("gift_card_payments.id", ondelete="SET NULL"))
    recommendation: Mapped[str | None] = mapped_column(String(20))  # send_evidence | refund
    draft: Mapped[str | None] = mapped_column(Text)  # the response to PayPal; staff edit it before sending
    draft_by_ai: Mapped[bool] = mapped_column(default=False)
    decision: Mapped[str | None] = mapped_column(String(20))  # evidence_sent | message_sent | refunded
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)

    donation: Mapped["Donation | None"] = relationship()
    gift_card: Mapped["GiftCard | None"] = relationship()
    gift_card_payment: Mapped["GiftCardPayment | None"] = relationship()


class PayPalLink(Base):
    """A user's own PayPal account, connected with Log in with PayPal. The money they receive goes there."""

    __tablename__ = "paypal_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    payer_id: Mapped[str] = mapped_column(String(100), index=True)  # Log in with PayPal's user id: 43 characters
    email: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    verified_account: Mapped[bool] = mapped_column(default=False)  # PayPal's own check of the account
    connected_at: Mapped[datetime] = mapped_column(default=now)

    user: Mapped[User] = relationship()


class InsuranceClaim(Base):
    """A contents claim the household sends their insurer: a snapshot of the pre-disaster inventory with the policy's
    limits applied. The insurer's adjuster opens it with a private link, decides the amount and pays it with PayPal;
    Hearthline passes the money straight on to the household's own PayPal account."""

    __tablename__ = "insurance_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("insurance_policies.id", ondelete="SET NULL"))
    token: Mapped[str] = mapped_column(String(40), unique=True)  # the adjuster's link; whoever has it can view and pay
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted | paid
    insurer: Mapped[str] = mapped_column(String(160))
    policy_number: Mapped[str | None] = mapped_column(String(60))
    loss_date: Mapped[date | None]
    items: Mapped[list] = mapped_column(JSON, default=list)  # the inventory as claimed (a snapshot)
    sub_limits: Mapped[list] = mapped_column(JSON, default=list)
    inventory_value: Mapped[Decimal] = mapped_column(Money)
    contents_limit: Mapped[Decimal | None] = mapped_column(Money)
    deductible: Mapped[Decimal | None] = mapped_column(Money)
    estimate: Mapped[Decimal] = mapped_column(Money)  # what the policy's limits suggest; the adjuster decides
    adjuster_name: Mapped[str | None] = mapped_column(String(120))
    adjuster_note: Mapped[str | None] = mapped_column(String(500))
    approved_amount: Mapped[Decimal | None] = mapped_column(Money)
    paypal_order_id: Mapped[str | None] = mapped_column(String(40), index=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(40))
    payout_ref: Mapped[str | None] = mapped_column(String(80))
    payout_status: Mapped[str | None] = mapped_column(String(20))  # sent | held (no account or PayPal refused)
    created_at: Mapped[datetime] = mapped_column(default=now)
    paid_at: Mapped[datetime | None]

    household: Mapped[Household] = relationship()


class LocalOffer(Base):
    """Something a local business sells. The Shopper buys from businesses that are open again before web stores."""

    __tablename__ = "local_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), default="other")
    unit_price: Mapped[Decimal] = mapped_column(Money)
    floor_price: Mapped[Decimal | None] = mapped_column(Money)  # the lowest the store's agent may agree to
    stock: Mapped[int] = mapped_column(default=3, server_default="3")
    available: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=now)

    business: Mapped[Business] = relationship()

    @property
    def floor(self) -> Decimal:
        return min(self.floor_price, self.unit_price) if self.floor_price is not None else self.unit_price


class GivingMandate(Base):
    """A donor's standing instruction: give from their saved PayPal account (PayPal Vault), within these limits, to
    verified families' needs in a disaster. The giving agent chooses among needs that pass the limits; code enforces
    them. Revoking deletes the saved account at PayPal."""

    __tablename__ = "giving_mandates"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | saving | active | paused | revoked
    states: Mapped[list] = mapped_column(JSON, default=list)  # US state codes; empty means anywhere
    categories: Mapped[list] = mapped_column(JSON, default=list)  # registry item categories; empty means any
    per_gift_max: Mapped[Decimal] = mapped_column(Money)
    monthly_max: Mapped[Decimal] = mapped_column(Money)
    note: Mapped[str] = mapped_column(String(280), default="")  # in the donor's words, e.g. "families with kids"
    paypal_setup_token_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    paypal_payment_token_id: Mapped[str | None] = mapped_column(String(64))
    paypal_customer_id: Mapped[str | None] = mapped_column(String(64))
    paypal_email: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=now)
    activated_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    last_run_at: Mapped[datetime | None]

    donor: Mapped[User] = relationship()
    gifts: Mapped[list["MandateGift"]] = relationship(back_populates="mandate", order_by="MandateGift.id.desc()")


class MandateGift(Base):
    """One gift a mandate gave (or tried to). The row is the claim: it is written before PayPal is called, and the
    unique constraints stop the same gift being made twice. `paypal_request_id` is PayPal's dedup key for the order."""

    __tablename__ = "mandate_gifts"
    __table_args__ = (UniqueConstraint("mandate_id", "registry_item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mandate_id: Mapped[int] = mapped_column(ForeignKey("giving_mandates.id", ondelete="CASCADE"), index=True)
    registry_item_id: Mapped[int] = mapped_column(ForeignKey("registry_items.id", ondelete="CASCADE"))
    donation_id: Mapped[int | None] = mapped_column(ForeignKey("donations.id", ondelete="SET NULL"))
    amount: Mapped[Decimal] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(String(500), default="")  # the giving agent's explanation, for the donor
    by_ai: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="claimed")  # claimed | given | failed | checking
    paypal_request_id: Mapped[str] = mapped_column(String(100), unique=True)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=now)
    given_at: Mapped[datetime | None]

    mandate: Mapped[GivingMandate] = relationship(back_populates="gifts")
    item: Mapped["RegistryItem"] = relationship()
    donation: Mapped[Donation | None] = relationship()


class MarketQuote(Base):
    """A local store's pricing agent's quote to the Shopper for one need, and how it ended. The store's agent sets the
    price within its owner's rules (never below the offer's floor); the Shopper may counter once."""

    __tablename__ = "market_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("local_offers.id", ondelete="CASCADE"))
    registry_item_id: Mapped[int | None] = mapped_column(ForeignKey("registry_items.id", ondelete="SET NULL"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id", ondelete="SET NULL"), index=True)
    quantity: Mapped[int] = mapped_column(default=1)
    list_price: Mapped[Decimal] = mapped_column(Money)  # per unit
    unit_price: Mapped[Decimal] = mapped_column(Money)  # the price on the table now
    delivery_days: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(
        String(20), default="quoted"
    )  # quoted | countered | final | accepted | declined
    messages: Mapped[list] = mapped_column(JSON, default=list)  # [{from, text, unit_price}]
    by_ai: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None]

    business: Mapped[Business] = relationship()
    offer: Mapped[LocalOffer] = relationship()


class RapidAidTrigger(Base):
    """An official warning or disaster declaration covering a disaster's zone: the start of first-72-hours aid.
    Households that prepared (verified, with an inventory from before the disaster, a PayPal account) get emergency
    cash in one PayPal Payouts batch once one person approves; Sentinel holds back the risky ones for review."""

    __tablename__ = "rapid_aid_triggers"
    __table_args__ = (UniqueConstraint("disaster_event_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    disaster_event_id: Mapped[int] = mapped_column(ForeignKey("disaster_events.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # nws | declaration | simulated
    external_id: Mapped[str] = mapped_column(String(200))  # the NWS alert id or declaration number
    event: Mapped[str] = mapped_column(String(120))  # e.g. "Evacuation Order", "Fire Management Assistance"
    headline: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(20), default="Severe")
    issued_at: Mapped[datetime] = mapped_column(default=now)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | approved | dismissed
    aid_batch_id: Mapped[int | None] = mapped_column(ForeignKey("aid_batches.id", ondelete="SET NULL"))
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now)

    disaster: Mapped[DisasterEvent] = relationship()
    batch: Mapped[AidBatch | None] = relationship()


class ReadinessGiver(Base):
    """A monthly gift to the readiness fund through PayPal Subscriptions: money that is there before the next disaster,
    so first-72-hours aid can be paid the hour a warning comes. Seeded givers have no PayPal subscription."""

    __tablename__ = "readiness_givers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    monthly: Mapped[Decimal] = mapped_column(Money)
    paypal_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # pending (waiting for the person at PayPal) | active | cancelled | suspended | expired
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=now)
    activated_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]

    payments: Mapped[list["ReadinessPayment"]] = relationship(
        back_populates="giver", cascade="all, delete-orphan", order_by="ReadinessPayment.id"
    )


class ReadinessPayment(Base):
    """One monthly payment PayPal collected for the readiness fund (a subscription sale)."""

    __tablename__ = "readiness_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    giver_id: Mapped[int] = mapped_column(ForeignKey("readiness_givers.id", ondelete="CASCADE"), index=True)
    paypal_sale_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    paid_at: Mapped[datetime] = mapped_column(default=now)

    giver: Mapped[ReadinessGiver] = relationship(back_populates="payments")


class ReadinessPlan(Base):
    """The PayPal billing plan for one monthly amount (made once, then reused)."""

    __tablename__ = "readiness_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    monthly: Mapped[Decimal] = mapped_column(Money, unique=True)
    paypal_plan_id: Mapped[str] = mapped_column(String(64))


class NavigatorCheck(Base):
    """A step only the family can see done (applying to FEMA, an insurance deadline), marked done by them."""

    __tablename__ = "navigator_checks"
    __table_args__ = (UniqueConstraint("household_id", "step_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(String(160))
    done_at: Mapped[datetime] = mapped_column(default=now)


class NavigatorNote(Base):
    """The navigator's explanation of a family's steps, in one language, for one set of facts (asked once)."""

    __tablename__ = "navigator_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"), index=True)
    lang: Mapped[str] = mapped_column(String(5))
    facts_hash: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(default=now)
