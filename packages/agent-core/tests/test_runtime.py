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


def test_max_steps_limit_terminates_loop():
    registries = build_default_registries()
    # A model that never answers — always asks for another tool call.
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

    assert result.stopped_reason == "max_steps"
    assert result.answer is None
    assert result.steps == 3  # bounded, no infinite loop


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
