"""Semantic validation of a parsed extraction against the catalog and our rules.

Pydantic (schema.py) guarantees the *shape*. This layer checks *meaning*: that
every service code actually exists, and that the follow-up / work-order flags are
internally consistent. A failure here means the output is never saved as a work
order; the orchestrator retries once, then parks the message for review.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.catalog import Catalog
from app.core.schema import ExtractedOrder


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def validate_extraction(order: ExtractedOrder, catalog: Catalog) -> ValidationResult:
    errors: list[str] = []
    valid_codes = catalog.codes()

    for sel in order.services:
        if sel.code not in valid_codes:
            errors.append(f"unknown service code: {sel.code}")
        if not 1 <= sel.quantity <= 10:
            errors.append(f"quantity for {sel.code} out of range (1-10): {sel.quantity}")

    if order.needs_followup and not (order.followup_question or "").strip():
        errors.append("needs_followup is true but followup_question is empty")

    if order.is_work_order:
        # A work order must either have services to price, or be waiting on a
        # follow-up that will produce them. Otherwise there is nothing to do.
        if not order.services and not order.needs_followup:
            errors.append("work order has no services and no pending follow-up")
    else:
        # Not a work order => we should not be inventing services to charge for.
        if order.services:
            errors.append("non-work-order should not carry service selections")

    return ValidationResult(ok=not errors, errors=errors)
