# Changelog

All notable changes to `kontinuum-AI-anomaly` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/); this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Recurrence detection** (`recurrence.py`, `RecurrenceDetector`) — closes the
  last functional gap: novelty fires exactly once, so recurring misbehaviour
  disappeared from the radar after its first occurrence. The detector keeps
  **time-windowed counts of every observed action** (not only flagged ones,
  bounded by a ring buffer) and derives three periodic signals with
  `[recurrence] …` reasons: `new action established` (recently-new action now
  firing frequently — the core case), `rate spike` (known action far above its
  own median + k·MAD baseline), and `gone silent` (a regular action absent from
  the current window). Wired into `AnomalyWatch` via `check_recurrence()` /
  `recurrence_report()` / `route_recurrence()`, fed from every `observe()`
  **without changing the live per-event verdict or its false-alarm rate**.
  Persisted via `recurrence_path` and exposed as a new `recurrence` CLI command.

### Fixed

- **Per-version Python trove classifiers** (`3.9`–`3.12`) added to
  `pyproject.toml`. Only `Programming Language :: Python :: 3` was declared, so
  the PyPI `pyversions` README badge had no per-minor data to show. Takes effect
  with the next published release.

### Added

- **CI** (`.github/workflows/ci.yml`) — test matrix across Python 3.9–3.12 **and**
  two `kontinuum-core` versions (`0.6.0` guard-path, `0.6.3` modern path), so the
  version skew that broke releases before is now caught automatically. Plus a
  build job that `twine check`s the sdist/wheel.
- **PyPI publish workflow** (`.github/workflows/publish.yml`) — builds on a `v*`
  tag push and uploads via OIDC Trusted Publishing (no stored token). Closes the
  gap where a tagged release never actually reached PyPI.
- **Command-line interface** (`cli.py` / `python -m kontinuum_ai_anomaly`, also
  the `kontinuum-AI-anomaly` console script) — `watch` streams actions through
  the pipeline and prints the run's real metrics, `report` prints a ledger's real
  `summary()`/`patterns()`, `dashboard` renders the ledger to HTML. Every number
  is measured from real input.
- **Docs** — `docs/API.md` (full public API) and `docs/SCORING.md` (how the
  scoring decides and how to tune it).
- **Dedicated unit tests** for `correlation`, `feedback`, `presets`, `dashboard`,
  the CLI, and learning-state normalization (86 tests, up from 52).
