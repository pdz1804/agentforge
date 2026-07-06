"""Multi-agent: a supervisor delegates to sub-agents via the agents-as-tools
pattern. Offline, with a per-agent scripted model."""

import asyncio

import pytest

from agent_core import (
    EchoTool,
    ModelProvider,
    ModelResponse,
    ToolCall,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)
from agent_core.errors import AgentCoreError, UnknownReferenceError
from agent_core.interfaces import Scope


class ScriptedModelProvider(ModelProvider):
    provider = "scripted"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self._i = 0

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        resp = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return resp


def _leaf(provider: str) -> dict:
    return {
        "id": "leaf",
        "model": {"provider": provider, "name": "x"},
        "prompt_ref": "prompts/echo_agent.md",
    }


def test_supervisor_delegates_to_two_sub_agents():
    registries = build_default_registries()
    registries.models.register("planner_model", ScriptedModelProvider([ModelResponse(text="PLAN")]))
    registries.models.register("coder_model", ScriptedModelProvider([ModelResponse(text="CODE")]))
    registries.models.register(
        "sup_model",
        ScriptedModelProvider(
            [
                ModelResponse(tool_calls=[ToolCall(name="ask_planner", args={"input": "plan"})]),
                ModelResponse(tool_calls=[ToolCall(name="ask_coder", args={"input": "code"})]),
                ModelResponse(text="DONE"),
            ]
        ),
    )

    agents = {
        "planner": load_manifest_dict({**_leaf("planner_model"), "id": "planner"}),
        "coder": load_manifest_dict({**_leaf("coder_model"), "id": "coder"}),
    }
    supervisor = load_manifest_dict(
        {
            "id": "supervisor",
            "model": {"provider": "sup_model", "name": "x"},
            "prompt_ref": "prompts/echo_agent.md",
            "sub_agents": ["planner", "coder"],
            "limits": {"max_steps": 10},
        }
    )
    resolve_manifest(supervisor, registries, known_agents=set(agents))
    agent = compile_agent(supervisor, registries, agents=agents)

    result = asyncio.run(agent.arun("build a thing"))

    assert result.answer == "DONE"
    nodes = {e.node for e in result.trace if e.type == "tool"}
    assert "ask_planner" in nodes and "ask_coder" in nodes  # both sub-agents ran


def test_sub_agent_cycle_is_rejected():
    registries = build_default_registries()
    registries.models.register("m", ScriptedModelProvider([ModelResponse(text="x")]))
    agents = {
        "a": load_manifest_dict(
            {
                "id": "a",
                "model": {"provider": "m", "name": "x"},
                "prompt_ref": "prompts/echo_agent.md",
                "sub_agents": ["b"],
            }
        ),
        "b": load_manifest_dict(
            {
                "id": "b",
                "model": {"provider": "m", "name": "x"},
                "prompt_ref": "prompts/echo_agent.md",
                "sub_agents": ["a"],
            }
        ),
    }
    with pytest.raises(AgentCoreError):
        compile_agent(agents["a"], registries, agents=agents)


def test_eval_mode_propagates_to_sub_agents():
    # A supervisor eval run must keep its sub-agents eval-isolated: the sub-agent
    # with memory must NOT persist during the supervisor's eval_mode=True run.
    registries = build_default_registries()
    registries.models.register("sub_model", ScriptedModelProvider([ModelResponse(text="ok")]))
    registries.models.register(
        "sup_model",
        ScriptedModelProvider(
            [
                ModelResponse(tool_calls=[ToolCall(name="ask_leaf", args={"input": "go"})]),
                ModelResponse(text="DONE"),
            ]
        ),
    )
    sub = load_manifest_dict(
        {
            "id": "leaf",
            "model": {"provider": "sub_model", "name": "x"},
            "prompt_ref": "prompts/echo_agent.md",
            "memory": {"provider": "in_memory", "scope": "user", "namespace": "subns"},
        }
    )
    supervisor = load_manifest_dict(
        {
            "id": "sup",
            "model": {"provider": "sup_model", "name": "x"},
            "prompt_ref": "prompts/echo_agent.md",
            "sub_agents": ["leaf"],
            "limits": {"max_steps": 6},
        }
    )
    resolve_manifest(supervisor, registries, known_agents={"leaf"})
    agent = compile_agent(supervisor, registries, agents={"leaf": sub})

    asyncio.run(agent.arun("build", eval_mode=True))

    mem = registries.memory.get("in_memory")
    assert asyncio.run(mem.all(Scope.user, "subns")) == []  # eval propagated -> no persist


def test_sub_agent_tool_name_collision_is_rejected():
    registries = build_default_registries()
    registries.models.register("m", ScriptedModelProvider([ModelResponse(text="x")]))
    registries.tools.register("ask_leaf", EchoTool())  # collides with sub-agent 'leaf'
    sub = load_manifest_dict(_leaf("m"))
    supervisor = load_manifest_dict(
        {
            "id": "sup",
            "model": {"provider": "m", "name": "x"},
            "prompt_ref": "prompts/echo_agent.md",
            "tools": ["ask_leaf"],
            "sub_agents": ["leaf"],
        }
    )
    with pytest.raises(AgentCoreError):
        compile_agent(supervisor, registries, agents={"leaf": sub})


def test_missing_sub_agent_manifest_errors():
    registries = build_default_registries()
    registries.models.register("m", ScriptedModelProvider([ModelResponse(text="x")]))
    supervisor = load_manifest_dict(
        {
            "id": "s",
            "model": {"provider": "m", "name": "x"},
            "prompt_ref": "prompts/echo_agent.md",
            "sub_agents": ["ghost"],
        }
    )
    with pytest.raises(UnknownReferenceError):
        compile_agent(supervisor, registries, agents={})
