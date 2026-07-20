"""Anomaly history, persistence, alert routing and the dashboard."""
from datetime import datetime, timedelta, timezone

from ai_kontinuum_monitor import (
    AlertRouter,
    AnomalyHistory,
    AnomalyRecord,
    CallbackSink,
    LogSink,
    render_dashboard,
)
from ai_kontinuum_monitor.scoring import AnomalyScore


def _score(action="deploy", novel=True):
    return AnomalyScore(
        action=action, is_anomaly=True, score=0.8, surprise=0.8,
        threshold=0.4, is_novel=novel, reasons=["never-seen action"],
        strategy="novelty",
    )


def test_history_records_and_queries():
    h = AnomalyHistory()
    now = datetime.now(timezone.utc)
    h.record(AnomalyRecord.from_score(_score("a"), ts=now))
    h.record(AnomalyRecord.from_score(_score("b"), ts=now - timedelta(days=30)))
    assert len(h.records) == 2
    assert len(h.recent(days=7)) == 1
    assert len(h.for_action("a")) == 1


def test_history_summary():
    h = AnomalyHistory()
    now = datetime.now(timezone.utc)
    for a in ("a", "a", "b"):
        h.record(AnomalyRecord.from_score(_score(a), ts=now))
    s = h.summary()
    assert s["total"] == 3
    assert s["by_action"]["a"] == 2
    assert s["novel"] == 3


def test_history_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "hist.json")
    h = AnomalyHistory(persist_path=path)
    h.record(AnomalyRecord.from_score(_score("a")))
    h2 = AnomalyHistory(persist_path=path)
    assert len(h2.records) == 1
    assert h2.records[0].action == "a"


def test_history_max_records_evicts_oldest():
    h = AnomalyHistory(max_records=3)
    for i in range(5):
        h.record(AnomalyRecord.from_score(_score(f"a{i}")))
    assert len(h.records) == 3
    assert h.records[0].action == "a2"


def test_callback_sink_receives_record():
    seen = []
    router = AlertRouter([CallbackSink(seen.append)])
    rec = AnomalyRecord.from_score(_score("deploy"))
    report = router.route(rec)
    assert report["delivered"] is True
    assert report["sinks"]["callback"] is True
    assert seen and seen[0].action == "deploy"


def test_callback_sink_swallows_handler_error():
    def boom(_rec):
        raise RuntimeError("bad handler")

    router = AlertRouter([CallbackSink(boom)])
    report = router.route(AnomalyRecord.from_score(_score()))
    # Routing did not raise; the sink reported failure.
    assert report["sinks"]["callback"] is False


def test_router_rate_limiting():
    seen = []
    router = AlertRouter([CallbackSink(seen.append)], cooldown_seconds=60)
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rec = AnomalyRecord.from_score(_score("x"))
    assert router.route(rec, now=now)["delivered"] is True
    # Same action inside the cooldown is suppressed.
    assert router.route(rec, now=now + timedelta(seconds=10))["delivered"] is False
    # After the cooldown it delivers again.
    assert router.route(rec, now=now + timedelta(seconds=120))["delivered"] is True
    assert len(seen) == 2
    assert router.suppressed == 1


def test_log_sink_delivers(caplog):
    router = AlertRouter([LogSink()])
    report = router.route(AnomalyRecord.from_score(_score("deploy")))
    assert report["sinks"]["log"] is True


def test_dashboard_renders_self_contained_html():
    h = AnomalyHistory()
    h.record(AnomalyRecord.from_score(_score("deploy")))
    html = render_dashboard(h, days=7)
    assert html.startswith("<!doctype html>")
    assert "deploy" in html
    # Self-contained: no external asset references.
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html


def test_dashboard_empty_window():
    html = render_dashboard(AnomalyHistory(), days=7)
    assert "No anomalies" in html
