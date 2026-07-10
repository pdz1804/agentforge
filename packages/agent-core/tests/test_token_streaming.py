"""Live token streaming: a streaming-capable provider's deltas surface as
"token" trace events during astream, while arun and guardrailed runs do not
stream (their answer is assembled/held and delivered once)."""
import asyncio

from agent_core import build_default_registries, compile_agent, load_manifest_dict
from agent_core.interfaces import ModelProvider, ModelResponse

_DELTAS = ["Hello", ", ", "world", "!"]
_FULL = "".join(_DELTAS)


class _FakeStreamingProvider(ModelProvider):
    provider = "faketok"
    supports_token_streaming = True

    async def complete(self, messages, tools=None, **cfg):
        return ModelResponse(text=_FULL, usage={"input_tokens": 1, "output_tokens": 4})

    async def astream_complete(self, messages, tools=None, *, on_token=None, **cfg):
        for d in _DELTAS:
            if on_token is not None:
                on_token(d)
        return ModelResponse(text=_FULL, usage={"input_tokens": 1, "output_tokens": 4})


def _manifest(**extra):
    return {
        "id": "tokver",
        "model": {"provider": "faketok", "name": "x"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
        **extra,
    }


def _registries():
    r = build_default_registries()
    r.models.register("faketok", _FakeStreamingProvider())
    return r


def _stream(manifest_dict):
    agent = compile_agent(load_manifest_dict(manifest_dict), _registries())

    async def run():
        return [ev async for ev in agent.astream("hi")]

    return asyncio.run(run())


def test_astream_emits_token_events_then_final_answer():
    events = _stream(_manifest())
    tokens = [e.detail for e in events if e.type == "token"]
    answers = [e.detail for e in events if e.type == "answer"]
    assert tokens == _DELTAS  # each delta streamed live, in order
    assert answers == [_FULL]  # the authoritative full answer still arrives
    # Tokens precede the final answer event.
    assert [e.type for e in events if e.type in ("token", "answer")][-1] == "answer"


def test_arun_does_not_stream_tokens():
    agent = compile_agent(load_manifest_dict(_manifest()), _registries())
    result = asyncio.run(agent.arun("hi"))
    assert result.answer == _FULL
    assert all(e.type != "token" for e in result.trace)


def test_guardrailed_run_holds_answer_and_does_not_stream_tokens():
    # A guardrail rewrites the final answer after the graph, so raw tokens must
    # NOT stream first (that would leak the pre-guardrail text).
    events = _stream(_manifest(guardrails=["educational_disclaimer"]))
    assert all(e.type != "token" for e in events)
    answers = [e.detail for e in events if e.type == "answer"]
    assert answers and _FULL in answers[0]  # disclaimer appended to the full text
