"""Tests for the time-pattern strategies (Stufe 2, zeitmuster).

Deterministic by construction: fixed timestamps, no randomness, the
"judge first, learn after" school made explicit — an event can never
shift the baseline it is judged against. The scenarios mirror the
benchmarks' B2 semantics on purpose: the Stufe-2 candidate is measured
against exactly that baseline, so the unit tests pin the same laws.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kontinuum_ai_anomaly import AnomalyWatch
from kontinuum_ai_anomaly.monitor import AgentMonitor
from kontinuum_ai_anomaly.presets import builtin_presets, import_preset, export_preset
from kontinuum_ai_anomaly.scoring import AnomalyScorer
from kontinuum_ai_anomaly.zeitmuster import (
    FunkstilleStrategy,
    SchwallStrategy,
    StundenprofilStrategy,
    zeitmuster_strategy,
)

UTC = timezone.utc


def _obs(action: str = "deploy", ts: datetime | None = None, **extra):
    o = {"action": action, "surprise": 0.1, "threshold": 0.4,
         "is_novel": False, "learning_state": "mature"}
    if ts is not None:
        o["ts"] = ts
    o.update(extra)
    return o


# ---------------------------------------------------------------------------
# Schwall — the rate window
# ---------------------------------------------------------------------------
def test_schwall_paced_stream_stays_quiet():
    """A normal 30-second rhythm never reaches the burst threshold."""
    s = SchwallStrategy()
    start = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)
    urteile = [
        s.evaluate(_obs(ts=start + timedelta(seconds=30 * i)))
        for i in range(150)
    ]
    assert not any(u.is_anomaly for u in urteile)


def test_schwall_burst_is_flagged_after_warmup():
    """30 events in ~15 s trip the window once the 100-window warmup is paid."""
    s = SchwallStrategy()
    start = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)
    # Warm-up: 120 paced events (window standings >= warmlauf).
    for i in range(120):
        s.evaluate(_obs(ts=start + timedelta(seconds=30 * i)))
    # The burst: 30 events at 0.5 s spacing.
    burst_start = start + timedelta(seconds=30 * 120)
    urteile = [
        s.evaluate(_obs(ts=burst_start + timedelta(seconds=0.5 * j)))
        for j in range(30)
    ]
    flags = [u for u in urteile if u.is_anomaly]
    assert flags, "the burst must be flagged after warm-up"
    assert all("burst" in r for u in flags for r in u.reasons)


def test_schwall_burst_before_warmup_stays_quiet():
    """Before 100 window standings the strategy stays inert — honest warm-up."""
    s = SchwallStrategy()
    start = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)
    urteile = [
        s.evaluate(_obs(ts=start + timedelta(seconds=0.5 * j)))
        for j in range(40)
    ]
    assert not any(u.is_anomaly for u in urteile)


def test_schwall_without_ts_is_inert():
    s = SchwallStrategy()
    urteil = s.evaluate(_obs())
    assert not urteil.is_anomaly


# ---------------------------------------------------------------------------
# Funkstille — the suspicious gap
# ---------------------------------------------------------------------------
def test_funkstille_hole_midpoint_in_seen_hour_is_flagged():
    """A >2h hole whose midpoint lies in a working hour is radio silence."""
    s = FunkstilleStrategy()
    day = datetime(2026, 3, 2, tzinfo=UTC)
    # Working hours 9..17 established by a paced day.
    for h in range(9, 18):
        s.evaluate(_obs(ts=day + timedelta(hours=h, minutes=10)))
    # The hole: last event 10:00, return 14:30 — 4.5 h, midpoint ~12:15 seen.
    letzte = s.evaluate(_obs(ts=day + timedelta(hours=10)))
    assert not letzte.is_anomaly
    rueckkehr = s.evaluate(_obs(ts=day + timedelta(hours=14, minutes=30)))
    assert rueckkehr.is_anomaly
    assert any("silence" in r for r in rueckkehr.reasons)


def test_funkstille_night_pause_is_the_evening_off():
    """A 15h overnight gap with its midpoint in never-seen hours stays quiet."""
    s = FunkstilleStrategy()
    day1 = datetime(2026, 3, 2, tzinfo=UTC)
    day2 = datetime(2026, 3, 3, tzinfo=UTC)
    for h in range(9, 18):
        s.evaluate(_obs(ts=day1 + timedelta(hours=h, minutes=10)))
    feierabend = s.evaluate(_obs(ts=day1 + timedelta(hours=17, minutes=55)))
    assert not feierabend.is_anomaly
    morgen = s.evaluate(_obs(ts=day2 + timedelta(hours=9, minutes=5)))
    assert not morgen.is_anomaly, "the night pause is not radio silence"


# ---------------------------------------------------------------------------
# Stundenprofil — the unseen local hour
# ---------------------------------------------------------------------------
def test_stundenprofil_off_hour_flagged_after_day_shape():
    """Work at 03:00 after two repeated days of 9..17 is off-hours."""
    s = StundenprofilStrategy()
    tage = [datetime(2026, 3, d, tzinfo=UTC) for d in (2, 3)]
    for tag in tage:
        for i in range(80):  # 2 × 80 = 160 >= stunden_warmlauf
            s.evaluate(_obs(ts=tag + timedelta(hours=9, minutes=7 * i)))
    nacht = s.evaluate(_obs(ts=datetime(2026, 3, 4, 3, 0, tzinfo=UTC)))
    assert nacht.is_anomaly
    assert any("off-hours" in r for r in nacht.reasons)


def test_stundenprofil_before_day_shape_stays_quiet():
    """One day of history: a new hour is an unexplored schedule, not an anomaly."""
    s = StundenprofilStrategy()
    tag = datetime(2026, 3, 2, tzinfo=UTC)
    for i in range(100):
        s.evaluate(_obs(ts=tag + timedelta(hours=9, minutes=7 * i)))
    abend = s.evaluate(_obs(ts=tag + timedelta(hours=21)))
    assert not abend.is_anomaly


# ---------------------------------------------------------------------------
# The observation carries its timestamp
# ---------------------------------------------------------------------------
def test_monitor_obs_carries_ts():
    """AgentMonitor.observe() exposes the (UTC-normalized) event timestamp."""
    m = AgentMonitor(agent_id="test")
    ts = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    obs = m.observe("deploy", ts=ts)
    assert obs["ts"] == datetime(2026, 3, 2, 11, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Integration: watch + composite + preset round-trip
# ---------------------------------------------------------------------------
def test_watch_with_zeitmuster_flags_burst():
    """The full Stufe-2 composite flags a burst through AnomalyWatch."""
    w = AnomalyWatch(agent_id="test", strategy=zeitmuster_strategy())
    start = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)
    for i in range(120):
        w.observe("deploy", ts=start + timedelta(seconds=30 * i))
    flags = [
        w.observe("deploy", ts=start + timedelta(seconds=30 * 120 + 0.5 * j))
        for j in range(30)
    ]
    assert any(f.is_anomaly for f in flags)


def test_zeitmuster_preset_round_trip():
    """The zeitmuster preset survives an export/import round-trip."""
    strat = builtin_presets()["zeitmuster"]
    hin = export_preset(strat, name="zeitmuster-test")
    zurueck = import_preset(hin)
    scorer_hin = AnomalyScorer(strategy=strat)
    scorer_zur = AnomalyScorer(strategy=zurueck)
    ts = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)
    start = ts
    for i in range(110):
        scorer_hin.score(_obs("deploy", ts=start + timedelta(seconds=30 * i)))
        scorer_zur.score(_obs("deploy", ts=start + timedelta(seconds=30 * i)))
    burst = start + timedelta(seconds=30 * 110)
    a = scorer_hin.score(_obs("deploy", ts=burst + timedelta(seconds=0.5)))
    b = scorer_zur.score(_obs("deploy", ts=burst + timedelta(seconds=0.5)))
    assert a.is_anomaly == b.is_anomaly
