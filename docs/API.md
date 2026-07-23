# API reference

A compact tour of the public surface. Everything below is importable directly
from the top-level package:

```python
from kontinuum_ai_anomaly import AnomalyWatch, AlertRouter, LogSink  # etc.
```

For a runnable walk-through see [`USAGE.md`](USAGE.md); for *why* the scorer
decides the way it does see [`SCORING.md`](SCORING.md).

---

## Orchestration

### `AnomalyWatch(agent_id="agent", *, brain_path=None, history_path=None, strategy=None, router=None, recurrence=None, recurrence_path=None, track_recurrence=True)`

The headline entry point. One `observe()` runs the whole pipeline: ingest →
score → record (if flagged) → alert (if flagged).

| Method | Returns | Notes |
|---|---|---|
| `observe(action, detail=None, *, ts=None)` | `AnomalyScore` | Run one action through the pipeline. |
| `context()` | `str` | Rendered LLM context from the core engine. |
| `diagnostics()` | `dict` | Ingestion health (guarded for old cores — see below). |
| `stream_stats()` | `dict` | Per-stream counters (observations, anomalies, trend). |
| `metrics()` | `dict` | Run-wide metrics (see [Metrics](#metrics-dictionary)). |
| `recent_anomalies(days=7.0)` | `list[AnomalyRecord]` | The recent ledger window. |
| `check_recurrence(*, now=None)` | `list[RecurrenceFinding]` | Recurring-behaviour findings; read-only, out-of-band from the live verdict. |
| `recurrence_report(*, now=None)` | `list[dict]` | `check_recurrence` as JSON-friendly dicts. |
| `route_recurrence(*, now=None)` | `list[RecurrenceFinding]` | Route findings through the alert router (≤ once per action per window). |
| `save()` | `None` | Persist brain + ledger + recurrence (no-op without paths). |

### `MultiAgentWatch(*, window_seconds=60.0, strategy=None, router=None, brain_dir=None, history_dir=None)`

Runs one `AnomalyWatch` per agent and correlates anomalies across them.

| Method | Returns | Notes |
|---|---|---|
| `observe(agent_id, action, detail=None, *, ts=None)` | `AnomalyScore` | Lazily creates a per-agent watch. |
| `watch_for(agent_id)` | `AnomalyWatch` | The (memoized) watch for one agent. |
| `correlated_clusters(*, min_agents=2)` | `list[dict]` | Time clusters spanning ≥ `min_agents` agents. |
| `save()` | `None` | Persist every agent's watch. |

---

## Ingestion

### `AgentMonitor(persist_path=None, agent_id="agent", *, step_seconds=100)`

Feeds named actions into `kontinuum-core`, hiding the token/room mechanics.

- `observe(action, detail=None, *, ts=None) -> dict` — returns `action`,
  `surprise`, `anomaly` (raw core flag — **advisory**), `threshold`,
  `is_novel`, `learning_state`.
- `diagnostics() -> dict` — `get_diagnostics()` is `hasattr`-guarded; on a core
  build that predates it (< 0.6.2) you get `{"available": False, ...}` instead
  of an exception.
- `context()`, `save()`.

`slug(action) -> str` normalizes an action name to a token-safe `[a-z0-9_]` form.

---

## Scoring

Strategies turn one monitor observation into an `AnomalyScore`. All implement
`evaluate(obs) -> AnomalyScore`.

| Strategy | Flags | Key params |
|---|---|---|
| `NoveltyStrategy` | first occurrence of any action | — |
| `AdaptiveThresholdStrategy` | a *known* action exceeding its own robust baseline | `window`, `k`, `warmup`, `floor`, `min_spread`, `early_warmup`, `early_k_boost` |
| `SequenceStrategy` | a familiar action in an unexpected *order* | `min_context`, `min_prob` |
| `CompositeStrategy` | OR/AND over sub-strategies | `strategies`, `mode` |

Factories: `default_strategy()` (novelty OR adaptive) and
`sequence_aware_strategy()` (adds sequence).

### `AnomalyScore`

Fields: `action`, `is_anomaly`, `score` (0–1 severity), `surprise`,
`threshold`, `is_novel`, `reasons` (list), `strategy`. `.as_dict()` returns a
JSON-friendly form.

### `AnomalyScorer(strategy=None)`

Applies a strategy and tracks per-stream aggregates.

- `score(obs) -> AnomalyScore`
- `stream_stats() -> dict`
- `metrics() -> dict` (see below)
- `learning_progress() -> float` (0–1, volume-based)

### `normalize_learning_state(state) -> str`

Collapses core's two learning-state dialects — `cold_start`/`learning`/`stable`
(engine) and `cold_start`/`warming`/`mature` (LLM-context helper) — onto one
canonical `cold_start`/`warming`/`mature` scale. See [SCORING.md](SCORING.md#learning-state).

---

## History

### `AnomalyHistory(persist_path=None, max_records=10000, autosave=True)`

- `record(rec)`, `since(when)`, `recent(days=7.0)`, `for_action(action)`
- `summary(days=None) -> dict`
- `patterns(weeks=None) -> dict` — long-horizon buckets (by week / weekday /
  hour) and recurring actions (flagged in 2+ distinct weeks).

### `AnomalyRecord`

A recorded anomaly; `AnomalyRecord.from_score(result, *, agent_id, detail, ts)`
builds one. `.datetime()` parses its ISO timestamp.

---

## Recurrence

`RecurrenceDetector(*, bucket_seconds=86400, max_buckets=30, new_within_days=7,
established_min_count=5, spike_factor=3.0, spike_k=4.0, baseline_min_buckets=3,
silence_min_median=1.0)` keeps time-windowed counts of **every** observed action
(bounded ring buffer) and derives recurring-behaviour signals that novelty —
which fires only on the first occurrence — cannot.

- `record(action, *, ts=None)` — count one occurrence (fed from every
  `AnomalyWatch.observe`; does not affect the live verdict).
- `report(*, now=None) -> list[RecurrenceFinding]` — read-only evaluation. With
  no `now`, the current window is taken from the latest recorded bucket.
- `to_dict()` / `from_dict(data)` — JSON round-trip including buckets.
- `RecurrenceFinding(action, signal, reason, rate_now, baseline, severity,
  first_seen)`; `signal` is `"new_established"` | `"rate_spike"` |
  `"gone_silent"`; `.as_dict()` for a JSON-friendly form.

On `AnomalyWatch`: `check_recurrence(*, now=None)`, `recurrence_report(*, now=None)`
(dicts), and `route_recurrence(*, now=None)` (through the alert router, at most
once per action per window). Enabled by default; disable with
`track_recurrence=False`, persist with `recurrence_path=...`.

---

## Alerting

`AlertRouter(sinks=None, cooldown_seconds=0.0, *, level_thresholds=None)` fans a
flagged anomaly out to sinks with per-action rate-limiting, per-sink minimum
levels, and snooze.

- Sinks: `LogSink(level=WARNING)`, `WebhookSink(url, template="generic"|"slack"|"discord")`,
  `CallbackSink(callback)`, and `feedback.LLMFeedbackSink`.
- `route(rec, *, now=None) -> dict`, `snooze(action, seconds)`, `unsnooze(action)`.
- Helpers: `escalation_level(rec, thresholds=None) -> "info"|"warning"|"critical"`,
  `format_alert(rec) -> str`, `LEVELS`.

A sink entry may be a bare sink (receives every level) or a `(sink, min_level)`
pair.

---

## Correlation

- `CrossStreamCorrelator(window_seconds=60.0, max_events=10000)` —
  `record(...)`, `correlated_with(ev, *, cross_agent_only=True)`,
  `clusters(*, min_agents=2)`.
- `CorrelatedEvent(agent_id, action, score, ts)` — a frozen event.

---

## Feedback

- `LLMFeedbackSink(llm, *, context_provider=None, on_reply=None, preamble=..., max_calls=None)` —
  an `AlertSink` that renders the anomaly to a prompt and calls your `llm(prompt) -> str`.
  Errors in `llm`, `context_provider`, and `on_reply` are all isolated so a
  flaky model can never break routing. `max_calls` caps cost.
- `build_prompt(rec, *, context=None, preamble=...) -> str`.

---

## Presets

Serialize a strategy tree to a safe, declarative JSON spec (never pickled code):
`export_preset`, `import_preset`, `save_preset`, `load_preset`, and
`builtin_presets()` (`default`, `sequence_aware`, `novelty_only`, `sensitive`).

---

## Dashboard

`render_dashboard(history, *, title=..., days=7.0, metrics=None) -> str` returns
a single self-contained HTML page (inline CSS/JS, no external assets),
optionally with learning-progress and surprise-trend cards from `metrics`.

---

## CLI

`python -m kontinuum_ai_anomaly` (or the `kontinuum-AI-anomaly` console script):

| Command | What it does |
|---|---|
| `watch [INPUT] [--agent --brain --history --recurrence --preset --json --quiet]` | Stream actions (one per line, `-` = stdin), report what's flagged plus the run's real `metrics()`. `--recurrence FILE` persists windowed action counts. |
| `report --history FILE [--days --weeks --json]` | Print the ledger's real `summary()` and `patterns()`. Read-only. |
| `recurrence --recurrence FILE [--json]` | Print recurrence findings (new-established / rate-spike / gone-silent) from a saved recurrence state. Read-only. |
| `dashboard --history FILE [--out --days]` | Render the ledger to self-contained HTML. |

Every number printed is measured from real input — the CLI never fabricates a
metric it did not compute.

---

## Metrics dictionary

`AnomalyScorer.metrics()` / `AnomalyWatch.metrics()` return:

| Key | Meaning |
|---|---|
| `observations` | total events scored |
| `streams` | distinct actions seen |
| `anomalies`, `anomaly_rate` | count and fraction flagged |
| `mean_surprise` | mean surprise across all streams |
| `surprise_trend` | recent-half mean minus older-half mean (drift) |
| `learning_state` | core's label normalized to `cold_start`/`warming`/`mature` |
| `learning_state_raw` | core's exact label, verbatim |
| `learning_progress`, `learning_progress_pct` | volume-based estimate toward maturity |

> `learning_progress_pct` is **volume only**; core's `learning_state` also
> weighs prediction accuracy, so 100 % progress while still `warming` is a valid
> state, not a bug. See [SCORING.md](SCORING.md#learning-state).
