"""Pricing is money, computed in code -> highest-risk, highest-certainty module.

We test: exact Decimal arithmetic (no float drift), per-wheel/multi-bike
quantities, multi-service sums, the requires_inspection flag, and that bad input
fails loudly instead of producing a wrong estimate.
"""
from decimal import Decimal

import pytest

from app.core.catalog import UnknownServiceError
from app.core.pricing import price_order


def test_single_service_total(catalog):
    order = price_order([("TUNE_BASIC", 1)], catalog)
    assert order.total == Decimal("65.00")
    assert order.currency == "USD"
    assert order.estimate_pending_inspection is False


def test_per_wheel_quantity_multiplies(catalog):
    # Brake pad replacement is priced per wheel: 2 wheels = 2 x 35.00
    order = price_order([("BRAKE_PADS", 2)], catalog)
    assert order.total == Decimal("70.00")
    assert order.line_items[0].quantity == 2
    assert order.line_items[0].unit_price == Decimal("35.00")


def test_multi_service_sum(catalog):
    # Sample #5: rear brake squeal + gears skip -> brake adjust + gear adjust
    order = price_order([("BRAKE_ADJUST", 1), ("GEAR_ADJUST", 1)], catalog)
    assert order.total == Decimal("43.00")  # 18.00 + 25.00
    assert len(order.line_items) == 2


def test_two_bikes_quantity(catalog):
    # Sample #40: basic tune-up for two bikes
    order = price_order([("TUNE_BASIC", 2)], catalog)
    assert order.total == Decimal("130.00")


def test_requires_inspection_flag_but_price_still_included(catalog):
    # E-bike diagnostic requires inspection; price is still part of the estimate.
    order = price_order([("EBIKE_DIAG", 1)], catalog)
    assert order.total == Decimal("60.00")
    assert order.estimate_pending_inspection is True


def test_no_float_drift(catalog):
    # 18.00*1 + 35.00*2 + 40.00*2 = 18 + 70 + 80 = 168.00 exactly
    order = price_order(
        [("BRAKE_ADJUST", 1), ("BRAKE_PADS", 2), ("BRAKE_BLEED", 2)], catalog
    )
    assert order.total == Decimal("168.00")
    assert isinstance(order.total, Decimal)


def test_empty_selection_is_zero(catalog):
    order = price_order([], catalog)
    assert order.total == Decimal("0.00")
    assert order.line_items == ()


def test_unknown_code_raises(catalog):
    with pytest.raises(UnknownServiceError):
        price_order([("NOT_A_CODE", 1)], catalog)


def test_zero_quantity_raises(catalog):
    with pytest.raises(ValueError):
        price_order([("TUNE_BASIC", 0)], catalog)
