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
