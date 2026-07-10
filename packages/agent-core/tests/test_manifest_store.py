"""Manifest store: versioning + diff (Gap G4)."""

import asyncio

from agent_core import (
    InMemoryManifestStore,
    diff_manifest_versions,
    select_manifest_store,
)


def _manifest(temp: float = 0.2) -> dict:
    return {
        "id": "agent_a",
        "model": {"provider": "echo", "name": "test-model", "temperature": temp},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
    }


def test_save_assigns_monotonic_versions_starting_at_one():
    store = InMemoryManifestStore()

    async def scenario():
        v1 = await store.save("agent_a", _manifest(0.2))
        v2 = await store.save("agent_a", _manifest(0.5))
        assert v1.version == 1
        assert v2.version == 1 + 1
        # Store-assigned version is independent of the manifest dict's own value.
        assert (await store.get("agent_a")).version == 2

    asyncio.run(scenario())


def test_get_specific_and_latest_and_missing():
    store = InMemoryManifestStore()

    async def scenario():
        await store.save("agent_a", _manifest(0.2))
        await store.save("agent_a", _manifest(0.5))
        assert (await store.get("agent_a", 1)).manifest["model"]["temperature"] == 0.2
        assert (await store.get("agent_a")).manifest["model"]["temperature"] == 0.5
        assert await store.get("agent_a", 99) is None  # out of range
        assert await store.get("missing") is None

    asyncio.run(scenario())


def test_list_ids_and_versions():
    store = InMemoryManifestStore()

    async def scenario():
        await store.save("agent_a", _manifest())
        await store.save("agent_b", _manifest())
        await store.save("agent_a", _manifest(0.9))
        assert set(await store.list_ids()) == {"agent_a", "agent_b"}
        versions = await store.list_versions("agent_a")
        assert [v.version for v in versions] == [1, 2]
        assert await store.list_versions("missing") == []

    asyncio.run(scenario())


def test_diff_reports_changed_fields_and_text():
    store = InMemoryManifestStore()

    async def scenario():
        v1 = await store.save("agent_a", _manifest(0.2))
        v2 = await store.save("agent_a", {**_manifest(0.5), "tools": ["echo"]})
        diff = diff_manifest_versions(v1, v2)
        assert diff["from_version"] == 1
        assert diff["to_version"] == 2
        changed_fields = {c["field"] for c in diff["fields_changed"]}
        assert changed_fields == {"model", "tools"}
        tools_change = next(c for c in diff["fields_changed"] if c["field"] == "tools")
        assert tools_change["from"] == []
        assert tools_change["to"] == ["echo"]
        assert "+" in diff["text_diff"] and "echo" in diff["text_diff"]

    asyncio.run(scenario())


def test_select_manifest_store_defaults_to_in_memory():
    assert isinstance(select_manifest_store(), InMemoryManifestStore)
