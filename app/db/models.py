"""SQLAlchemy ORM models mirroring alembic/sql/0001_initial.sql.

Money is NUMERIC(12,2) (Decimal in Python). Never cast to float.
Quantities are Integer. Status columns use the DB enums.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import DECIMAL, Decimal  # noqa: F401  (type hint convenience)
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
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import CIDTYPE, INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin

# Re-export enum names matching the DB types.
SubscriptionStatus = str  # values validated by the DB enum
EstimateStatus = str
InvoiceStatus = str
JobStatus = str
PaymentStatus = str
TokenPurpose = str


class Company(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_account_id: Mapped[Optional[str]] = mapped_column(Text)
    default_currency: Mapped[str] = mapped_column(
        Enum("USD", name="money_currency"), default="USD", server_default="USD"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CIDTYPE, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    full_name: Mapped[Optional[str]] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="technician", server_default="technician")
    mfa_secret_enc: Mapped[Optional[bytes]] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("uq_users_company_email", "company_id", "email", unique=True),)


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
    email: Mapped[Optional[str]] = mapped_column(CIDTYPE)
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


class Vessel(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "vessels"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id")
    )
    name: Mapped[Optional[str]] = mapped_column(Text)
    make: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(Text)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    hull_id: Mapped[Optional[str]] = mapped_column(Text)
    registration: Mapped[Optional[str]] = mapped_column(Text)
    length_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    engine_hours: Mapped[Optional[int]] = mapped_column(Integer)


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
    __tablename__ = "jobs"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id")
    )
    vessel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("vessels.id")
    )
    status: Mapped[str] = mapped_column(
        Enum("scheduled", "in_progress", "on_hold", "completed", "canceled", name="job_status"),
        default="scheduled", server_default="scheduled",
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    technician_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
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
    line_items: Mapped[list["EstimateLineItem"]] = relationship(back_populates="estimate")


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
    estimate: Mapped["Estimate"] = relationship(back_populates="line_items")
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
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (Index("idx_invoices_company_created", "company_id", "created_at"),)


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


class PublicToken(UUIDPKMixin, Base):
    __tablename__ = "public_tokens"
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(
        Enum("estimate_approve", "invoice_pay", "intake_form", "document_upload", name="token_purpose"),
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
