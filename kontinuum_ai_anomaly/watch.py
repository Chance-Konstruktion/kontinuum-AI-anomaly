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

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from ._timeutil import as_utc_or_now
from .alerting import AlertRouter
from .history import AnomalyHistory, AnomalyRecord
from .monitor import AgentMonitor
from .recurrence import RecurrenceDetector, RecurrenceFinding
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
        recurrence: A :class:`RecurrenceDetector` to feed. If omitted one is
            created (unless ``track_recurrence`` is False). Recording is side-
            effect free w.r.t. the live verdict — see :mod:`.recurrence`.
        recurrence_path: Optional JSON path to load/persist the detector's
            windowed counts across runs.
        track_recurrence: Set False to disable recurrence tracking entirely.
    """

    def __init__(
        self,
        agent_id: str = "agent",
        *,
        brain_path: Optional[str] = None,
        history_path: Optional[str] = None,
        strategy: Optional[ScoringStrategy] = None,
        router: Optional[AlertRouter] = None,
        recurrence: Optional[RecurrenceDetector] = None,
        recurrence_path: Optional[str] = None,
        track_recurrence: bool = True,
    ):
        self.monitor = AgentMonitor(persist_path=brain_path, agent_id=agent_id)
        self.scorer = AnomalyScorer(strategy=strategy)
        self.history = AnomalyHistory(persist_path=history_path)
        self.router = router
        self.agent_id = agent_id

        self.recurrence_path = recurrence_path
        if recurrence is not None:
            self.recurrence: Optional[RecurrenceDetector] = recurrence
        elif track_recurrence:
            self.recurrence = RecurrenceDetector()
        else:
            self.recurrence = None
        if self.recurrence is not None and recurrence_path and os.path.exists(recurrence_path):
            with open(recurrence_path, "r", encoding="utf-8") as fh:
                self.recurrence.from_dict(json.load(fh))

    def observe(
        self,
        action: str,
        detail: Optional[str] = None,
        *,
        ts: Optional[datetime] = None,
    ) -> AnomalyScore:
        """Run one action through the whole pipeline and return its verdict.

        Recurrence tracking observes *every* action here, but only updates
        windowed counts — it never alters ``result`` or triggers ``is_anomaly``.
        """
        obs = self.monitor.observe(action, detail, ts=ts)
        result = self.scorer.score(obs)
        if result.is_anomaly:
            rec = AnomalyRecord.from_score(
                result, agent_id=self.agent_id, detail=detail, ts=ts
            )
            self.history.record(rec)
            if self.router is not None:
                self.router.route(rec, now=ts)
        if self.recurrence is not None:
            self.recurrence.record(action, ts=ts)
        return result

    # ------------------------------------------------------------------
    # Recurrence — periodic, out-of-band from the live verdict
    # ------------------------------------------------------------------
    def check_recurrence(
        self, *, now: Optional[datetime] = None
    ) -> List[RecurrenceFinding]:
        """Current recurrence findings (new-established / rate-spike / silent).

        A read-only evaluation; it does not touch the live scoring path. Returns
        an empty list if recurrence tracking is disabled.
        """
        if self.recurrence is None:
            return []
        return self.recurrence.report(now=now)

    def recurrence_report(
        self, *, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """:meth:`check_recurrence` as JSON-friendly dicts (for the CLI / logs)."""
        return [f.as_dict() for f in self.check_recurrence(now=now)]

    def route_recurrence(
        self, *, now: Optional[datetime] = None
    ) -> List[RecurrenceFinding]:
        """Route current findings through the alert router, at most one per
        action per window (the router's own per-action cooldown de-dupes repeats).

        No-op returning ``[]`` if there is no router or no recurrence tracking.
        """
        findings = self.check_recurrence(now=now)
        if self.router is None:
            return findings
        routed: List[RecurrenceFinding] = []
        for f in findings:
            rec = AnomalyRecord(
                action=f.action,
                score=round(f.severity, 4),
                surprise=0.0,
                threshold=0.0,
                is_novel=(f.signal == "new_established"),
                reasons=[f.reason],
                strategy="recurrence",
                ts=as_utc_or_now(now).isoformat(),
                agent_id=self.agent_id,
            )
            report = self.router.route(rec, now=now)
            if report.get("delivered"):
                routed.append(f)
        return routed

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
        """Persist the core brain, the anomaly ledger, and recurrence counts."""
        self.monitor.save()
        self.history.save()
        if self.recurrence is not None and self.recurrence_path:
            tmp = f"{self.recurrence_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.recurrence.to_dict(), fh)
            os.replace(tmp, self.recurrence_path)
