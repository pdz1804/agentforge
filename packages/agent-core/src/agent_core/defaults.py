"""Default registry wiring.

``build_default_registries`` returns a ``Registries`` pre-populated with the
Phase-1 built-ins. Later phases extend this by registering more tools / model
providers / memory backends — without editing the core.
"""

from __future__ import annotations

from pathlib import Path

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
from .tools.web_search import WebSearchTool
from .vectorstore import select_vector_store

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
    registries.tools.register(
        "embedding_search", EmbeddingSearchTool(select_vector_store(), openai_embed)
    )
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


def load_prompts_dir(registries: Registries, prompts_dir: str | Path) -> None:
    """Register every ``*.md`` file under ``prompts_dir`` as a prompt."""
    base = Path(prompts_dir)
    for path in base.rglob("*.md"):
        key = path.relative_to(base.parent).as_posix()
        registries.prompts.register(key, path.read_text(encoding="utf-8"), overwrite=True)
