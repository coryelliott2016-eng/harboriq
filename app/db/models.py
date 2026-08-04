"""SQLAlchemy ORM models mirroring alembic/sql/0001_initial.sql.

Money is NUMERIC(12,2) (Decimal in Python). Never cast to float.
Quantities are Integer. Status columns use the DB enums.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin

# Re-export enum names matching the DB types.
SubscriptionStatus = str  # values validated by the DB enum
EstimateStatus = str
InvoiceStatus = str
PaymentStatus = str
TokenPurpose = str


class JobStatus(StrEnum):
    """Mirrors the `job_status` PostgreSQL enum (migration 0001).

    Legal transitions live in `app.services.state_machines.JobSM` — never
    write this column without going through it.
    """

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELED = "canceled"


class MessageSenderType(StrEnum):
    """Mirrors the `message_sender_type` PostgreSQL enum (migration 0008)."""

    CUSTOMER = "customer"
    STAFF = "staff"


class JobPriority(StrEnum):
    """Mirrors the `job_priority` PostgreSQL enum (migration 0003)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class JobLineItemKind(StrEnum):
    """Mirrors the `job_line_item_kind` PostgreSQL enum (migration 0003)."""

    LABOR = "labor"
    PART = "part"
    FEE = "fee"


class UserRole(StrEnum):
    """Mirrors the `user_role` PostgreSQL enum (migration 0002).

    owner      — billing + full control; can create other owners
    admin      — full operational control; can invite non-owner users
    office     — front desk: customers, estimates, invoices
    technician — job execution: jobs, inventory usage
    """

    OWNER = "owner"
    ADMIN = "admin"
    OFFICE = "office"
    TECHNICIAN = "technician"


#: Roles allowed to invite/create other users.
USER_MANAGEMENT_ROLES = frozenset({UserRole.OWNER, UserRole.ADMIN})

#: Roles allowed to create customers/vessels and to create, edit, schedule and
#: assign work orders. `office` is the front desk, which is exactly this job.
OPERATIONS_ROLES = frozenset({UserRole.OWNER, UserRole.ADMIN, UserRole.OFFICE})

#: Roles that may be assigned as a job's technician. Owners and admins are
#: included because in a small yard they do fieldwork themselves; `office` is
#: not, because front-desk staff are not who a work order is dispatched to.
JOB_ASSIGNABLE_ROLES = frozenset({UserRole.TECHNICIAN, UserRole.ADMIN, UserRole.OWNER})


class Company(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_account_id: Mapped[Optional[str]] = mapped_column(Text)
    #: Stripe Connect Standard account id (migration 0007), set once the
    #: tenant completes onboarding via `POST /billing/connect/onboarding-link`.
    #: NULL means "not connected yet" -> checkout/refund flows fall back to
    #: today's single-platform-account behavior (see `stripe_billing.py`).
    #: Distinct from `stripe_account_id` above, which predates this phase and
    #: is unused by any code path.
    stripe_connect_account_id: Mapped[Optional[str]] = mapped_column(Text)
    default_currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    # Shop home-base coordinates (migration 0006) — a distance-scoring
    # fallback for the dispatch engine when a customer has no coordinates yet.
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name="ck_companies_latlng_pair"
        ),
    )


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    full_name: Mapped[Optional[str]] = mapped_column(Text)
    role: Mapped[str] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.TECHNICIAN,
        server_default=UserRole.TECHNICIAN.value,
    )
    mfa_secret_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Account lockout (migration 0005). Mutated only inside `auth_service.login`
    # under the same row lock (`SELECT ... FOR UPDATE`) as the rest of the
    # login transaction — never a separate round-trip.
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Dispatch engine (migration 0006). Free-text skill tags, e.g.
    # {"outboard","electrical","fiberglass"} — matched against a job's
    # `required_skills` for the technician-fit scoring factor. A normalized
    # skills table with per-skill proficiency levels is a natural upgrade once
    # there's a real need to query "who's the best X"; a plain TEXT[] is all
    # this MVP's set-overlap scoring needs.
    skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    #: Where the technician's day starts (the shop, or their home port) —
    #: nullable; the dispatch engine's distance factor degrades to neutral
    #: when unset.
    home_latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    home_longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))

    __table_args__ = (
        Index("uq_users_company_email", "company_id", "email", unique=True),
        # Login resolves by email before any tenant is known, so email must be
        # unique platform-wide (migration 0002).
        Index("uq_users_email_global", "email", unique=True),
        CheckConstraint(
            "(home_latitude IS NULL) = (home_longitude IS NULL)",
            name="ck_users_home_latlng_pair",
        ),
    )


