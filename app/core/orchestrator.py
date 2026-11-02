"""The processing state machine for one message.

Ties together the pieces, each of which stays independently testable:
  extract (LLM) -> validate -> [follow-up? | price-only? | price it] -> persist.

All work happens inside one tenant_session, so every write is RLS-scoped to the
shop. Money is only ever produced by price_order (code), never by the model.

Outcomes (work_order.status):
  OPEN         valid work order, priced and ready
  NEEDS_INFO   waiting on a follow-up reply (one question asked)
  INFO_ONLY    price question / no repair -> not a real work order
  NEEDS_REVIEW model output failed validation twice, or needs a human
"""
from __future__ import annotations

from datetime import datetime

from app.core.catalog import Catalog, load_catalog
from app.core.pricing import price_order
from app.core.schema import Intent
from app.core.spend import is_over_cap
from app.db import repo
from app.db.engine import tenant_session
from app.llm.client import OpenAIProvider
from app.llm.extractor import ExtractOutcome, extract


def _month() -> str:
    return datetime.now().strftime("%Y-%m")


def process_message(
    shop_id: str,
    message_id: str,
    *,
    provider=None,
    catalog: Catalog | None = None,
    job_type: str = "PROCESS",
) -> str:
    """Process (or resume) one message. Returns the resulting work_order status.

    Transient provider errors (LLMError) are NOT caught here -- they propagate to
    the worker, which backs off and retries the whole job.
    """
    provider = provider or OpenAIProvider()
    catalog = catalog or load_catalog()

    shop = catalog.get_shop(shop_id)
    shop_label = f"{shop.name} ({shop.id})" if shop else shop_id

    with tenant_session(shop_id) as s:
        inbound = repo.get_inbound(s, message_id)
        if inbound is None:
            return "MISSING"

        # Spend cap: check BEFORE the only thing that costs money (the LLM call).
        if is_over_cap(s, shop_id, _month()):
            repo.upsert_work_order(s, shop_id, message_id, status="DEFERRED")
            return "DEFERRED"

        text = _build_context(s, inbound, message_id, job_type)
        outcome = _extract_with_retry(
            s, shop_id, message_id, text, catalog, provider, shop_label
        )

        if outcome.status != "OK":
            repo.upsert_work_order(s, shop_id, message_id, status="NEEDS_REVIEW")
            return "NEEDS_REVIEW"

        order = outcome.order

        # Cancellations are parked for a human, not auto-actioned (see NOT_BUILT).
        if order.intent == Intent.cancellation:
            repo.upsert_work_order(
                s, shop_id, message_id, status="NEEDS_REVIEW", order=order
            )
            return "NEEDS_REVIEW"

        if order.needs_followup:
            repo.open_followup(
                s, shop_id, message_id, order.followup_question, order.followup_field
            )
            repo.upsert_work_order(
                s, shop_id, message_id, status="NEEDS_INFO", order=order
            )
            return "NEEDS_INFO"

        if not order.is_work_order:
            repo.upsert_work_order(
                s, shop_id, message_id, status="INFO_ONLY", order=order
            )
            return "INFO_ONLY"

        # The model picked codes; WE compute the money, from the catalog.
        priced = price_order(
            [(sel.code, sel.quantity) for sel in order.services], catalog
        )
        repo.upsert_work_order(
            s, shop_id, message_id, status="OPEN", order=order, priced=priced
        )
        if job_type == "RESUME":
            repo.close_conversation(s, message_id)
        return "OPEN"


def _build_context(s, inbound, message_id: str, job_type: str) -> str:
    """For a resume, fold the asked question + customer reply into the context."""
    if job_type != "RESUME":
        return inbound.body
    conv = repo.get_conversation(s, message_id)
    if conv and conv.reply_body:
        return (
            f"{inbound.body}\n\n"
            f"[We asked: {conv.pending_question}]\n"
            f"[Customer replied: {conv.reply_body}]"
        )
    return inbound.body


def _extract_with_retry(
    s, shop_id: str, message_id: str, text: str, catalog, provider, shop_label: str
) -> ExtractOutcome:
    """Extract, recording spend each attempt. Retry ONCE on invalid content
    (transient provider errors are raised, not retried here)."""
    month = _month()

    def _attempt() -> ExtractOutcome:
        outcome = extract(text, catalog, provider, shop_label)
        repo.record_llm_call(
            s,
            shop_id,
            message_id,
            provider.model,
            outcome.result.prompt_tokens,
            outcome.result.completion_tokens,
            outcome.result.cost_usd,
            outcome.status,
        )
        repo.add_spend(s, shop_id, outcome.result.cost_usd, month)
        return outcome

    outcome = _attempt()
    if outcome.status == "OK":
        return outcome
    return _attempt()
