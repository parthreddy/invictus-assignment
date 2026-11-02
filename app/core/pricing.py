"""Deterministic pricing engine.

 This module has no knowledge of the LLM and takes only (code, quantity)
pairs plus the catalog
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.core.catalog import Catalog

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class LineItem:
    code: str
    name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    requires_inspection: bool


@dataclass(frozen=True)
class PricedOrder:
    currency: str
    line_items: tuple[LineItem, ...]
    total: Decimal
    # True if any chosen service needs the bike seen before the price is final.
    # The listed price is still included in the estimate (per the brief).
    estimate_pending_inspection: bool


def price_order(
    selections: Iterable[tuple[str, int]], catalog: Catalog
) -> PricedOrder:
    """Price a list of (service_code, quantity) pairs against the catalog.

    Raises UnknownServiceError if a code is not in the catalog, and ValueError
    for a non-positive quantity. Both are caller bugs or bad model output and
    must fail loudly rather than produce a wrong estimate.
    """
    lines: list[LineItem] = []
    total = Decimal("0")
    pending = False

    for code, quantity in selections:
        if quantity < 1:
            raise ValueError(f"quantity for {code} must be >= 1, got {quantity}")
        svc = catalog.get(code)  # raises UnknownServiceError for bad codes
        subtotal = (svc.price * quantity).quantize(_CENTS)
        total += subtotal
        pending = pending or svc.requires_inspection
        lines.append(
            LineItem(
                code=svc.code,
                name=svc.name,
                quantity=quantity,
                unit_price=svc.price,
                subtotal=subtotal,
                requires_inspection=svc.requires_inspection,
            )
        )

    return PricedOrder(
        currency=catalog.currency,
        line_items=tuple(lines),
        total=total.quantize(_CENTS),
        estimate_pending_inspection=pending,
    )
