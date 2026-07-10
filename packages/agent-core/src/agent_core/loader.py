"""Manifest loading and reference resolution.

Two stages, both fail-fast:
1. ``load_manifest_*`` — parse + schema-validate into an ``AgentManifest``.
2. ``resolve_manifest`` — check every reference (model provider, prompt, tools,
   mcp servers, memory provider, sub-agents) exists in the registries.

This is the Phase 1 exit contract: a valid manifest resolves; a manifest naming
something unregistered raises ``UnknownReferenceError`` listing every miss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ManifestValidationError, UnknownReferenceError
from .registry import Registries
from .schema import AgentManifest


def load_manifest_dict(data: dict[str, Any]) -> AgentManifest:
    """Validate a manifest mapping into an ``AgentManifest``."""
    try:
        return AgentManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestValidationError(f"invalid manifest: {exc}") from exc


def load_manifest_file(path: str | Path) -> AgentManifest:
    """Load and validate a YAML manifest file."""
    p = Path(path)
    if not p.exists():
        raise ManifestValidationError(f"manifest file not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestValidationError(f"manifest {p} must be a YAML mapping")
    return load_manifest_dict(data)


def resolve_manifest(
    manifest: AgentManifest,
    registries: Registries,
    *,
    known_agents: set[str] | None = None,
) -> None:
    """Verify every reference in ``manifest`` resolves against ``registries``.

    Collects *all* missing references (better DX than first-miss-only) and
    raises a single ``UnknownReferenceError`` if any are absent. ``known_agents``
    is checked for ``sub_agents`` only when provided (sub-agent resolution needs
    the full set of manifest ids, which the caller supplies).

    DEFERRED (not enforced in Phase 1, so do not treat these as validated):
    - ``sub_agents`` are only checked when ``known_agents`` is supplied; the
      single-manifest path (e.g. the validate endpoint) cannot resolve them yet.
      Multi-manifest resolution lands with the runtime in Phase 2.
    - ``io_schema`` names are not resolved to Pydantic models yet (Phase 2).
    """
    missing: list[str] = []

    if not registries.models.has(manifest.model.provider):
        missing.append(f"model provider '{manifest.model.provider}'")
    if not registries.prompts.has(manifest.prompt_ref):
        missing.append(f"prompt '{manifest.prompt_ref}'")
    for tool in manifest.tools:
        if not registries.tools.has(tool):
            missing.append(f"tool '{tool}'")
    for server in manifest.mcp_servers:
        if not registries.mcp.has(server):
            missing.append(f"mcp server '{server}'")
    for guardrail in manifest.guardrails:
        if not registries.guardrails.has(guardrail):
            missing.append(f"guardrail '{guardrail}'")
    if manifest.memory and not registries.memory.has(manifest.memory.provider):
        missing.append(f"memory provider '{manifest.memory.provider}'")
    if known_agents is not None:
        for sub in manifest.sub_agents:
            if sub not in known_agents:
                missing.append(f"sub_agent '{sub}'")

    if missing:
        raise UnknownReferenceError(
            f"manifest '{manifest.id}' references unregistered: " + ", ".join(missing)
        )
