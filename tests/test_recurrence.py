"""Tests for recurrence detection — the signal novelty structurally can't give.

Covers the three signals (new-established / rate-spike / gone-silent), the
no-false-alarm guarantee on a steady rhythm, the regression that the live
per-event verdict is unchanged by recurrence tracking, and a persistence
round-trip including the windowed buckets.
"""
from datetime import datetime, timedelta, timezone

from kontinuum_ai_anomaly import (
    AlertRouter,
    AnomalyWatch,
    CallbackSink,
    RecurrenceDetector,
)

DAY = timedelta(days=1)
T0 = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def _detector(**kw):
    # Small, explicit thresholds so the day-bucketed scenarios are unambiguous.
    cfg = dict(
        established_min_count=5,
        baseline_min_buckets=3,
        spike_factor=3.0,
        spike_k=4.0,
        new_within_days=7.0,
        silence_min_median=1.0,
    )
    cfg.update(kw)
    return RecurrenceDetector(**cfg)


# --------------------------------------------------------------------------
# 1. New action established — the core case novelty misses after the 1st event
# --------------------------------------------------------------------------
def test_new_action_established():
    det = _detector()
    # Introduce it once on day 0, then run it frequently on day 1.
    det.record("deploy", ts=T0)
    for i in range(8):
        det.record("deploy", ts=T0 + DAY + timedelta(minutes=i))
    findings = det.report(now=T0 + DAY + timedelta(hours=1))
    hit = [f for f in findings if f.action == "deploy"]
    assert hit and hit[0].signal == "new_established"
    assert "new action established" in hit[0].reason
    assert hit[0].rate_now == 8


def test_new_established_via_watch_while_is_anomaly_is_false():
    """Acceptance: after the first event `is_anomaly` is False, yet recurrence
    still surfaces the recurring action."""
    watch = AnomalyWatch(agent_id="bot", recurrence=_detector())
    first = watch.observe("scrape", ts=T0)
    assert first.is_anomaly  # novelty fires once
    # Same action, many times over the next day — novelty stays silent.
    for i in range(8):
        r = watch.observe("scrape", ts=T0 + DAY + timedelta(minutes=i))
        assert not r.is_anomaly
    findings = watch.check_recurrence(now=T0 + DAY + timedelta(hours=1))
    assert any(f.action == "scrape" and f.signal == "new_established" for f in findings)


# --------------------------------------------------------------------------
# 2. Rate spike — known action far above its own robust baseline
# --------------------------------------------------------------------------
def test_rate_spike():
    det = _detector(new_within_days=0.0)  # not "new" — force the spike path
    # Stable baseline: 2/day for 6 days.
    for d in range(6):
        for i in range(2):
            det.record("poll", ts=T0 + d * DAY + timedelta(minutes=i))
    # Day 6: rate jumps 10× to 20.
    for i in range(20):
        det.record("poll", ts=T0 + 6 * DAY + timedelta(minutes=i))
    findings = det.report(now=T0 + 6 * DAY + timedelta(hours=1))
    hit = [f for f in findings if f.action == "poll"]
    assert hit and hit[0].signal == "rate_spike"
    assert hit[0].rate_now == 20 and hit[0].baseline == 2


# --------------------------------------------------------------------------
# 3. Gone silent — regular action absent from the current window
# --------------------------------------------------------------------------
def test_gone_silent():
    det = _detector(new_within_days=0.0)
    # "heartbeat" fires 3/day on days 0-4, and a second action keeps the clock
    # moving on day 5 so there IS a current window.
    for d in range(5):
        for i in range(3):
            det.record("heartbeat", ts=T0 + d * DAY + timedelta(minutes=i))
    det.record("other", ts=T0 + 5 * DAY)
    findings = det.report(now=T0 + 5 * DAY + timedelta(hours=1))
    hit = [f for f in findings if f.action == "heartbeat"]
    assert hit and hit[0].signal == "gone_silent"
    assert hit[0].rate_now == 0 and hit[0].baseline == 3


