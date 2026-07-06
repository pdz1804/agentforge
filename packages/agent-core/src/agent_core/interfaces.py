"""Core interfaces for the Unified Agent Core (PRD Section 8.3).

Everything the harness composes is defined here as an abstract contract. New
capabilities are added by implementing one of these interfaces and registering
the implementation — never by editing the runtime. Phase 1 ships concrete
implementations only for BaseTool (EchoTool) and ModelProvider (Echo +
Anthropic); the remaining interfaces are declared now so later phases plug in
without a redesign.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
class ToolResult(BaseModel):
    """Uniform return type for every tool invocation."""

    ok: bool = True
    output: Any = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    """A callable capability exposed to an agent.

    Subclasses set ``name``, ``description`` and ``args_schema`` (a Pydantic
    model describing the arguments) and implement ``run``. The args schema is
    what gets surfaced to the LLM as the tool's JSON schema.
    """

    name: str
    description: str
    args_schema: type[BaseModel]

    def validate_args(self, **kwargs: Any) -> BaseModel:
        """Validate raw kwargs against ``args_schema`` and return the model."""
        return self.args_schema(**kwargs)

    @abstractmethod
    async def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool. Implementations should call ``validate_args``."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Model providers
# --------------------------------------------------------------------------- #
class ToolCall(BaseModel):
    """A model's request to invoke a tool with arguments."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class Message(BaseModel):
    """A provider-neutral chat message.

    Carries tool-use: an assistant message may include ``tool_calls``; a
    ``role="tool"`` message is a tool result linked by ``tool_call_id``. Provider
    adapters translate this neutral shape into their native wire format.
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ModelResponse(BaseModel):
    """Normalized model completion result.

    A response carries free text and/or a list of ``tool_calls``. An empty
    ``tool_calls`` list means the model produced a final answer.
    """

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)


class ModelProvider(ABC):
    """Abstracts a chat/completion model behind one interface.

    ``provider`` is the registry key (e.g. ``"anthropic"``) referenced by a
    manifest's ``model.provider`` field.
    """

    provider: str

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: list[BaseTool] | None = None,
        **cfg: Any,
    ) -> ModelResponse:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
class Scope(StrEnum):
    user = "user"
    agent = "agent"
    session = "session"


class MemoryItem(BaseModel):
    id: str | None = None
    text: str
    meta: dict[str, Any] = Field(default_factory=dict)


class MemoryProvider(ABC):
    """Long-term memory backend (e.g. mem0). Concrete impl arrives in Phase 5."""

    provider: str

    @abstractmethod
    async def add(self, scope: Scope, namespace: str, items: list[MemoryItem]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self, scope: Scope, namespace: str, query: str, k: int = 5
    ) -> list[MemoryItem]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, scope: Scope, namespace: str, ids: list[str]) -> None:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Code execution (sandbox) — interface only; impl arrives in Phase 4
# --------------------------------------------------------------------------- #
class ExecResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    returned: Any = None
    artifacts: list[str] = Field(default_factory=list)
    exit_code: int = 0
    timed_out: bool = False


class RunContext(BaseModel):
    """Execution limits / environment for a sandbox run."""

    wall_clock_s: int = 30
    allow_network: bool = False
    packages: list[str] = Field(default_factory=list)


class CodeExecutor(ABC):
    """Sandboxed code execution backend (E2B/Docker). Impl arrives in Phase 4."""

    @abstractmethod
    async def run(self, code: str, ctx: RunContext) -> ExecResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# MCP — interface only; connector impl arrives in Phase 3b
# --------------------------------------------------------------------------- #
class MCPConnector(ABC):
    """Discovers tools from an MCP server and adapts them to BaseTool."""

    @abstractmethod
    async def discover(self, server_cfg: dict[str, Any]) -> list[BaseTool]:
        raise NotImplementedError
