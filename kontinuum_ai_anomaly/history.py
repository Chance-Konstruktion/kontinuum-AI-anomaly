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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ._timeutil import as_utc, as_utc_or_now, now_utc
from .scoring import AnomalyScore

_now = now_utc  # backwards-compatible alias


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
            ts=as_utc_or_now(ts).isoformat(),
            agent_id=agent_id,
            detail=detail,
        )

    def datetime(self) -> datetime:
        """This record's timestamp, always timezone-aware (UTC).

        Ledgers written before timestamps were normalized at the boundary — and
        records hand-built by callers — can carry a naive ISO string; those are
        read as UTC so window queries never mix aware and naive datetimes.
        """
        return as_utc(datetime.fromisoformat(self.ts))


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
        """Records at or after ``when`` (a naive ``when`` is read as UTC)."""
        cutoff = as_utc(when)
        return [r for r in self.records if r.datetime() >= cutoff]

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
    # Long-term analysis — "anomaly patterns over weeks"
    # ------------------------------------------------------------------
    def patterns(self, weeks: Optional[float] = None) -> Dict[str, Any]:
        """Retrospective pattern analysis over a long window.

        Answers GrokAI's "Anomaly-Muster über Wochen": bucket anomalies by ISO
        week, by weekday and by hour-of-day, and surface *recurring* actions
        (flagged in 2+ distinct weeks) — the long-horizon view core, which only
        judges the present event, cannot give.

        Args:
            weeks: Look-back window in weeks (``None`` = all recorded history).
        """
        records = (
            self.recent(weeks * 7) if weeks is not None else list(self.records)
        )
        by_week: "Counter[str]" = Counter()
        by_weekday: "Counter[str]" = Counter()
        by_hour: "Counter[int]" = Counter()
        weeks_per_action: Dict[str, set] = {}
        weekday_names = [
            "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
        ]
        for r in records:
            dt = r.datetime()
            iso = dt.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
            by_week[week_key] += 1
            by_weekday[weekday_names[dt.weekday()]] += 1
            by_hour[dt.hour] += 1
            weeks_per_action.setdefault(r.action, set()).add(week_key)

        recurring = {
            action: sorted(wks)
            for action, wks in weeks_per_action.items()
            if len(wks) >= 2
        }
        n_weeks = len(by_week) or 1
        return {
            "window_weeks": weeks,
            "total": len(records),
            "weeks_observed": len(by_week),
            "by_week": dict(sorted(by_week.items())),
            "by_weekday": {d: by_weekday.get(d, 0) for d in weekday_names},
            "by_hour": {h: by_hour.get(h, 0) for h in range(24)},
            "mean_per_week": round(len(records) / n_weeks, 2),
            "peak_week": by_week.most_common(1)[0] if by_week else None,
            "recurring_actions": dict(
                sorted(recurring.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            ),
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
