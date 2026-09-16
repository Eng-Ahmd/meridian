"""Inventory math tests against hand-computed values."""
import math

from meridian.agents.inventory import (
    economic_order_quantity,
    plan_replenishment,
    reorder_point,
    safety_stock,
    z_for_service_level,
)


def test_z_for_service_level():
    assert z_for_service_level(0.95) == 1.645
    assert z_for_service_level(0.90) == 1.28
    # Interpolation between 0.95 and 0.98 anchors.
    z = z_for_service_level(0.965)
    assert 1.645 < z < 2.05
    # Clamped to the table range.
    assert z_for_service_level(0.50) == 1.28
    assert z_for_service_level(0.999) == 2.33


def test_safety_stock_known_value():
    # z=1.645, sigma=15, L=7 -> 1.645 * 15 * sqrt(7) = 65.28...
    ss = safety_stock(15.0, 7.0, 0.95)
    assert ss == 1.645 * 15.0 * math.sqrt(7.0)
    assert round(ss, 2) == 65.28


def test_safety_stock_degenerate_inputs():
    assert safety_stock(0.0, 7.0, 0.95) == 0.0
    assert safety_stock(15.0, 0.0, 0.95) == 0.0


def test_reorder_point():
    assert reorder_point(100.0, 7.0, 65.28) == 765.28


def test_eoq_known_value():
    # sqrt(2 * 12000 * 50 / 2) = sqrt(600000) ~= 774.60
    assert round(economic_order_quantity(12000, 50, 2), 2) == 774.60
    assert economic_order_quantity(0, 50, 2) == 0.0
    assert economic_order_quantity(12000, 0, 2) == 0.0


def test_plan_orders_up_to_target():
    plan = plan_replenishment(
        sku_id="SKU-X",
        on_hand=100.0,
        on_order=0.0,
        forecast_daily=[50.0] * 30,
        demand_sigma=5.0,
        lead_time_days=7.0,
        review_period_days=7,
        service_level=0.95,
    )
    # Cover = 14 days * 50 = 700, plus safety stock ~34.5 -> target ~734.5 -> order 635.
    assert plan["order_quantity"] == math.ceil(700 + safety_stock(5.0, 7.0, 0.95) - 100)
    assert plan["below_reorder_point"] is True


def test_plan_no_order_when_covered():
    plan = plan_replenishment(
        sku_id="SKU-X",
        on_hand=10000.0,
        on_order=0.0,
        forecast_daily=[50.0] * 30,
        demand_sigma=5.0,
        lead_time_days=7.0,
        review_period_days=7,
        service_level=0.95,
    )
    assert plan["order_quantity"] == 0
    assert plan["below_reorder_point"] is False


def test_plan_respects_min_order_qty():
    plan = plan_replenishment(
        sku_id="SKU-X",
        on_hand=699.0,
        on_order=0.0,
        forecast_daily=[50.0] * 30,
        demand_sigma=5.0,
        lead_time_days=7.0,
        review_period_days=7,
        service_level=0.95,
        min_order_qty=25,
    )
    # Raw need is small but positive -> raised to the MOQ.
    assert plan["order_quantity"] == 25
