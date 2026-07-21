# Usage

A minimal, end-to-end openclaw example: watch an agent's action stream, feed
anomalies back to the bot, and render a dashboard.

## 1. Wire up the pipeline

```python
from ai_kontinuum_monitor import (
    AnomalyWatch, AlertRouter, LogSink, WebhookSink, CallbackSink,
)

def notify_openclaw(rec):
    # Push the anomaly back to the bot so it can pause / ask for review.
    openclaw.report_anomaly(action=rec.action, score=rec.score, why=rec.reasons)

router = AlertRouter(
    sinks=[
        LogSink(),                                   # local log line
        WebhookSink("https://hooks.slack.com/…", template="slack"),
        CallbackSink(notify_openclaw),               # back into the agent
    ],
    cooldown_seconds=300,   # don't alert on the same action more than once / 5 min
)

watch = AnomalyWatch(
    agent_id="openclaw",
    brain_path="brain.json",
    history_path="anomalies.json",
    router=router,
)
```

## 2. Log every action the agent takes

```python
for step in agent_run():
    verdict = watch.observe(step.action, detail=step.summary)
    if verdict.is_anomaly:
        print(f"⚠ {verdict.action}: {verdict.reasons}")

watch.save()   # persist brain + ledger between runs
```

`watch.observe(...)` returns an `AnomalyScore` with `is_anomaly`, `score`
(0–1 severity), `surprise`, `is_novel` and `reasons`.

## 3. Ask "what was odd this week?"

```python
for rec in watch.recent_anomalies(days=7):
    print(rec.ts, rec.action, rec.reasons)

print(watch.history.summary(days=7))
print(watch.stream_stats())   # per-action observation / anomaly rollups
```

## 4. Render a dashboard

```python
from ai_kontinuum_monitor import render_dashboard

with open("dashboard.html", "w") as fh:
    fh.write(render_dashboard(watch.history, days=7))
```

The output is a single self-contained HTML file (inline CSS, no external
assets, no JavaScript).

## Choosing / tuning strategies

The default verdict is **novelty OR per-stream adaptive threshold**. To
customize:

```python
from ai_kontinuum_monitor import (
    AnomalyWatch, CompositeStrategy, NoveltyStrategy, AdaptiveThresholdStrategy,
)

strategy = CompositeStrategy(
    [
        NoveltyStrategy(),
        # Engage the per-stream outlier test sooner, and be stricter.
        AdaptiveThresholdStrategy(warmup=60, k=4.0, min_spread=0.25),
    ],
    mode="or",
)
watch = AnomalyWatch(agent_id="openclaw", strategy=strategy)
```

* **`NoveltyStrategy`** — flags the first occurrence of any action. Robust at
  any run length; this is the signal you can trust early.
* **`AdaptiveThresholdStrategy`** — flags a *known* action whose surprise spikes
  clearly above its own rolling baseline (`median + k·MAD`, floored by
  `min_spread`). Stays silent until a stream has `warmup` samples, matching
  core's ~100-event cold-start boundary.

## Diagnostics

If nothing seems to be learning, check the ingestion counters (silent drops are
core's classic trap, SPEC §5.3):

```python
print(watch.diagnostics())
# events_dropped_unregistered / events_dropped_no_room should stay at 0
```

`diagnostics()` is `hasattr`-guarded, so on an older `kontinuum-core` build that
predates `get_diagnostics()` it returns `{"available": False, …}` instead of
raising (SPEC §5.1).

## Next-stage features (v0.2.0)

All of these live in this package; `kontinuum-core` is untouched.

### Sequence-awareness

Catch an action arriving in an unexpected *order* (not just a novel action):

```python
from ai_kontinuum_monitor import AnomalyWatch, sequence_aware_strategy

watch = AnomalyWatch("openclaw", strategy=sequence_aware_strategy())
# novelty OR per-stream adaptive OR first-order transition model
```

`SequenceStrategy` learns, per action, which action usually follows it. Once a
predecessor is seen `min_context` times, a rare/never-seen transition is flagged
— sequence-awareness added on top of core, where core itself is weak.

### Multi-agent / cross-stream correlation

```python
from ai_kontinuum_monitor import MultiAgentWatch

maw = MultiAgentWatch(window_seconds=60)
maw.observe("botA", "escalate")
maw.observe("botB", "crash")          # within 60s of botA's anomaly
for c in maw.correlated_clusters(min_agents=2):
    print("cross-agent incident:", c["agents"], c["actions"])
```

Each agent gets its own watch/brain; anomalies coinciding in time across agents
surface as clusters — the shared-fault signal a single watch can't see.

### Strategy presets (export / import)

```python
from ai_kontinuum_monitor import builtin_presets, save_preset, load_preset

save_preset(builtin_presets()["sensitive"], "preset.json", name="sensitive")
strategy = load_preset("preset.json")     # safe declarative JSON, no pickled code
watch = AnomalyWatch("openclaw", strategy=strategy)
```

### Alerting: escalation levels + snooze

```python
from ai_kontinuum_monitor import AlertRouter, LogSink, WebhookSink

router = AlertRouter([
    (LogSink(), "info"),                      # everything
    (WebhookSink(url, "slack"), "critical"),  # only page on critical
])
router.snooze("flappy_action", seconds=3600)  # mute a known-noisy stream for 1h
```

`escalation_level(rec)` maps the severity score to `info`/`warning`/`critical`
(a novel action is always at least `warning`).

### LLM feedback loop

```python
from ai_kontinuum_monitor import AlertRouter, LLMFeedbackSink

def ask_model(prompt: str) -> str:
    ...  # wrap the Anthropic SDK / any client; provider-agnostic

sink = LLMFeedbackSink(ask_model, context_provider=watch.context,
                       on_reply=lambda rec, reply: print(rec.action, "→", reply))
router = AlertRouter([sink])
```

On each anomaly the sink builds a compact prompt (anomaly + optional live engine
context) and asks your model for a verdict. Model errors are swallowed so alert
routing never breaks; `max_calls` caps cost.

### Long-term analysis — patterns over weeks

```python
pat = watch.history.patterns(weeks=8)
print(pat["by_weekday"], pat["recurring_actions"], pat["peak_week"])
```

Buckets anomalies by ISO week / weekday / hour and flags actions that recur
across 2+ weeks — the long-horizon view core (present-event only) can't give.
