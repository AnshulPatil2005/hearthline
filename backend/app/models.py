"""Core data model. Later weeks add ledger, registry, review and contractor tables."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, LargeBinary, Numeric, String, false
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
    created_at: Mapped[datetime] = mapped_column(default=now)

    members: Mapped[list[User]] = relationship(back_populates="household", foreign_keys="User.household_id")
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
    amount: Mapped[Decimal] = mapped_column(Money)
    fee: Mapped[Decimal | None] = mapped_column(Money)
    payment_method: Mapped[str] = mapped_column(String(20), default="paypal")  # paypal | venmo | paylater
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
    ai_reasoning: Mapped[str] = mapped_column(String(1000), default="")
    ai_confidence: Mapped[float | None]
    candidates_considered: Mapped[int] = mapped_column(default=0)
    payment_rail: Mapped[str] = mapped_column(String(20), default="payouts")  # payouts | vault
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
