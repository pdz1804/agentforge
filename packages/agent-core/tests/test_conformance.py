"""Parametric interface-conformance tests (PRD Section 14.5 "Contract" tier).

Every implementation of a core interface (``MemoryProvider``, ``ModelProvider``,
``CodeExecutor``, ``BaseTool``) must satisfy the same contract suite. Each suite
below is parametrized over the implementations it covers; adding a new backend
is: implement the interface, add one entry to the relevant parameter list. No
network, no changes to the suites themselves.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from agent_core import (
    CodeExecutorTool,
    EchoTool,
    EmbeddingSearchTool,
    InMemoryMemoryProvider,
    InMemoryVectorStore,
    Message,
    ModelResponse,
    ToolResult,
    WebSearchTool,
)
from agent_core.interfaces import (
    CodeExecutor,
    ExecResult,
    MemoryItem,
    MemoryProvider,
    RunContext,
    Scope,
)
from agent_core.models.anthropic import AnthropicModelProvider
from agent_core.models.echo import EchoModelProvider
from agent_core.models.openai import OpenAIModelProvider
from agent_core.sandbox.docker_executor import DockerCodeExecutor


# --------------------------------------------------------------------------- #
# MemoryProvider contract — InMemory + a fake "mem0-shaped" backend
# --------------------------------------------------------------------------- #
class FakeSemanticMemoryProvider(MemoryProvider):
    """A second, structurally different MemoryProvider impl (flat list + a
    different match strategy than InMemory's bucketed word-overlap) standing in
    for a semantic backend like mem0 — proves the contract suite is not
    accidentally coupled to InMemory's internals.
    """

    provider = "fake_semantic"

    def __init__(self) -> None:
        self._rows: list[tuple[str, str, MemoryItem]] = []
        self._next_id = 0

    async def add(self, scope: Scope, namespace: str, items: list[MemoryItem]) -> None:
        for item in items:
            stored = item.model_copy()
            if stored.id is None:
                stored.id = f"fake-{self._next_id}"
                self._next_id += 1
            self._rows.append((str(scope), namespace, stored))

    async def search(
        self, scope: Scope, namespace: str, query: str, k: int = 5
    ) -> list[MemoryItem]:
        terms = set(query.lower().split())
        matches = [
            item
            for s, ns, item in self._rows
            if s == str(scope) and ns == namespace and terms & set(item.text.lower().split())
        ]
        return matches[:k]

    async def delete(self, scope: Scope, namespace: str, ids: list[str]) -> None:
        key = (str(scope), namespace)
        self._rows = [
            row
            for row in self._rows
            if not (row[0] == key[0] and row[1] == key[1] and row[2].id in ids)
        ]

    async def all(self, scope: Scope, namespace: str) -> list[MemoryItem]:
        return [item for s, ns, item in self._rows if s == str(scope) and ns == namespace]


MEMORY_PROVIDER_FACTORIES = [
    pytest.param(InMemoryMemoryProvider, id="in_memory"),
    pytest.param(FakeSemanticMemoryProvider, id="fake_mem0_shaped"),
]


@pytest.fixture(params=MEMORY_PROVIDER_FACTORIES)
def memory_provider(request: pytest.FixtureRequest) -> MemoryProvider:
    return request.param()  # fresh instance per test — no cross-test bleed


def test_memory_add_then_all_roundtrips(memory_provider: MemoryProvider):
    async def scenario():
        await memory_provider.add(Scope.user, "ns1", [MemoryItem(text="the rose is red")])
        items = await memory_provider.all(Scope.user, "ns1")
        assert len(items) == 1
        assert items[0].text == "the rose is red"
        assert items[0].id is not None  # an id is always assigned

    asyncio.run(scenario())


def test_memory_search_finds_relevant_and_ignores_unrelated(memory_provider: MemoryProvider):
    async def scenario():
        fact = MemoryItem(text="favorite flower is the rose")
        await memory_provider.add(Scope.user, "ns1", [fact])
        await memory_provider.add(Scope.user, "ns1", [MemoryItem(text="lives in Hanoi")])
        hits = await memory_provider.search(Scope.user, "ns1", "which flower", k=5)
        assert hits and "rose" in hits[0].text

    asyncio.run(scenario())


def test_memory_delete_removes_by_id(memory_provider: MemoryProvider):
    async def scenario():
        await memory_provider.add(Scope.user, "ns1", [MemoryItem(text="to be deleted")])
        items = await memory_provider.all(Scope.user, "ns1")
        await memory_provider.delete(Scope.user, "ns1", [items[0].id])
        assert await memory_provider.all(Scope.user, "ns1") == []

    asyncio.run(scenario())


def test_memory_namespaces_are_isolated(memory_provider: MemoryProvider):
    async def scenario():
        await memory_provider.add(Scope.user, "alice", [MemoryItem(text="secret alpha")])
        assert await memory_provider.all(Scope.user, "bob") == []
        assert await memory_provider.all(Scope.agent, "alice") == []  # scope isolation too

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# ModelProvider contract — Echo (real, offline) + Anthropic/OpenAI (their SDKs
# are faked out via `sys.modules` so `.complete()` runs for real with zero
# network I/O and zero dependency on the optional SDK extras being installed).
# --------------------------------------------------------------------------- #
def _fake_anthropic_module() -> SimpleNamespace:
    async def create(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hi from anthropic")],
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            self.messages = SimpleNamespace(create=create)

    return SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic)


def _fake_openai_module() -> SimpleNamespace:
    async def create(**kwargs: Any) -> SimpleNamespace:
        message = SimpleNamespace(content="hi from openai", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
        )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    return SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)


def _make_echo_provider(monkeypatch: pytest.MonkeyPatch) -> EchoModelProvider:
    return EchoModelProvider()


def _make_anthropic_provider(monkeypatch: pytest.MonkeyPatch) -> AnthropicModelProvider:
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module())
    return AnthropicModelProvider(api_key="test-key")


def _make_openai_provider(monkeypatch: pytest.MonkeyPatch) -> OpenAIModelProvider:
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module())
    return OpenAIModelProvider(api_key="test-key")


MODEL_PROVIDER_MAKERS = [
    pytest.param(_make_echo_provider, id="echo"),
    pytest.param(_make_anthropic_provider, id="anthropic_fake_sdk"),
    pytest.param(_make_openai_provider, id="openai_fake_sdk"),
]


@pytest.mark.parametrize("make_provider", MODEL_PROVIDER_MAKERS)
def test_model_provider_complete_contract(make_provider, monkeypatch: pytest.MonkeyPatch):
    provider = make_provider(monkeypatch)
    messages = [
        Message(role="system", content="be helpful"),
        Message(role="user", content="hello"),
    ]
    resp = asyncio.run(
        provider.complete(messages, tools=[EchoTool()], model="x", temperature=0.1, max_tokens=64)
    )
    assert isinstance(resp, ModelResponse)
    assert isinstance(resp.text, str)
    assert isinstance(resp.tool_calls, list)
    assert isinstance(resp.usage, dict)


@pytest.mark.parametrize("make_provider", MODEL_PROVIDER_MAKERS)
def test_model_provider_complete_without_tools_does_not_crash(
    make_provider, monkeypatch: pytest.MonkeyPatch
):
    provider = make_provider(monkeypatch)
    resp = asyncio.run(provider.complete([Message(role="user", content="hi")], tools=None))
    assert isinstance(resp, ModelResponse)


# --------------------------------------------------------------------------- #
# CodeExecutor contract — a deterministic fake + the real Docker executor
# (skipped automatically when Docker is unavailable).
# --------------------------------------------------------------------------- #
class _FakeCodeExecutor(CodeExecutor):
    """Deterministic, no-Docker stand-in proving the contract without I/O."""

    async def run(self, code: str, ctx: RunContext) -> ExecResult:
        return ExecResult(stdout=f"ran: {code}", exit_code=0)


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


CODE_EXECUTOR_FACTORIES = [
    pytest.param(_FakeCodeExecutor, id="fake"),
    pytest.param(
        DockerCodeExecutor,
        id="docker",
        marks=pytest.mark.skipif(not _docker_available(), reason="docker not available"),
    ),
]


@pytest.mark.parametrize("make_executor", CODE_EXECUTOR_FACTORIES)
def test_code_executor_returns_well_formed_exec_result(make_executor):
    executor = make_executor()
    result = asyncio.run(executor.run("print(1)", RunContext(wall_clock_s=10)))
    assert isinstance(result, ExecResult)
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)
    assert isinstance(result.exit_code, int)
    assert isinstance(result.timed_out, bool)
    assert isinstance(result.artifacts, list)


# --------------------------------------------------------------------------- #
# BaseTool contract — json_schema()/validate_args() across every built-in tool.
# --------------------------------------------------------------------------- #
async def _fake_search_fn(query: str, max_results: int) -> list[dict]:
    return [{"title": "t", "url": "u", "content": query}]


async def _fake_embed_fn(text: str) -> list[float]:
    return [float(len(text)), 0.0]


TOOL_CASES = [
    pytest.param(EchoTool, {"text": "hi"}, None, id="echo"),
    pytest.param(
        lambda: WebSearchTool(search_fn=_fake_search_fn),
        {"query": "flowers"},
        {"query": "x", "max_results": 999},  # over the ge=1,le=20 bound
        id="web_search",
    ),
    pytest.param(
        lambda: CodeExecutorTool(_FakeCodeExecutor()),
        {"code": "print(1)"},
        {"code": "print(1)", "timeout_s": 999},  # over the ge=1,le=60 bound
        id="code_executor",
    ),
    pytest.param(
        lambda: EmbeddingSearchTool(InMemoryVectorStore(), _fake_embed_fn),
        {"query": "rose"},
        {"query": "rose", "k": 999},  # over the ge=1,le=20 bound
        id="embedding_search",
    ),
]


@pytest.mark.parametrize("make_tool,valid_kwargs,invalid_kwargs", TOOL_CASES)
def test_tool_json_schema_and_validate_args_contract(make_tool, valid_kwargs, invalid_kwargs):
    tool = make_tool()
    schema = tool.json_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema  # every built-in is Pydantic-schema-backed

    validated = tool.validate_args(**valid_kwargs)
    assert isinstance(validated, tool.args_schema)

    if invalid_kwargs is not None:
        with pytest.raises(ValidationError):
            tool.validate_args(**invalid_kwargs)

    result = asyncio.run(tool.run(**valid_kwargs))
    assert isinstance(result, ToolResult)
