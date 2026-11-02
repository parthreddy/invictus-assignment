"""Turns a raw message into a validated ExtractedOrder (or a typed failure).

The model returns JSON (json_object mode); WE validate it against our own Pydantic
schema and then our semantic rules. The provider's output is never trusted as-is
-- this is the "validate every model output; invalid is never saved" gate.

It never raises on bad *content*: it returns status="INVALID" so the orchestrator
can retry once and then park the message. Transient provider errors (timeout /
outage) DO propagate, so the worker can back off and retry the whole job.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.catalog import Catalog
from app.core.schema import ExtractedOrder
from app.core.validator import validate_extraction
from app.llm.client import LLMResult
from app.llm.prompts import build_system_prompt


@dataclass
class ExtractOutcome:
    order: ExtractedOrder | None
    result: LLMResult
    status: str  # "OK" | "INVALID"
    error: str | None = None


def extract(
    message_text: str, catalog: Catalog, provider, shop_label: str = "an unspecified shop"
) -> ExtractOutcome:
    system = build_system_prompt(catalog, shop_label)
    result = provider.complete(system, message_text)  # may raise LLMError (transient)

    # Gate 1: parse to JSON and validate shape against our Pydantic schema.
    try:
        data = json.loads(result.content)
        order = ExtractedOrder.model_validate(data)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        return ExtractOutcome(None, result, "INVALID", f"schema: {exc}")

    # Gate 2: semantic rules the schema can't express (codes exist, consistency).
    semantic = validate_extraction(order, catalog)
    if not semantic.ok:
        return ExtractOutcome(None, result, "INVALID", "; ".join(semantic.errors))

    return ExtractOutcome(order, result, "OK")
