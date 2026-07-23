"""AnomalyWatch — the orchestrator that ties the layers together.

One call, ``watch.observe(action)``, runs the full pipeline:

    AgentMonitor (ingest into core)
      → AnomalyScorer (robust verdict)
        → AnomalyHistory (record if flagged)
          → AlertRouter (notify if flagged)

This is the package's headline entry point and the surface the acceptance
criterion (SPEC.md §4) is written against.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .alerting import AlertRouter
from .history import AnomalyHistory, AnomalyRecord
from .monitor import AgentMonitor
from .scoring import AnomalyScore, AnomalyScorer, ScoringStrategy


class AnomalyWatch:
    """Full anomaly-monitoring pipeline over an agent action stream.

    Args:
        agent_id: Agent label.
        brain_path: Optional path for the core brain (passed to AgentMonitor).
        history_path: Optional path for the anomaly ledger.
        strategy: Scoring strategy (defaults to novelty OR adaptive threshold).
        router: Alert router; if omitted, no alerts are routed (scoring and
            history still run).
    """

    def __init__(
        self,
        agent_id: str = "agent",
        *,
        brain_path: Optional[str] = None,
        history_path: Optional[str] = None,
        strategy: Optional[ScoringStrategy] = None,
        router: Optional[AlertRouter] = None,
    ):
        self.monitor = AgentMonitor(persist_path=brain_path, agent_id=agent_id)
        self.scorer = AnomalyScorer(strategy=strategy)
        self.history = AnomalyHistory(persist_path=history_path)
        self.router = router
        self.agent_id = agent_id

    def observe(
        self,
        action: str,
        detail: Optional[str] = None,
        *,
        ts: Optional[datetime] = None,
    ) -> AnomalyScore:
        """Run one action through the whole pipeline and return its verdict."""
        obs = self.monitor.observe(action, detail, ts=ts)
        result = self.scorer.score(obs)
        if result.is_anomaly:
            rec = AnomalyRecord.from_score(
                result, agent_id=self.agent_id, detail=detail, ts=ts
            )
            self.history.record(rec)
            if self.router is not None:
                self.router.route(rec, now=ts)
        return result

    # ------------------------------------------------------------------
    # Pass-throughs / rollups
    # ------------------------------------------------------------------
    def context(self) -> str:
        return self.monitor.context()

    def diagnostics(self) -> Dict[str, Any]:
        return self.monitor.diagnostics()

    def stream_stats(self) -> Dict[str, Dict[str, float]]:
        return self.scorer.stream_stats()

    def metrics(self) -> Dict[str, Any]:
        """Run-wide metrics (learning progress %, surprise trend, anomaly rate)."""
        return self.scorer.metrics()

    def recent_anomalies(self, days: float = 7.0) -> List[AnomalyRecord]:
        return self.history.recent(days)

    def save(self) -> None:
        """Persist both the core brain and the anomaly ledger."""
        self.monitor.save()
        self.history.save()
