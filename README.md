# kontinuum-AI-anomaly

[![CI](https://github.com/Chance-Konstruktion/kontinuum-AI-anomaly/actions/workflows/ci.yml/badge.svg)](https://github.com/Chance-Konstruktion/kontinuum-AI-anomaly/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-kontinuum-monitor.svg)](https://pypi.org/project/ai-kontinuum-monitor/)
[![Python versions](https://img.shields.io/pypi/pyversions/ai-kontinuum-monitor.svg)](https://pypi.org/project/ai-kontinuum-monitor/)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

**A novelty & anomaly monitor for agent action streams.**
Point it at what your agent *does* — not what a home does — and it learns the
agent's normal rhythm, then tells you when a step doesn't fit.

Built on [`kontinuum-core`](https://github.com/Chance-Konstruktion/kontinuum-core),
a neuro-inspired learning engine. This package is the layer on top that turns the
engine's raw signal into a usable verdict, keeps a history, and can alert you.

> 🇩🇪 Eine deutsche Version dieser README findest du in
> [README.de.md](README.de.md).

---

## Why this exists

`kontinuum-core` was written to learn the behaviour of a *home* — lights,
sensors, rooms. But its core idea (learn a stream of events, flag what's
surprising) isn't specific to homes. An autonomous agent — a bot, a scraper, an
"openclaw" worker — also produces a stream of actions with a normal rhythm. When
that rhythm breaks, you usually want to know.

Core gives you a raw per-event "surprise" flag, but on its own that flag is
jittery on short runs and has no memory of *what was odd last week*. This package
adds exactly the parts core deliberately leaves out:

| Layer | Module | What it adds |
|---|---|---|
| Ingestion | `AgentMonitor` | Feeds named agent actions into the engine, hiding the token/room mechanics core requires. |
| Scoring | `scoring` | Turns the jittery raw flag into a stable verdict: novelty-first, plus an adaptive threshold for *known* actions once there's enough data. |
| History | `history` | A ledger — "what was flagged this week?" — which core does not keep. |
| Alerting | `alerting` | Routes anomalies to a webhook, a log, or a callback back into your agent. |
| Correlation | `correlation` | Watches several agents/streams at once and links related anomalies. |
| Feedback | `feedback` | Renders the engine's state as a prompt so the agent's own LLM can reflect. |
| Dashboard | `dashboard` | A tiny self-contained HTML view. |
| Orchestration | `AnomalyWatch` | Wires all of the above together behind one `observe()` call. |

---

## Install

```bash
pip install kontinuum-AI-anomaly
```

Requires Python ≥ 3.9 and `kontinuum-core >= 0.6.2` (pulled in automatically).

---

## Quick start

```python
from ai_kontinuum_monitor import AnomalyWatch

watch = AnomalyWatch(agent_id="openclaw")

# Let it learn the agent's normal rhythm.
rhythm = ["plan", "act", "observe", "reflect", "done"]
for _ in range(20):
    for action in rhythm:
        watch.observe(action)

# A rehearsed step is unremarkable...
watch.observe("plan").is_anomaly        # -> False

# ...a never-seen step is flagged.
verdict = watch.observe("escalate")
print(verdict.is_anomaly, verdict.score, verdict.reasons)
# True 0.72 ['[novelty] never-seen action']
```

That output is real, not illustrative — it's what the snippet above prints on a
fresh install.

Each `observe()` returns an `AnomalyScore` with: `action`, `is_anomaly`,
`score` (0–1 severity), `surprise`, `threshold`, `is_novel`, `reasons`, and
`strategy`. Call `.as_dict()` for a JSON-friendly form.

---

## Alerting into your agent

```python
from ai_kontinuum_monitor import AnomalyWatch, AlertRouter, WebhookSink, LogSink

watch = AnomalyWatch(
    agent_id="openclaw",
    history_path="anomaly_history.json",   # persist the ledger
    router=AlertRouter([
        LogSink(),
        WebhookSink("https://example.com/hooks/openclaw"),
    ]),
)
```

Only actions that cross the anomaly bar are recorded and routed, so your webhook
stays quiet during normal operation. Use `CallbackSink` to hand the anomaly
straight back to your agent's own code.

See [`examples/openclaw_demo.py`](examples/openclaw_demo.py) for an end-to-end
run that rehearses a rhythm, injects a novelty, alerts, and renders a dashboard.

---

## Command line

The package ships a small CLI for driving it without writing code. Every number
it prints is measured from real input — it never fabricates a metric.

```bash
# Stream actions (one per line) and report what's flagged + the real metrics.
python -m ai_kontinuum_monitor watch actions.txt --history anomaly_history.json

# Print the ledger's real summary + long-horizon patterns.
python -m ai_kontinuum_monitor report --history anomaly_history.json

# Render the ledger to a self-contained HTML dashboard.
python -m ai_kontinuum_monitor dashboard --history anomaly_history.json --out dash.html
```

`ai-kontinuum-monitor` is also installed as a console script.

---

## What it's good at — and what it isn't

Being honest about this saves you from trusting the wrong signal:

- **Reliable:** *novelty* — a genuinely never-seen action is flagged
  immediately and confidently.
- **Weaker:** *order/sequence* anomalies (right actions, wrong order). The
  engine needs a lot of events before this sharpens, and stays in a
  `cold_start` learning phase under 100 events. `SequenceStrategy` helps but
  don't expect miracles on short runs.
- **Not a thing it does:** it does **not** train or change your agent. It's an
  external observer that produces a signal; what you do with that signal is up
  to you.

The design reflects this: scoring is **novelty-first**, and the adaptive
threshold for known actions only switches on once there's enough data to be
trustworthy.

For the hard-won details of *how* core actually ingests events — and the traps
that cost real debugging time — see
[`docs/INSIGHTS.md`](docs/INSIGHTS.md). Those notes came out of reverse-
engineering core's ingestion path and aren't documented anywhere else.

## Documentation

- [`docs/USAGE.md`](docs/USAGE.md) — a runnable, end-to-end openclaw example.
- [`docs/API.md`](docs/API.md) — the full public API at a glance.
- [`docs/SCORING.md`](docs/SCORING.md) — *how* the scoring decides, and how to tune it.
- [`docs/INSIGHTS.md`](docs/INSIGHTS.md) — field notes on core's ingestion path.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup and how to run the tests.

---

## License

AGPL-3.0. `kontinuum-core` is AGPL-3.0 and this package imports it, so the
copyleft and network-service obligations propagate here too. If you build on
this, keep that in mind.