# --------------------------------------------------------------------------
# 4. No false alarm on a steady rhythm
# --------------------------------------------------------------------------
def test_no_false_alarm_on_steady_rhythm():
    det = _detector(new_within_days=0.0)
    # A constant 4/day for 10 days — nothing new, no spike, no silence.
    for d in range(10):
        for i in range(4):
            det.record("tick", ts=T0 + d * DAY + timedelta(minutes=i))
    findings = det.report(now=T0 + 9 * DAY + timedelta(hours=1))
    assert findings == []


# --------------------------------------------------------------------------
# 5. Live verdict unchanged by recurrence tracking (regression)
# --------------------------------------------------------------------------
def test_live_verdict_identical_with_and_without_recurrence():
    stream = ["a", "b", "a", "c", "a", "b", "d", "a", "c", "b"]

    def run(track):
        w = AnomalyWatch(agent_id="reg", track_recurrence=track)
        out = []
        for i, action in enumerate(stream):
            r = w.observe(action, ts=T0 + i * timedelta(minutes=1))
            out.append((r.is_anomaly, round(r.score, 6), tuple(r.reasons)))
        return out

    assert run(True) == run(False)


def test_recurrence_tracking_can_be_disabled():
    w = AnomalyWatch(track_recurrence=False)
    w.observe("x", ts=T0)
    assert w.recurrence is None
    assert w.check_recurrence() == []


# --------------------------------------------------------------------------
# 6. Persistence round-trip including buckets
# --------------------------------------------------------------------------
def test_persistence_roundtrip_preserves_findings():
    det = _detector()
    det.record("deploy", ts=T0)
    for i in range(8):
        det.record("deploy", ts=T0 + DAY + timedelta(minutes=i))

    restored = RecurrenceDetector(
        established_min_count=5, baseline_min_buckets=3
    ).from_dict(det.to_dict())

    now = T0 + DAY + timedelta(hours=1)
    assert [f.as_dict() for f in restored.report(now=now)] == [
        f.as_dict() for f in det.report(now=now)
    ]


def test_report_without_now_uses_current_window_not_wall_clock():
    """Regression: polling report() with no `now` on historical data must judge
    age against the latest recorded window, not the process wall clock."""
    det = _detector()
    det.record("deploy", ts=T0)  # long in the past relative to today's clock
    for i in range(8):
        det.record("deploy", ts=T0 + DAY + timedelta(minutes=i))
    findings = det.report()  # no now= → derived from the current window
    assert any(f.action == "deploy" and f.signal == "new_established" for f in findings)


def test_from_dict_tolerates_missing_keys():
    # An older/partial state must still load rather than raising.
    det = RecurrenceDetector().from_dict({})
    assert det.report() == []


def test_watch_persists_recurrence_to_file(tmp_path):
    path = str(tmp_path / "rec.json")
    w = AnomalyWatch(agent_id="p", recurrence_path=path, recurrence=_detector())
    w.observe("deploy", ts=T0)
    for i in range(8):
        w.observe("deploy", ts=T0 + DAY + timedelta(minutes=i))
    w.save()

    w2 = AnomalyWatch(agent_id="p", recurrence_path=path, recurrence=_detector())
    findings = w2.check_recurrence(now=T0 + DAY + timedelta(hours=1))
    assert any(f.action == "deploy" and f.signal == "new_established" for f in findings)


# --------------------------------------------------------------------------
# 7. Ring buffer bounds memory
# --------------------------------------------------------------------------
def test_ring_buffer_prunes_old_buckets():
    det = _detector(max_buckets=5)
    for d in range(20):
        det.record("x", ts=T0 + d * DAY)
    # Only the last 5 day-buckets are retained.
    assert len(det._counts["x"]) <= 5


# --------------------------------------------------------------------------
# 8. Optional routing — at most once per action per window
# --------------------------------------------------------------------------
def test_route_recurrence_through_alert_router():
    seen = []
    router = AlertRouter([CallbackSink(lambda rec: seen.append(rec.action))])
    w = AnomalyWatch(agent_id="r", router=router, recurrence=_detector())
    w.observe("deploy", ts=T0)
    for i in range(8):
        w.observe("deploy", ts=T0 + DAY + timedelta(minutes=i))
    routed = w.route_recurrence(now=T0 + DAY + timedelta(hours=1))
    assert any(f.action == "deploy" for f in routed)
    assert "deploy" in seen
