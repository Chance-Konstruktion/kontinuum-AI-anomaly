"""Command-line interface — ``python -m kontinuum_ai_anomaly``.

Three subcommands, all of which print only *measured* numbers — nothing here
fabricates a metric it did not compute from real input:

* ``watch``     — stream actions through the full pipeline and report what was
  flagged, plus the run's real :meth:`AnomalyWatch.metrics`.
* ``report``    — load a persisted anomaly ledger and print its real
  :meth:`AnomalyHistory.summary` and :meth:`AnomalyHistory.patterns`.
* ``dashboard`` — render the persisted ledger to a self-contained HTML file.

Input for ``watch`` is one action per line (``-`` = stdin). Blank lines and
lines beginning with ``#`` are ignored. A line may be a bare action name, an
``action<TAB>detail`` pair, or a JSON object ``{"action": ..., "detail": ...}``.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, Iterator, List, Optional, TextIO

from . import __version__
from .alerting import format_alert
from .history import AnomalyHistory, AnomalyRecord
from .presets import builtin_presets
from .scoring import ScoringStrategy
from .watch import AnomalyWatch


def _open_input(path: str) -> TextIO:
    if path == "-":
        return sys.stdin
    return open(path, "r", encoding="utf-8")


def _parse_line(line: str) -> Optional[Dict[str, Any]]:
    """Turn one input line into ``{"action", "detail"}`` or ``None`` to skip."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped[0] in "{[":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and obj.get("action"):
            return {"action": str(obj["action"]), "detail": obj.get("detail")}
        # Fall through: treat the raw text as the action name.
    if "\t" in stripped:
        action, detail = stripped.split("\t", 1)
        return {"action": action.strip(), "detail": detail.strip() or None}
    return {"action": stripped, "detail": None}


def _iter_events(fh: Iterable[str]) -> Iterator[Dict[str, Any]]:
    for line in fh:
        ev = _parse_line(line)
        if ev is not None:
            yield ev


def _resolve_strategy(preset: Optional[str]) -> Optional[ScoringStrategy]:
    if not preset:
        return None
    presets = builtin_presets()
    if preset not in presets:
        raise SystemExit(
            f"unknown preset {preset!r}; choose from: {', '.join(sorted(presets))}"
        )
    return presets[preset]


def _cmd_watch(args: argparse.Namespace) -> int:
    strategy = _resolve_strategy(args.preset)
    watch = AnomalyWatch(
        agent_id=args.agent,
        brain_path=args.brain,
        history_path=args.history,
        strategy=strategy,
    )
    flagged = 0
    total = 0
    with _open_input(args.input) as fh:
        for ev in _iter_events(fh):
            total += 1
            result = watch.observe(ev["action"], ev.get("detail"))
            if result.is_anomaly:
                flagged += 1
                if args.json:
                    print(json.dumps(result.as_dict()))
                elif not args.quiet:
                    rec = AnomalyRecord.from_score(
                        result, agent_id=args.agent, detail=ev.get("detail")
                    )
                    print(format_alert(rec))
    if args.brain or args.history:
        watch.save()

    metrics = watch.metrics()
    if args.json:
        print(json.dumps({"summary": {"observed": total, "flagged": flagged},
                          "metrics": metrics}))
    else:
        print(
            f"\n{total} actions observed, {flagged} flagged — "
            f"learning {metrics['learning_state']} "
            f"({metrics['learning_progress_pct']:g}% by volume), "
            f"anomaly rate {metrics['anomaly_rate']:.2%}, "
            f"surprise trend {metrics['surprise_trend']:+.3f}",
            file=sys.stderr,
        )
    return 0


def _load_history(path: Optional[str]) -> AnomalyHistory:
    if not path:
        raise SystemExit("this command needs a persisted ledger (--history PATH)")
    # Read-only view: never rewrite the ledger from a reporting command.
    return AnomalyHistory(persist_path=path, autosave=False)


def _cmd_report(args: argparse.Namespace) -> int:
    history = _load_history(args.history)
    report = {
        "summary": history.summary(days=args.days),
        "patterns": history.patterns(weeks=args.weeks),
    }
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    s = report["summary"]
    p = report["patterns"]
    print(f"Anomaly report — {len(history.records)} records on file")
    window = f"last {args.days:g} days" if args.days is not None else "all time"
    print(f"  window:   {window}")
    print(f"  total:    {s['total']} ({s['novel']} novel)")
    print(f"  streams:  {len(s['by_action'])}")
    if s["by_action"]:
        top = list(s["by_action"].items())[:5]
        print("  top actions: " + ", ".join(f"{a} ×{c}" for a, c in top))
    print(f"  weeks observed: {p['weeks_observed']} "
          f"(mean {p['mean_per_week']}/week)")
    if p["peak_week"]:
        print(f"  peak week: {p['peak_week'][0]} ({p['peak_week'][1]})")
    if p["recurring_actions"]:
        print("  recurring (2+ weeks): "
              + ", ".join(f"{a} ({len(w)}w)"
                          for a, w in p["recurring_actions"].items()))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import render_dashboard

    history = _load_history(args.history)
    html = render_dashboard(history, days=args.days)
    if args.out and args.out != "-":
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"wrote {args.out} ({len(history.records)} records)", file=sys.stderr)
    else:
        sys.stdout.write(html)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kontinuum_ai_anomaly",
        description="Anomaly / novelty monitor for agent action streams.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    w = sub.add_parser("watch", help="stream actions through the pipeline")
    w.add_argument("input", nargs="?", default="-",
                   help="input file, one action per line ('-' = stdin)")
    w.add_argument("--agent", default="agent", help="agent id label")
    w.add_argument("--brain", default=None, help="core brain JSON to load/save")
    w.add_argument("--history", default=None, help="anomaly ledger JSON to append to")
    w.add_argument("--preset", default=None,
                   help="scoring preset (default|sequence_aware|novelty_only|sensitive)")
    w.add_argument("--json", action="store_true", help="emit JSON lines")
    w.add_argument("--quiet", action="store_true", help="suppress per-anomaly lines")
    w.set_defaults(func=_cmd_watch)

    r = sub.add_parser("report", help="print real summary/patterns from a ledger")
    r.add_argument("--history", default=None, help="anomaly ledger JSON to read")
    r.add_argument("--days", type=float, default=None,
                   help="summary window in days (default: all time)")
    r.add_argument("--weeks", type=float, default=None,
                   help="pattern look-back in weeks (default: all history)")
    r.add_argument("--json", action="store_true", help="emit JSON")
    r.set_defaults(func=_cmd_report)

    d = sub.add_parser("dashboard", help="render the ledger to self-contained HTML")
    d.add_argument("--history", default=None, help="anomaly ledger JSON to read")
    d.add_argument("--out", default="-", help="output HTML path ('-' = stdout)")
    d.add_argument("--days", type=float, default=7.0,
                   help="timeline window in days (default: 7)")
    d.set_defaults(func=_cmd_dashboard)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
