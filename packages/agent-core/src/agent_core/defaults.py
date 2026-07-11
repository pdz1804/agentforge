"""Default registry wiring.

``build_default_registries`` returns a ``Registries`` pre-populated with the
Phase-1 built-ins. Later phases extend this by registering more tools / model
providers / memory backends — without editing the core.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .embeddings import openai_embed
from .guardrails import (
    EducationalDisclaimerGuardrail,
    NoMedicalDosageGuardrail,
    NoSecretExfilGuardrail,
)
from .memory.in_memory import InMemoryMemoryProvider
from .memory.mem0_provider import Mem0MemoryProvider
from .models.anthropic import AnthropicModelProvider
from .models.echo import EchoModelProvider
from .models.openai import OpenAIModelProvider
from .registry import Registries
from .sandbox.docker_executor import DockerCodeExecutor
from .tools.code_executor import CodeExecutorTool
from .tools.echo import EchoTool
from .tools.embedding_search import EmbeddingSearchTool
from .tools.http_fetch import HttpFetchTool
from .tools.web_search import WebSearchTool
from .vectorstore import select_vector_store

logger = logging.getLogger(__name__)

# Env var carrying EXTRA MCP servers (JSON list of {"name","command","args",
# "env"}), the auth-capable path: a token for a real/private server goes in
# "env" (never in code). See `_register_mcp_servers` below.
ENV_MCP_SERVERS = "AGENTFORGE_MCP_SERVERS"

# A few short facts about AgentForge itself, indexed into `embedding_search`
# at startup (best-effort) so the tool returns real hits out of the box
# instead of an empty corpus. See `_seed_demo_docs`.
_DEMO_DOCS: list[tuple[str, str]] = [
    (
        "demo_manifest",
        "AgentForge agents are declared as YAML/JSON manifests with a model "
        "config, prompt_ref, a list of tools, and optional memory, MCP "
        "servers, sub-agents, guardrails, and an io_schema.",
    ),
    (
        "demo_registries",
        "AgentForge uses pluggable registries for tools, models, memory, "
        "prompts, and MCP servers, so a new capability is added by "
        "implementing an interface and registering it — never by editing "
        "the core.",
    ),
    (
        "demo_sandbox",
        "The code_executor tool runs Python inside an isolated Docker "
        "sandbox with no network access and a wall-clock timeout, so an "
        "agent can compute things without touching the host.",
    ),
    (
        "demo_eval",
        "AgentForge ships a dev/held-out evaluation harness that scores "
        "agent runs against a suite and can gate a deploy on a regression "
        "check against a stored baseline.",
    ),
]

# The example echo agent's prompt. The packaged file `prompts/echo_agent.md` is
# the single source of truth; the inline string is only a fallback for installs
# where the prompts directory is not shipped (e.g. a wheel without package data).
_ECHO_PROMPT_KEY = "prompts/echo_agent.md"
_ECHO_PROMPT_FALLBACK = (
    "You are a friendly echo agent. Repeat the user's message back to them.\n"
)


def _echo_prompt_text() -> str:
    # defaults.py -> agent_core -> src -> <package root>/prompts/echo_agent.md
    path = Path(__file__).resolve().parents[2] / "prompts" / "echo_agent.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return _ECHO_PROMPT_FALLBACK


def build_default_registries(prompts_dir: str | Path | None = None) -> Registries:
    """Create registries with the Phase-1 built-ins registered.

    If ``prompts_dir`` is given, every ``*.md`` under it is also registered as a
    prompt keyed by its path relative to the directory's parent
    (e.g. ``prompts/echo_agent.md``).
    """
    registries = Registries()

    registries.tools.register("echo", EchoTool())
    registries.tools.register("web_search", WebSearchTool())
    registries.tools.register("code_executor", CodeExecutorTool(DockerCodeExecutor()))
    registries.tools.register("http_fetch", HttpFetchTool())
    embedding_search_tool = EmbeddingSearchTool(select_vector_store(), openai_embed)
    registries.tools.register("embedding_search", embedding_search_tool)
    _seed_demo_docs(embedding_search_tool)
    _register_mcp_servers(registries)
    registries.models.register("echo", EchoModelProvider())
    registries.models.register("anthropic", AnthropicModelProvider())
    registries.models.register("openai", OpenAIModelProvider())
    registries.memory.register("in_memory", InMemoryMemoryProvider())
    registries.memory.register("mem0", Mem0MemoryProvider())
    registries.guardrails.register("no_medical_dosage", NoMedicalDosageGuardrail())
    registries.guardrails.register("educational_disclaimer", EducationalDisclaimerGuardrail())
    registries.guardrails.register("no_secret_exfil", NoSecretExfilGuardrail())
    registries.prompts.register(_ECHO_PROMPT_KEY, _echo_prompt_text())
    registries.prompts.register(
        "prompts/assistant.md",
        "You are a helpful assistant. Use the available tools when they help "
        "answer the user's request, then give a clear final answer.\n",
    )

    if prompts_dir is not None:
        load_prompts_dir(registries, prompts_dir)

    return registries


def _seed_demo_docs(tool: EmbeddingSearchTool) -> None:
    """Best-effort index the demo docs so ``embedding_search`` returns hits
    without a separate indexing step.

    Needs a working embed provider (``OPENAI_API_KEY`` + the ``openai``
    package); wrapped in a broad try/except so an unset key, missing
    package, or offline test environment silently leaves the corpus empty
    instead of breaking ``build_default_registries``. Uses the same
    ``_run_sync`` helper the MCP auto-binding path uses, so this works
    whether or not an event loop is already running.
    """
    from .runtime import _run_sync  # local import: avoids import cost when unused

    try:
        for doc_id, text in _DEMO_DOCS:
            _run_sync(tool.index(doc_id, text))
    except Exception as exc:
        logger.info("skipping embedding_search demo doc seeding: %s", exc)


def _register_mcp_servers(registries: Registries) -> None:
    """Best-effort ``registries.mcp`` registration — never fatal.

    Registers the public ``everything`` reference MCP server (no auth) plus
    any EXTRA servers named in the ``AGENTFORGE_MCP_SERVERS`` env var (a JSON
    list of ``{"name", "command", "args", "env"}`` objects) — the
    authenticated path: a token for a real/private server goes in ``env``,
    letting a caller add one without any code change.

    ``.discover()`` (which spawns a subprocess) is NEVER called here — only
    the connector + static config are registered, so this is safe to run at
    import/startup time even without ``npx`` or the ``mcp`` package
    installed. Any failure (missing ``mcp`` package, bad env JSON, a
    malformed entry) is logged and skipped, never raised, so environments
    without MCP support still get a working ``Registries``.
    """
    try:
        from .mcp.connector import StdioMCPConnector
        from .runtime import MCPServerBinding
    except ImportError as exc:  # pragma: no cover - optional extra
        logger.info("mcp support unavailable; skipping MCP server registration: %s", exc)
        return

    try:
        registries.mcp.register(
            "everything",
            MCPServerBinding(
                StdioMCPConnector(),
                {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"]},
            ),
        )
    except Exception as exc:
        logger.info("failed to register the default 'everything' MCP server: %s", exc)

    raw = os.environ.get(ENV_MCP_SERVERS)
    if not raw:
        return
    try:
        extra_servers = json.loads(raw)
        if not isinstance(extra_servers, list):
            raise ValueError(f"{ENV_MCP_SERVERS} must be a JSON list of server objects")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.info("ignoring invalid %s: %s", ENV_MCP_SERVERS, exc)
        return

    for entry in extra_servers:
        try:
            _register_one_extra_mcp_server(registries, entry)
        except Exception as exc:
            logger.info("skipping invalid %s entry %r: %s", ENV_MCP_SERVERS, entry, exc)


def _register_one_extra_mcp_server(registries: Registries, entry: Any) -> None:
    """Parse and register a single ``AGENTFORGE_MCP_SERVERS`` list entry.

    Raises on a malformed entry; the caller logs + skips rather than letting
    one bad entry take down the whole registration pass.
    """
    from .mcp.connector import StdioMCPConnector
    from .runtime import MCPServerBinding

    if not isinstance(entry, dict):
        raise ValueError("server entry must be a JSON object")
    name = entry.get("name")
    command = entry.get("command")
    if not name or not isinstance(name, str):
        raise ValueError("server entry missing a string 'name'")
    if not command or not isinstance(command, str):
        raise ValueError("server entry missing a string 'command'")
    config: dict[str, Any] = {
        "command": command,
        "args": entry.get("args") or [],
        "env": entry.get("env"),
    }
    registries.mcp.register(name, MCPServerBinding(StdioMCPConnector(), config))


def load_prompts_dir(registries: Registries, prompts_dir: str | Path) -> None:
    """Register every ``*.md`` file under ``prompts_dir`` as a prompt."""
    base = Path(prompts_dir)
    for path in base.rglob("*.md"):
        key = path.relative_to(base.parent).as_posix()
        registries.prompts.register(key, path.read_text(encoding="utf-8"), overwrite=True)
