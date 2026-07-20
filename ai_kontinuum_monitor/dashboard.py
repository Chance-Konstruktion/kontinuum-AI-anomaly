"""A tiny, dependency-free HTML dashboard for the anomaly history.

Renders an :class:`AnomalyHistory` into a single self-contained HTML string
(inline CSS, no external assets) — enough to eyeball "what was odd this week"
without standing up a web stack. Fourth reason the package earns its existence.
"""
from __future__ import annotations

import html
from collections import Counter
from typing import Optional

from .history import AnomalyHistory


def _bar(count: int, total: int) -> str:
    pct = int(round(100 * count / total)) if total else 0
    return (
        f'<div class="bar"><span style="width:{pct}%"></span>'
        f'<em>{count}</em></div>'
    )


def render_dashboard(
    history: AnomalyHistory,
    *,
    title: str = "KONTINUUM Anomaly Monitor",
    days: Optional[float] = 7.0,
) -> str:
    """Return a self-contained HTML page summarizing recent anomalies."""
    records = list(reversed(history.recent(days))) if days else list(reversed(history.records))
    summary = history.summary(days)
    by_action = Counter(r.action for r in records)
    top = by_action.most_common()
    max_count = top[0][1] if top else 0

    rows = "\n".join(
        f"<tr class='{'novel' if r.is_novel else 'anom'}'>"
        f"<td>{html.escape(r.ts)}</td>"
        f"<td>{html.escape(r.action)}</td>"
        f"<td>{'novel' if r.is_novel else 'outlier'}</td>"
        f"<td>{r.score:.2f}</td>"
        f"<td>{r.surprise:.2f}</td>"
        f"<td>{html.escape('; '.join(r.reasons))}</td>"
        f"</tr>"
        for r in records
    ) or "<tr><td colspan='6' class='empty'>No anomalies in window 🎉</td></tr>"

    action_rows = "\n".join(
        f"<tr><td>{html.escape(a)}</td><td>{_bar(c, max_count)}</td></tr>"
        for a, c in top
    ) or "<tr><td colspan='2' class='empty'>—</td></tr>"

    window = f"last {days:g} days" if days else "all time"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{color-scheme:light dark}}
body{{font:15px/1.5 system-ui,sans-serif;margin:0;padding:2rem;
 background:#0f1115;color:#e6e6e6}}
h1{{font-size:1.4rem;margin:0 0 .25rem}}
.sub{{color:#9aa4b2;margin:0 0 1.5rem}}
.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem}}
.card{{background:#1b1f27;border:1px solid #2a2f3a;border-radius:10px;
 padding:1rem 1.25rem;min-width:120px}}
.card b{{display:block;font-size:1.8rem}}
.card span{{color:#9aa4b2;font-size:.85rem}}
h2{{font-size:1rem;color:#9aa4b2;margin:1.5rem 0 .5rem}}
table{{width:100%;border-collapse:collapse;background:#1b1f27;
 border-radius:10px;overflow:hidden}}
th,td{{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #2a2f3a}}
th{{color:#9aa4b2;font-weight:600;font-size:.8rem;text-transform:uppercase}}
tr.novel td:nth-child(3){{color:#ffb454}}
tr.anom td:nth-child(3){{color:#f07178}}
.empty{{color:#9aa4b2;text-align:center}}
.bar{{position:relative;background:#2a2f3a;border-radius:4px;height:1.2rem}}
.bar span{{position:absolute;left:0;top:0;bottom:0;background:#3d7eff;
 border-radius:4px}}
.bar em{{position:relative;padding-left:.4rem;font-style:normal;font-size:.8rem}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="sub">Window: {window}</p>
<div class="cards">
 <div class="card"><b>{summary['total']}</b><span>anomalies</span></div>
 <div class="card"><b>{summary['novel']}</b><span>novel actions</span></div>
 <div class="card"><b>{len(by_action)}</b><span>streams affected</span></div>
</div>
<h2>By action</h2>
<table><thead><tr><th>Action</th><th>Count</th></tr></thead>
<tbody>{action_rows}</tbody></table>
<h2>Timeline</h2>
<table><thead><tr><th>When (UTC)</th><th>Action</th><th>Kind</th>
<th>Score</th><th>Surprise</th><th>Why</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""
