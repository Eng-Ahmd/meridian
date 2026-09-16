"""Policy guardrail tests."""
from meridian.core.config import Settings
from meridian.core.policy import evaluate_order


def _settings(**overrides):
    base = dict(
        max_single_po_value=25000.0,
        approval_threshold=5000.0,
    )
    base.update(overrides)
    return Settings(**base)


def test_small_order_passes_clean():
    v = evaluate_order(
        settings=_settings(), supplier_approved=True, quantity=10,
        unit_cost=100.0, days_of_cover_after_order=20.0, planning_horizon_days=30,
    )
    assert v.allowed is True
    assert v.needs_approval is False
    assert v.reasons == []


def test_threshold_order_needs_approval():
    v = evaluate_order(
        settings=_settings(), supplier_approved=True, quantity=50,
        unit_cost=100.0, days_of_cover_after_order=20.0, planning_horizon_days=30,
    )
    assert v.allowed is True
    assert v.needs_approval is True
    assert any("approval" in r for r in v.reasons)


def test_unapproved_supplier_blocked():
    v = evaluate_order(
        settings=_settings(), supplier_approved=False, quantity=10,
        unit_cost=100.0, days_of_cover_after_order=20.0, planning_horizon_days=30,
    )
    assert v.allowed is False
    assert v.needs_approval is False


def test_over_cap_order_blocked():
    v = evaluate_order(
        settings=_settings(), supplier_approved=True, quantity=1000,
        unit_cost=100.0, days_of_cover_after_order=20.0, planning_horizon_days=30,
    )
    assert v.allowed is False
    assert any("cap" in r for r in v.reasons)


def test_zero_quantity_blocked():
    v = evaluate_order(
        settings=_settings(), supplier_approved=True, quantity=0,
        unit_cost=100.0, days_of_cover_after_order=20.0, planning_horizon_days=30,
    )
    assert v.allowed is False


def test_excessive_cover_flagged_but_allowed():
    v = evaluate_order(
        settings=_settings(), supplier_approved=True, quantity=10,
        unit_cost=100.0, days_of_cover_after_order=60.0, planning_horizon_days=30,
    )
    assert v.allowed is True
    assert any("1.5x" in r for r in v.reasons)
