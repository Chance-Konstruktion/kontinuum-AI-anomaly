"""Time-pattern strategies (Stufe 2 of the measurement ticket).

The Stufe-1 measurement bench proved the lever is NOT the core path but the
TIME patterns: burst (``schwall``), silence (``funkstille``) and off-hours
work (``ungewohnte-uhrzeit``) are caught only by the B2 baseline, because
only B2 counts windows itself — and the core's burst gate eats a burst
before the engine ever sees it. These three strategies close exactly that
gap, in the monitor layer, core untouched, counting BEFORE any gate:

* :class:`SchwallStrategy` — rolling rate window: too many events per
  ``fenster_s`` compared to the stream's own window medians.
* :class:`FunkstilleStrategy` — an inter-event gap beyond ``funkstille_s``
  whose midpoint lies in an hour the agent has already been seen working
  (a night pause in never-seen hours is the evening off, not radio
  silence).
* :class:`StundenprofilStrategy` — an event in a local hour never seen
  before, only after the day shape has repeated (``min_tage`` distinct
  calendar days) and the stream is long enough (``stunden_warmlauf``).

Honesty rules, same school as the benchmarks' B2 and the package's own
adaptive/sequence strategies:

* **Judge first, learn after.** An event is only judged by what came
  before it; it can never shift its own baseline.
* **No randomness, no wall clock.** Only event timestamps and counted
  facts; the same event sequence yields the same verdict sequence.
* **The thresholds are named, not hidden.** Defaults mirror the B2
  baseline of the measurement bench on purpose: a candidate whose
  settings one had to guess would be a poor benchmark peer.

Timestamps: the strategies read ``obs["ts"]`` (a tz-aware datetime, UTC
after the monitor's normalization). A constant UTC offset preserves the
unseen-hour semantics bijectively, so hour profiles learned in UTC judge
local-time off-hours correctly.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from statistics import median
from typing import Any, Deque, Dict, List, Optional, Set

from .scoring import AnomalyScore, CompositeStrategy, ScoringStrategy


def _ts_aus(obs: Dict[str, Any]) -> Optional[datetime]:
    """The observation's timestamp, or ``None`` if the caller withheld it.

    Without a timestamp no time pattern can be judged — the strategies
    stay honest and inert rather than guessing.
    """
    ts = obs.get("ts")
    if isinstance(ts, datetime):
        return ts
    return None


class SchwallStrategy:
    """Flag bursts: too many events inside a rolling time window.

    Keeps a deque of recent event timestamps and a record of past window
    occupancies. A window count is a burst when it reaches
    ``max(schwall_min, schwall_faktor * median(past occupancies))`` —
    an absolute floor so short streams cannot trip on noise, and a
    relative factor so a naturally chatty agent's bar rises with its own
    rhythm. Judgement activates only after ``warmlauf`` windows, exactly
    like the B2 baseline.
    """

    name = "schwall"

    def __init__(
        self,
        fenster_s: float = 60.0,
        schwall_min: int = 10,
        schwall_faktor: float = 5.0,
        warmlauf: int = 100,
    ) -> None:
        self.fenster_s = float(fenster_s)
        self.schwall_min = int(schwall_min)
        self.schwall_faktor = float(schwall_faktor)
        self.warmlauf = int(warmlauf)
        self._im_fenster: Deque[datetime] = deque()
        self._fenster_staende: List[int] = []

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        ts = _ts_aus(obs)
        action = str(obs.get("action", ""))
        surprise = float(obs.get("surprise", 0.0))
        if ts is None:
            return AnomalyScore(
                action=action, is_anomaly=False, score=0.0, surprise=surprise,
                threshold=float(obs.get("threshold", 0.0)),
                is_novel=bool(obs.get("is_novel")),
                reasons=[], strategy=self.name,
            )

        # Judge — with what came before (this event not yet in the window).
        while (self._im_fenster
               and (ts - self._im_fenster[0]).total_seconds() > self.fenster_s):
            self._im_fenster.popleft()
        rate = len(self._im_fenster) + 1  # the current event counts
        schwelle: Optional[float] = None
        schwall = False
        if len(self._fenster_staende) >= self.warmlauf:
            schwelle = max(
                float(self.schwall_min),
                self.schwall_faktor * float(median(self._fenster_staende)),
            )
            schwall = rate >= schwelle

        # Learn — after the verdict.
        self._im_fenster.append(ts)
        self._fenster_staende.append(rate)

        reasons: List[str] = []
        if schwall and schwelle is not None:
            reasons.append(
                f"burst: {rate} events in {self.fenster_s:.0f}s window "
                f"(threshold {schwelle:.0f})"
            )
        return AnomalyScore(
            action=action,
            is_anomaly=schwall,
            score=min(1.0, rate / schwelle) if (schwall and schwelle) else 0.0,
            surprise=surprise,
            threshold=float(obs.get("threshold", 0.0)),
            is_novel=bool(obs.get("is_novel")),
            reasons=reasons,
            strategy=self.name,
        )


class FunkstilleStrategy:
    """Flag the first event after a suspiciously long silence.

    A gap counts as radio silence when it exceeds ``funkstille_s`` AND the
    midpoint of the hole lies in an hour the agent has already been seen
    working: the night pause between two workdays falls into never-seen
    hours and is the evening off, not an outage (the B2 school).
    """

    name = "funkstille"

    def __init__(self, funkstille_s: float = 7200.0) -> None:
        self.funkstille_s = float(funkstille_s)
        self._letzter_ts: Optional[datetime] = None
        self._stunden: Set[int] = set()

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        ts = _ts_aus(obs)
        action = str(obs.get("action", ""))
        surprise = float(obs.get("surprise", 0.0))
        if ts is None:
            return AnomalyScore(
                action=action, is_anomaly=False, score=0.0, surprise=surprise,
                threshold=float(obs.get("threshold", 0.0)),
                is_novel=bool(obs.get("is_novel")),
                reasons=[], strategy=self.name,
            )

        # Judge — the hole to the PREVIOUS event, hours learned before it.
        stille = False
        loch_s: Optional[float] = None
        if self._letzter_ts is not None:
            loch_s = (ts - self._letzter_ts).total_seconds()
            if loch_s > self.funkstille_s:
                mitte = self._letzter_ts + (ts - self._letzter_ts) / 2
                if mitte.hour in self._stunden:
                    stille = True

        # Learn — after the verdict.
        self._letzter_ts = ts
        self._stunden.add(ts.hour)

        reasons: List[str] = []
        if stille and loch_s is not None:
            reasons.append(
                f"radio silence: {loch_s / 3600.0:.1f}h gap, midpoint in a "
                "seen hour"
            )
        return AnomalyScore(
            action=action,
            is_anomaly=stille,
            score=(min(1.0, loch_s / (2.0 * self.funkstille_s))
                   if stille and loch_s else 0.0),
            surprise=surprise,
            threshold=float(obs.get("threshold", 0.0)),
            is_novel=bool(obs.get("is_novel")),
            reasons=reasons,
            strategy=self.name,
        )


class StundenprofilStrategy:
    """Flag work in a local hour never seen before.

    Activates only once the day shape has had a chance to establish
    itself: at least ``min_tage`` distinct calendar days delivered events
    AND at least ``stunden_warmlauf`` events total. Before that, every
    new hour is just an unexplored schedule, not an anomaly (the B2
    school — a stream living in its activity window has seen every one
    of its hours after one repeated day).
    """

    name = "stundenprofil"

    def __init__(self, stunden_warmlauf: int = 150, min_tage: int = 2) -> None:
        self.stunden_warmlauf = int(stunden_warmlauf)
        self.min_tage = int(min_tage)
        self._stunden: Set[int] = set()
        self._tage: Set[str] = set()
        self._ereignisse = 0

    def evaluate(self, obs: Dict[str, Any]) -> AnomalyScore:
        ts = _ts_aus(obs)
        action = str(obs.get("action", ""))
        surprise = float(obs.get("surprise", 0.0))
        if ts is None:
            return AnomalyScore(
                action=action, is_anomaly=False, score=0.0, surprise=surprise,
                threshold=float(obs.get("threshold", 0.0)),
                is_novel=bool(obs.get("is_novel")),
                reasons=[], strategy=self.name,
            )

        # Judge — with the hours and days learned BEFORE this event.
        stunde_fremd = (
            len(self._tage) >= self.min_tage
            and self._ereignisse >= self.stunden_warmlauf
            and ts.hour not in self._stunden
        )

        # Learn — after the verdict.
        self._stunden.add(ts.hour)
        self._tage.add(ts.date().isoformat())
        self._ereignisse += 1

        reasons: List[str] = []
        if stunde_fremd:
            reasons.append(
                f"off-hours: hour {ts.hour:02d} never seen "
                f"({self._ereignisse} events over {len(self._tage)} days)"
            )
        return AnomalyScore(
            action=action,
            is_anomaly=stunde_fremd,
            score=0.5 if stunde_fremd else 0.0,
            surprise=surprise,
            threshold=float(obs.get("threshold", 0.0)),
            is_novel=bool(obs.get("is_novel")),
            reasons=reasons,
            strategy=self.name,
        )


def zeitmuster_strategy() -> CompositeStrategy:
    """The three time-pattern strategies, OR-combined.

    Rate window, silence gap and hour profile — the levers the Stufe-1
    bench named. Compose with :func:`kontinuum_ai_anomaly.scoring.
    sequence_aware_strategy` to get the full Stufe-2 candidate.
    """
    return CompositeStrategy(
        [
            SchwallStrategy(),
            FunkstilleStrategy(),
            StundenprofilStrategy(),
        ],
        mode="or",
    )


__all__ = [
    "SchwallStrategy",
    "FunkstilleStrategy",
    "StundenprofilStrategy",
    "zeitmuster_strategy",
]
