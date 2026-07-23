"""LLM feedback sink: prompt construction, cost cap, error isolation."""
from datetime import datetime, timezone

from kontinuum_ai_anomaly import LLMFeedbackSink, build_prompt
from kontinuum_ai_anomaly.history import AnomalyRecord


def _rec(**over):
    base = dict(
        action="escalate",
        score=0.9,
        surprise=0.9,
        threshold=0.4,
        is_novel=True,
        reasons=["never-seen action"],
        strategy="composite(or)",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
        agent_id="bot",
        detail="paged the on-call",
    )
    base.update(over)
    return AnomalyRecord(**base)


def test_build_prompt_includes_key_fields_and_context():
    prompt = build_prompt(_rec(), context="engine says: calm")
    assert "escalate" in prompt
    assert "never-seen action" in prompt
    assert "engine says: calm" in prompt
    assert "agent: bot" in prompt
    assert "paged the on-call" in prompt


def test_feedback_sink_calls_llm_and_stores_reply():
    seen = {}

    def llm(prompt: str) -> str:
        seen["prompt"] = prompt
        return "verdict: investigate"

    sink = LLMFeedbackSink(llm)
    assert sink.deliver(_rec()) is True
    assert sink.last_reply == "verdict: investigate"
    assert len(sink.replies) == 1
    assert "escalate" in seen["prompt"]


def test_feedback_sink_respects_max_calls():
    calls = {"n": 0}

    def llm(_p: str) -> str:
        calls["n"] += 1
        return "ok"

    sink = LLMFeedbackSink(llm, max_calls=1)
    assert sink.deliver(_rec()) is True
    assert sink.deliver(_rec()) is False  # capped
    assert calls["n"] == 1
    assert sink.calls == 1
    assert sink.skipped == 1


def test_feedback_sink_swallows_llm_errors():
    def llm(_p: str) -> str:
        raise RuntimeError("model down")

    sink = LLMFeedbackSink(llm)
    # A failing model must never propagate out of a sink.
    assert sink.deliver(_rec()) is False
    assert sink.calls == 0


def test_feedback_sink_context_provider_error_is_isolated():
    def ctx() -> str:
        raise RuntimeError("no context")

    sink = LLMFeedbackSink(lambda _p: "ok", context_provider=ctx)
    # A broken context provider degrades to no context, still delivers.
    assert sink.deliver(_rec()) is True
    assert sink.last_reply == "ok"


def test_feedback_sink_on_reply_callback():
    got = []
    sink = LLMFeedbackSink(lambda _p: "reply", on_reply=lambda rec, r: got.append((rec.action, r)))
    sink.deliver(_rec())
    assert got == [("escalate", "reply")]
