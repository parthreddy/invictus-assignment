"""Customer-facing HTTP surface.

Design rule: this layer NEVER calls the LLM and NEVER computes prices. It
validates the envelope, records the message idempotently, enqueues work, and
returns fast (202). The slow/failable work happens in the worker. That boundary is
why a provider outage can never hang or fail an inbound request.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from app.auth import require_shop
from app.db import repo
from app.db.engine import tenant_session

app = FastAPI(title="Riverbend Intake", version="0.1.0")


class InboundPayload(BaseModel):
    message_id: str = Field(min_length=1)
    channel: str = "web"
    body: str = Field(min_length=1)
    received_at: datetime | None = None


class ReplyPayload(BaseModel):
    message_id: str = Field(min_length=1)  # the original message being replied to
    body: str = Field(min_length=1)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/messages", status_code=202)
def ingest(payload: InboundPayload, shop_id: str = Depends(require_shop)):
    """Accept an inbound message. Idempotent on (shop_id, message_id): a duplicate
    returns the same 202 and creates no second work order."""
    received = payload.received_at or datetime.now()
    with tenant_session(shop_id) as s:
        is_new = repo.record_inbound(
            s, shop_id, payload.message_id, payload.channel, payload.body, received
        )
        if is_new:
            repo.enqueue(s, shop_id, payload.message_id, "PROCESS")

    return {
        "shop_id": shop_id,
        "message_id": payload.message_id,
        "status": "accepted" if is_new else "duplicate",
        # What the customer sees at submit -- identical whether or not the LLM is
        # healthy or the shop is at its cap. The request path never blocks on either.
        "message": "Thanks! We've received your message and will send your work order shortly.",
    }


@app.post("/v1/replies", status_code=202)
def reply(payload: ReplyPayload, shop_id: str = Depends(require_shop)):
    """Customer answer to a follow-up question. Records it and enqueues a RESUME.
    (Resume processing is implemented with the follow-up loop; see orchestrator.)"""
    with tenant_session(shop_id) as s:
        repo.record_reply(s, shop_id, payload.message_id, payload.body)
        repo.enqueue(s, shop_id, payload.message_id, "RESUME")
    return {"shop_id": shop_id, "message_id": payload.message_id, "status": "accepted"}


@app.get("/v1/work-orders")
def work_orders(status: str | None = None, shop_id: str = Depends(require_shop)):
    """List this shop's work orders with an estimated total. RLS guarantees only
    this shop's rows are visible.

    Defaults to the open queue (OPEN + NEEDS_INFO). Pass ?status=DEFERRED,NEEDS_REVIEW
    to see the deferred / needs-attention queues (spend cap and outage fallout)."""
    statuses = tuple(s.strip() for s in status.split(",")) if status else repo.OPEN_STATUSES
    with tenant_session(shop_id) as s:
        orders = repo.list_work_orders(s, statuses)
        items = [_serialize(w) for w in orders]
        total = sum((w.estimate_total or Decimal("0")) for w in orders)

    return {
        "shop_id": shop_id,
        "statuses": list(statuses),
        "count": len(items),
        "estimated_total": f"{Decimal(total):.2f}",
        "currency": "USD",
        "work_orders": items,
    }


# Customer-facing message per processing state (what the customer would be told).
_CUSTOMER_MESSAGE = {
    "OPEN": "Your work order is ready. See the estimated total.",
    "NEEDS_INFO": "We need one detail to finish your work order.",
    "INFO_ONLY": "Thanks for your question -- a team member will reply.",
    "DEFERRED": "We've received your message; a team member will follow up with you shortly.",
    "NEEDS_REVIEW": "We've received your message; a team member will follow up with you shortly.",
}


@app.get("/v1/messages/{message_id}")
def message_status(message_id: str, shop_id: str = Depends(require_shop)):
    """Status of one message -- what the customer would see as it's processed.

    Covers the degraded cases too: DEFERRED (spend cap) and NEEDS_REVIEW (provider
    outage) both map to a graceful 'a team member will follow up' message."""
    with tenant_session(shop_id) as s:
        wo = repo.get_work_order(s, message_id)
        conv = repo.get_conversation(s, message_id)
        if wo is None:
            # Accepted but not yet processed (e.g. still queued / provider retrying).
            return {"message_id": message_id, "status": "PROCESSING",
                    "customer_message": "We've received your message and are preparing your work order."}
        customer_message = _CUSTOMER_MESSAGE.get(wo.status, "We've received your message.")
        if wo.status == "NEEDS_INFO" and conv and conv.pending_question:
            customer_message = conv.pending_question
        return {
            "message_id": message_id,
            "status": wo.status,
            "customer_message": customer_message,
            "estimate_total": f"{(wo.estimate_total or Decimal('0')):.2f}",
        }


def _serialize(w) -> dict:
    return {
        "id": w.id,
        "source_message_id": w.source_message_id,
        "status": w.status,
        "bike_type": w.bike_type,
        "reported_issues": w.reported_issues,
        "urgency": w.urgency,
        "requested_date": w.requested_date.isoformat() if w.requested_date else None,
        "line_items": w.line_items,
        "estimate_total": f"{(w.estimate_total or Decimal('0')):.2f}",
        "estimate_pending_inspection": w.estimate_pending_inspection,
        "wrong_shop_suspected": w.wrong_shop_suspected,
    }
