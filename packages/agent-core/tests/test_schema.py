"""Manifest schema validation."""

import pytest

from agent_core import AgentManifest, ManifestValidationError, load_manifest_dict


def _valid_manifest() -> dict:
    return {
        "id": "demo",
        "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
        "prompt_ref": "prompts/demo.md",
        "tools": ["echo"],
    }


def test_valid_manifest_parses_with_defaults():
    m = load_manifest_dict(_valid_manifest())
    assert isinstance(m, AgentManifest)
    assert m.id == "demo"
    assert m.version == 1
    assert m.model.temperature == 0.2
    assert m.limits.max_steps == 20  # default applied


def test_unknown_field_is_rejected():
    data = _valid_manifest()
    data["typo_field"] = True
    with pytest.raises(ManifestValidationError):
        load_manifest_dict(data)


def test_missing_required_field_raises():
    data = _valid_manifest()
    del data["model"]
    with pytest.raises(ManifestValidationError):
        load_manifest_dict(data)


def test_memory_config_scope_enum():
    data = _valid_manifest()
    data["memory"] = {"provider": "mem0", "scope": "session", "namespace": "x"}
    m = load_manifest_dict(data)
    assert m.memory is not None
    assert m.memory.scope.value == "session"
