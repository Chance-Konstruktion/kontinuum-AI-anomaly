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
        warmup: Minimum samples before the full adaptive test activates; below
            it, only novelty and the optional early test flag.
        floor: Absolute surprise floor — never flag below this even if a stream
            is unusually calm, to avoid alerting on noise.
        min_spread: Minimum margin the threshold must sit above the stream's
            median. Without it a very *steady* stream collapses MAD→0 and every
            tiny wobble trips the flag; requiring a real jump (default 0.2) means
            only a clear spike above a known action's own normal is anomalous.
        early_warmup: Sample count at which a *provisional* test engages, before
            the full ``warmup`` is reached. This lets short or very stable
            streams react sooner instead of staying blind until 100 samples
            (the previous behaviour was slow to react on short runs). During the
            early window the threshold is widened by ``early_k_boost`` so the
            provisional verdict stays conservative on thin evidence. Set to
            ``None`` (or ``>= warmup``) to disable and keep the old behaviour.
        early_k_boost: Extra margin applied to ``min_spread`` during the early
            window (added, not multiplied), keeping early flags to clear spikes.
    """

    name = "adaptive"

    def __init__(
        self,
        window: int = 300,
        k: float = 3.0,
        warmup: int = 100,
        floor: float = 0.4,
        min_spread: float = 0.2,
        early_warmup: Optional[int] = 20,
        early_k_boost: float = 0.15,
    ):
        self.window = window
        self.k = k
        self.warmup = warmup
        self.floor = floor
        self.min_spread = min_spread
        self.early_warmup = early_warmup
        self.early_k_boost = early_k_boost
        self._history: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self.window)
        )

    def _threshold(self, samples: List[float], min_spread: Optional[float] = None) -> float:
        med = median(samples)
        mad = median([abs(x - med) for x in samples])
        # Robust spread, but never below min_spread so a flat stream can't
        # collapse the band onto its own median.
        floor_spread = self.min_spread if min_spread is None else min_spread
        spread = max(floor_spread, self.k * _MAD_TO_STD * mad)
        return med + spread

    def _early_active(self, n: int) -> bool:
        return (
            self.early_warmup is not None
            and self.early_warmup <= n < self.warmup
        )

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
        elif self._early_active(len(samples)):
            # Provisional test on partial history: same robust estimator with a
            # widened spread so thin evidence only trips on a clear spike.
            threshold = max(
                self.floor,
                self._threshold(samples, min_spread=self.min_spread + self.early_k_boost),
            )
            if surprise >= threshold:
                is_anomaly = True
                reasons.append(
                    f"surprise {surprise:.2f} ≥ provisional threshold "
                    f"{threshold:.2f} (early, {len(samples)}/{self.warmup} samples)"
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


class SequenceStrategy:
    """Order / transition anomalies: catch an *unexpected next action*.

    Core's own sequence-awareness is weak on short runs (SPEC §2), and that is a
    *core* limitation — so this strategy adds the missing signal **in the monitor
    layer** instead, without touching core. It learns a first-order transition
    model: for each action, how often each *following* action occurs. Once a
    predecessor has been seen enough times (``min_context``), a transition whose
    learned probability falls at or below ``min_prob`` — including a never-before-
    seen transition — is flagged as a sequence anomaly.

    This is deliberately first-order (bigram). It complements, and does not
    replace, :class:`NoveltyStrategy`: novelty catches a brand-new *action*, this
    catches a familiar action arriving in an unfamiliar *order*.

    Args:
        min_context: Minimum times the predecessor must have been observed
            before its outgoing transitions are judged (avoids flagging on thin
            evidence).
        min_prob: A transition at or below this learned probability is anomalous.
            ``0.0`` flags only never-seen transitions; the default also catches
            very rare ones.
    """

    name = "sequence"

    def __init__(self, min_context: int = 20, min_prob: float = 0.02):
        self.min_context = min_context
        self.min_prob = min_prob
        self._transitions: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._outgoing: Dict[str, int] = defaultdict(int)
        self._prev: Optional[str] = None

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        action = obs["action"]
        surprise = float(obs.get("surprise", 0.0))
        novel = bool(obs.get("is_novel"))
        prev = self._prev

        reasons: List[str] = []
        is_anomaly = False
        score = 0.0
        # Threshold field carries the probability bar for transparency.
        threshold = self.min_prob

        if prev is not None and self._outgoing[prev] >= self.min_context and not novel:
            total = self._outgoing[prev]
            count = self._transitions[prev].get(action, 0)
            prob = count / total if total else 0.0
            if prob <= self.min_prob:
                is_anomaly = True
                score = round(1.0 - prob, 4)
                kind = "never-seen" if count == 0 else "rare"
                reasons.append(
                    f"{kind} transition {prev!r}→{action!r} "
                    f"(p={prob:.3f} ≤ {self.min_prob:.3f})"
                )

        # Learn the transition AFTER judging it, so the current event never
        # dilutes its own rarity (mirrors the adaptive strategy's pre-read).
        if prev is not None:
            self._transitions[prev][action] += 1
            self._outgoing[prev] += 1
        self._prev = action

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


def sequence_aware_strategy() -> CompositeStrategy:
    """Novelty OR per-stream adaptive threshold OR first-order sequence.

    Adds :class:`SequenceStrategy` on top of :func:`default_strategy`, so an
    action arriving in an unexpected *order* is caught in addition to novel and
    per-stream-outlier actions — the sequence-awareness GrokAI flagged as
    missing, provided entirely in the monitor layer (core untouched).
    """
    return CompositeStrategy(
        [NoveltyStrategy(), AdaptiveThresholdStrategy(), SequenceStrategy()],
        mode="or",
    )


class AnomalyScorer:
    """Applies a :class:`ScoringStrategy` and tracks per-stream aggregates.

    Beyond the per-event verdict it maintains lightweight counters per action
    stream (observations, anomalies, mean surprise) so a caller can aggregate
    "which streams have been noisy" across the whole run — the multi-stream
    aggregation the raw core engine does not offer.
    """

    # Core's learning-state thresholds (SPEC.md §5.4): cold_start < 100 events,
    # warming < 2000, then mature. Used to express learning as a smooth 0-1
    # progress toward maturity alongside core's authoritative state label.
    MATURE_EVENTS = 2000
    # Rolling window used to estimate the *trend* of surprise (recent mean vs.
    # older mean). Small enough to react, large enough to be stable.
    _TREND_WINDOW = 50

    def __init__(self, strategy: Optional[ScoringStrategy] = None):
        self.strategy: ScoringStrategy = strategy or default_strategy()
        self._counts: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"observations": 0, "anomalies": 0, "surprise_sum": 0.0}
        )
        self._recent_surprise: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=self._TREND_WINDOW)
        )
        self._total_observations = 0
        self._learning_state = "cold_start"

    def score(self, obs: Dict[str, Any]) -> AnomalyScore:
        result = self.strategy.evaluate(obs)
        c = self._counts[result.action]
        c["observations"] += 1
        c["surprise_sum"] += result.surprise
        if result.is_anomaly:
            c["anomalies"] += 1
        self._recent_surprise[result.action].append(result.surprise)
        self._total_observations += 1
        state = obs.get("learning_state")
        if state:
            self._learning_state = state
        return result

    @staticmethod
    def _trend(samples: List[float]) -> float:
        """Signed surprise trend: recent-half mean minus older-half mean.

        Positive means this stream is getting *more* surprising over time
        (drift / degrading predictability); negative means it is settling.
        """
        if len(samples) < 4:
            return 0.0
        half = len(samples) // 2
        older = samples[:half]
        recent = samples[half:]
        return (sum(recent) / len(recent)) - (sum(older) / len(older))

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
                "surprise_trend": round(self._trend(list(self._recent_surprise[action])), 4),
            }
        return out

    def learning_progress(self) -> float:
        """Fraction (0-1) toward a *mature* model, from observed event volume.

        Capped at 1.0. This mirrors core's own maturity thresholds
        (SPEC.md §5.4) so callers get a single "learning progress %" number
        without having to read the discrete ``learning_state`` label.
        """
        return min(1.0, self._total_observations / self.MATURE_EVENTS)

    def metrics(self) -> Dict[str, Any]:
        """Run-wide metrics: learning progress, surprise trend, anomaly rate.

        Complements :meth:`stream_stats` (per-stream) with the aggregate numbers
        a dashboard or health check wants at a glance.
        """
        total_obs = self._total_observations or 1
        total_anom = sum(int(c["anomalies"]) for c in self._counts.values())
        total_surprise = sum(c["surprise_sum"] for c in self._counts.values())
        all_recent: List[float] = []
        for dq in self._recent_surprise.values():
            all_recent.extend(dq)
        return {
            "observations": self._total_observations,
            "streams": len(self._counts),
            "anomalies": total_anom,
            "anomaly_rate": round(total_anom / total_obs, 4),
            "mean_surprise": round(total_surprise / total_obs, 4),
            "surprise_trend": round(self._trend(all_recent), 4),
            "learning_state": self._learning_state,
            "learning_progress": round(self.learning_progress(), 4),
            "learning_progress_pct": round(100 * self.learning_progress(), 1),
        }
