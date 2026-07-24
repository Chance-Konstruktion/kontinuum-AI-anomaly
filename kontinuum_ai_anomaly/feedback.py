"""LLM feedback loop — turn an anomaly into a prompt and ask a model about it.

GrokAI's "Anomalie → direkt Prompt an LLM schicken". Core is an *observer* and
this package deliberately never changes the agent's own model (SPEC §2), but a
flagged anomaly is exactly the moment you might want a second opinion: *"was this
escalate action actually a problem, or expected?"*

This module stays provider-agnostic and dependency-free. You supply a callable
``llm(prompt: str) -> str`` (wrapping whatever client you use — the Anthropic
SDK, a local model, a stub in tests); the sink builds a compact prompt from the
anomaly and optional live engine context and calls it. It is an
:class:`~kontinuum_ai_anomaly.alerting.AlertSink`, so it drops straight into an
``AlertRouter`` alongside log / webhook sinks.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .alerting import escalation_level
from .history import AnomalyRecord

logger = logging.getLogger("kontinuum_ai_anomaly.feedback")

# What the caller wires in: prompt in, model reply out. Any exception is caught
# by the sink so a flaky model call can never break alert routing.
LLMCallable = Callable[[str], str]
# Optional provider of live engine context (e.g. ``AnomalyWatch.context``).
ContextProvider = Callable[[], str]


DEFAULT_SYSTEM_PREAMBLE = (
    "You are a monitoring assistant reviewing an anomaly flagged in an AI "
    "agent's action stream. Judge whether it is a genuine problem or expected "
    "behaviour, and suggest one concrete next step. Be concise."
)


def build_prompt(
    rec: AnomalyRecord,
    *,
    context: Optional[str] = None,
    preamble: str = DEFAULT_SYSTEM_PREAMBLE,
) -> str:
    """Render an anomaly (and optional live context) into an LLM prompt."""
    lines: List[str] = [preamble, "", "## Flagged anomaly"]
    lines.append(f"- agent: {rec.agent_id}")
    lines.append(f"- action: {rec.action}")
    lines.append(f"- escalation: {escalation_level(rec)}")
    lines.append(f"- novel: {rec.is_novel}")
    lines.append(f"- score: {rec.score:.2f} (surprise {rec.surprise:.2f}, "
                 f"threshold {rec.threshold:.2f})")
    lines.append(f"- reasons: {'; '.join(rec.reasons) or 'flagged'}")
    lines.append(f"- when: {rec.ts}")
    if rec.detail:
        lines.append(f"- detail: {rec.detail}")
    if context:
        lines.append("")
        lines.append("## Live engine context")
        lines.append(context)
    lines.append("")
    lines.append("## Question")
    lines.append(
        "Is this anomaly a real problem? Give a one-line verdict "
        "(expected / investigate / act) and one suggested next step."
    )
    return "\n".join(lines)


class LLMFeedbackSink:
    """An alert sink that sends the anomaly to an LLM and keeps its reply.

    Args:
        llm: Callable ``(prompt) -> reply``. You wrap your own client; nothing
            here imports a provider SDK, so there is no hard dependency and tests
            can pass a stub.
        context_provider: Optional zero-arg callable returning live engine
            context (e.g. ``watch.context``) to enrich the prompt.
        on_reply: Optional callback invoked with ``(rec, reply)`` after a
            successful call — route the model's verdict onward (log it, feed it
            back into openclaw, escalate).
        preamble: System-style instruction prepended to every prompt.
        max_calls: Optional cap on total LLM calls (cost guard); ``None`` =
            unlimited. Calls beyond the cap are skipped and counted.

    The most recent reply is available as :attr:`last_reply`; all replies are
    appended to :attr:`replies`.
    """

    name = "llm_feedback"

    def __init__(
        self,
        llm: LLMCallable,
        *,
        context_provider: Optional[ContextProvider] = None,
        on_reply: Optional[Callable[[AnomalyRecord, str], Any]] = None,
        preamble: str = DEFAULT_SYSTEM_PREAMBLE,
        max_calls: Optional[int] = None,
    ):
        self.llm = llm
        self.context_provider = context_provider
        self.on_reply = on_reply
        self.preamble = preamble
        self.max_calls = max_calls
        self.calls = 0
        self.skipped = 0
        self.replies: List[Dict[str, Any]] = []
        self.last_reply: Optional[str] = None

    def deliver(self, rec: AnomalyRecord) -> bool:
        if self.max_calls is not None and self.calls >= self.max_calls:
            self.skipped += 1
            return False
        context = None
        if self.context_provider is not None:
            try:
                context = self.context_provider()
            except Exception:  # context is best-effort
                logger.exception("LLMFeedbackSink context_provider raised")
        prompt = build_prompt(rec, context=context, preamble=self.preamble)
        try:
            reply = self.llm(prompt)
        except Exception:  # a sink must never break routing
            logger.exception("LLMFeedbackSink llm call raised")
            return False
        self.calls += 1
        self.last_reply = reply
        self.replies.append({"action": rec.action, "ts": rec.ts, "reply": reply})
        if self.on_reply is not None:
            try:
                self.on_reply(rec, reply)
            except Exception:  # on_reply is the caller's code; never break routing
                logger.exception("LLMFeedbackSink on_reply raised")
        return True