class UserSession(UUIDPKMixin, Base):
    """An issued refresh token. Rotation inserts a new row in the same family."""

    __tablename__ = "user_sessions"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    ip: Mapped[Optional[str]] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_user_sessions_family", "family_id"),
        Index("idx_user_sessions_user", "company_id", "user_id"),
    )


class PasswordResetToken(UUIDPKMixin, Base):
    __tablename__ = "password_reset_tokens"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[Optional[str]] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("idx_password_reset_user", "company_id", "user_id"),)


class SubscriptionPlan(UUIDPKMixin, Base):
    __tablename__ = "subscription_plans"
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    monthly_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    annual_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    seat_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (CheckConstraint("monthly_price >= 0", name="ck_plan_price_gte0"),)


class Subscription(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("trialing", "active", "past_due", "canceled", "paused", name="subscription_status"),
        default="trialing", server_default="trialing",
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(Text)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(Text)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class StripeProcessedEvent(Base):
    __tablename__ = "stripe_processed_events"
    stripe_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id")
    )
    resource_id: Mapped[Optional[str]] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)


class OutboxEvent(UUIDPKMixin if False else Base):  # type: ignore[misc]
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_outbox_pending", "status", "created_at", postgresql_where="status = 'pending'"),
    )


class Customer(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    first_name: Mapped[Optional[str]] = mapped_column(Text)
    last_name: Mapped[Optional[str]] = mapped_column(Text)
    #: Set for a business customer; a private owner has only first/last name.
    company_name: Mapped[Optional[str]] = mapped_column(Text)
    email: Mapped[Optional[str]] = mapped_column(CITEXT)
    phone: Mapped[Optional[str]] = mapped_column(Text)
    sms_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sms_opted_out: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    address_line1: Mapped[Optional[str]] = mapped_column(Text)
    address_line2: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[Optional[str]] = mapped_column(Text)
    postal_code: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Dispatch engine (migration 0006). Geocoding address_line1/city/state/
    # postal_code against a real geocoding API is explicitly out of scope for
    # this phase; these are nullable and mostly NULL for now — the dispatch
    # scorer's distance factor degrades to neutral rather than erroring when
    # unset. A future phase can populate them.
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 6))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "COALESCE(NULLIF(BTRIM(first_name), ''), NULLIF(BTRIM(last_name), ''), "
            "NULLIF(BTRIM(company_name), '')) IS NOT NULL",
            name="ck_customers_has_a_name",
        ),
        Index("idx_customers_company_name", "company_id", "last_name", "first_name"),
        Index(
            "idx_customers_company_email",
            "company_id",
            "email",
            postgresql_where="email IS NOT NULL",
        ),
        CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)", name="ck_customers_latlng_pair"
        ),
    )


class Vessel(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "vessels"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # The real constraint is the composite FK (company_id, customer_id) ->
    # customers(company_id, id) from migration 0003, which makes a cross-tenant
    # reference unrepresentable. Declared here for ORM relationship resolution.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(Text)
    make: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    #: Hull Identification Number — unique per hull, so unique per tenant.
    hull_id: Mapped[Optional[str]] = mapped_column(Text)
    registration: Mapped[Optional[str]] = mapped_column(Text)
    length_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    beam_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    draft_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    engine_make: Mapped[Optional[str]] = mapped_column(Text)
    engine_model: Mapped[Optional[str]] = mapped_column(Text)
    engine_hours: Mapped[Optional[int]] = mapped_column(Integer)
    engine_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    storage_location: Mapped[Optional[str]] = mapped_column(Text)
    slip_number: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("year IS NULL OR year BETWEEN 1850 AND 2200", name="ck_vessels_year"),
        CheckConstraint("length_ft IS NULL OR length_ft > 0", name="ck_vessels_length"),
        CheckConstraint("beam_ft IS NULL OR beam_ft > 0", name="ck_vessels_beam"),
        CheckConstraint("draft_ft IS NULL OR draft_ft > 0", name="ck_vessels_draft"),
        CheckConstraint(
            "engine_hours IS NULL OR engine_hours >= 0", name="ck_vessels_engine_hours"
        ),
        CheckConstraint("engine_count >= 0", name="ck_vessels_engine_count"),
        Index("idx_vessels_company_customer", "company_id", "customer_id"),
        Index(
            "uq_vessels_company_hull_id",
            "company_id",
            "hull_id",
            unique=True,
            postgresql_where="hull_id IS NOT NULL",
        ),
    )


