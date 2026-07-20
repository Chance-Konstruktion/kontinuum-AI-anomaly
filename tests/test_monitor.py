"""AgentMonitor: registration/dedup, novelty, persistence, context, diagnostics."""
from datetime import datetime, timezone

import pytest

from ai_kontinuum_monitor import AgentMonitor, slug


def test_slug_is_token_safe():
    assert slug("Plan Action!") == "plan_action"
    assert slug("escalate") == "escalate"
    assert slug("") == "action"


def test_registration_and_distinct_tokens():
    m = AgentMonitor()
    m.observe("plan")
    m.observe("act")
    # Each action registered its own room → its own switch entity.
    assert "plan" in m._registered
    assert "act" in m._registered
    diag = m.diagnostics()
    if diag.get("available"):
        # Events actually reached the engine (not silently dropped, SPEC §5.3).
        assert diag["events_processed"] >= 2
        assert diag["events_dropped_unregistered"] == 0


def test_dedup_worked_around_by_state_alternation():
    """Consecutive repeats of the SAME action must not be lost to core's
    per-entity last-token dedup (SPEC §1)."""
    m = AgentMonitor()
    for _ in range(6):
        m.observe("act")  # same action, back-to-back
    diag = m.diagnostics()
    if diag.get("available"):
        # All six alternated on/off, so none were dedup-dropped.
        assert diag["events_processed"] == 6


def test_novelty_flag():
    m = AgentMonitor()
    first = m.observe("deploy")
    assert first["is_novel"] is True
    second = m.observe("deploy")
    assert second["is_novel"] is False


def test_novelty_trips_surprise_and_anomaly_signal():
    """A never-seen action produces high surprise — the reliable signal."""
    m = AgentMonitor()
    for i in range(30):
        m.observe("routine")
    novel = m.observe("totally_new_action")
    assert novel["is_novel"] is True
    # First occurrence of a new token has no learned expectation.
    assert novel["surprise"] >= 0.5


def test_context_shape():
    m = AgentMonitor()
    for _ in range(5):
        m.observe("plan")
    ctx = m.context()
    assert isinstance(ctx, str)
    assert "KONTINUUM" in ctx
    assert "Anomaly" in ctx


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "brain.json")
    m = AgentMonitor(persist_path=path, agent_id="bot")
    for _ in range(10):
        for a in ("plan", "act", "done"):
            m.observe(a)
    ticks_before = m.engine.tick_count
    seen_before = set(m._seen_actions)
    m.save()

    m2 = AgentMonitor(persist_path=path)
    assert m2.agent_id == "bot"
    assert m2.engine.tick_count == ticks_before
    assert set(m2._seen_actions) == seen_before
    # A previously-seen action is not novel after reload.
    assert m2.observe("plan")["is_novel"] is False


def test_supplied_timestamp_used():
    m = AgentMonitor()
    ts = datetime(2030, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    m.observe("plan", ts=ts)
    # Virtual clock advanced to at least the supplied ts.
    assert m._clock >= ts


def test_diagnostics_available_on_modern_core():
    m = AgentMonitor(agent_id="bot")
    m.observe("plan")
    diag = m.diagnostics()
    # This core build has get_diagnostics(); the marker and label are present.
    assert diag["available"] is True
    assert diag["agent_id"] == "bot"
    assert diag["actions_seen"] == 1


def test_diagnostics_graceful_degradation():
    """diagnostics() must not raise on a core without get_diagnostics()
    (SPEC §5.1)."""
    m = AgentMonitor()

    class _OldCore:
        """Stand-in for a published core that predates get_diagnostics()."""

    m.engine = _OldCore()
    diag = m.diagnostics()
    assert diag["available"] is False
    assert "reason" in diag
