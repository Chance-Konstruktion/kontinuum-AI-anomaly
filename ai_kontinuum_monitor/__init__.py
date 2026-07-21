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
    LEVELS,
    AlertRouter,
    CallbackSink,
    LogSink,
    WebhookSink,
    escalation_level,
    format_alert,
)
from .correlation import (
    CorrelatedEvent,
    CrossStreamCorrelator,
    MultiAgentWatch,
)
from .dashboard import render_dashboard
from .feedback import LLMFeedbackSink, build_prompt
from .history import AnomalyHistory, AnomalyRecord
from .monitor import AgentMonitor, slug
from .presets import (
    builtin_presets,
    export_preset,
    import_preset,
    load_preset,
    save_preset,
)
from .scoring import (
    AdaptiveThresholdStrategy,
    AnomalyScore,
    AnomalyScorer,
    CompositeStrategy,
    NoveltyStrategy,
    SequenceStrategy,
    default_strategy,
    sequence_aware_strategy,
)
from .watch import AnomalyWatch

__version__ = "0.2.0"

__all__ = [
    "AgentMonitor",
    "slug",
    "AnomalyScorer",
    "AnomalyScore",
    "NoveltyStrategy",
    "AdaptiveThresholdStrategy",
    "SequenceStrategy",
    "CompositeStrategy",
    "default_strategy",
    "sequence_aware_strategy",
    "AnomalyHistory",
    "AnomalyRecord",
    "AlertRouter",
    "LogSink",
    "WebhookSink",
    "CallbackSink",
    "format_alert",
    "escalation_level",
    "LEVELS",
    "render_dashboard",
    "AnomalyWatch",
    # Cross-stream correlation
    "MultiAgentWatch",
    "CrossStreamCorrelator",
    "CorrelatedEvent",
    # LLM feedback loop
    "LLMFeedbackSink",
    "build_prompt",
    # Strategy presets
    "export_preset",
    "import_preset",
    "save_preset",
    "load_preset",
    "builtin_presets",
]