class InventoryItem(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "inventory_items"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    sku: Mapped[Optional[str]] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    retail_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reorder_point: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    low_stock_alerted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    __table_args__ = (
        CheckConstraint("unit_cost >= 0", name="ck_inv_unit_cost_gte0"),
        CheckConstraint("retail_price >= 0", name="ck_inv_retail_gte0"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inv_qty_gte0"),
        Index("idx_inventory_company_sku", "company_id", "sku"),
    )


class Job(UUIDPKMixin, TimestampMixin, Base):
    """A work order.

    `status` is driven exclusively by `app.services.state_machines.JobSM`; the
    service layer loads the current value under `FOR UPDATE` before asserting a
    transition, so two concurrent updates cannot both pass the same check.
    """

    __tablename__ = "jobs"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # As with Vessel, the enforced constraints are the composite (company_id, *)
    # FKs added in migration 0003.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    vessel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("vessels.id")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(
            JobStatus, name="job_status", values_callable=lambda e: [m.value for m in e]
        ),
        default=JobStatus.SCHEDULED, server_default=JobStatus.SCHEDULED.value,
    )
    priority: Mapped[str] = mapped_column(
        Enum(
            JobPriority,
            name="job_priority",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=JobPriority.NORMAL, server_default=JobPriority.NORMAL.value,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    technician_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    hold_reason: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Dispatch engine (migration 0006). Free-text skill tags this job needs,
    # matched against a candidate technician's `users.skills`.
    required_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    #: The scorer's last computed, technician-independent score (urgency +
    #: revenue + customer value) and an explainable per-factor breakdown,
    #: cached so the intake queue/schedule board does not recompute it on
    #: every page load. See `app.services.dispatch.recompute_and_cache_score`.
    dispatch_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    dispatch_score_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB)
    dispatch_scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    line_items: Mapped[list[JobLineItem]] = relationship(back_populates="job")

    __table_args__ = (
        CheckConstraint("BTRIM(title) <> ''", name="ck_jobs_title_not_blank"),
        CheckConstraint(
            "scheduled_end_at IS NULL OR scheduled_at IS NULL "
            "OR scheduled_end_at >= scheduled_at",
            name="ck_jobs_schedule_window",
        ),
        Index(
            "idx_jobs_company_technician_scheduled",
            "company_id", "technician_id", "scheduled_at",
        ),
        Index(
            "idx_jobs_company_status_scheduled", "company_id", "status", "scheduled_at"
        ),
        Index("idx_jobs_company_customer", "company_id", "customer_id"),
        Index(
            "idx_jobs_company_vessel",
            "company_id",
            "vessel_id",
            postgresql_where="vessel_id IS NOT NULL",
        ),
    )


class JobLineItem(UUIDPKMixin, TimestampMixin, Base):
    """Billable labor/part/fee on a work order — the invoicing phase's input.

    `quantity` is NUMERIC rather than estimate_line_items' INTEGER because labor
    is billed in fractional hours. `invoice_id`/`invoiced_at` are reserved for
    invoicing and are not written yet.
    """

    __tablename__ = "job_line_items"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        Enum(
            JobLineItemKind,
            name="job_line_item_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    inventory_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inventory_items.id")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    taxable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: True once stock was actually deducted via POST /api/v1/inventory/use.
    inventory_committed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # The real constraint is the composite FK (company_id, invoice_id) ->
    # invoices(company_id, id) from migration 0003/0004, which makes a
    # cross-tenant reference unrepresentable. Declared here for ORM parity.
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoices.id")
    )
    invoiced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    job: Mapped[Job] = relationship(back_populates="line_items")
    # line_total is GENERATED ALWAYS AS (quantity * unit_price) STORED in the DB.

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_job_line_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_job_line_items_unit_price"),
        CheckConstraint("BTRIM(description) <> ''", name="ck_job_line_items_description"),
        CheckConstraint(
            "inventory_item_id IS NULL OR kind = 'part'",
            name="ck_job_line_items_stock_is_a_part",
        ),
        CheckConstraint(
            "inventory_committed = false OR inventory_item_id IS NOT NULL",
            name="ck_job_line_items_committed_has_stock",
        ),
        CheckConstraint(
            "(invoice_id IS NULL) = (invoiced_at IS NULL)",
            name="ck_job_line_items_invoiced_together",
        ),
        Index("idx_job_line_items_job", "company_id", "job_id"),
        Index(
            "idx_job_line_items_uninvoiced",
            "company_id",
            "job_id",
            postgresql_where="invoice_id IS NULL",
        ),
    )


