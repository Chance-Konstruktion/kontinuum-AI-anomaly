"""Cross-stream correlation: temporal co-occurrence and multi-agent clusters."""
from datetime import datetime, timedelta, timezone

from ai_kontinuum_monitor import (
    CorrelatedEvent,
    CrossStreamCorrelator,
    MultiAgentWatch,
    NoveltyStrategy,
)

BASE = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return BASE + timedelta(seconds=seconds)


def test_correlated_with_finds_cross_agent_neighbours():
    c = CrossStreamCorrelator(window_seconds=30)
    a = c.record("agent-a", "act", 0.9, ts=_at(0))
    c.record("agent-b", "escalate", 0.8, ts=_at(10))  # within window, other agent
    c.record("agent-a", "plan", 0.7, ts=_at(5))       # same agent, excluded
    c.record("agent-c", "halt", 0.6, ts=_at(120))     # out of window
    neighbours = c.correlated_with(a)
    ids = {e.agent_id for e in neighbours}
    assert ids == {"agent-b"}


def test_correlated_with_can_include_same_agent():
    c = CrossStreamCorrelator(window_seconds=30)
    a = c.record("agent-a", "act", 0.9, ts=_at(0))
    c.record("agent-a", "plan", 0.7, ts=_at(5))
    neighbours = c.correlated_with(a, cross_agent_only=False)
    assert [e.action for e in neighbours] == ["plan"]


def test_clusters_requires_min_agents():
    c = CrossStreamCorrelator(window_seconds=30)
    # Tight burst across two agents → a cross-stream cluster.
    c.record("agent-a", "act", 0.9, ts=_at(0))
    c.record("agent-b", "escalate", 0.8, ts=_at(5))
    # A lone later event from one agent → not a cross-stream cluster.
    c.record("agent-a", "plan", 0.5, ts=_at(500))
    clusters = c.clusters(min_agents=2)
    assert len(clusters) == 1
    cl = clusters[0]
    assert cl["agents"] == ["agent-a", "agent-b"]
    assert cl["size"] == 2
    assert cl["max_score"] == 0.9


def test_clusters_empty_when_no_events():
    assert CrossStreamCorrelator().clusters() == []


def test_max_events_evicts_oldest():
    c = CrossStreamCorrelator(window_seconds=30, max_events=3)
    for i in range(5):
        c.record("a", f"x{i}", 0.5, ts=_at(i))
    # Only the last 3 survive.
    assert len(c._events) == 3
    assert [e.action for _, _, e in c._events] == ["x2", "x3", "x4"]


def test_multi_agent_watch_correlates_novel_actions():
    m = MultiAgentWatch(window_seconds=60, strategy=NoveltyStrategy())
    # Two agents both hit a brand-new action within the window → clustered.
    r1 = m.observe("agent-a", "boom", ts=_at(0))
    r2 = m.observe("agent-b", "boom", ts=_at(20))
    assert r1.is_anomaly and r2.is_anomaly
    clusters = m.correlated_clusters(min_agents=2)
    assert len(clusters) == 1
    assert set(clusters[0]["agents"]) == {"agent-a", "agent-b"}


def test_multi_agent_watch_reuses_one_watch_per_agent():
    m = MultiAgentWatch(strategy=NoveltyStrategy())
    m.observe("agent-a", "x", ts=_at(0))
    w1 = m.watch_for("agent-a")
    m.observe("agent-a", "y", ts=_at(1))
    w2 = m.watch_for("agent-a")
    assert w1 is w2


def test_correlated_event_is_hashable_frozen():
    ev = CorrelatedEvent(agent_id="a", action="x", score=0.5, ts=_at(0))
    assert ev in {ev}
