"""console router: pure aggregation + tool-call enrichment paths."""

from __future__ import annotations

from app.routers.console import _aggregate_scores


def test_aggregate_scores_returns_neutral_zero_when_empty():
    out = _aggregate_scores([])
    assert {row["key"] for row in out} == {"knowledge", "latency", "empathy", "compliance"}
    assert all(row["value"] == 0 for row in out)
    assert all(row["label"] == row["key"].capitalize() for row in out)


def test_aggregate_scores_averages_known_axes():
    analyses = [
        {"scores": {"knowledge": 80, "latency": 70, "empathy": 90, "compliance": 100}},
        {"scores": {"knowledge": 60, "latency": 50, "empathy": 80, "compliance": 90}},
    ]
    out = {row["key"]: row["value"] for row in _aggregate_scores(analyses)}
    assert out["knowledge"] == 70
    assert out["latency"] == 60
    assert out["empathy"] == 85
    assert out["compliance"] == 95


def test_aggregate_scores_skips_non_dict_and_non_numeric():
    analyses = [
        {"scores": {"knowledge": 80}},
        "string-not-a-dict",
        {"scores": "also-not-a-dict"},
        {"scores": {"knowledge": "ninety", "latency": 50}},  # string skipped, int taken
        {"scores": {"knowledge": 60}},
    ]
    out = {row["key"]: row["value"] for row in _aggregate_scores(analyses)}
    # knowledge: (80 + 60) / 2 = 70 ("ninety" rejected)
    assert out["knowledge"] == 70
    # latency: 50 / 1
    assert out["latency"] == 50
    # empathy/compliance: never present → 0
    assert out["empathy"] == 0
    assert out["compliance"] == 0


def test_aggregate_scores_handles_floats():
    out = {
        row["key"]: row["value"]
        for row in _aggregate_scores([{"scores": {"knowledge": 75.5, "latency": 25.4}}])
    }
    assert out["knowledge"] == 75  # int() truncates
    assert out["latency"] == 25
