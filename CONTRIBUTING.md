# Contributing

Thanks for your interest in `ai-kontinuum-monitor`. This is a small, focused
package; contributions that keep it that way — a thin, honest layer over
`kontinuum-core` — are very welcome.

## Development setup

```bash
git clone https://github.com/Chance-Konstruktion/kontinuum-AI-anomaly
cd kontinuum-AI-anomaly
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

That pulls in `kontinuum-core` and `pytest`.

## Running the tests

```bash
pytest -q
```

CI runs the suite across Python 3.9–3.12 **and** two `kontinuum-core`
versions (`0.6.0` and `0.6.2`). The two core versions are deliberate: `0.6.0`
predates `get_diagnostics()` and exercises the `hasattr`-guard / graceful-
degradation path, while `0.6.2` is the modern path. If you touch anything that
talks to core, test both locally:

```bash
pip install "kontinuum-core==0.6.0" && pytest -q
pip install "kontinuum-core==0.6.2" && pytest -q
```

Version-independent tests should pass on both; version-specific behaviour should
be guarded (see `AgentMonitor.diagnostics` and the tests around it for the
pattern) so the same suite stays green across the matrix.

## Ground rules

- **Core stays untouched.** Everything this package adds is a layer *on top* of
  `kontinuum-core`. If you find yourself wanting to change core, that belongs in
  the core repo.
- **Be honest about signals.** The README is explicit about what's reliable
  (novelty) and what's weaker (sequence on short runs). Keep new features
  honest — don't present a jittery signal as ground truth, and never print a
  metric that wasn't measured.
- **Match the surrounding style.** Type hints, module docstrings that explain
  *why*, and tests for new behaviour. No new hard dependencies without a good
  reason — the stdlib-only footprint is a feature.

## Submitting changes

1. Branch off `main`.
2. Add or update tests; make sure `pytest -q` is green.
3. Keep the PR focused and describe the *why*, not just the *what*.

## Reporting bugs and requesting features

Use the issue templates. For anything touching ingestion, please include your
`kontinuum-core` version and the output of `AgentMonitor(...).diagnostics()` —
it saves a lot of back-and-forth.

## License

By contributing you agree that your contributions are licensed under the
project's [AGPL-3.0](LICENSE) license.
