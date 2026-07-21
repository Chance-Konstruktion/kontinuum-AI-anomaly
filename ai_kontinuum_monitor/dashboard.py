"""A tiny, dependency-free HTML dashboard for the anomaly history.

Renders an :class:`AnomalyHistory` into a single self-contained HTML string
(inline CSS, no external assets) — enough to eyeball "what was odd this week"
without standing up a web stack. Fourth reason the package earns its existence.
"""
from __future__ import annotations

import html
from collections import Counter
from typing import Any, Dict, Optional

from .history import AnomalyHistory


def _bar(count: int, total: int) -> str:
    pct = int(round(100 * count / total)) if total else 0
    return (
        f'<div class="bar"><span style="width:{pct}%"></span>'
        f'<em>{count}</em></div>'
    )


def _metric_cards(metrics: Dict[str, Any]) -> str:
    """Extra summary cards for run-wide metrics, if provided."""
    if not metrics:
        return ""
    prog = metrics.get("learning_progress_pct")
    trend = metrics.get("surprise_trend")
    cards = []
    if prog is not None:
        cards.append(
            f'<div class="card"><b>{prog:g}%</b>'
            f'<span>learning progress</span></div>'
        )
    if trend is not None:
        arrow = "▲" if trend > 0 else "▼" if trend < 0 else "▬"
        cls = "up" if trend > 0 else "down" if trend < 0 else ""
        cards.append(
            f'<div class="card"><b class="{cls}">{arrow} {trend:+.3f}</b>'
            f'<span>surprise trend</span></div>'
        )
    if metrics.get("mean_surprise") is not None:
        cards.append(
            f'<div class="card"><b>{metrics["mean_surprise"]:.2f}</b>'
            f'<span>mean surprise</span></div>'
        )
    return "\n".join(cards)


def render_dashboard(
    history: AnomalyHistory,
    *,
    title: str = "KONTINUUM Anomaly Monitor",
    days: Optional[float] = 7.0,
    metrics: Optional[Dict[str, Any]] = None,
) -> str:
    """Return a self-contained HTML page summarizing recent anomalies.

    Args:
        history: The anomaly ledger to render.
        title: Page title.
        days: Window in days (``None`` = all time).
        metrics: Optional run-wide metrics dict (from
            :meth:`AnomalyWatch.metrics`); when given, learning-progress and
            surprise-trend cards are added to the header.

    The timeline is filterable client-side (a search box plus novel/outlier
    toggles) using inline JS only — the page stays a single self-contained file
    with no external assets.
    """
    records = list(reversed(history.recent(days))) if days else list(reversed(history.records))
    summary = history.summary(days)
    by_action = Counter(r.action for r in records)
    top = by_action.most_common()
    max_count = top[0][1] if top else 0

    rows = "\n".join(
        f"<tr class='{'novel' if r.is_novel else 'anom'}' "
        f"data-action='{html.escape(r.action, quote=True)}' "
        f"data-kind='{'novel' if r.is_novel else 'outlier'}'>"
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
    metric_cards = _metric_cards(metrics or {})
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
.card b.up{{color:#f07178}}.card b.down{{color:#8ce99a}}
.filters{{display:flex;gap:.75rem;align-items:center;flex-wrap:wrap;
 margin:.5rem 0 1rem}}
.filters input,.filters select{{background:#1b1f27;color:#e6e6e6;
 border:1px solid #2a2f3a;border-radius:6px;padding:.4rem .6rem;font:inherit}}
.filters .count{{color:#9aa4b2;font-size:.85rem}}
tr.hidden{{display:none}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p class="sub">Window: {window}</p>
<div class="cards">
 <div class="card"><b>{summary['total']}</b><span>anomalies</span></div>
 <div class="card"><b>{summary['novel']}</b><span>novel actions</span></div>
 <div class="card"><b>{len(by_action)}</b><span>streams affected</span></div>
 {metric_cards}
</div>
<h2>By action</h2>
<table><thead><tr><th>Action</th><th>Count</th></tr></thead>
<tbody>{action_rows}</tbody></table>
<h2>Timeline</h2>
<div class="filters">
 <input id="q" type="search" placeholder="Filter actions…" aria-label="Filter actions">
 <select id="kind" aria-label="Filter by kind">
  <option value="">All kinds</option>
  <option value="novel">Novel only</option>
  <option value="outlier">Outliers only</option>
 </select>
 <span class="count" id="count"></span>
</div>
<table id="timeline"><thead><tr><th>When (UTC)</th><th>Action</th><th>Kind</th>
<th>Score</th><th>Surprise</th><th>Why</th></tr></thead>
<tbody>{rows}</tbody></table>
<script>
(function(){{
 var q=document.getElementById('q'),kind=document.getElementById('kind'),
     count=document.getElementById('count'),
     rows=[].slice.call(document.querySelectorAll('#timeline tbody tr'))
            .filter(function(r){{return r.hasAttribute('data-action');}});
 function apply(){{
  var term=q.value.trim().toLowerCase(),k=kind.value,shown=0;
  rows.forEach(function(r){{
   var a=(r.getAttribute('data-action')||'').toLowerCase(),
       rk=r.getAttribute('data-kind');
   var ok=(!term||a.indexOf(term)>-1)&&(!k||rk===k);
   r.classList.toggle('hidden',!ok);
   if(ok)shown++;
  }});
  count.textContent=shown+' / '+rows.length+' shown';
 }}
 q.addEventListener('input',apply);kind.addEventListener('change',apply);apply();
}})();
</script>
</body></html>"""
