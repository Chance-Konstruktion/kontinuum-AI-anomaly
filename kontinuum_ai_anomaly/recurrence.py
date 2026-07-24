"""Recurrence detection — the signal novelty structurally cannot give.

Novelty fires exactly **once**: the first time an action is seen it trips the
anomaly flag, and every repeat after that scores 0. That is correct for a
one-off outlier, but it means *recurring* misbehaviour disappears from the radar
after its first occurrence — the practically most painful case ("was new three
days ago, now runs 50× a day") is invisible today.

This module closes that gap **additively**, without touching the live per-event
verdict:

* It keeps a **time-bucketed count of every observed action** (not only flagged
  ones), so "50× per day vs 2× per week" becomes derivable — the thing
  ``AnomalyScorer._counts`` (cumulative, unwindowed) cannot answer.
* It derives three periodic signals from that history:

  - ``[recurrence] new action established`` — an action that was new recently and
    is now firing frequently. The core case.
  - ``[recurrence] rate spike`` — a known action whose current-window rate is far
    above its own robust baseline (median + k·MAD of earlier windows, matching
    the engine's robust-stats convention).
  - ``[recurrence] gone silent`` — an action that used to appear regularly and
    has dropped out of the current window. Absence is a signal too: an agent that
    stopped working is a problem.

These are **retrospective evaluations, not per-event flags**. Recording is
side-effect free with respect to :meth:`AnomalyWatch.observe`; the live
``is_anomaly`` verdict and its false-alarm rate are untouched. Callers pull a
report on their own cadence via :meth:`AnomalyWatch.check_recurrence`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from ._timeutil import as_utc as _as_utc, now_utc as _now

# median-absolute-deviation → std-equivalent, same constant the scoring layer and
# core use so the robust baseline here reads on the same scale.
_MAD_TO_STD = 1.4826

_DAY_SECONDS = 86_400.0


@dataclass
class RecurrenceFinding:
    """One recurrence signal for one action (a report row, not a live verdict)."""

    action: str
    signal: str  # "new_established" | "rate_spike" | "gone_silent"
    reason: str  # "[recurrence] ..." — same style as the scorer's reasons
    rate_now: float  # occurrences in the current window
    baseline: float  # robust baseline (median of earlier windows), or age for new
    severity: float  # 0-1, higher = more notable
    first_seen: Optional[str] = None  # ISO-8601 UTC

    def as_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "signal": self.signal,
            "reason": self.reason,
            "rate_now": round(self.rate_now, 4),
            "baseline": round(self.baseline, 4),
            "severity": round(self.severity, 4),
            "first_seen": self.first_seen,
        }


class RecurrenceDetector:
    """Time-windowed counts of every action, plus three derived recurrence signals.

    Args:
        bucket_seconds: Width of a counting window (default: one day). "Rate" is
            occurrences per bucket.
        max_buckets: Ring size — only the most recent ``max_buckets`` windows are
            kept, so memory is bounded over a long-lived install (the same reason
            core caps ``NucleusAccumbens.MAX_ENTRIES``).
        new_within_days: An action counts as "recently new" if its first sighting
            is within this many days of the current window.
        established_min_count: Occurrences in the current window at/above which a
            recently-new action is considered *established*.
        spike_factor: A known action's current rate must be at least this multiple
            of its baseline median to qualify as a spike (guards the MAD=0 case
            where a perfectly stable baseline would otherwise flag any increase).
        spike_k: …and at least ``median + spike_k·MAD`` above baseline, the robust
            test used when the baseline has spread.
        baseline_min_buckets: Minimum earlier windows required before a spike or a
            silence call is trustworthy.
        silence_min_median: A gone-silent call requires the action's baseline
            median to be at least this (i.e. it really was regular).
    """

    def __init__(
        self,
        *,
        bucket_seconds: float = _DAY_SECONDS,
        max_buckets: int = 30,
        new_within_days: float = 7.0,
        established_min_count: int = 5,
        spike_factor: float = 3.0,
        spike_k: float = 4.0,
        baseline_min_buckets: int = 3,
        silence_min_median: float = 1.0,
    ):
        self.bucket_seconds = float(bucket_seconds)
        self.max_buckets = int(max_buckets)
        self.new_within_days = float(new_within_days)
        self.established_min_count = int(established_min_count)
        self.spike_factor = float(spike_factor)
        self.spike_k = float(spike_k)
        self.baseline_min_buckets = int(baseline_min_buckets)
        self.silence_min_median = float(silence_min_median)

        # action -> {bucket_index: count}
        self._counts: Dict[str, Dict[int, int]] = {}
        # action -> first-seen timestamp (kept even as old buckets are pruned,
        # until the action falls out of the ring entirely)
        self._first_seen: Dict[str, datetime] = {}
        # highest bucket index ever recorded, so "current window" is well-defined
        # even for an action that has gone silent.
        self._latest_bucket: Optional[int] = None

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def _bucket(self, ts: datetime) -> int:
        return int(_as_utc(ts).timestamp() // self.bucket_seconds)

    def record(self, action: str, *, ts: Optional[datetime] = None) -> None:
        """Count one occurrence of ``action``. Fed from every ``observe()``.

        Cheap and side-effect free with respect to the live verdict — this only
        updates windowed counts used by :meth:`report`.
        """
        when = _as_utc(ts) if ts is not None else _now()
        b = self._bucket(when)
        buckets = self._counts.setdefault(action, {})
        buckets[b] = buckets.get(b, 0) + 1
        if action not in self._first_seen or when < self._first_seen[action]:
            self._first_seen[action] = when
        # Pruning only ever removes buckets that fell out of the ring, and that
        # can only happen when the ring actually advances. Running it on every
        # single event made ingestion O(actions × buckets) per observation —
        # measurably the hot path once a deployment tracks a few hundred
        # actions. Gating it on a new window keeps the identical end state.
        if self._latest_bucket is None or b > self._latest_bucket:
            self._latest_bucket = b
            self._prune()

    def _prune(self) -> None:
        """Drop windows older than the ring; forget actions that fall out entirely."""
        if self._latest_bucket is None:
            return
        oldest = self._latest_bucket - self.max_buckets + 1
        for action in list(self._counts):
            buckets = self._counts[action]
            for b in list(buckets):
                if b < oldest:
                    del buckets[b]
            if not buckets:
                del self._counts[action]
                self._first_seen.pop(action, None)

    # ------------------------------------------------------------------
    # Reporting (read-only: never mutates state)
    # ------------------------------------------------------------------
    def report(self, *, now: Optional[datetime] = None) -> List[RecurrenceFinding]:
        """Evaluate all tracked actions and return the current recurrence findings.

        Pure: calling it does not change any counts, so it is safe to poll.
        ``now`` fixes the "current window"; if omitted, the most recent recorded
        window is used (so a gone-silent action is judged against windows that
        other actions are still filling).
        """
        if self._latest_bucket is None:
            return []
        if now is not None:
            cur_bucket = self._bucket(now)
            ref_dt = _as_utc(now)
        else:
            cur_bucket = self._latest_bucket
            # No wall clock given: measure "now" from the current window itself,
            # not the process clock — the data may be historical (loaded from a
            # file), and age-of-action must be relative to the window under test.
            ref_dt = datetime.fromtimestamp(
                (cur_bucket + 1) * self.bucket_seconds, tz=timezone.utc
            )

        findings: List[RecurrenceFinding] = []
        for action in sorted(self._counts):
            f = self._evaluate(action, cur_bucket, ref_dt)
            if f is not None:
                findings.append(f)
        # Most notable first, stable by action for deterministic output.
        findings.sort(key=lambda f: (-f.severity, f.action))
        return findings

    def _evaluate(
        self, action: str, cur_bucket: int, ref_dt: datetime
    ) -> Optional[RecurrenceFinding]:
        buckets = self._counts[action]
        first_seen = self._first_seen.get(action)
        first_iso = first_seen.isoformat() if first_seen else None
        cur = buckets.get(cur_bucket, 0)

        # Baseline = the earlier windows, zero-filling silent gaps so a sporadic
        # action's median isn't inflated by counting only the days it fired.
        present = [b for b in buckets if b < cur_bucket]
        if present:
            start = max(min(present), cur_bucket - self.max_buckets)
            baseline = [buckets.get(b, 0) for b in range(start, cur_bucket)]
        else:
            baseline = []

        # Age of the action relative to the current window.
        if first_seen is not None:
            age_days = (ref_dt - first_seen).total_seconds() / _DAY_SECONDS
        else:
            age_days = float("inf")
        is_new = age_days <= self.new_within_days

        # 1) New action established — the core case. Recently new, now frequent.
        if is_new and cur >= self.established_min_count:
            severity = min(1.0, cur / (self.established_min_count * 2))
            return RecurrenceFinding(
                action=action,
                signal="new_established",
                reason=(
                    f"[recurrence] new action established — first seen "
                    f"{age_days:.1f}d ago, now {cur}/window"
                ),
                rate_now=float(cur),
                baseline=round(age_days, 2),
                severity=severity,
                first_seen=first_iso,
            )

        # 2) Rate spike — known action far above its own robust baseline.
        if cur > 0 and len(baseline) >= self.baseline_min_buckets:
            med = median(baseline)
            mad = median([abs(x - med) for x in baseline]) * _MAD_TO_STD
            robust_gate = med + self.spike_k * mad
            ratio_gate = self.spike_factor * med
            if med > 0 and cur >= max(ratio_gate, robust_gate):
                ratio = cur / med if med else float(cur)
                severity = min(1.0, ratio / (self.spike_factor * 2))
                return RecurrenceFinding(
                    action=action,
                    signal="rate_spike",
                    reason=(
                        f"[recurrence] rate spike — {cur}/window vs baseline "
                        f"median {med:g} ({ratio:.1f}×)"
                    ),
                    rate_now=float(cur),
                    baseline=float(med),
                    severity=severity,
                    first_seen=first_iso,
                )

        # 3) Gone silent — was regular, absent from the current window.
        if cur == 0 and not is_new and len(baseline) >= self.baseline_min_buckets:
            active = [x for x in baseline if x > 0]
            if len(active) >= self.baseline_min_buckets:
                med = median(active)
                if med >= self.silence_min_median:
                    severity = min(1.0, 0.4 + 0.15 * med)
                    return RecurrenceFinding(
                        action=action,
                        signal="gone_silent",
                        reason=(
                            f"[recurrence] gone silent — was ~{med:g}/window, "
                            f"0 in the current window"
                        ),
                        rate_now=0.0,
                        baseline=float(med),
                        severity=severity,
                        first_seen=first_iso,
                    )
        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "bucket_seconds": self.bucket_seconds,
            "max_buckets": self.max_buckets,
            "latest_bucket": self._latest_bucket,
            # bucket indices as strings so the mapping survives a JSON round-trip
            "counts": {
                action: {str(b): c for b, c in buckets.items()}
                for action, buckets in self._counts.items()
            },
            "first_seen": {a: ts.isoformat() for a, ts in self._first_seen.items()},
        }

    def from_dict(self, data: Dict[str, Any]) -> "RecurrenceDetector":
        """Load persisted state. Missing keys fall back so older files still load."""
        self._counts = {
            action: {int(b): int(c) for b, c in buckets.items()}
            for action, buckets in data.get("counts", {}).items()
        }
        self._first_seen = {}
        for action, iso in data.get("first_seen", {}).items():
            try:
                self._first_seen[action] = _as_utc(datetime.fromisoformat(iso))
            except (ValueError, TypeError):
                continue
        self._latest_bucket = data.get("latest_bucket")
        if self._latest_bucket is None and self._counts:
            self._latest_bucket = max(
                b for buckets in self._counts.values() for b in buckets
            )
        # Honour the current ring size even if the saved file was larger.
        self._prune()
        return self
