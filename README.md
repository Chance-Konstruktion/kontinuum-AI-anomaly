# ai-kontinuum-monitor

An **anomaly / novelty monitor for agent action streams** (e.g. an
[openclaw](https://github.com/Chance-Konstruktion) bot), built on
[`kontinuum-core`](https://github.com/Chance-Konstruktion/kontinuum-core).

Core is a neuro-inspired learning engine designed for smart-home event streams.
This package points it at an **agent's action log** instead, and adds the layer
core deliberately doesn't have — the layer that makes it a *monitor*, not just
an engine:

| Layer | Module | What it adds on top of core |
|-------|--------|------------------------------|
| **Ingestion** | `monitor.py` (`AgentMonitor`) | Log named actions; hides token mechanics, works around core's filters. |
| **Scoring** | `scoring.py` | Robust verdict where core's raw flag is jittery: novelty + per-stream adaptive thresholds, aggregation across streams. |
| **History** | `history.py` | Persisted ledger — *"what was odd this week?"* — which core doesn't keep. |
| **Alerting** | `alerting.py` | Route anomalies out: webhook / log / callback back into openclaw, with rate-limiting. |
| **Dashboard** | `dashboard.py` | A tiny, self-contained HTML view of recent anomalies. |
| **Orchestration** | `watch.py` (`AnomalyWatch`) | One call runs the whole pipeline. |

Core stays **untouched** — this repo is a thin, additive layer.

### Next-stage features (v0.2.0)

Built entirely on top of core (core still untouched — its Home-Assistant
ingestion path is unchanged):

* **Sequence-awareness** — `SequenceStrategy` / `sequence_aware_strategy()`: a
  first-order transition model flags an action arriving in an unexpected order.
* **Multi-agent correlation** — `MultiAgentWatch` + `CrossStreamCorrelator`:
  anomalies coinciding across agents surface as cross-stream clusters.
* **Strategy presets** — `export_preset` / `load_preset` / `builtin_presets`:
  save & share tuned scoring configs as safe declarative JSON.
* **Alerting escalation + snooze** — per-sink `min_level` and `AlertRouter.snooze`.
* **LLM feedback loop** — `LLMFeedbackSink`: an anomaly becomes a prompt to a
  model you supply (provider-agnostic).
* **Long-term analysis** — `AnomalyHistory.patterns(weeks=…)`: anomaly patterns
  over weeks (by week / weekday / hour, recurring actions).

See [`docs/USAGE.md`](docs/USAGE.md) for examples of each.

## Install

```bash
pip install ai-kontinuum-monitor   # pulls in kontinuum-core
```

## Quick start

```python
from ai_kontinuum_monitor import AnomalyWatch, AlertRouter, LogSink

watch = AnomalyWatch(
    agent_id="openclaw",
    brain_path="brain.json",       # persist the learned model
    history_path="anomalies.json", # persist the anomaly ledger
    router=AlertRouter([LogSink()]),
)

# Rehearse the agent's normal rhythm.
for _ in range(20):
    for action in ["plan", "act", "observe", "reflect", "done"]:
        watch.observe(action)

# A never-seen action trips the monitor.
verdict = watch.observe("escalate")
print(verdict.is_anomaly, verdict.reasons)   # True  ['[novelty] never-seen action', ...]

watch.save()
```

## Honest limitations

* The **reliable signal is novelty**: a never-seen action produces high surprise
  and is flagged on its first occurrence.
* **Sequence / order anomalies are weak on short runs.** Core stays in
  `cold_start` under 100 events and its raw per-event `anomaly` flag is jittery
  below a few hundred events — the scoring layer's default is therefore
  novelty-first. The per-stream adaptive test reaches full strength once a
  stream has ~100 samples, but a **provisional, widened** early test engages
  from ~20 samples so short or very stable streams still react to a clear spike
  (tune or disable via `AdaptiveThresholdStrategy(early_warmup=…)`).

Run-wide metrics — `watch.metrics()` reports `learning_progress_pct` and a
signed `surprise_trend` — are available for dashboards and health checks, and
`render_dashboard(..., metrics=watch.metrics())` surfaces them with a filterable
timeline.
* This is an **observer, not training** — it never changes the agent's own LLM.

## License

AGPL-3.0 — a deliberate choice, because core is AGPL-3.0 and this package
imports it (see [`SPEC.md`](SPEC.md) §5.2). Not legal advice.

See [`docs/USAGE.md`](docs/USAGE.md) for a fuller openclaw example.
