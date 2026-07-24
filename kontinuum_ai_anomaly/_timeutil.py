"""Internal time helpers — one timezone convention for the whole package.

Every layer here (monitor clock, anomaly ledger, alert cooldowns, correlation
window, recurrence buckets) compares timestamps, and Python raises
``TypeError: can't compare offset-naive and offset-aware datetimes`` the moment
the two kinds meet. The package's own clocks are UTC-aware, but the most natural
call a user makes — ``watch.observe(action, ts=datetime.now())`` — hands in a
*naive* one, so the mix was reachable from the public API.

The rule is therefore: **a naive timestamp from a caller is interpreted as UTC**
at the boundary, and nothing downstream ever sees a naive datetime again.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def now_utc() -> datetime:
    """The current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def as_utc(ts: datetime) -> datetime:
    """Coerce any datetime to UTC; a naive one is *assumed* to already be UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def as_utc_or_now(ts: Optional[datetime]) -> datetime:
    """:func:`as_utc` for a supplied timestamp, else :func:`now_utc`."""
    return now_utc() if ts is None else as_utc(ts)
