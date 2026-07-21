"""Multi-agent / cross-stream correlation.

GrokAI's "Multi-Agent / Cross-Stream Correlation (Anomalien zwischen mehreren
Agenten)". A single :class:`~ai_kontinuum_monitor.watch.AnomalyWatch` judges one
agent in isolation. When several agents run together, the interesting signal is
often *coincidence*: two agents going anomalous within seconds of each other is
far more suspicious than either alone (a shared upstream fault, a cascading
failure).

This module adds that layer without touching core or the single-agent pipeline:

* :class:`CrossStreamCorrelator` — an in-memory log of anomaly events across
  streams that finds temporal co-occurrences.
* :class:`MultiAgentWatch` — runs one :class:`AnomalyWatch` per agent and feeds
  every flagged anomaly into the correlator automatically.
"""
from __future__ import annotations

from bisect import insort
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .alerting import AlertRouter
from .scoring import AnomalyScore, ScoringStrategy
from .watch import AnomalyWatch


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CorrelatedEvent:
    """One anomaly, as seen by the correlator."""

    agent_id: str
    action: str
    score: float
    ts: datetime


class CrossStreamCorrelator:
    """Find anomalies that co-occur across different agents/streams in time.

    Args:
        window_seconds: Two anomalies from *different* agents within this many
            seconds are considered correlated.
        max_events: Cap on retained events (oldest evicted).
    """

    def __init__(self, window_seconds: float = 60.0, max_events: int = 10_000):
        self.window_seconds = window_seconds
        self.max_events = max_events
        # Kept sorted by (ts, seq) so window lookups stay cheap. The monotonic
        # ``seq`` tie-breaks equal timestamps so the tuples stay orderable
        # without comparing the (unordered) event payload — and keeps this
        # 3.9-compatible (bisect ``key=`` only exists on 3.10+).
        self._events: List[Tuple[datetime, int, CorrelatedEvent]] = []
        self._seq = 0

    def record(
        self,
        agent_id: str,
        action: str,
        score: float,
        *,
        ts: Optional[datetime] = None,
    ) -> CorrelatedEvent:
        ts = ts or _now()
        ev = CorrelatedEvent(agent_id=agent_id, action=action, score=score, ts=ts)
        insort(self._events, (ts, self._seq, ev))
        self._seq += 1
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]
        return ev

    def correlated_with(
        self, ev: CorrelatedEvent, *, cross_agent_only: bool = True
    ) -> List[CorrelatedEvent]:
        """Events within the window of ``ev`` (by default, from other agents)."""
        lo = ev.ts - timedelta(seconds=self.window_seconds)
        hi = ev.ts + timedelta(seconds=self.window_seconds)
        out = []
        for ts, _seq, other in self._events:
            if ts < lo:
                continue
            if ts > hi:
                break
            if other is ev:
                continue
            if cross_agent_only and other.agent_id == ev.agent_id:
                continue
            out.append(other)
        return out

    def clusters(self, *, min_agents: int = 2) -> List[Dict[str, Any]]:
        """Group anomalies into time clusters spanning ``min_agents`` agents.

        A cluster is a run of events each within ``window_seconds`` of the
        previous one; only clusters touching at least ``min_agents`` distinct
        agents are returned — those are the cross-stream incidents worth a look.
        """
        if not self._events:
            return []
        clusters: List[List[CorrelatedEvent]] = []
        current: List[CorrelatedEvent] = [self._events[0][2]]
        gap = timedelta(seconds=self.window_seconds)
        for (ts, _seq, ev) in self._events[1:]:
            if ts - current[-1].ts <= gap:
                current.append(ev)
            else:
                clusters.append(current)
                current = [ev]
        clusters.append(current)

        out: List[Dict[str, Any]] = []
        for group in clusters:
            agents = sorted({e.agent_id for e in group})
            if len(agents) < min_agents:
                continue
            out.append(
                {
                    "start": group[0].ts.isoformat(),
                    "end": group[-1].ts.isoformat(),
                    "agents": agents,
                    "size": len(group),
                    "actions": sorted({e.action for e in group}),
                    "max_score": round(max(e.score for e in group), 4),
                }
            )
        return out


class MultiAgentWatch:
    """Run an :class:`AnomalyWatch` per agent and correlate across them.

    Each agent gets its own independent watch (its own core brain / history);
    ``observe(agent_id, action)`` lazily creates one on first sight. Every
    flagged anomaly is also fed into a shared :class:`CrossStreamCorrelator`, so
    :meth:`correlated_clusters` surfaces incidents where multiple agents went
    anomalous together.

    Args:
        window_seconds: Correlation window (see :class:`CrossStreamCorrelator`).
        strategy: Optional scoring strategy applied to every agent's watch.
        router: Optional shared alert router applied to every agent's watch.
        brain_dir / history_dir: If given, per-agent persistence files are
            created as ``{dir}/{agent_id}.json`` so each agent's model/ledger is
            saved separately.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        strategy: Optional[ScoringStrategy] = None,
        router: Optional[AlertRouter] = None,
        brain_dir: Optional[str] = None,
        history_dir: Optional[str] = None,
    ):
        self.window_seconds = window_seconds
        self.strategy = strategy
        self.router = router
        self.brain_dir = brain_dir
        self.history_dir = history_dir
        self.correlator = CrossStreamCorrelator(window_seconds=window_seconds)
        self.watches: Dict[str, AnomalyWatch] = {}

    def _path(self, base: Optional[str], agent_id: str) -> Optional[str]:
        if not base:
            return None
        import os

        os.makedirs(base, exist_ok=True)
        return os.path.join(base, f"{agent_id}.json")

    def watch_for(self, agent_id: str) -> AnomalyWatch:
        w = self.watches.get(agent_id)
        if w is None:
            w = AnomalyWatch(
                agent_id=agent_id,
                brain_path=self._path(self.brain_dir, agent_id),
                history_path=self._path(self.history_dir, agent_id),
                strategy=self.strategy,
                router=self.router,
            )
            self.watches[agent_id] = w
        return w

    def observe(
        self,
        agent_id: str,
        action: str,
        detail: Optional[str] = None,
        *,
        ts: Optional[datetime] = None,
    ) -> AnomalyScore:
        """Observe one action for ``agent_id`` and correlate if it's anomalous."""
        result = self.watch_for(agent_id).observe(action, detail, ts=ts)
        if result.is_anomaly:
            self.correlator.record(agent_id, action, result.score, ts=ts)
        return result

    def correlated_clusters(self, *, min_agents: int = 2) -> List[Dict[str, Any]]:
        """Cross-agent anomaly clusters (see :meth:`CrossStreamCorrelator.clusters`)."""
        return self.correlator.clusters(min_agents=min_agents)

    def save(self) -> None:
        for w in self.watches.values():
            w.save()
