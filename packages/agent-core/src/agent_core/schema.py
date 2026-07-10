"""The canonical Agent Manifest schema (PRD Section 8.2).

An agent is *data*: a validated manifest, not bespoke code. ``extra="forbid"``
everywhere means a typo in a manifest key is a loud validation error, not a
silently ignored field.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    provider: str
    name: str
    temperature: float = 0.2
    max_tokens: int = 4096


class MemoryScope(StrEnum):
    user = "user"
    agent = "agent"
    session = "session"


class MemoryConfig(BaseModel):
    model_config = _STRICT

    provider: str
    scope: MemoryScope = MemoryScope.user
    namespace: str = "default"


class Limits(BaseModel):
    model_config = _STRICT

    max_steps: int = 20
    max_tokens_total: int = 200_000
    wall_clock_s: int = 120


class IOSchema(BaseModel):
    model_config = _STRICT

    input: str | None = None
    output: str | None = None


# ------------------------------------------------------------------------- #
# io_schema content-shape vocabulary (PRD Section 8.2 `io_schema`)
#
# An `io_schema.input` / `io_schema.output` side is one of:
#   * a built-in *content-shape* keyword (below) checked offline with stdlib
#     `json` and no new dependencies, or
#   * the name of a Pydantic model registered in `Registries.schemas`, resolved
#     and enforced by the runtime.
#
# The content-shape vocabulary lives here (not in runtime.py) so both the
# loader's fail-fast reference check and the runtime's enforcement share one
# source of truth without the loader importing the heavy runtime module.
#
#   text / str / string  -> any string (no runtime check; declares "plain text")
#   json                 -> must parse as JSON (any JSON value)
#   json_object / object -> must parse as a JSON object (mapping)
#   json_array / array   -> must parse as a JSON array (list)
IO_SHAPE_ALIASES = {
    "json": "json",
    "json_object": "json_object",
    "object": "json_object",
    "json_array": "json_array",
    "array": "json_array",
}

# Shapes that impose no runtime check: a declared plain-text side is satisfied
# by any string, so it collapses to "no constraint".
IO_TEXT_SHAPES = frozenset({"", "text", "str", "string"})


def resolve_content_shape(raw: str | None) -> tuple[bool, str | None]:
    """Classify an io_schema side against the built-in content-shape vocabulary.

    Returns ``(is_content_shape, canonical_shape)``:

    * ``is_content_shape`` is True when ``raw`` is None or a built-in keyword
      (text-family or json-family). False means ``raw`` is a *named schema
      reference* to be resolved against ``Registries.schemas``.
    * ``canonical_shape`` is the canonical ``json*`` shape to enforce, or None
      for the text family / no declaration (i.e. "no constraint").

    Content-shape keywords take precedence over any registered model of the
    same name, so the existing vocabulary keeps its meaning (back-compat).
    """
    if raw is None:
        return True, None
    key = raw.strip().lower()
    if key in IO_TEXT_SHAPES:
        return True, None
    shape = IO_SHAPE_ALIASES.get(key)
    if shape is not None:
        return True, shape
    return False, None


class AgentManifest(BaseModel):
    """A complete, declarative specification of one agent."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    id: str
    version: int = 1
    model: ModelConfig
    prompt_ref: str
    tools: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    memory: MemoryConfig | None = None
    sub_agents: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    io_schema: IOSchema | None = None
    limits: Limits = Field(default_factory=Limits)
    eval_suite: str | None = None
