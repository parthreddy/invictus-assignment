"""Repository: the single place that reads/writes tenant data.

Every function takes an already-tenant-scoped Session (from tenant_session), so it
never has to be told the shop_id a second time -- the DB session already knows it,
and RLS enforces it. This is deliberate: callers cannot accidentally query the
wrong tenant because they never pass a shop_id to a query here.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    Conversation,
    InboundMessage,
    LlmCall,
    Outbox,
    SpendLedger,
    WorkOrder,
)

OPEN_STATUSES = ("OPEN", "NEEDS_INFO")


def record_inbound(
    session: Session,
    shop_id: str,
    message_id: str,
    channel: str,
    body: str,
    received_at: datetime,
) -> bool:
    """Insert an inbound message idempotently.

    Returns True if this is the first time we have seen (shop_id, message_id),
    False if it is a duplicate. The duplicate check is the composite PK, so a
    message arriving twice can never create two work orders.
    """
    stmt = (
        pg_insert(InboundMessage)
        .values(
            shop_id=shop_id,
            message_id=message_id,
            channel=channel,
            body=body,
            received_at=received_at,
        )
        .on_conflict_do_nothing(index_elements=["shop_id", "message_id"])
        .returning(InboundMessage.message_id)
    )
    # RETURNING yields a row only when a row was actually inserted; on a duplicate
    # the ON CONFLICT DO NOTHING suppresses it and nothing comes back.
    return session.execute(stmt).first() is not None


def enqueue(session: Session, shop_id: str, message_id: str, job_type: str) -> None:
    session.add(Outbox(shop_id=shop_id, message_id=message_id, job_type=job_type))


def open_followup(
    session: Session, shop_id: str, message_id: str, question: str, field: str | None
) -> None:
    """Record (or replace) the single open follow-up question for a message."""
    stmt = (
        pg_insert(Conversation)
        .values(
            shop_id=shop_id,
            message_id=message_id,
            state="AWAITING_REPLY",
            pending_question=question,
            question_field=field,
            reply_body=None,
        )
        .on_conflict_do_update(
            index_elements=["shop_id", "message_id"],
            set_={
                "state": "AWAITING_REPLY",
                "pending_question": question,
                "question_field": field,
                "reply_body": None,
            },
        )
    )
    session.execute(stmt)


def record_reply(session: Session, shop_id: str, message_id: str, body: str) -> None:
    """Attach the customer's answer to the open follow-up for this message.

    Upserts so a reply is captured even if the conversation row is missing (e.g. a
    reply that arrives before the question was persisted). The whole exchange --
    question asked and answer given -- then lives in one conversation row.
    """
    stmt = (
        pg_insert(Conversation)
        .values(
            shop_id=shop_id,
            message_id=message_id,
            state="REPLIED",
            reply_body=body,
        )
        .on_conflict_do_update(
            index_elements=["shop_id", "message_id"],
            set_={"state": "REPLIED", "reply_body": body},
        )
    )
    session.execute(stmt)


def get_conversation(session: Session, message_id: str) -> Conversation | None:
    # No shop_id in the filter -- RLS scopes it to the session's tenant already.
    stmt = select(Conversation).where(Conversation.message_id == message_id)
    return session.execute(stmt).scalars().first()


def close_conversation(session: Session, message_id: str) -> None:
    conv = get_conversation(session, message_id)
    if conv is not None:
        conv.state = "DONE"


def get_inbound(session: Session, message_id: str) -> InboundMessage | None:
    stmt = select(InboundMessage).where(InboundMessage.message_id == message_id)
    return session.execute(stmt).scalars().first()


def record_llm_call(
    session: Session,
    shop_id: str,
    message_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: Decimal,
    status: str,
) -> None:
    session.add(
        LlmCall(
            shop_id=shop_id,
            message_id=message_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            status=status,
        )
    )


def add_spend(session: Session, shop_id: str, cost_usd: Decimal, month: str) -> None:
    """Accumulate a shop's spend for the given month ('YYYY-MM'). Upsert + add."""
    stmt = (
        pg_insert(SpendLedger)
        .values(shop_id=shop_id, month=month, spent_usd=cost_usd)
        .on_conflict_do_update(
            index_elements=["shop_id", "month"],
            set_={"spent_usd": SpendLedger.spent_usd + cost_usd},
        )
    )
    session.execute(stmt)


