"""Regression tests for the defects found in the quality/optimization review.

Each test pins one behaviour that was previously wrong, so the fix cannot
silently regress. The names map 1:1 onto the review findings.
"""
from datetime import datetime, timedelta, timezone

import pytest

from kontinuum_ai_anomaly import (
    AgentMonitor,
    AlertRouter,
    AnomalyRecord,
    AnomalyScorer,
    AnomalyWatch,
    CallbackSink,
    CrossStreamCorrelator,
    NoveltyStrategy,
)
from kontinuum_ai_anomaly.recurrence import RecurrenceDetector

NAIVE = datetime(2025, 3, 1, 12, 0, 0)
AWARE = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------
# 1) Naive timestamps from callers must not blow up the pipeline.
#    ``watch.observe(action, ts=datetime.now())`` is the natural call and
#    ``datetime.now()`` is naive; it used to raise TypeError comparing against
#    the UTC-aware virtual clock.
# ----------------------------------------------------------------------
def test_monitor_accepts_naive_timestamp():
    mon = AgentMonitor()
    obs = mon.observe("boot", ts=NAIVE)
    assert obs["action"] == "boot"


def test_watch_naive_timestamp_survives_full_pipeline(tmp_path):
    watch = AnomalyWatch(agent_id="a", history_path=str(tmp_path / "h.json"))
    watch.observe("boot", ts=NAIVE)
    # The window query mixes the stored ts with an aware "now" internally.
    assert len(watch.recent_anomalies(3650)) == 1


def test_naive_and_aware_timestamps_interleave():
    watch = AnomalyWatch(agent_id="a")
    watch.observe("one", ts=NAIVE)
    watch.observe("two", ts=AWARE + timedelta(minutes=5))
    watch.observe("three", ts=NAIVE + timedelta(minutes=10))
    assert len(watch.recent_anomalies(3650)) == 3


def test_correlator_accepts_naive_timestamp():
    corr = CrossStreamCorrelator()
    corr.record("a1", "x", 0.9, ts=AWARE)
    corr.record("a2", "y", 0.9, ts=NAIVE + timedelta(seconds=5))
    assert len(corr.clusters(min_agents=2)) == 1


def test_router_accepts_naive_now():
    router = AlertRouter([CallbackSink(lambda rec: None)], cooldown_seconds=60)
    rec = _record("x", score=0.9)
    assert router.route(rec, now=NAIVE)["delivered"] is True
    # A repeat inside the cooldown is suppressed even though the first call
    # passed a naive datetime and this one passes an aware one.
    assert router.route(rec, now=AWARE + timedelta(seconds=1))["delivered"] is False


def test_snooze_accepts_naive_now():
    router = AlertRouter([CallbackSink(lambda rec: None)])
    router.snooze("x", 300, now=NAIVE)
    out = router.route(_record("x", score=0.9), now=AWARE + timedelta(seconds=1))
    assert out["reason"] == "snoozed"


# ----------------------------------------------------------------------
# 2) The cooldown clock may only start when an alert actually went out.
#    Arming it on a non-delivery swallowed the next, more severe alert.
# ----------------------------------------------------------------------
def _record(action, *, score, is_novel=False):
    return AnomalyRecord(
        action=action,
        score=score,
        surprise=score,
        threshold=0.5,
        is_novel=is_novel,
        reasons=[],
        strategy="test",
        ts=AWARE.isoformat(),
    )


def test_undelivered_alert_does_not_arm_the_cooldown():
    delivered = []
    sink = CallbackSink(lambda rec: delivered.append(rec.action))
    router = AlertRouter([(sink, "critical")], cooldown_seconds=300)

    # Below every sink's level: nothing is delivered.
    low = router.route(_record("x", score=0.1), now=AWARE)
    assert low["delivered"] is False and low["reason"] == "below_sink_levels"

    # A critical alert one second later must still get through.
    high = router.route(_record("x", score=0.99), now=AWARE + timedelta(seconds=1))
    assert high["delivered"] is True
    assert delivered == ["x"]


def test_delivered_alert_still_arms_the_cooldown():
    router = AlertRouter([CallbackSink(lambda rec: None)], cooldown_seconds=300)
    assert router.route(_record("x", score=0.9), now=AWARE)["delivered"] is True
    second = router.route(_record("x", score=0.9), now=AWARE + timedelta(seconds=1))
    assert second["reason"] == "rate_limited"


