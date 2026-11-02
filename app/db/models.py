"""Data model. Every tenant-owned table carries a NOT NULL shop_id and is
protected by a Row-Level Security policy (see rls.sql). The `shop` table itself
is global (used to authenticate an API key -> shop) and is not tenant-scoped.

Idempotency lives in the schema: inbound_message's primary key is
(shop_id, message_id), so a message that arrives twice cannot be inserted twice.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Shop(Base):
    __tablename__ = "shop"
    # A key maps to exactly one shop: no two shops may share an api_key_hash.
    __table_args__ = (UniqueConstraint("api_key_hash", name="uq_shop_api_key_hash"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False)
    # 4dp to match spend_ledger precision -- supports sub-cent caps for demos and
    # avoids a rounding mismatch between the cap and the accumulated spend.
    monthly_cap_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)


class InboundMessage(Base):
    __tablename__ = "inbound_message"

    # Composite PK = the idempotency key. Same message twice -> one row.
    shop_id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class WorkOrder(Base):
    __tablename__ = "work_order"
    # One work order per message: reprocessing a message updates, never duplicates.
    __table_args__ = (
        UniqueConstraint("shop_id", "source_message_id", name="uq_workorder_shop_msg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_message_id: Mapped[str] = mapped_column(String, nullable=False)
    # OPEN | NEEDS_INFO | REJECTED | NEEDS_REVIEW | DEFERRED | INFO_ONLY
    status: Mapped[str] = mapped_column(String, nullable=False)

    bike_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reported_issues: Mapped[list] = mapped_column(JSONB, default=list)
    urgency: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_date: Mapped[date | None] = mapped_column(nullable=True)

    line_items: Mapped[list] = mapped_column(JSONB, default=list)
    estimate_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    estimate_pending_inspection: Mapped[bool] = mapped_column(default=False)
    wrong_shop_suspected: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class Conversation(Base):
    """Follow-up state for one message thread (one open question at a time).

    The customer's reply lives here too, so the whole follow-up exchange -- the
    question we asked and the answer we got -- is visible in a single row rather
    than spread across tables.
    """

    __tablename__ = "conversation"

    shop_id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    # AWAITING_REPLY (question asked) | REPLIED (answer in, pending resume) | DONE
    state: Mapped[str] = mapped_column(String, nullable=False)
    pending_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_field: Mapped[str | None] = mapped_column(String, nullable=True)
    reply_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Outbox(Base):
    """DB-backed job queue. In GCP this role is played by Cloud Tasks."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False)
    job_type: Mapped[str] = mapped_column(String, nullable=False)  # PROCESS | RESUME
    status: Mapped[str] = mapped_column(String, nullable=False, default="QUEUED")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_after: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class SpendLedger(Base):
    """Per-shop, per-month accumulated LLM spend. The spend cap reads this."""

    __tablename__ = "spend_ledger"

    shop_id: Mapped[str] = mapped_column(String, primary_key=True)
    month: Mapped[str] = mapped_column(String, primary_key=True)  # 'YYYY-MM'
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0, nullable=False)


class LlmCall(Base):
    """Audit row for every model call -- feeds the results table + spend ledger."""

    __tablename__ = "llm_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False)  # OK | ERROR | TIMEOUT
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


# Tables that are tenant-scoped and must have RLS enabled.
TENANT_TABLES = [
    InboundMessage.__tablename__,
    WorkOrder.__tablename__,
    Conversation.__tablename__,
    Outbox.__tablename__,
    SpendLedger.__tablename__,
    LlmCall.__tablename__,
]
