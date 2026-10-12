# Changelog

All notable changes to `kontinuum-AI-anomaly` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/); this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **The dream's seed travels through the layers** (kontinuum-core 0.7.1,
  MR !19): `AgentMonitor` and `AnomalyWatch` accept `rng_seed` (default
  `TRAUM_SAAT_STANDARD = 0`, a named constant — never a hidden literal,
  deepseek G4) and pass it into the engine config. Same seed →
  bit-identical flags: the core line is no longer a coin toss on the
  dream replay (deepseek, Notiz 17519: on the frozen stand 5/40 global
  seeds flipped it). `None` sows from machine entropy. Cores < 0.7.1
  ignore the key — their dream stays the unseeded global coin.
- **The core line as a share in the table** (deepseek G3, Notiz 17519;
  claude's decision 17474): `laufe_messstand` records the raw per-seed
  counters (`je_saat.<saat>.kern.abweichungen_je_profil` — the indices
  where watch-voll and watch-ohne-kern disagree) and the table carries
  `kern_zeile`: core deviation in x of N seeds, Erstversuch index 1457
  in y of them, plus `traum_gesaet` (the proof state: seeded from core
  0.7.1 on; below, the line wears the coin warning).
- **The tarball case of `traum_gesaet` in one README sentence** (deepseek's
  Grenze 2, Gegenmessung Notiz 17627): the field reads the version of the
  INSTALLED core from package metadata. A source tarball without git
  metadata reports `0.0.0` — the table then honestly prints «Traum
  ungesät» and the core guards rest (`skipif`), although the seeded code
  runs. The benchmarks README now says so: install core from a git clone
  or a finished wheel to read the proof state; built from the tarball,
  the line stays conservatively silent instead of wrong.

### Changed

- **The core waches rest on unseeded cores** (`skipif` core < 0.7.1):
  below the seeded dream the line is a coin (not pinnable — that is
  what made `main` flake). The pinned verdict itself is unchanged: the
  revealed, spent Erstversuch seed 535396, index 1457, one flag under
  20 301 normal events.

### Fixed

- **Sommerzeit in `zeitmuster` (review of !7).** `FunkstilleStrategy` and
  `StundenprofilStrategy` formed their hours from the UTC labels of the
  (monitor-normalized) timestamps. A constant UTC offset maps hour profiles
  bijectively — but Germany turns its clocks twice a year, and after a
  switch every local hour sits one UTC hour off: the hour profile would
  cry "never seen" at the edge of the workday, and the silence verdict
  would rest on shifted hours. Hours (and the distinct-day warm-up gate)
  are now formed on the LOCAL clock of a configurable ``zone`` (default
  ``Europe/Berlin``, the house data; a naive ``ts`` is still read as UTC,
  the package rule). Two tests pin a stream across 25.10. — they fail on
  the old UTC-hour arithmetic.

### Changed

- **`SchwallStrategy` window standings are bounded** (review of !7):
  ``_fenster_staende`` grows no longer without limit and the median is no
  longer recomputed over an ever-longer list. A bounded
  ``deque(maxlen=fenster_gedaechtnis)`` (default 1000) keeps the bar
  "against the agent's own recent rhythm" and the memory O(1) for a
  monitor that runs for months.

### Added

- **Stufe 2: the three time-pattern strategies (`zeitmuster`).** The Stufe-1
  bench proved the lever is the time patterns, not the core path — burst
  (`schwall`), radio silence (`funkstille`) and off-hours work
  (`ungewohnte-uhrzeit`) were caught only by the B2 baseline, because only B2
  counts windows itself and the core's burst gate eats a burst before the
  engine sees it. `SchwallStrategy` (rolling rate window with the B2
  thresholds: `max(10, 5×median)` after a 100-window warm-up),
  `FunkstilleStrategy` (>2 h gap whose midpoint lies in an already-seen hour
  — the night pause stays the evening off) and `StundenprofilStrategy`
  (never-seen local hour, only after two distinct days and 150 events) close
  that gap in the monitor layer, core untouched. `AgentMonitor.observe()`
  now exposes the event timestamp as `ts` (tz-aware UTC); strategies without
  timestamps stay honestly inert. The bench's new third candidate
  `watch-zeit` catches all three rows at B2 level (paired difference −1.00 →
  +0.00), paying +0.8 false alarms per 1000 events for it; the two named
  blind spots (slow drift, off-target details) stay open for everyone,
  honestly in the table. Preset `zeitmuster` (novelty OR the three patterns)
  round-trips through the preset machinery.

- **`examples/zcode_watch.py`: a watcher for real coding agents.** Reads the
  tool calls that ZCode logs (read-only), runs one `AnomalyWatch` per model
  family through `MultiAgentWatch`, logs flagged steps as JSON lines and writes
  an HTML overview. From shell commands only the program name is kept: agents
  put access tokens into command lines, and those must never reach a ledger.
  It runs next to our own agent desk (about 14 000 calls of DeepSeek, Kimi and
  GLM as the learning phase). Tests pin the privacy rule against a fake DB.

### Changed

- **Ready for kontinuum-core 0.7.** `AgentMonitor` builds its engine with
  `claustrum=False, lagebild=False` when the core knows these switches. Core
  0.7 adds a Lagebild (the joint state of all devices) and a prediction market
  on top of the anomaly path; an agent stream has no device state and the
  monitor never reads the predictions, so both would only double the
  per-event work. The verdict is unaffected: the Messstand table (5 seeds) is
  bit-identical on core 0.6.3 and on core 0.7, and the suite passes on both.
  Older cores keep their single path.
- Note on the circadian pin (`NEUTRAL_CIRCADIAN_HOUR`): core 0.7 switches the
  fixed circadian curve off at the root (multiplier 1.0, event hour instead of
  the wall clock), so on that core the pin is a no-op. It stays for older
  cores.

## [0.1.0b1] — 2026-07-25

**First beta.** Still a pre-release, so it stays behind
`pip install --pre kontinuum-AI-anomaly` like the alphas before it. The trove
classifier moves `Development Status :: 3 - Alpha` → `4 - Beta`: the feature set
is complete and covered by CI (Python 3.9–3.12 × `kontinuum-core` 0.6.0/0.6.3,
plus lint and type checks), but the API stays open to change and the suffix-less
`0.1.0` is deliberately left unspent.

Everything below landed after `0.1.0a3`, which is where the recurrence detector
arrived. The headline is not new features but a quality pass: seven defects
fixed — one reachable from the most natural call in the public API, one that made
every verdict depend on the time of day — plus a documentation pass that
corrected two docs that were factually wrong.

> **Upgrading from `0.1.0a3` changes behaviour** — deliberately, since each item
> was a defect, but read these three before you upgrade:
>
> - **Severities are clamped to 0–1.** A novel action whose raw surprise exceeded
>   1 previously produced a `score` above 1; anything comparing `score` against
>   its own cut-points sees different (correct) numbers now.
> - **Colliding action names no longer share a core token.** If you feed action
>   names that differ only outside `[a-z0-9]` (`"deploy prod"` vs
>   `"deploy-prod"`), they were one pooled stream and are now two. An existing
>   brain file keeps its learned mapping; the split applies to newly seen names.
> - **The alert cooldown starts only on delivery.** An anomaly that reached no
>   sink no longer suppresses the next one for that action, so you may see
>   alerts that were previously (wrongly) swallowed.

### Added

- **Lint + type checking in CI** (`lint` job). `ruff` and `mypy` are configured
  in `pyproject.toml` and run on every push. `target-version = "py39"` matches
  `requires-python`; without it ruff reported ~190 "use PEP 585/604 syntax"
  findings that would be wrong to apply while 3.9 is supported. The rule
  selection is correctness-focused (`F`, `E9`, `B`, `DTZ`, `BLE`, `RUF100`)
  rather than stylistic, so a finding is always something to act on — `DTZ`
  in particular guards the naive-datetime class of defect fixed below. The
  package ships `py.typed`, so `mypy` keeps that promise honest.
- **Tests for `WebhookSink`** — the only sink that leaves the process had no
  coverage at all: constructor guard, all three payload templates (`generic` /
  `slack` / `discord`), 2xx vs non-2xx handling, and the network-failure
  contract (return `False`, never raise, don't stop other sinks). Plus the
  previously untested `AlertRouter.add_sink` validation, `unsnooze`, and snooze
  expiry. `alerting.py` coverage 84 % → 100 %.
- **Tests for the `recurrence` CLI subcommand** — guard clause, empty state,
  human-readable report and JSON mode were all unexercised. `cli.py` 85 % → 96 %.

  Overall coverage 94 % → 97 %; suite 125 → 157 tests.

- **`docs/API.md`: "Timestamps" and "Memory: what is bounded and what is not"
  sections.** The first documents the rule the timezone fix established (a naive
  datetime is read as UTC). The second closes a genuinely misleading gap: the
  docs advertise `max_records`, `max_events` and a "bounded ring buffer"
  throughout, which invites the conclusion that memory is bounded generally —
  those cap *events*, not *streams*, while every per-action structure grows with
  the action vocabulary and is never evicted. The bounded-vocabulary assumption
  is now also an honest-limitations bullet in both READMEs.

### Fixed

- **Verdicts no longer depend on what time of day the process runs.** Core's
  `Neurorhythms.get_circadian_multiplier()` reads the *local wall clock* when no
  hour is passed and maps it onto a learning-rate multiplier from 0.5 (20:00) to
  1.3 (08:00) — a 2.6× swing — then caches it for 60 s, so one clock reading
  governed an entire batch or replay. Identical input therefore produced
  different anomaly verdicts depending on when you ran it. `AgentMonitor` now
  pins a neutral phase (hour 13, multiplier 1.0) before every ingest, so an
  agent action stream — which has no day/night rhythm — is judged the same at
  03:00 as at 15:00. Pass `circadian_hour=None` to restore core's behaviour, or
  another hour to choose a different phase.

  This was not theoretical: the repository's own pipeline quality gate passed
  **only between 20:00 and 22:59 UTC** and failed the other 21 hours. CI had been
  green because every merge happened to land inside that window. The full suite
  now passes at all 24 hours, which is pinned by
  `tests/test_circadian_and_warmup.py`.

- **`docs/INSIGHTS.md` §5 documented the wrong learning-state thresholds.** It
  claimed the `mature` gate sits at 2000 events; core's `_learning_state()`
  opens its `stable` gate at **1000** (which `AnomalyScorer.MATURE_EVENTS`
  already anchored to, so the docs contradicted both core and `SCORING.md`). It
  also omitted the `acc < 0.3` accuracy condition entirely, presenting the state
  as purely event-count-driven — the omission that makes "100 % progress but
  still warming" look like a bug rather than the real signal it is. Also
  clarified that the raw core dialect is `cold_start`/`learning`/`stable` and
  the normalized one is `cold_start`/`warming`/`mature`.
- **Stale documentation of behaviour changed in this release** — `SPEC.md` §3
  and `docs/API.md` still described entity registration via
  `slug(action)` directly, which no longer predicts the entity id for colliding
  action names; `docs/SCORING.md` still described a novel action's severity as
  the *raw* surprise, which is now clamped to 0–1.
- Removed an unused `dataclasses.field` import and two unused test imports; the
  four `# noqa: BLE001` directives were dead (ruff exempts a blind `except`
  that calls `logger.exception`) and were replaced with plain rationale comments.

- **Naive timestamps no longer crash the pipeline.** `watch.observe(action,
  ts=datetime.now())` — the most natural call there is, since `datetime.now()`
  returns a *naive* datetime — raised `TypeError: can't compare offset-naive and
  offset-aware datetimes` against the UTC-aware virtual clock. The same mix
  reached the anomaly ledger's window queries, the alert cooldown, and the
  cross-stream correlator's sorted event list. A caller-supplied timestamp is
  now normalized to UTC at every boundary (new internal `_timeutil` module);
  a naive one is interpreted as UTC.
- **Alerts were silently swallowed by a cooldown that never delivered
  anything.** `AlertRouter.route()` armed the per-action rate limiter *before*
  checking whether any sink was eligible for that escalation level, so an
  `info`-level anomaly on a router whose only sink subscribes at `critical`
  started the clock — and a genuine `critical` alert for the same action inside
  the cooldown window was then dropped as `rate_limited` although nothing had
  ever been sent. The cooldown is now armed only on actual delivery.
- **Run-wide `surprise_trend` was computed across streams, not across time.**
  `AnomalyScorer.metrics()` concatenated the per-stream rolling windows and split
  the result in half, so the "older half" was really "whichever streams came
  first in the dict": two perfectly flat streams reported a trend of `-0.8`. The
  aggregate trend now uses its own chronological window (flat streams → ~0).
- **`AnomalyScore.score` could exceed its documented 0-1 range.** Novel actions
  passed raw surprise straight through, which is not bounded by 1 on every core
  build — feeding out-of-range severities to `escalation_level()` and the
  dashboard. Severities are clamped to 0-1.
- **Distinct action names could collapse onto one core token.** `slug()` maps
  everything outside `[a-z0-9]` to `_`, so `"deploy prod"` and `"deploy-prod"`
  shared one entity: their surprise histories were pooled and their on/off
  toggling interleaved, corrupting both streams. Each action now owns a unique
  slug (numeric suffix on collision), persisted with the brain so a reload keeps
  every action on the token it was learned under. Collision-free names are
  unaffected.
- **`AlertRouter` keyed sink levels by `id(sink)`**, which silently collapsed the
  same sink instance registered twice at two different levels; sinks and their
  minimum levels are now held together.

### Changed

- **The pipeline quality gate now tests the shipped configuration.** It used to
  lower `AdaptiveThresholdStrategy.warmup` from 100 to 25 so the adaptive path
  would engage inside a 40-cycle run, which asks the robust median+MAD estimator
  to judge on a quarter of its evidence — and at that sensitivity a *perfectly
  stable* rhythm does get flagged. The run is now long enough (120 cycles) to
  reach the real warmup, so the gate asserts the same strict "stable actions stay
  quiet" property against the defaults users actually get. The lowered-warmup
  weakness is kept as an executable note rather than dropped.

- **Recurrence ingestion is ~65× faster and no longer scales with the number of
  tracked actions.** `RecurrenceDetector.record()` pruned the entire ring on
  every single event (O(actions × buckets) per observation); pruning is now gated
  on the ring actually advancing, which reaches the identical state. Measured on
  20 000 events across 500 actions: 1.35 s → 0.02 s.

## [0.1.0a3] — 2026-07-23

First alpha to actually reach PyPI carrying the full feature set (the package
rename, the per-version classifiers, and recurrence detection). Still a
pre-release: `pip install --pre kontinuum-AI-anomaly`.

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

### Added

- **Niederlage-Wache für die erste gemessene Kern-Pfad-Flagge**
  (Erstversuch der versiegelten Sonde, deepseek Notiz 17387): Tor 3 des
  Messvertrags fiel durch GENAU EINE Flagge — watch-voll flaggt auf der
  enthüllten Erstversuch-Saat 535396 (eifrig) das normale
  ``editieren``-Ereignis Index 1457, das watch-ohne-kern durchlässt
  (1 unter 20 301 normalen Ereignissen; die Entwicklungssaaten bleiben
  bei 0,00). ``test_kern_pfad_erste_gemessene_flagge`` pinnt beide
  Seiten: die 0,00 der Entwicklungssaaten und die eine Flagge des
  versiegelten Satzes. README-Wortlaut präzisiert («trägt 0,00» →
  «erste messbare Flagge auf dem versiegelten Satz») und die
  Preiszeile auf den Stand der Sommerzeit-Heilung korrigiert
  (+1,6 gegen B0, +0,3 gegen watch-voll — die veröffentlichte
  10,1-Zeile war der UTC-Tag-Stand vorher; Gegenprüfung Notizen
  17382/17383).
