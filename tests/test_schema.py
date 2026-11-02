"""Schema + semantic validation: the gate that keeps bad model output from
becoming a work order, and the structural defense against prompt injection.
"""
import pytest
from pydantic import ValidationError

from app.core.schema import ExtractedOrder, Intent, ServiceSelection
from app.core.validator import validate_extraction


def _order(**kw):
    base = dict(intent=Intent.new_order, is_work_order=True)
    base.update(kw)
    return ExtractedOrder(**base)


def test_valid_order_parses(catalog):
    order = _order(
        bike_type="road",
        services=[ServiceSelection(code="TUNE_BASIC")],
        requested_date="2026-09-24",
    )
    assert validate_extraction(order, catalog).ok


def test_model_cannot_express_a_price():
    # Prompt-injection defense (#24): there is no price field to set. An attempt
    # to supply one is rejected as an unknown field.
    with pytest.raises(ValidationError):
        ExtractedOrder(
            intent=Intent.new_order,
            is_work_order=True,
            services=[{"code": "CHAIN_REPLACE", "price": 0}],
        )


def test_unknown_service_code_fails_semantic_validation(catalog):
    order = _order(services=[ServiceSelection(code="MADE_UP_CODE")])
    result = validate_extraction(order, catalog)
    assert not result.ok
    assert any("unknown service code" in e for e in result.errors)


def test_needs_followup_without_question_fails(catalog):
    order = _order(is_work_order=True, services=[], needs_followup=True,
                   followup_question="   ")
    result = validate_extraction(order, catalog)
    assert not result.ok


def test_work_order_with_nothing_to_do_fails(catalog):
    order = _order(is_work_order=True, services=[], needs_followup=False)
    result = validate_extraction(order, catalog)
    assert not result.ok


def test_price_question_carries_no_services(catalog):
    # Sample #18: asking cost only, no repair -> not a work order, no services.
    order = ExtractedOrder(intent=Intent.price_question, is_work_order=False)
    assert validate_extraction(order, catalog).ok

    bad = ExtractedOrder(intent=Intent.price_question, is_work_order=False,
                         services=[ServiceSelection(code="TUNE_FULL")])
    assert not validate_extraction(bad, catalog).ok


def test_invalid_date_rejected():
    with pytest.raises(ValidationError):
        ExtractedOrder(intent=Intent.new_order, is_work_order=True,
                       services=[ServiceSelection(code="TUNE_BASIC")],
                       requested_date="next Saturday")


def test_extra_top_level_field_forbidden():
    with pytest.raises(ValidationError):
        ExtractedOrder(intent=Intent.new_order, is_work_order=True,
                       urgent_vip=True)
