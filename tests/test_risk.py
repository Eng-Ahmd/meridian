"""Risk agent tests: spike/drop detection on injected anomalies."""
from meridian.agents.risk import days_of_cover, demand_anomalies


def _flat(n: int, value: float = 100.0) -> list[float]:
    # Small deterministic wobble so sigma is nonzero.
    return [value + (i % 5 - 2) for i in range(n)]


def test_spike_detected():
    series = _flat(60)
    series[55] = 400.0
    hits = demand_anomalies(series)
    assert hits, "expected the injected spike to be flagged"
    assert hits[-1]["direction"] == "spike"
    assert hits[-1]["z_score"] > 3.0


def test_drop_detected():
    series = _flat(60)
    series[55] = 10.0
    hits = demand_anomalies(series)
    assert hits, "expected the injected drop to be flagged"
    assert hits[-1]["direction"] == "drop"


def test_quiet_series_has_no_findings():
    assert demand_anomalies(_flat(60)) == []


def test_short_series_returns_empty():
    assert demand_anomalies([1.0, 2.0, 3.0]) == []


def test_days_of_cover():
    assert days_of_cover(300.0, 100.0, 50.0) == 8.0
    assert days_of_cover(100.0, 0.0, 0.0) is None
