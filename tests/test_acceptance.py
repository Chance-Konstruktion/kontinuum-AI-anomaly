"""SPEC.md §4 acceptance criterion, plus the full-pipeline wiring.

Feed the rhythm ``plan → act → observe → reflect → done`` ~20 times, then inject
a never-seen action ``escalate``. ``escalate`` must be anomalous; the rehearsed
actions must not be.
"""
from ai_kontinuum_monitor import AnomalyWatch

RHYTHM = ["plan", "act", "observe", "reflect", "done"]


def test_acceptance_escalate_is_anomalous_rehearsed_is_not():
    watch = AnomalyWatch(agent_id="openclaw")
    for _ in range(20):
        for action in RHYTHM:
            watch.observe(action)

    rehearsed = {a: watch.observe(a).is_anomaly for a in RHYTHM}
    assert not any(rehearsed.values()), rehearsed

    escalate = watch.observe("escalate")
    assert escalate.is_anomaly is True
    assert escalate.is_novel is True


def test_pipeline_records_and_stats():
    watch = AnomalyWatch(agent_id="openclaw")
    for _ in range(20):
        for action in RHYTHM:
            watch.observe(action)
    watch.observe("escalate")

    # The novel action was recorded in history...
    recent = watch.recent_anomalies(days=3650)
    assert any(r.action == "escalate" for r in recent)
    # ...and per-stream stats span every action seen.
    stats = watch.stream_stats()
    assert set(RHYTHM).issubset(stats.keys())


def test_pipeline_persistence_roundtrip(tmp_path):
    brain = str(tmp_path / "brain.json")
    hist = str(tmp_path / "hist.json")
    w = AnomalyWatch(brain_path=brain, history_path=hist)
    for _ in range(20):
        for action in RHYTHM:
            w.observe(action)
    w.observe("escalate")
    w.save()

    w2 = AnomalyWatch(brain_path=brain, history_path=hist)
    # State intact: escalate is no longer novel after reload.
    assert w2.monitor.observe("escalate")["is_novel"] is False
    assert any(r.action == "escalate" for r in w2.history.records)
