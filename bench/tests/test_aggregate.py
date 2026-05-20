import pytest
from aggregate import aggregate_cells


def make_rows(scenario, metric, values, notes=""):
    rows = []
    for i, v in enumerate(values, 1):
        rows.append({
            "ts_iso": "2026-05-20T10:00:00Z",
            "scenario": scenario,
            "metric": metric,
            "run": str(i),
            "value": str(v),
            "unit": "ms",
            "median": str(v),
            "p95": str(v),
            "stddev": "0.000",
            "mean": str(v),
            "n_samples": "1",
            "notes": notes,
        })
    return rows


def test_cross_run_stats_from_csv_rows():
    rows = make_rows("wg-plain", "lat_idle", [24.0, 24.2, 23.8, 24.1, 23.9])
    cells = aggregate_cells(rows)
    cell = cells[("wg-plain", "lat_idle")]
    assert cell["n"] == 5
    assert cell["mean"] == pytest.approx(24.0)
    assert cell["median"] == pytest.approx(24.0)
    assert cell["stddev"] == pytest.approx(0.14142, rel=1e-3)


def test_aggregate_skips_partial_cells():
    rows = make_rows("wg-plain", "tcp_t", [885.0, 880.0])
    cells = aggregate_cells(rows, expected_n=5)
    cell = cells[("wg-plain", "tcp_t")]
    assert cell["n"] == 2
    assert cell["notes"] == "only 2/5 runs"


def test_aggregate_handles_string_notes_column():
    rows = make_rows("wg-plain", "udp", [49.8, 50.1, 49.9], notes="no-loss-at-top")
    cells = aggregate_cells(rows)
    cell = cells[("wg-plain", "udp")]
    assert cell["n"] == 3
    assert cell["mean"] == pytest.approx((49.8 + 50.1 + 49.9) / 3, rel=1e-3)
