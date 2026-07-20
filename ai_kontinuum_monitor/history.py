"""Anomaly history & persistence — "what was odd this week?".

Core answers "is this event surprising *right now*"; it keeps no ledger of past
anomalies. This module records every flagged anomaly with its timestamp,
persists the ledger as JSON, and answers retrospective questions (recent
window, per-action rollups). This is the second reason the package earns its
own existence.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .scoring import AnomalyScore


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AnomalyRecord:
    """One recorded anomaly."""

    action: str
    score: float
    surprise: float
    threshold: float
    is_novel: bool
    reasons: List[str]
    strategy: str
    ts: str  # ISO-8601 UTC
    agent_id: str = "agent"
    detail: Optional[str] = None

    @classmethod
    def from_score(
        cls,
        result: AnomalyScore,
        *,
        agent_id: str = "agent",
        detail: Optional[str] = None,
        ts: Optional[datetime] = None,
    ) -> "AnomalyRecord":
        return cls(
            action=result.action,
            score=round(result.score, 4),
            surprise=round(result.surprise, 4),
            threshold=round(result.threshold, 4),
            is_novel=result.is_novel,
            reasons=list(result.reasons),
            strategy=result.strategy,
            ts=(ts or _now()).isoformat(),
            agent_id=agent_id,
            detail=detail,
        )

    def datetime(self) -> datetime:
        return datetime.fromisoformat(self.ts)


class AnomalyHistory:
    """An append-only, optionally file-backed ledger of anomalies.

    Args:
        persist_path: If given, the ledger is loaded on construction and (when
            ``autosave`` is on) written back on every :meth:`record`.
        max_records: Cap on retained records (oldest evicted); ``None`` = keep
            all.
        autosave: Persist on every ``record``. Convenient, but an O(n) rewrite
            per anomaly — turn it off for high-volume streams and call
            :meth:`save` yourself (e.g. from ``AnomalyWatch.save``). Anomalies
            are rare by design, so it defaults on.
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        max_records: Optional[int] = 10_000,
        autosave: bool = True,
    ):
        self.persist_path = persist_path
        self.max_records = max_records
        self.autosave = autosave
        self.records: List[AnomalyRecord] = []
        if persist_path and os.path.exists(persist_path):
            self._load(persist_path)

    def record(self, rec: AnomalyRecord) -> AnomalyRecord:
        self.records.append(rec)
        if self.max_records is not None and len(self.records) > self.max_records:
            self.records = self.records[-self.max_records :]
        if self.persist_path and self.autosave:
            self.save()
        return rec

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def since(self, when: datetime) -> List[AnomalyRecord]:
        """Records at or after ``when``."""
        return [r for r in self.records if r.datetime() >= when]

    def recent(self, days: float = 7.0) -> List[AnomalyRecord]:
        """Records within the last ``days`` (default: this week)."""
        return self.since(_now() - timedelta(days=days))

    def for_action(self, action: str) -> List[AnomalyRecord]:
        return [r for r in self.records if r.action == action]

    def summary(self, days: Optional[float] = None) -> Dict[str, Any]:
        """Rollup over all records (or the last ``days`` if given)."""
        records = self.recent(days) if days is not None else list(self.records)
        by_action = Counter(r.action for r in records)
        novel = sum(1 for r in records if r.is_novel)
        return {
            "total": len(records),
            "novel": novel,
            "window_days": days,
            "by_action": dict(by_action.most_common()),
            "first": records[0].ts if records else None,
            "last": records[-1].ts if records else None,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self) -> None:
        if not self.persist_path:
            return
        payload = {"version": 1, "records": [asdict(r) for r in self.records]}
        tmp = f"{self.persist_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, self.persist_path)

    def _load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.records = [AnomalyRecord(**r) for r in payload.get("records", [])]
