"""Extension conformance (PRD Section 14.6): the "no redesign" guarantee.

Registers a brand-new tool, model provider, and memory backend defined
ENTIRELY in this test file — outside `agent_core` — then compiles and runs an
agent that uses all three. Passing operationalizes PRD Section 8.5's promise:
extension is "implement the interface + register", never "edit the core".
Zero diffs to `packages/agent-core/src` were needed to write this test.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from pydantic import BaseModel

from agent_core import (
    BaseTool,
    MemoryItem,
    MemoryProvider,
    ModelProvider,
    ModelResponse,
    Registries,
    Scope,
    ToolCall,
    ToolResult,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)


# --------------------------------------------------------------------------- #
# A brand-new tool, defined entirely outside agent_core.
# --------------------------------------------------------------------------- #
class ReverseArgs(BaseModel):
    text: str


class ReverseTool(BaseTool):
    """Reverses the input text. Proves a new BaseTool needs zero core edits."""

    name = "reverse"
    description = "Reverse the input text."
    args_schema = ReverseArgs

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        return ToolResult(ok=True, output=args.text[::-1])


# --------------------------------------------------------------------------- #
# A brand-new model provider, defined entirely outside agent_core.
# --------------------------------------------------------------------------- #
class UppercaseModelProvider(ModelProvider):
    """Calls `reverse` once, then answers with the tool result uppercased.
    Proves a new ModelProvider needs zero core edits.
    """

    provider = "uppercase"

    def __init__(self) -> None:
        self._called_tool = False

    async def complete(self, messages, tools=None, **cfg: Any) -> ModelResponse:
        if not self._called_tool:
            self._called_tool = True
            return ModelResponse(tool_calls=[ToolCall(name="reverse", args={"text": "hello"})])
        last_tool_result = next((m.content for m in reversed(messages) if m.role == "tool"), "")
        return ModelResponse(text=last_tool_result.upper())


# --------------------------------------------------------------------------- #
# A brand-new memory backend, defined entirely outside agent_core.
# --------------------------------------------------------------------------- #
class ListMemoryProvider(MemoryProvider):
    """A minimal, list-backed MemoryProvider. Proves a new MemoryProvider
    needs zero core edits — a structurally different impl than InMemory or
    mem0, but conforms to the same interface (see test_conformance.py).
    """

    provider = "list_memory"

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], list[MemoryItem]] = {}

    async def add(self, scope: Scope, namespace: str, items: list[MemoryItem]) -> None:
        bucket = self._items.setdefault((str(scope), namespace), [])
        for item in items:
            stored = item.model_copy()
            stored.id = stored.id or uuid.uuid4().hex
            bucket.append(stored)

    async def search(
        self, scope: Scope, namespace: str, query: str, k: int = 5
    ) -> list[MemoryItem]:
        bucket = self._items.get((str(scope), namespace), [])
        return [it for it in bucket if query.lower() in it.text.lower()][:k]

    async def delete(self, scope: Scope, namespace: str, ids: list[str]) -> None:
        key = (str(scope), namespace)
        self._items[key] = [it for it in self._items.get(key, []) if it.id not in ids]

    async def all(self, scope: Scope, namespace: str) -> list[MemoryItem]:
        return list(self._items.get((str(scope), namespace), []))


def test_new_tool_model_and_memory_work_with_zero_core_changes():
    # A fresh, empty `Registries` — nothing built-in. Every capability the
    # agent uses below is registered from this test file only.
    registries = Registries()
    registries.tools.register("reverse", ReverseTool())
    registries.models.register("uppercase", UppercaseModelProvider())
    registries.memory.register("list_memory", ListMemoryProvider())
    registries.prompts.register("prompts/ext.md", "You are a test agent.")

    manifest = load_manifest_dict(
        {
            "id": "extended",
            "model": {"provider": "uppercase", "name": "x"},
            "prompt_ref": "prompts/ext.md",
            "tools": ["reverse"],
            "memory": {"provider": "list_memory", "scope": "user", "namespace": "ext"},
        }
    )
    resolve_manifest(manifest, registries)  # every reference resolves — no core changes needed
    agent = compile_agent(manifest, registries)

    result = asyncio.run(agent.arun("go"))

    assert result.answer == "OLLEH"  # 'hello' reversed by the new tool, then uppercased
    assert result.stopped_reason == "answer"
    tool_events = [e for e in result.trace if e.type == "tool"]
    assert tool_events and tool_events[0].node == "reverse"
    assert tool_events[0].detail == "olleh"

    # the new memory backend actually persisted the exchange
    mem = registries.memory.get("list_memory")
    stored = asyncio.run(mem.all(Scope.user, "ext"))
    assert stored and "OLLEH" in stored[0].text
