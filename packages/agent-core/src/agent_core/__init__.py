"""agent-core — the Unified Agent Core (AgentForge PRD Section 8).

Public surface for Phase 1: manifest schema + loader/validator, pluggable
registries, core interfaces, and the built-in Echo tool / model providers.
Consumed by both AgentForge and FloraLens.
"""

from __future__ import annotations

from .defaults import build_default_registries, load_prompts_dir
from .errors import (
    AgentCoreError,
    ManifestValidationError,
    RegistrationError,
    UnknownReferenceError,
)
from .interfaces import (
    BaseTool,
    CodeExecutor,
    ExecResult,
    MCPConnector,
    MemoryItem,
    MemoryProvider,
    Message,
    ModelProvider,
    ModelResponse,
    RunContext,
    Scope,
    ToolCall,
    ToolResult,
)
from .loader import load_manifest_dict, load_manifest_file, resolve_manifest
from .memory.in_memory import InMemoryMemoryProvider
from .memory.mem0_provider import Mem0MemoryProvider
from .models.anthropic import AnthropicModelProvider
from .models.echo import EchoModelProvider
from .models.openai import OpenAIModelProvider
from .registry import Registries, Registry
from .runtime import CompiledAgent, RunResult, TraceEvent, compile_agent
from .sandbox.docker_executor import DockerCodeExecutor
from .schema import (
    AgentManifest,
    IOSchema,
    Limits,
    MemoryConfig,
    MemoryScope,
    ModelConfig,
)
from .tools.code_executor import CodeExecArgs, CodeExecutorTool
from .tools.echo import EchoArgs, EchoTool
from .tools.web_search import WebSearchArgs, WebSearchTool

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # schema
    "AgentManifest",
    "ModelConfig",
    "MemoryConfig",
    "MemoryScope",
    "Limits",
    "IOSchema",
    # registries
    "Registry",
    "Registries",
    "build_default_registries",
    "load_prompts_dir",
    # loader
    "load_manifest_dict",
    "load_manifest_file",
    "resolve_manifest",
    # interfaces
    "BaseTool",
    "ToolResult",
    "ModelProvider",
    "ModelResponse",
    "ToolCall",
    "Message",
    "MemoryProvider",
    "MemoryItem",
    "Scope",
    "CodeExecutor",
    "ExecResult",
    "RunContext",
    "MCPConnector",
    # runtime
    "compile_agent",
    "CompiledAgent",
    "RunResult",
    "TraceEvent",
    # built-ins
    "EchoTool",
    "EchoArgs",
    "WebSearchTool",
    "WebSearchArgs",
    "CodeExecutorTool",
    "CodeExecArgs",
    "DockerCodeExecutor",
    "EchoModelProvider",
    "AnthropicModelProvider",
    "OpenAIModelProvider",
    "InMemoryMemoryProvider",
    "Mem0MemoryProvider",
    # errors
    "AgentCoreError",
    "RegistrationError",
    "UnknownReferenceError",
    "ManifestValidationError",
]
