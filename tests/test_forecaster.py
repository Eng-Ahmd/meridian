"""Forecaster tests: trend recovery, fallbacks, edge cases."""
from meridian.agents.forecaster import forecast_demand, holt_forecast, moving_average_forecast


def test_holt_recovers_linear_trend():
    series = [10.0 + 2.0 * i for i in range(60)]
    fc = holt_forecast(series, 5)
    assert len(fc) == 5
    # Next values of the true line are 130, 132, ...; allow a tolerance band.
    for got, want in zip(fc, [130.0, 132.0, 134.0, 136.0, 138.0], strict=True):
        assert abs(got - want) < 3.0


def test_long_history_uses_holt():
    series = [100.0] * 60
    fc = forecast_demand("SKU-X", series, 30)
    assert fc.method == "holt-linear-trend"
    assert len(fc.daily) == 30
    assert fc.total == sum(fc.daily)


def test_short_history_falls_back_to_moving_average():
    series = [10.0, 12.0, 11.0, 13.0, 12.0]
    fc = forecast_demand("SKU-X", series, 7)
    assert fc.method == "moving-average"
    assert all(x == fc.daily[0] for x in fc.daily)


def test_moving_average_window():
    fc = moving_average_forecast([1.0, 2.0, 3.0, 4.0], 3, window=2)
    assert fc == [3.5, 3.5, 3.5]


def test_empty_history_yields_zeros():
    fc = forecast_demand("SKU-X", [], 10)
    assert fc.method == "no-history"
    assert fc.daily == [0.0] * 10
    assert fc.sigma == 0.0


def test_forecast_never_negative():
    fc = forecast_demand("SKU-X", [5.0, 1.0, 0.0, 0.0, 2.0] * 8, 10)
    assert all(x >= 0.0 for x in fc.daily)
