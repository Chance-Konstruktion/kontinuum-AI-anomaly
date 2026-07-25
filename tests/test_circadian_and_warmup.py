"""Wall-clock independence, and the adaptive strategy's warmup sensitivity.

Two properties discovered while investigating a CI failure that only appeared
after midnight UTC. Both are pinned here so neither can quietly come back.

1. **Verdicts must not depend on when the process runs.** Core's
   ``Neurorhythms.get_circadian_multiplier()`` reads the *local wall clock* when
   no hour is given and maps it onto a learning-rate multiplier from 0.5 (20:00)
   to 1.3 (08:00). That 2.6× swing moved the adaptive threshold, so the same
   input produced different verdicts depending on the time of day — the pipeline
   quality gate passed only between 20:00 and 22:59 UTC. ``AgentMonitor`` now
   pins a neutral phase.

2. **The adaptive strategy needs its warmup.** At ``warmup=25`` the robust
   median+MAD estimator judges on a quarter of the evidence it is tuned for, and
   a perfectly stable rhythm does trip it. That is why the quality gate runs long
   enough to reach the shipped warmup of 100 instead of lowering the bar.
"""
import datetime as _dt
from datetime import datetime, timedelta, timezone

import pytest

from kontinuum_ai_anomaly import AnomalyWatch, sequence_aware_strategy
from kontinuum_ai_anomaly.monitor import NEUTRAL_CIRCADIAN_HOUR, AgentMonitor

RHYTHM = ("plan", "act", "observe", "reflect", "done")
BASE = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen_hour(monkeypatch):
    """Pin the *wall clock* (not event time) to a chosen hour of day."""

    def _freeze(hour):
        real = _dt.datetime

        class FrozenDatetime(real):
            @classmethod
            def now(cls, tz=None):
                return real(2026, 3, 1, hour, 30, tzinfo=tz)

        import kontinuum_core.neurorhythms as nr

        monkeypatch.setattr(nr.dt if hasattr(nr, "dt") else _dt, "datetime",
                            FrozenDatetime, raising=False)
        monkeypatch.setattr(_dt, "datetime", FrozenDatetime)

    return _freeze


def _stable_run(*, circadian_hour=NEUTRAL_CIRCADIAN_HOUR, warmup=None, cycles=40):
    """Replay a fixed rhythm; return the per-event anomaly verdicts."""
    strategy = sequence_aware_strategy()
    strategy.strategies[1].early_warmup = None
    if warmup is not None:
        strategy.strategies[1].warmup = warmup
    watch = AnomalyWatch(agent_id="phase", strategy=strategy, track_recurrence=False)
    watch.monitor.circadian_hour = circadian_hour
    verdicts = []
    for cycle in range(cycles):
        for offset, action in enumerate(RHYTHM):
            result = watch.observe(
                action,
                ts=BASE + timedelta(seconds=(cycle * len(RHYTHM) + offset) * 120),
            )
            verdicts.append(result.is_anomaly)
    return verdicts


# ----------------------------------------------------------------------
# 1) Wall-clock independence
# ----------------------------------------------------------------------
def test_neutral_phase_multiplier_is_one():
    """The pinned hour is the phase where the circadian model is a no-op."""
    from kontinuum_core.neurorhythms import _circadian_base

    multiplier = 0.5 + _circadian_base(NEUTRAL_CIRCADIAN_HOUR) * 0.8
    assert multiplier == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("hour", [0, 3, 8, 12, 16, 20, 23])
def test_verdicts_are_identical_at_every_wall_clock_hour(frozen_hour, hour):
    frozen_hour(hour)
    assert _stable_run() == _stable_run(circadian_hour=NEUTRAL_CIRCADIAN_HOUR)


def test_a_stable_rhythm_stays_quiet_regardless_of_wall_clock(frozen_hour):
    """The property the quality gate asserts, checked across the whole day."""
    for hour in (0, 6, 8, 14, 20, 23):
        frozen_hour(hour)
        # Cycles chosen to reach the shipped warmup, as the quality gate does.
        assert not any(_stable_run(cycles=120)[len(RHYTHM):])


def test_pinning_is_on_by_default():
    assert AgentMonitor().circadian_hour == NEUTRAL_CIRCADIAN_HOUR


def test_pinning_can_be_disabled():
    """``None`` hands the phase back to core's own wall-clock behaviour."""
    monitor = AgentMonitor(circadian_hour=None)
    assert monitor.circadian_hour is None
    # Still ingests normally; only the phase source changes.
    assert monitor.observe("plan")["action"] == "plan"


class _EngineWithoutRhythms:
    """Stands in for a core build that has no `neurorhythms` attribute."""


class _EngineWithOldSignature:
    """Stands in for a core whose multiplier takes no `hour` argument."""

    class _Rhythms:
        def get_circadian_multiplier(self):
            return 1.0

    neurorhythms = _Rhythms()


def test_pinning_is_a_noop_on_a_core_without_the_hook():
    monitor = AgentMonitor()
    monitor.engine = _EngineWithoutRhythms()
    monitor._pin_circadian_phase(BASE)  # getattr-guarded: must not raise


def test_pinning_is_a_noop_on_an_older_multiplier_signature():
    monitor = AgentMonitor()
    monitor.engine = _EngineWithOldSignature()
    monitor._pin_circadian_phase(BASE)  # TypeError is caught: must not raise


def test_pinning_passes_the_configured_hour_to_core():
    calls = []

    class _Rhythms:
        def get_circadian_multiplier(self, hour=None):
            calls.append(hour)
            return 1.0

    class _Engine:
        neurorhythms = _Rhythms()

    monitor = AgentMonitor(circadian_hour=7)
    monitor.engine = _Engine()
    monitor._pin_circadian_phase(BASE)
    assert calls == [7]


def test_disabled_pinning_does_not_touch_core():
    calls = []

    class _Rhythms:
        def get_circadian_multiplier(self, hour=None):
            calls.append(hour)
            return 1.0

    class _Engine:
        neurorhythms = _Rhythms()

    monitor = AgentMonitor(circadian_hour=None)
    monitor.engine = _Engine()
    monitor._pin_circadian_phase(BASE)
    assert calls == []


# ----------------------------------------------------------------------
# 2) Warmup sensitivity — why the gate no longer lowers it
# ----------------------------------------------------------------------
def test_shipped_warmup_keeps_a_stable_rhythm_quiet():
    """With the default warmup of 100, a stable rhythm produces no anomalies."""
    verdicts = _stable_run(cycles=120)
    assert not any(verdicts[len(RHYTHM):])


def test_lowered_warmup_produces_false_alarms_on_a_stable_rhythm():
    """Documented weakness: at warmup=25 the same stable rhythm is flagged.

    Kept as an executable note rather than a bug — the estimator is simply being
    asked to judge on a quarter of its evidence. It is the reason the quality
    gate runs long enough to reach the real warmup.
    """
    verdicts = _stable_run(warmup=25, cycles=40)
    assert any(verdicts[len(RHYTHM):])
