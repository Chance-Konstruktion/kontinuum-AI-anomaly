"""Scoring strategies — the robust anomaly verdict layer.

Core gives a per-event ``surprise`` and a raw ``anomaly`` flag, but that flag is
jittery on short runs (see :mod:`ai_kontinuum_monitor.monitor`). This layer sits
*on top* and turns the raw signal into a stable verdict, which is the first
reason this package earns its own existence:

* :class:`NoveltyStrategy` — a never-before-seen action is anomalous. This is
  the reliable signal (SPEC.md §2) and is stable at any run length.
* :class:`AdaptiveThresholdStrategy` — a **known** action is judged against a
  robust, *per-stream* baseline (median + k·MAD of that action's own surprise
  history), so "this familiar action just became weirdly surprising" is caught
  without the noisy global flag.
* :class:`CompositeStrategy` — OR/AND aggregation over several strategies and,
  via :meth:`AnomalyScorer.score`, aggregation across multiple action streams.

Each strategy returns an :class:`AnomalyScore`.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Deque, Dict, List, Optional, Protocol

# median-absolute-deviation → std-equivalent, matching core's own convention.
_MAD_TO_STD = 1.4826


@dataclass
class AnomalyScore:
    """The verdict for a single observation."""

    action: str
    is_anomaly: bool
    score: float  # 0-1 severity; higher = more anomalous
    surprise: float
    threshold: float
    is_novel: bool
    reasons: List[str] = field(default_factory=list)
    strategy: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "is_anomaly": self.is_anomaly,
            "score": round(self.score, 4),
            "surprise": round(self.surprise, 4),
            "threshold": round(self.threshold, 4),
            "is_novel": self.is_novel,
            "reasons": list(self.reasons),
            "strategy": self.strategy,
        }


class ScoringStrategy(Protocol):
    """A strategy turns one monitor observation into an :class:`AnomalyScore`.

    ``obs`` is the dict returned by :meth:`AgentMonitor.observe`.
    """

    name: str

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore: ...


class NoveltyStrategy:
    """Flag the first occurrence of any action as anomalous.

    This is the reliable, run-length-independent signal: a never-seen action is
    novel by definition. Its severity is the raw surprise (novel actions have
    no learned expectation, so surprise is high).
    """

    name = "novelty"

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        novel = bool(obs.get("is_novel"))
        surprise = float(obs.get("surprise", 0.0))
        reasons = ["never-seen action"] if novel else []
        return AnomalyScore(
            action=obs["action"],
            is_anomaly=novel,
            score=surprise if novel else 0.0,
            surprise=surprise,
            threshold=float(obs.get("threshold", 0.0)),
            is_novel=novel,
            reasons=reasons,
            strategy=self.name,
        )


class AdaptiveThresholdStrategy:
    """Per-stream robust outlier detection for *known* actions.

    Keeps a rolling window of each action's surprise values and flags the
    action when its current surprise exceeds ``median + k·(MAD_TO_STD·MAD)`` of
    its own history — the same robust estimator core uses globally, but scoped
    to a single action stream so a chatty benign action can't raise the bar for
    a rare critical one. Novel actions are always flagged (no baseline yet).

    Args:
        window: Rolling window size per action.
        k: MAD multiplier; higher = more conservative (fewer flags).
        warmup: Minimum samples before the adaptive test activates; below it,
            only novelty flags.
        floor: Absolute surprise floor — never flag below this even if a stream
            is unusually calm, to avoid alerting on noise.
        min_spread: Minimum margin the threshold must sit above the stream's
            median. Without it a very *steady* stream collapses MAD→0 and every
            tiny wobble trips the flag; requiring a real jump (default 0.2) means
            only a clear spike above a known action's own normal is anomalous.
    """

    name = "adaptive"

    def __init__(
        self,
        window: int = 300,
        k: float = 3.0,
        warmup: int = 100,
        floor: float = 0.4,
        min_spread: float = 0.2,
    ):
        self.window = window
        self.k = k
        self.warmup = warmup
        self.floor = floor
        self.min_spread = min_spread
        self._history: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )

    def _threshold(self, samples: List[float]) -> float:
        med = median(samples)
        mad = median([abs(x - med) for x in samples])
        # Robust spread, but never below min_spread so a flat stream can't
        # collapse the band onto its own median.
        spread = max(self.min_spread, self.k * _MAD_TO_STD * mad)
        return med + spread

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        action = obs["action"]
        surprise = float(obs.get("surprise", 0.0))
        novel = bool(obs.get("is_novel"))
        hist = self._history[action]
        samples = list(hist)

        reasons: List[str] = []
        is_anomaly = False
        threshold = self.floor

        if novel:
            is_anomaly = True
            reasons.append("never-seen action")
        elif len(samples) >= self.warmup:
            threshold = max(self.floor, self._threshold(samples))
            if surprise >= threshold:
                is_anomaly = True
                reasons.append(
                    f"surprise {surprise:.2f} ≥ per-stream threshold "
                    f"{threshold:.2f}"
                )

        # Record AFTER evaluating so the current event never shifts its own
        # baseline (mirrors core's pre-read of the anomaly threshold).
        hist.append(surprise)

        score = 0.0
        if is_anomaly:
            span = max(1e-6, 1.0 - threshold)
            score = max(0.0, min(1.0, (surprise - threshold) / span)) if not novel else surprise
        return AnomalyScore(
            action=action,
            is_anomaly=is_anomaly,
            score=score,
            surprise=surprise,
            threshold=threshold,
            is_novel=novel,
            reasons=reasons,
            strategy=self.name,
        )


class CompositeStrategy:
    """Combine several strategies with OR (default) or AND aggregation.

    OR is the sensible default for anomaly detection: any strategy raising a
    flag is enough. The combined score is the max (OR) / min (AND) of the
    component scores, and reasons are merged.
    """

    name = "composite"

    def __init__(self, strategies: List[ScoringStrategy], mode: str = "or"):
        if mode not in ("or", "and"):
            raise ValueError("mode must be 'or' or 'and'")
        if not strategies:
            raise ValueError("CompositeStrategy needs at least one strategy")
        self.strategies = strategies
        self.mode = mode

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        parts = [s.evaluate(obs) for s in self.strategies]
        flags = [p.is_anomaly for p in parts]
        is_anomaly = any(flags) if self.mode == "or" else all(flags)
        scores = [p.score for p in parts]
        score = max(scores) if self.mode == "or" else min(scores)
        # Merge reasons, keeping each distinct underlying reason once (several
        # strategies flagging "never-seen action" shouldn't repeat it), but
        # tagging it with the first strategy that raised it.
        reasons: List[str] = []
        seen_reasons: set[str] = set()
        for p in parts:
            if not p.is_anomaly:
                continue
            for r in p.reasons:
                if r in seen_reasons:
                    continue
                seen_reasons.add(r)
                reasons.append(f"[{p.strategy}] {r}")
        base = parts[0]
        return AnomalyScore(
            action=base.action,
            is_anomaly=is_anomaly,
            score=score,
            surprise=base.surprise,
            threshold=base.threshold,
            is_novel=base.is_novel,
            reasons=reasons,
            strategy=f"{self.name}({self.mode})",
        )


def default_strategy() -> CompositeStrategy:
    """The recommended default: novelty OR per-stream adaptive threshold.

    Robust at any run length — novelty carries short runs, the adaptive test
    takes over as each stream accumulates history.
    """
    return CompositeStrategy(
        [NoveltyStrategy(), AdaptiveThresholdStrategy()], mode="or"
    )


class AnomalyScorer:
    """Applies a :class:`ScoringStrategy` and tracks per-stream aggregates.

    Beyond the per-event verdict it maintains lightweight counters per action
    stream (observations, anomalies, mean surprise) so a caller can aggregate
    "which streams have been noisy" across the whole run — the multi-stream
    aggregation the raw core engine does not offer.
    """

    def __init__(self, strategy: Optional[ScoringStrategy] = None):
        self.strategy: ScoringStrategy = strategy or default_strategy()
        self._counts: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"observations": 0, "anomalies": 0, "surprise_sum": 0.0}
        )

    def score(self, obs: Dict[str, Any]) -> AnomalyScore:
        result = self.strategy.evaluate(obs)
        c = self._counts[result.action]
        c["observations"] += 1
        c["surprise_sum"] += result.surprise
        if result.is_anomaly:
            c["anomalies"] += 1
        return result

    def stream_stats(self) -> Dict[str, Dict[str, float]]:
        """Aggregated per-stream stats across everything scored so far."""
        out: Dict[str, Dict[str, float]] = {}
        for action, c in self._counts.items():
            n = c["observations"] or 1
            out[action] = {
                "observations": int(c["observations"]),
                "anomalies": int(c["anomalies"]),
                "anomaly_rate": round(c["anomalies"] / n, 4),
                "mean_surprise": round(c["surprise_sum"] / n, 4),
            }
        return out
