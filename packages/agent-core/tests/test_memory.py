"""Memory: InMemory provider CRUD + runtime cross-run recall + eval isolation."""

import asyncio

from agent_core import (
    InMemoryMemoryProvider,
    ModelProvider,
    ModelResponse,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)
from agent_core.interfaces import MemoryItem, Scope


# --- provider ------------------------------------------------------------- #
def test_provider_add_search_delete():
    prov = InMemoryMemoryProvider()

    async def scenario():
        await prov.add(Scope.user, "u1", [MemoryItem(text="favorite flower is the rose")])
        await prov.add(Scope.user, "u1", [MemoryItem(text="lives in Hanoi")])
        hits = await prov.search(Scope.user, "u1", "which flower do I like", k=5)
        assert hits and "rose" in hits[0].text
        all_items = await prov.all(Scope.user, "u1")
        assert len(all_items) == 2
        await prov.delete(Scope.user, "u1", [all_items[0].id])
        assert len(await prov.all(Scope.user, "u1")) == 1

    asyncio.run(scenario())


def test_namespaces_are_isolated():
    prov = InMemoryMemoryProvider()

    async def scenario():
        await prov.add(Scope.user, "alice", [MemoryItem(text="secret alpha")])
        assert await prov.all(Scope.user, "bob") == []

    asyncio.run(scenario())


# --- runtime wiring ------------------------------------------------------- #
class ScriptedModelProvider(ModelProvider):
    provider = "scripted"

    def __init__(self, text: str) -> None:
        self._text = text
        self.last_messages = None

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        self.last_messages = messages
        return ModelResponse(text=self._text)


def _memory_manifest() -> dict:
    return {
        "id": "rememberer",
        "model": {"provider": "scripted", "name": "x"},
        "prompt_ref": "prompts/echo_agent.md",
        "memory": {"provider": "in_memory", "scope": "user", "namespace": "u1"},
    }


def test_second_run_recalls_first_run_fact():
    registries = build_default_registries()  # shares one InMemory instance
    scripted = ScriptedModelProvider("noted")
    registries.models.register("scripted", scripted)
    manifest = load_manifest_dict(_memory_manifest())
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    # Run 1 persists the exchange.
    asyncio.run(agent.arun("my favorite flower is the rose"))
    # Run 2 should retrieve it and inject it into the model's context.
    asyncio.run(agent.arun("what is my favorite flower"))

    injected = "\n".join(m.content for m in scripted.last_messages if m.role == "system")
    assert "rose" in injected  # prior fact recalled into the second run


def test_eval_mode_is_memory_isolated():
    registries = build_default_registries()
    scripted = ScriptedModelProvider("noted")
    registries.models.register("scripted", scripted)
    manifest = load_manifest_dict(_memory_manifest())
    resolve_manifest(manifest, registries)
    agent = compile_agent(manifest, registries)

    asyncio.run(agent.arun("I love tulips", eval_mode=False))  # persisted
    asyncio.run(agent.arun("what do I love", eval_mode=True))  # must NOT retrieve

    injected = "\n".join(m.content for m in scripted.last_messages if m.role == "system")
    assert "tulips" not in injected
