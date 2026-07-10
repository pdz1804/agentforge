"""agent-core — the Unified Agent Core (AgentForge PRD Section 8).

Public surface for Phase 1: manifest schema + loader/validator, pluggable
registries, core interfaces, and the built-in Echo tool / model providers.
Consumed by both AgentForge and FloraLens.
"""

from __future__ import annotations

# Phase 5: durable checkpointer for multi-turn thread memory.
from .checkpoint import checkpointer_from_env, in_memory_checkpointer, sqlite_checkpointer
from .defaults import build_default_registries, load_prompts_dir
from .errors import (
    AgentCoreError,
    ManifestValidationError,
    RegistrationError,
    UnknownReferenceError,
)
from .guardrails import (
    EducationalDisclaimerGuardrail,
    Guardrail,
    GuardrailOutcome,
    NoMedicalDosageGuardrail,
    NoSecretExfilGuardrail,
)
from .eval import (
    DevHeldOutReport,
    EvalReport,
    EvalSuite,
    EvalTask,
    JudgeFn,
    MatchType,
    RegressionResult,
    ScoringMode,
    Split,
    SpotCheckSample,
    SuitePair,
    TaskScore,
    check_disjoint,
    check_regression,
    collect_spot_check_samples,
    discover_suite_pairs,
    evaluate_pair,
    load_suite_dict,
    load_suite_file,
    make_model_judge_fn,
    render_judge_prompt,
    run_suite,
    run_task,
    score_llm_judge,
    score_programmatic,
    score_rubric,
    score_task,
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
    VectorHit,
    VectorStore,
)
from .loader import load_manifest_dict, load_manifest_file, resolve_manifest
from .manifest_store import (
    InMemoryManifestStore,
    ManifestStore,
    ManifestVersion,
    diff_manifest_versions,
    select_manifest_store,
)
from .eval_store import (
    EvalReportStore,
    InMemoryEvalReportStore,
    StoredBaseline,
    StoredEvalReport,
    select_eval_report_store,
)
from .mcp.connector import StdioMCPConnector, build_mcp_tools
from .memory.in_memory import InMemoryMemoryProvider
from .memory.mem0_provider import Mem0MemoryProvider
from .models.anthropic import AnthropicModelProvider
from .models.echo import EchoModelProvider
from .models.openai import OpenAIModelProvider
from .observability import (
    InMemoryRunStore,
    RunRecord,
    RunStore,
    token_cost,
    usage_totals,
)
from .registry import Registries, Registry
from .runtime import (
    CompiledAgent,
    MCPServerBinding,
    RunResult,
    SubAgentTool,
    TraceEvent,
    compile_agent,
)
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
from .tools.embedding_search import EmbeddingSearchArgs, EmbeddingSearchTool
from .tools.web_search import WebSearchArgs, WebSearchTool
from .vectorstore.in_memory import InMemoryVectorStore

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
    # guardrails
    "Guardrail",
    "GuardrailOutcome",
    "NoMedicalDosageGuardrail",
    "EducationalDisclaimerGuardrail",
    "NoSecretExfilGuardrail",
    # runtime
    "compile_agent",
    "CompiledAgent",
    "SubAgentTool",
    "RunResult",
    "TraceEvent",
    "MCPServerBinding",
    # built-ins
    "EchoTool",
    "EchoArgs",
    "WebSearchTool",
    "WebSearchArgs",
    "CodeExecutorTool",
    "CodeExecArgs",
    "DockerCodeExecutor",
    "EmbeddingSearchTool",
    "EmbeddingSearchArgs",
    "InMemoryVectorStore",
    "VectorStore",
    "VectorHit",
    "StdioMCPConnector",
    "build_mcp_tools",
    "RunRecord",
    "RunStore",
    "InMemoryRunStore",
    "token_cost",
    "usage_totals",
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
    # eval harness (Phase 9)
    "EvalSuite",
    "EvalTask",
    "ScoringMode",
    "Split",
    "MatchType",
    "SuitePair",
    "TaskScore",
    "EvalReport",
    "DevHeldOutReport",
    "RegressionResult",
    "JudgeFn",
    "SpotCheckSample",
    "collect_spot_check_samples",
    "load_suite_dict",
    "load_suite_file",
    "discover_suite_pairs",
    "check_disjoint",
    "score_programmatic",
    "score_rubric",
    "score_llm_judge",
    "score_task",
    "make_model_judge_fn",
    "render_judge_prompt",
    "run_task",
    "run_suite",
    "evaluate_pair",
    "check_regression",
    # manifest persistence + versioning (Gap G4)
    "ManifestStore",
    "ManifestVersion",
    "InMemoryManifestStore",
    "diff_manifest_versions",
    "select_manifest_store",
    # eval report + regression baseline persistence (Gap G5)
    "EvalReportStore",
    "StoredEvalReport",
    "StoredBaseline",
    "InMemoryEvalReportStore",
    "select_eval_report_store",
    # checkpointer (Phase 5)
    "checkpointer_from_env",
    "in_memory_checkpointer",
    "sqlite_checkpointer",
    # run store durability + retention (Phase 8)
    "PostgresRunStore",
    "select_run_store",
    "truncate_trace",
    "postgres_reachable",
]

# Phase 8: durable Postgres-backed run store + trace retention/sampling.
# Kept as a separate import block (rather than merged into the Section-G
# import above) so this addition stays a clean append and doesn't reorder
# the existing observability import.
from .observability import (  # noqa: E402
    DEFAULT_MAX_TRACE_EVENTS,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_RETENTION_ROWS,
    PostgresRunStore,
    postgres_reachable,
    select_run_store,
    truncate_trace,
)

__all__ += [
    "DEFAULT_MAX_TRACE_EVENTS",
    "DEFAULT_RETENTION_DAYS",
    "DEFAULT_RETENTION_ROWS",
]
