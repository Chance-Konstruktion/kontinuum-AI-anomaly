"""Dashboard rendering: self-contained HTML, escaping, metric cards."""
from datetime import datetime, timezone

from kontinuum_ai_anomaly import render_dashboard
from kontinuum_ai_anomaly.history import AnomalyHistory, AnomalyRecord


def _rec(action="act", *, novel=False, score=0.6, surprise=0.6, reasons=None):
    return AnomalyRecord(
        action=action,
        score=score,
        surprise=surprise,
        threshold=0.4,
        is_novel=novel,
        reasons=reasons or ["flagged"],
        strategy="composite(or)",
        ts=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc).isoformat(),
    )


def _history(records):
    h = AnomalyHistory()
    for r in records:
        h.record(r)
    return h


def test_dashboard_is_self_contained_html():
    html = render_dashboard(_history([_rec()]), days=None)
    assert html.startswith("<!doctype html>")
    # No external assets — CSP-friendly, single file.
    assert "http://" not in html and "https://" not in html
    assert "<script" in html  # inline filter JS


def test_dashboard_empty_history_has_friendly_message():
    html = render_dashboard(_history([]), days=7.0)
    assert "No anomalies in window" in html


def test_dashboard_escapes_action_names():
    html = render_dashboard(_history([_rec(action="<script>x</script>")]), days=None)
    assert "<script>x</script>" not in html.replace("<script", "", 1)
    assert "&lt;script&gt;" in html


def test_dashboard_counts_reflect_records():
    recs = [_rec("a", novel=True), _rec("a"), _rec("b")]
    html = render_dashboard(_history(recs), days=None)
    # Three anomalies, one novel, two distinct streams.
    assert ">3<" in html  # total anomalies card
    assert ">2<" in html  # streams affected card


def test_dashboard_metric_cards_render_when_metrics_given():
    metrics = {
        "learning_progress_pct": 42.0,
        "surprise_trend": 0.123,
        "mean_surprise": 0.55,
    }
    html = render_dashboard(_history([_rec()]), days=None, metrics=metrics)
    assert "learning progress" in html
    assert "42%" in html
    assert "surprise trend" in html
    assert "▲" in html  # positive trend arrow
