"""ai-kontinuum-monitor — an anomaly / novelty monitor for agent action streams.

A thin, additive layer over `kontinuum-core` (which stays untouched), plus the
things core deliberately does *not* do and this package adds on top:

* :class:`AgentMonitor` — ingest named agent actions into the core engine.
* scoring strategies — a robust anomaly verdict where the raw core flag is
  jittery (:mod:`.scoring`).
* anomaly history & persistence — "what was odd this week?" (:mod:`.history`).
* alerting & routing — webhook / log / openclaw callback (:mod:`.alerting`).
* a tiny HTML dashboard (:mod:`.dashboard`).
* :class:`AnomalyWatch` — the orchestrator wiring all of the above together.
"""
from .alerting import (
    AlertRouter,
    CallbackSink,
    LogSink,
    WebhookSink,
    format_alert,
)
from .dashboard import render_dashboard
from .history import AnomalyHistory, AnomalyRecord
from .monitor import AgentMonitor, slug
from .scoring import (
    AdaptiveThresholdStrategy,
    AnomalyScore,
    AnomalyScorer,
    CompositeStrategy,
    NoveltyStrategy,
    default_strategy,
)
from .watch import AnomalyWatch

__version__ = "0.1.0"

__all__ = [
    "AgentMonitor",
    "slug",
    "AnomalyScorer",
    "AnomalyScore",
    "NoveltyStrategy",
    "AdaptiveThresholdStrategy",
    "CompositeStrategy",
    "default_strategy",
    "AnomalyHistory",
    "AnomalyRecord",
    "AlertRouter",
    "LogSink",
    "WebhookSink",
    "CallbackSink",
    "format_alert",
    "render_dashboard",
    "AnomalyWatch",
]