def upsert_work_order(
    session: Session,
    shop_id: str,
    message_id: str,
    status: str,
    *,
    order=None,
    priced=None,
) -> None:
    """Create or update the single work order for a message (idempotent on
    (shop_id, source_message_id)). `order` is an ExtractedOrder or None; `priced`
    is a PricedOrder or None. Money comes only from `priced` (computed in code)."""
    values: dict = {
        "shop_id": shop_id,
        "source_message_id": message_id,
        "status": status,
        "bike_type": order.bike_type if order else None,
        "reported_issues": list(order.reported_issues) if order else [],
        "urgency": order.urgency.value if order and order.urgency else None,
        "requested_date": _parse_date(order.requested_date) if order else None,
        "wrong_shop_suspected": bool(order.wrong_shop_suspected) if order else False,
        "line_items": _serialize_lines(priced),
        "estimate_total": priced.total if priced else Decimal("0"),
        "estimate_pending_inspection": (
            priced.estimate_pending_inspection if priced else False
        ),
    }
    update_cols = {k: v for k, v in values.items() if k not in ("shop_id", "source_message_id")}
    stmt = (
        pg_insert(WorkOrder)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_workorder_shop_msg", set_=update_cols
        )
    )
    session.execute(stmt)


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _serialize_lines(priced) -> list[dict]:
    if priced is None:
        return []
    # Money stored as strings in JSONB so Decimal precision survives round-trips.
    return [
        {
            "code": li.code,
            "name": li.name,
            "quantity": li.quantity,
            "unit_price": str(li.unit_price),
            "subtotal": str(li.subtotal),
            "requires_inspection": li.requires_inspection,
        }
        for li in priced.line_items
    ]


def add_work_order(session: Session, **fields) -> WorkOrder:
    wo = WorkOrder(**fields)
    session.add(wo)
    session.flush()
    return wo


def list_work_orders(session: Session, statuses=OPEN_STATUSES) -> list[WorkOrder]:
    """List this shop's work orders. No shop_id filter needed -- RLS applies it."""
    stmt = select(WorkOrder).where(WorkOrder.status.in_(statuses))
    return list(session.execute(stmt).scalars())


def get_work_order(session: Session, message_id: str) -> WorkOrder | None:
    stmt = select(WorkOrder).where(WorkOrder.source_message_id == message_id)
    return session.execute(stmt).scalars().first()


def get_cap(session: Session, shop_id: str) -> Decimal | None:
    """This shop's monthly LLM spend cap, from the global shop table."""
    row = session.execute(
        text("SELECT monthly_cap_usd FROM shop WHERE id = :id"), {"id": shop_id}
    ).first()
    return Decimal(str(row[0])) if row else None


def current_month_spend(session: Session, shop_id: str, month: str) -> Decimal:
    """How much this shop has spent on the LLM in the given month ('YYYY-MM')."""
    total = session.execute(
        select(func.coalesce(func.sum(SpendLedger.spent_usd), 0)).where(
            SpendLedger.month == month
        )
    ).scalar_one()
    return Decimal(str(total))


def list_all_work_orders_unscoped_for_test(session: Session) -> list[WorkOrder]:
    """A deliberately naive 'SELECT * FROM work_order' with NO shop filter.

    Used only by the tenancy test to prove that even a query that forgets to
    filter by shop still returns only the current tenant's rows, because RLS
    enforces isolation at the data layer.
    """
    return list(session.execute(select(WorkOrder)).scalars())