class Estimate(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "estimates"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("jobs.id")
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id")
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "draft", "sent", "viewed", "approved", "declined", "expired", "invoiced",
            name="estimate_status",
        ),
        default="draft", server_default="draft",
    )
    currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    balance_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_ip: Mapped[Optional[str]] = mapped_column(INET)
    approved_user_agent: Mapped[Optional[str]] = mapped_column(Text)
    estimate_pdf_version: Mapped[Optional[str]] = mapped_column(Text)
    line_items: Mapped[list[EstimateLineItem]] = relationship(back_populates="estimate")


class EstimateLineItem(UUIDPKMixin, Base):
    __tablename__ = "estimate_line_items"
    estimate_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("estimates.id"), nullable=False
    )
    inventory_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inventory_items.id")
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer, CheckConstraint("quantity > 0"))
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), CheckConstraint("unit_price >= 0"), default=0, server_default="0"
    )
    estimate: Mapped[Estimate] = relationship(back_populates="line_items")
    # line_total is GENERATED ALWAYS AS (quantity * unit_price) STORED in the DB.


class Invoice(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "invoices"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    estimate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("estimates.id")
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id")
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "draft", "sent", "partial", "paid", "void", "uncollectible",
            "refunded", "partially_refunded", name="invoice_status",
        ),
        default="draft", server_default="draft",
    )
    currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    balance_due: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    #: Applied to taxable line subtotal only; 0..1 (e.g. 0.07 == 7%).
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=0, server_default="0"
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(Text)
    stripe_checkout_session_id: Mapped[Optional[str]] = mapped_column(Text)
    #: Dunning cadence (migration 0007) — NULL means "never reminded yet".
    #: Set by `app/jobs/dunning_sweep.py` each time it queues a reminder, so
    #: the sweep can skip invoices reminded within the cadence window.
    last_reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_invoices_company_created", "company_id", "created_at"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 1", name="ck_invoices_tax_rate"),
        CheckConstraint("amount_paid <= total", name="ck_invoices_amount_paid_lte_total"),
    )


class Payment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoices.id")
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "succeeded", "failed", "refunded", "partially_refunded", name="payment_status"),
        default="pending", server_default="pending",
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), CheckConstraint("amount >= 0"))
    currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    stripe_charge_id: Mapped[Optional[str]] = mapped_column(Text)
    stripe_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))


class Refund(UUIDPKMixin, Base):
    """A Stripe refund (full or partial) applied to an invoice (migration
    0007). Distinct from `Payment`: `payments` records money coming IN,
    `refunds` records money going back OUT, keyed by `stripe_refund_id` for
    idempotency/audit rather than reusing a `payments` row with a negative
    amount."""

    __tablename__ = "refunds"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), CheckConstraint("amount > 0"))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    stripe_refund_id: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_refunds_company_invoice", "company_id", "invoice_id"),
        Index("idx_refunds_company_created", "company_id", "created_at"),
    )


class PublicToken(UUIDPKMixin, Base):
    __tablename__ = "public_tokens"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(
        Enum(
            "estimate_approve",
            "invoice_pay",
            "intake_form",
            "document_upload",
            "user_invite",
            #: Phase 9 — a durable, revocable customer-portal magic link.
            #: `resource_type="customer"`, long TTL (see
            #: `app.services.portal.PORTAL_TOKEN_TTL_HOURS`), effectively-
            #: unlimited `max_uses` within that window; renewed by issuing a
            #: fresh one (`POST /customers/{id}/portal-invite`) rather than
            #: mutating the existing row.
            "portal",
            name="token_purpose",
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(UUIDPKMixin, Base):
    """A customer<->staff message (migration 0008).

    `job_id` is nullable: a message can be a general portal message or tied
    to a specific job. `sender_user_id` is only set for `sender_type=staff`
    (see `ck_messages_staff_has_sender`) -- a customer sends through their
    magic-link portal session, not a `users` row.
    """

    __tablename__ = "messages"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # The real constraint is the composite FK (company_id, customer_id) ->
    # customers(company_id, id) from migration 0008, matching every other
    # customer-referencing table since 0003.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("jobs.id")
    )
    sender_type: Mapped[str] = mapped_column(
        Enum(
            MessageSenderType,
            name="message_sender_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    sender_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("BTRIM(body) <> ''", name="ck_messages_body_not_blank"),
        CheckConstraint(
            "sender_type != 'staff' OR sender_user_id IS NOT NULL",
            name="ck_messages_staff_has_sender",
        ),
        Index("idx_messages_company_customer", "company_id", "customer_id", "created_at"),
        Index(
            "idx_messages_company_job",
            "company_id",
            "job_id",
            "created_at",
            postgresql_where="job_id IS NOT NULL",
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    actor_ip: Mapped[Optional[str]] = mapped_column(INET)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(Text)
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
