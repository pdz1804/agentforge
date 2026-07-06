"""Manifest loading + reference resolution — the Phase 1 exit contract."""

from pathlib import Path

import pytest

from agent_core import (
    UnknownReferenceError,
    build_default_registries,
    load_manifest_dict,
    load_manifest_file,
    resolve_manifest,
)

PKG_ROOT = Path(__file__).resolve().parents[1]
ECHO_AGENT = PKG_ROOT / "agents" / "echo_agent.yaml"


def test_example_manifest_resolves_against_default_registries():
    registries = build_default_registries()
    manifest = load_manifest_file(ECHO_AGENT)
    # Should not raise: anthropic model, echo tool, and prompt are all registered.
    resolve_manifest(manifest, registries)
    assert manifest.id == "echo_agent"


def test_unknown_tool_reference_fails_clearly():
    registries = build_default_registries()
    manifest = load_manifest_dict(
        {
            "id": "broken",
            "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
            "prompt_ref": "prompts/echo_agent.md",
            "tools": ["does_not_exist"],
        }
    )
    with pytest.raises(UnknownReferenceError) as exc:
        resolve_manifest(manifest, registries)
    assert "does_not_exist" in str(exc.value)


def test_all_missing_references_are_reported_together():
    registries = build_default_registries()
    manifest = load_manifest_dict(
        {
            "id": "broken",
            "model": {"provider": "no_model", "name": "x"},
            "prompt_ref": "prompts/missing.md",
            "tools": ["nope"],
        }
    )
    with pytest.raises(UnknownReferenceError) as exc:
        resolve_manifest(manifest, registries)
    msg = str(exc.value)
    assert "no_model" in msg
    assert "prompts/missing.md" in msg
    assert "nope" in msg


def test_unknown_sub_agent_reported_when_known_agents_supplied():
    registries = build_default_registries()
    manifest = load_manifest_dict(
        {
            "id": "supervisor",
            "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
            "prompt_ref": "prompts/echo_agent.md",
            "sub_agents": ["ghost"],
        }
    )
    with pytest.raises(UnknownReferenceError) as exc:
        resolve_manifest(manifest, registries, known_agents={"echo_agent"})
    assert "ghost" in str(exc.value)
