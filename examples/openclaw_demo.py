"""End-to-end demo: rehearse an agent rhythm, inject a novelty, alert, render.

Run:  python examples/openclaw_demo.py
Then open the printed dashboard path in a browser.
"""
from kontinuum_ai_anomaly import AlertRouter, AnomalyWatch, LogSink, render_dashboard

RHYTHM = ["plan", "act", "observe", "reflect", "done"]


def main() -> None:
    alerts = []
    watch = AnomalyWatch(
        agent_id="openclaw",
        router=AlertRouter([LogSink()]),
    )
    # Record what gets flagged so we can print a summary.
    watch.router.add_sink(type("Cap", (), {
        "name": "capture",
        "deliver": lambda self, rec: alerts.append(rec) or True,
    })())

    print("Rehearsing the agent's normal rhythm (20 cycles)…")
    for _ in range(20):
        for action in RHYTHM:
            watch.observe(action)

    print("Rehearsed actions after warmup:")
    for action in RHYTHM:
        v = watch.observe(action)
        print(f"  {action:<9} anomaly={v.is_anomaly}  surprise={v.surprise:.2f}")

    print("\nInjecting a never-seen action 'escalate':")
    v = watch.observe("escalate")
    print(f"  escalate  anomaly={v.is_anomaly}  reasons={v.reasons}")

    print("\nPer-stream stats:")
    for action, stats in sorted(watch.stream_stats().items()):
        print(f"  {action:<9} {stats}")

    out = "dashboard.html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_dashboard(watch.history, days=7))
    print(f"\nDashboard written to {out} ({len(alerts)} alerts routed).")


if __name__ == "__main__":
    main()