def test_same_sink_at_two_levels_keeps_both_registrations():
    seen = []
    sink = CallbackSink(lambda rec: seen.append(rec.action))
    router = AlertRouter()
    router.add_sink(sink, min_level="info")
    router.add_sink(sink, min_level="critical")
    assert len(router.sinks) == 2
    router.route(_record("x", score=0.1), now=AWARE)
    assert seen == ["x"]  # the info registration fired, the critical one did not


# ----------------------------------------------------------------------
# 3) The run-wide surprise trend must be chronological, not a walk over the
#    per-stream windows (which reported a large trend for flat streams).
# ----------------------------------------------------------------------
def test_global_trend_is_zero_for_flat_streams():
    scorer = AnomalyScorer()
    for i in range(40):
        scorer.score({"action": "hot", "surprise": 0.9, "is_novel": i == 0,
                      "threshold": 0.5})
        scorer.score({"action": "calm", "surprise": 0.1, "is_novel": i == 0,
                      "threshold": 0.5})
    assert abs(scorer.metrics()["surprise_trend"]) < 0.1


def test_global_trend_follows_a_real_rise():
    scorer = AnomalyScorer()
    for _ in range(30):
        scorer.score({"action": "a", "surprise": 0.1, "is_novel": False,
                      "threshold": 0.5})
    for _ in range(30):
        scorer.score({"action": "a", "surprise": 0.9, "is_novel": False,
                      "threshold": 0.5})
    assert scorer.metrics()["surprise_trend"] > 0.5


# ----------------------------------------------------------------------
# 4) ``AnomalyScore.score`` is documented as a 0-1 severity; raw surprise is
#    not bounded by 1 on every core build.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("surprise", [1.5, 3.7, 42.0])
def test_novelty_score_stays_in_range(surprise):
    result = NoveltyStrategy().evaluate(
        {"action": "z", "surprise": surprise, "is_novel": True, "threshold": 0.5}
    )
    assert 0.0 <= result.score <= 1.0


def test_scores_stay_in_range_through_the_pipeline():
    scorer = AnomalyScorer()
    result = scorer.score(
        {"action": "z", "surprise": 9.0, "is_novel": True, "threshold": 0.5}
    )
    assert 0.0 <= result.score <= 1.0


# ----------------------------------------------------------------------
# 5) Distinct action names must not collapse onto one core token just because
#    slug() normalizes them identically.
# ----------------------------------------------------------------------
def test_colliding_action_names_get_distinct_tokens():
    mon = AgentMonitor()
    for action in ("deploy prod", "deploy-prod", "deploy.prod"):
        mon.observe(action)
    tokens = set(mon._action_slug.values())
    assert len(tokens) == 3


def test_slug_assignment_is_stable_per_action():
    mon = AgentMonitor()
    mon.observe("deploy prod")
    mon.observe("deploy-prod")
    first = dict(mon._action_slug)
    mon.observe("deploy prod")
    mon.observe("deploy-prod")
    assert mon._action_slug == first


def test_slug_assignment_survives_persistence(tmp_path):
    path = str(tmp_path / "brain.json")
    mon = AgentMonitor(persist_path=path)
    mon.observe("deploy prod")
    mon.observe("deploy-prod")
    before = dict(mon._action_slug)
    mon.save()

    reloaded = AgentMonitor(persist_path=path)
    assert reloaded._action_slug == before
    # A previously seen action stays known (not re-flagged as novel).
    assert reloaded.observe("deploy-prod")["is_novel"] is False


# ----------------------------------------------------------------------
# 6) Recurrence ingestion must not prune the whole ring on every event, and
#    gating the prune on a new window must not change the resulting state.
# ----------------------------------------------------------------------
def test_prune_gating_preserves_ring_bound():
    det = RecurrenceDetector(bucket_seconds=60.0, max_buckets=3)
    base = AWARE
    for i in range(20):
        for action in ("a", "b", "c"):
            det.record(action, ts=base + timedelta(seconds=i * 60))
    kept = {b for buckets in det._counts.values() for b in buckets}
    assert len(kept) <= 3
    assert det._latest_bucket is not None
    assert min(kept) > det._latest_bucket - 3


def test_recurrence_findings_unchanged_by_prune_gating():
    det = RecurrenceDetector(bucket_seconds=3600.0, max_buckets=10,
                             new_within_days=1.0, established_min_count=5)
    base = AWARE
    for i in range(8):
        det.record("spiky", ts=base + timedelta(seconds=i * 60))
    findings = det.report()
    assert [f.signal for f in findings] == ["new_established"]
