"""Repository-specific quality gate for the full anomaly pipeline.

This test exercises the production-facing contract that differentiates this
package from a thin wrapper around kontinuum-core: stable rhythmic actions must
stay quiet, first-time actions must be recorded as anomalies, known actions that
become surprising must be caught by the adaptive scorer, unexpected ordering
must be caught by the sequence-aware preset, and persisted monitor state must
keep novelty decisions stable across process boundaries.
"""
from datetime import datetime, timedelta, timezone

from kontinuum_ai_anomaly import AnomalyWatch, sequence_aware_strategy

RHYTHM = ("plan", "act", "observe", "reflect", "done")


def test_quality_gate_full_pipeline_stability_drift_sequence_and_persistence(tmp_path):
    strategy = sequence_aware_strategy()
    strategy.strategies[1].warmup = 25
    strategy.strategies[1].early_warmup = None
    strategy.strategies[2].min_context = 15
    strategy.strategies[2].min_prob = 0.0

    brain_path = str(tmp_path / "brain.json")
    history_path = str(tmp_path / "history.json")
    base = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
    watch = AnomalyWatch(
        agent_id="quality-gate-agent",
        brain_path=brain_path,
        history_path=history_path,
        strategy=strategy,
        track_recurrence=False,
    )

    # Train a deterministic openclaw-style work loop long enough for both the
    # adaptive scorer and sequence model to have per-action context.
    for cycle in range(40):
        for offset, action in enumerate(RHYTHM):
            result = watch.observe(
                action,
                ts=base + timedelta(seconds=(cycle * len(RHYTHM) + offset) * 120),
            )
            if cycle > 0:
                assert result.is_anomaly is False, result.as_dict()

    rehearsed = {
        action: watch.observe(
            action,
            ts=base + timedelta(hours=3, minutes=index * 2),
        ).as_dict()
        for index, action in enumerate(RHYTHM)
    }
    assert all(not verdict["is_anomaly"] for verdict in rehearsed.values()), rehearsed

    novel = watch.observe("escalate", ts=base + timedelta(hours=4))
    assert novel.is_anomaly is True
    assert novel.is_novel is True
    assert any("never-seen action" in reason for reason in novel.reasons)

    # Simulate a known action becoming highly surprising without letting the
    # current sample move its own baseline first.
    adaptive_obs = {
        "action": "act",
        "surprise": 0.95,
        "is_novel": False,
        "threshold": 0.0,
        "learning_state": "stable",
    }
    drift = watch.scorer.score(adaptive_obs)
    assert drift.is_anomaly is True
    assert any("per-stream threshold" in reason for reason in drift.reasons)

    # A familiar action in an unseen position is a sequence anomaly, not novelty.
    watch.scorer.score({
        "action": "plan",
        "surprise": 0.2,
        "is_novel": False,
        "threshold": 0.0,
        "learning_state": "stable",
    })
    sequence_break = watch.scorer.score({
        "action": "done",
        "surprise": 0.2,
        "is_novel": False,
        "threshold": 0.0,
        "learning_state": "stable",
    })
    assert sequence_break.is_anomaly is True
    assert sequence_break.is_novel is False
    assert any("transition" in reason for reason in sequence_break.reasons)

    stats = watch.stream_stats()
    assert set(RHYTHM).issubset(stats)
    assert stats["act"]["observations"] >= 40
    assert stats["act"]["anomalies"] == 2
    metrics = watch.metrics()
    assert metrics["observations"] >= 200
    assert metrics["learning_state"] == "mature"
    assert metrics["learning_state_raw"] == "stable"

    watch.save()
    reloaded = AnomalyWatch(
        agent_id="quality-gate-agent",
        brain_path=brain_path,
        history_path=history_path,
        strategy=sequence_aware_strategy(),
        track_recurrence=False,
    )
    reloaded_escalate = reloaded.monitor.observe("escalate", ts=base + timedelta(hours=5))
    assert reloaded_escalate["is_novel"] is False
    assert any(record.action == "escalate" for record in reloaded.history.records)