- **OSS scaffolding** — `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue/PR
  templates, and README badges.

### Changed

- Require **kontinuum-core >= 0.6.3** (was `>=0.6.0`), aligning with the rest of
  the KONTINUUM family on the current PyPI release. `get_diagnostics()` landed in
  0.6.2, so the observable-ingestion counters are guaranteed present (the call
  stays `hasattr`-guarded for robustness), and the CI matrix now exercises the
  `0.6.3` modern path alongside the `0.6.0` guard path.
- Expanded the README badge row (Downloads, `kontinuum-core` version) and added
  the same real, clickable badge set to the German README (`README.de.md`).
- **Normalized `learning_state`** — `AnomalyScorer.metrics()` now reports core's
  maturity label collapsed onto one canonical `cold_start`/`warming`/`mature`
  scale (`normalize_learning_state()`), with the verbatim label preserved as
  `learning_state_raw`. Core emits two dialects (`cold_start`/`learning`/`stable`
  from the engine, `warming`/`mature` from the LLM-context helper) which could
  show two words for one concept next to the progress bar. `MATURE_EVENTS` is now
  anchored to core's actual 1000-event `stable` gate (was 2000). Documented that
  volume-based `learning_progress_pct` and accuracy-aware `learning_state` can
  legitimately diverge.
- **License metadata** modernized to a PEP 639 SPDX expression
  (`AGPL-3.0-or-later`), fixing `twine check` on the built distributions
  (requires `setuptools>=77` at build time).

### Changed

- **Renamed the package to `kontinuum-AI-anomaly`** to match the repository. The
  PyPI distribution (`kontinuum-AI-anomaly`), the import package
  (`ai_kontinuum_monitor` → `kontinuum_ai_anomaly`), and the console script are
  now all one name. Update imports to `from kontinuum_ai_anomaly import …` and
  invoke the module as `python -m kontinuum_ai_anomaly`.
- **First release is experimental (alpha).** Tagged `v0.1.0a1` and marked
  `Development Status :: 3 - Alpha`; PyPI treats it as a pre-release
  (`pip install` needs `--pre` to pick it up).

### Fixed

- **Install command** in both READMEs pointed at the repository name
  (`kontinuum-AI-anomaly`) instead of the actual PyPI distribution name — it now
  reads `pip install kontinuum-AI-anomaly`. The stated `kontinuum-core`
  requirement (`>= 0.6.2`) was also brought in line with `pyproject.toml`
  (`>= 0.6.3`).
- **Documented the release process** in `CONTRIBUTING.md`: tag-driven versioning
  via `setuptools-scm` and OIDC Trusted Publishing, including the one-time PyPI
  trusted-publisher setup.

## [0.2.0] — Next-stage improvements

Implements the next-stage improvement list (sequence-awareness, cross-stream
correlation, config presets, alerting escalation/snooze, LLM feedback loop,
long-term analysis). Every item is an **additive layer in this package** —
`kontinuum-core` is untouched, so its Home-Assistant ingestion path is
unchanged. All new behaviour is opt-in; existing call sites keep working.

### Added

- **Sequence-awareness (`SequenceStrategy`)** — a first-order (bigram)
  transition model in the monitor layer catches an action arriving in an
  unexpected *order* (never-seen / rare transition), the signal core is weak on.
  Wire it in via the new `sequence_aware_strategy()` factory (novelty OR
  adaptive OR sequence). This addresses the "sequence-awareness" item *without*
  a core change — it lives entirely on top of core.
- **Cross-stream correlation (`correlation.py`)** — `CrossStreamCorrelator`
  finds anomalies that co-occur across different agents within a time window,
  and `MultiAgentWatch` runs one `AnomalyWatch` per agent (own brain/ledger)
  while feeding every flagged anomaly into the shared correlator;
  `correlated_clusters()` surfaces multi-agent incidents.
- **Strategy presets (`presets.py`)** — export/import a scoring configuration as
  safe declarative JSON (`export_preset`/`import_preset`, `save_preset`/
  `load_preset`), plus named `builtin_presets()` (`default`, `sequence_aware`,
  `novelty_only`, `sensitive`).
- **Alerting escalation + snooze** — `escalation_level()` maps a score to
  `info`/`warning`/`critical` (novel actions floored to `warning`); `AlertRouter`
  accepts `(sink, min_level)` pairs so each sink only fires at/above its level,
  and gains `snooze()`/`unsnooze()` to mute a known-flapping action for a window.
- **LLM feedback loop (`feedback.py`)** — `LLMFeedbackSink` is an alert sink that
  builds a compact prompt from the anomaly (plus optional live engine context)
  and calls a user-supplied `llm(prompt) -> str`. Provider-agnostic, no new hard
  dependency; model/handler errors are swallowed so routing can't break, with an
  optional `max_calls` cost guard.
- **Long-term analysis** — `AnomalyHistory.patterns(weeks=…)` buckets anomalies
  by ISO week / weekday / hour and reports *recurring* actions (flagged in 2+
  weeks) — "Anomalie-Muster über Wochen".

## [Unreleased]

Constructive-improvement pass — addresses feedback on threshold latency,
missing run-wide metrics, dashboard interactivity, and clock configurability.
All changes are additive and backward-compatible; existing call sites keep
their behaviour unless they opt into the new parameters.

### Added

- **Run-wide metrics** — `AnomalyScorer.metrics()` (and pass-through
  `AnomalyWatch.metrics()`) report `learning_progress` / `learning_progress_pct`
  (event volume toward core's maturity threshold, SPEC §5.4) and a signed
  `surprise_trend` (recent-half mean vs. older-half mean — positive = drifting
  more surprising). `stream_stats()` now also carries a per-stream
  `surprise_trend`.
- **Earlier adaptive engagement** — `AdaptiveThresholdStrategy` gained an
  `early_warmup` window (default 20): a *provisional*, deliberately widened
  per-stream test runs on partial history so short or very stable streams react
  before the full 100-sample warmup instead of staying blind. Set
  `early_warmup=None` to keep the previous fully-conservative behaviour.
- **Interactive dashboard** — `render_dashboard()` timeline is now filterable
  (inline search box + novel/outlier toggle, self-contained inline JS, still no
  external assets) and can render learning-progress / surprise-trend / mean
  cards when passed the optional `metrics=` dict.
- **Configurable virtual clock** — `AgentMonitor(step_seconds=…)` lets callers
  widen event spacing for genuinely high-frequency replays; clamped to the
  burst-safe default so it can't reintroduce silent drops (SPEC §5.5).

## [0.1.0] - 2026-07-20

Initial release: an anomaly / novelty monitor for agent action streams, built as
a thin, additive layer over `kontinuum-core` (core stays untouched).

### Added

- **`AgentMonitor`** (`monitor.py`) — log named agent actions and read back
  surprise / novelty / anomaly. Works around core's ingestion filters:
  per-action room registration for distinct tokens (SPEC §3), on/off state
  alternation to defeat per-entity last-token dedup (SPEC §1), and a monotonic
  virtual clock spaced above the reticular burst gate (SPEC §5.5).
- **Scoring layer** (`scoring.py`) — a robust verdict where core's raw flag is
  jittery on short runs: `NoveltyStrategy`, `AdaptiveThresholdStrategy`
  (per-stream `median + k·MAD` with a `min_spread` floor and a warmup aligned to
  core's ~100-event cold-start boundary), `CompositeStrategy` (OR/AND), and
  `AnomalyScorer` with cross-stream aggregate stats.
- **Anomaly history** (`history.py`) — a persisted, queryable ledger
  (`recent`, `for_action`, `summary`) answering *"what was odd this week?"*.
- **Alerting & routing** (`alerting.py`) — `LogSink`, `WebhookSink`
  (generic / Slack / Discord), `CallbackSink` (feed back into openclaw), and
  `AlertRouter` with per-action rate-limiting.
- **Dashboard** (`dashboard.py`) — `render_dashboard()` produces a single
  self-contained HTML view of recent anomalies (no external assets, no JS).
- **`AnomalyWatch`** (`watch.py`) — orchestrator wiring monitor → scorer →
  history → alerts behind one `observe()` call.
- **Diagnostics** — `AgentMonitor.diagnostics()` passes through
  `engine.get_diagnostics()` under an `hasattr` guard, degrading gracefully on
  cores that predate it (SPEC §5.1).
- Tests for registration/dedup, novelty, persistence roundtrips, `context()`
  shape, diagnostics degradation, every scoring strategy, history/alerting, the
  dashboard, and the SPEC §4 acceptance criterion.
- `docs/USAGE.md` with a minimal openclaw example.

### Polish

- `CompositeStrategy` now dedupes shared reasons, so a novel action reports
  `never-seen action` once instead of once per strategy.
- `AnomalyHistory` gained an `autosave` flag (default on); turn it off for
  high-volume streams to skip the O(n) rewrite per anomaly and persist via
  `save()` / `AnomalyWatch.save()`.
- Ships `py.typed` — the package is distributed as typed.

### Notes

- Licensed **AGPL-3.0**, deliberately, because core is AGPL-3.0 and this package
  imports it (SPEC §5.2). Not legal advice.
- Depends on `kontinuum-core>=0.6.0`.
