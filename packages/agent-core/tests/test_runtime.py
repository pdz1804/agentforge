"""Runtime: manifest -> LangGraph -> run. Driven offline by scripted/echo models.

The Phase 2 exit contract: run a one-agent manifest; a tool call executes; the
trace is produced; limits are enforced.
"""

import asyncio

from agent_core import (
    ModelProvider,
    ModelResponse,
    ToolCall,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)


class ScriptedModelProvider(ModelProvider):
    """Returns a fixed sequence of responses; repeats the last one if exhausted."""

    provider = "scripted"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self._i = 0

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp


def _manifest(provider: str, tools: list[str], max_steps: int = 20) -> dict:
    return {
        "id": "runner",
        "model": {"provider": provider, "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": tools,
        "limits": {"max_steps": max_steps},
    }


def test_tool_call_executes_then_answers():
    registries = build_default_registries()
    registries.models.register(
        "scripted",
        ScriptedModelProvider(
            [
                ModelResponse(tool_calls=[ToolCall(name="echo", args={"text": "pinged"})]),
                ModelResponse(text="final answer"),
            ]
        ),
    )
    manifest = load_manifest_dict(_manifest("scripted", ["echo"]))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("go"))

    assert result.answer == "final answer"
    assert result.stopped_reason == "answer"
    assert result.steps == 2
    types = [e.type for e in result.trace]
    assert "model" in types and "tool" in types and "answer" in types
    tool_events = [e for e in result.trace if e.type == "tool"]
    assert tool_events[0].detail == "pinged"  # the echo tool actually ran


def test_max_steps_forces_best_effort_answer():
    # A model that never answers on its own — always asks for another tool call —
    # must still terminate at the step budget AND return a best-effort answer via
    # the finalize turn, never dead-ending answer-less.
    registries = build_default_registries()
    registries.models.register(
        "scripted",
        ScriptedModelProvider(
            [ModelResponse(tool_calls=[ToolCall(name="echo", args={"text": "again"})])]
        ),
    )
    manifest = load_manifest_dict(_manifest("scripted", ["echo"], max_steps=3))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("go"))

    assert result.steps == 3  # loop is bounded — no infinite recursion
    assert result.answer is not None  # never dead-ends without an answer
    assert result.stopped_reason == "answer"
    assert "max_steps" in result.answer  # the fallback explains why it stopped


def test_finalize_uses_model_text_when_budget_reached():
    # When the budget is hit, finalize makes one tool-disabled model call; if the
    # model then produces text, that text is the answer.
    registries = build_default_registries()
    registries.models.register(
        "scripted",
        ScriptedModelProvider(
            [
                ModelResponse(tool_calls=[ToolCall(name="echo", args={"text": "a"})]),
                ModelResponse(tool_calls=[ToolCall(name="echo", args={"text": "b"})]),
                ModelResponse(text="Here is my best answer after running out of budget."),
            ]
        ),
    )
    manifest = load_manifest_dict(_manifest("scripted", ["echo"], max_steps=2))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("go"))

    assert result.steps == 2
    assert result.answer == "Here is my best answer after running out of budget."
    assert result.stopped_reason == "answer"


def test_astream_forces_best_effort_answer_on_budget():
    # The stream must not end silently on budget exhaustion: it emits a best-effort
    # ``answer`` event (from finalize) rather than a terminal ``limit`` dead-end.
    registries = build_default_registries()
    registries.models.register(
        "scripted",
        ScriptedModelProvider(
            [ModelResponse(tool_calls=[ToolCall(name="echo", args={"text": "again"})])]
        ),
    )
    manifest = load_manifest_dict(_manifest("scripted", ["echo"], max_steps=2))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    async def collect():
        return [ev async for ev in agent.astream("go")]

    events = asyncio.run(collect())
    assert any(e.type == "answer" for e in events)  # best-effort answer produced
    assert events[-1].type == "answer"
    assert not any(e.type == "limit" for e in events)  # no answer-less dead-end


def test_bad_tool_args_become_recoverable_error():
    # A model can emit out-of-range args; that must feed an error back into the
    # loop (so the model can recover), not crash the run.
    registries = build_default_registries()  # includes the web_search tool
    registries.models.register(
        "scripted",
        ScriptedModelProvider(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall(name="web_search", args={"query": "x", "max_results": 999})
                    ]
                ),
                ModelResponse(text="done"),
            ]
        ),
    )
    manifest = load_manifest_dict(_manifest("scripted", ["web_search"]))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("go"))

    assert result.answer == "done"
    tool_events = [e for e in result.trace if e.type == "tool"]
    assert tool_events and "error" in tool_events[0].detail


def test_no_tool_path_returns_answer():
    registries = build_default_registries()  # has the offline "echo" model
    manifest = load_manifest_dict(_manifest("echo", []))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("hello world"))

    assert result.answer == "hello world"  # echo model echoes the user message
    assert result.stopped_reason == "answer"
    assert result.steps == 1


def test_astream_yields_trace_events():
    registries = build_default_registries()
    manifest = load_manifest_dict(_manifest("echo", []))
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    async def collect():
        return [e async for e in agent.astream("hi there", eval_mode=True)]

    events = asyncio.run(collect())
    assert any(e.type == "answer" and e.detail == "hi there" for e in events)
