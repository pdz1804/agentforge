"""Agent runtime — compile a manifest into a runnable LangGraph and drive it.

Design (PRD Section 8.4): LangGraph is used purely as the orchestration +
checkpointing graph. The nodes call our own ``ModelProvider`` / ``BaseTool``
abstractions directly, so the Unified Agent Core stays the single source of
truth (and FloraLens reuse stays clean) rather than coupling every provider to
LangChain's model/tool types.

Graph shape (a minimal ReAct loop):

    START -> agent -> (tool_calls?) -> tools -> agent -> ... -> END

``agent`` calls the model; if it returns tool calls, ``tools`` executes them and
loops back; otherwise the run ends with an answer. ``limits.max_steps`` bounds
the loop; ``limits.wall_clock_s`` bounds non-streaming runs.
"""

import asyncio
import contextvars
import logging
import operator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, NamedTuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .checkpoint import CheckpointerArg, checkpointer_from_env
from .checkpoint import aclose as aclose_checkpointer
from .checkpoint import materialize as materialize_checkpointer
from .errors import AgentCoreError, UnknownReferenceError
from .guardrails import Guardrail
from .interfaces import (
    BaseTool,
    MCPConnector,
    MemoryItem,
    MemoryProvider,
    Message,
    ModelProvider,
    Scope,
    ToolCall,
    ToolResult,
)
from .registry import Registries
from .schema import AgentManifest

logger = logging.getLogger(__name__)

# Carries the active run's eval_mode across the tool-loop boundary so a
# supervisor's delegation to sub-agents stays eval-isolated (deterministic, no
# memory writes). Set around graph execution in arun/astream.
_RUN_EVAL: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agent_run_eval_mode", default=False
)


class TraceEvent(BaseModel):
    """One observable step in a run (PRD Section 8.4 trace bus)."""

    step: int
    type: str  # "model" | "tool" | "answer" | "limit" | "guardrail"
    node: str
    detail: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    # Set to the acting guardrail's name on a "guardrail" event; empty on every
    # other event. Additive with a default so the SSE TraceEvent schema and all
    # non-guardrail traces are unchanged.
    guardrail: str = ""


class RunResult(BaseModel):
    answer: str | None
    steps: int
    trace: list[TraceEvent]
    stopped_reason: str  # "answer" | "max_steps" | "no_action"


class _RunState(TypedDict):
    messages: Annotated[list[Message], operator.add]
    trace: Annotated[list[TraceEvent], operator.add]
    steps: int
    answer: str | None
    pending: list[ToolCall]


class CompiledAgent:
    """A manifest compiled into a runnable graph. Reusable across runs."""

    def __init__(
        self,
        manifest: AgentManifest,
        provider: ModelProvider,
        system_prompt: str,
        tools: dict[str, BaseTool],
        memory: MemoryProvider | None = None,
        checkpointer: CheckpointerArg = None,
        guardrails: list[Guardrail] | None = None,
    ) -> None:
        self.manifest = manifest
        self._provider = provider
        self._system_prompt = system_prompt
        self._tools = tools
        self._memory = memory
        # Output guardrails run in listed order over the final answer. Empty
        # (the default for every manifest without a `guardrails` list) means
        # enforcement is skipped entirely and the run is unchanged.
        self._guardrails = guardrails or []
        # Opt-in durable checkpointer (Phase 5): None keeps the Phase 2
        # contract (each run starts fresh, no cross-run bleed). When set,
        # LangGraph persists state per `thread_id` so same-thread runs resume.
        # May start out as a `PendingSqliteCheckpointer` spec (constructing
        # the real async saver needs a running event loop; see
        # `_ensure_checkpointer_ready`) and get replaced by the real saver on
        # first use. A lock guards that one-time replacement against
        # concurrent runs racing to materialize it.
        self._checkpointer = checkpointer
        self._checkpointer_lock = asyncio.Lock()
        if manifest.memory is not None:
            self._mem_scope: Scope | None = Scope(manifest.memory.scope.value)
            self._mem_namespace = manifest.memory.namespace
        else:
            self._mem_scope = None
            self._mem_namespace = ""
        builder = self._build_state_graph()
        ready = self._checkpointer if isinstance(self._checkpointer, BaseCheckpointSaver) else None
        self._graph = builder.compile(checkpointer=ready)
        # A second, permanently checkpointer-less compile of the same graph
        # definition. Eval runs always use this one: eval reproducibility
        # requires every run to start fresh regardless of any configured
        # checkpointer (see `arun`/`astream`), and a single shared
        # `CompiledStateGraph` cannot safely have its `.checkpointer` toggled
        # per call under concurrent runs, so a separate static instance is
        # used instead of mutating `self._graph` around eval calls.
        self._eval_graph = builder.compile(checkpointer=None)

    # -- graph construction ------------------------------------------------- #
    def _build_state_graph(self) -> StateGraph:
        max_steps = self.manifest.limits.max_steps

        async def agent_node(state: _RunState, config: RunnableConfig | None = None) -> dict:
            cfg = (config or {}).get("configurable", {})
            resp = await self._provider.complete(
                state["messages"],
                tools=list(self._tools.values()),
                model=self.manifest.model.name,
                temperature=cfg.get("temperature", self.manifest.model.temperature),
                max_tokens=self.manifest.model.max_tokens,
            )
            step = state["steps"] + 1
            if resp.tool_calls:
                # Ensure every tool call has a stable id so the assistant turn and
                # the matching tool-result turn pair correctly for any provider
                # (real providers supply ids; scripted/echo may not).
                for i, tc in enumerate(resp.tool_calls):
                    if tc.id is None:
                        tc.id = f"call_{step}_{i}"
                assistant = Message(
                    role="assistant", content=resp.text, tool_calls=resp.tool_calls
                )
                return {
                    "messages": [assistant],
                    "steps": step,
                    "pending": resp.tool_calls,
                    "trace": [
                        TraceEvent(
                            step=step,
                            type="model",
                            node="agent",
                            detail=f"requested {len(resp.tool_calls)} tool call(s)",
                            tool_calls=resp.tool_calls,
                            usage=resp.usage,
                        )
                    ],
                }
            return {
                "messages": [Message(role="assistant", content=resp.text)],
                "steps": step,
                "answer": resp.text,
                "pending": [],
                "trace": [
                    TraceEvent(
                        step=step, type="answer", node="agent", detail=resp.text,
                        usage=resp.usage,
                    )
                ],
            }

        async def tools_node(state: _RunState) -> dict:
            new_messages: list[Message] = []
            events: list[TraceEvent] = []
            for call in state["pending"]:
                tool = self._tools.get(call.name)
                if tool is None:  # defensive; resolver should have caught this
                    detail = f"tool '{call.name}' not available"
                    new_messages.append(
                        Message(
                            role="tool", content=detail, tool_call_id=call.id, name=call.name
                        )
                    )
                    events.append(
                        TraceEvent(step=state["steps"], type="tool", node=call.name, detail=detail)
                    )
                    continue
                try:
                    result = await tool.run(**call.args)
                    content = result.output if result.ok else f"error: {result.error}"
                except Exception as exc:
                    # Bad args (e.g. schema validation) or a tool bug becomes a
                    # recoverable tool-result the model can react to, not a crash.
                    content = f"error: {exc}"
                new_messages.append(
                    Message(
                        role="tool",
                        content=str(content),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
                events.append(
                    TraceEvent(
                        step=state["steps"],
                        type="tool",
                        node=call.name,
                        detail=str(content),
                    )
                )
            return {"messages": new_messages, "pending": [], "trace": events}

        def route_after_agent(state: _RunState) -> str:
            if state.get("answer") is not None:
                return END
            if state["steps"] >= max_steps:
                return END
            if state.get("pending"):
                return "tools"
            return END

        builder: StateGraph = StateGraph(_RunState)
        builder.add_node("agent", agent_node)
        builder.add_node("tools", tools_node)
        builder.add_edge(START, "agent")
        builder.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
        builder.add_edge("tools", "agent")
        # Phase 2 default (checkpointer=None): runs are single-shot, so each
        # run starts from a fresh initial state and stays isolated (no
        # cross-run state bleed). Phase 5: an opt-in checkpointer (see
        # `checkpoint.py`), compiled in by `__init__`, persists state per
        # `thread_id`, so same-thread runs resume prior state (short-term
        # multi-turn memory) while other threads stay isolated.
        return builder

    # -- helpers ------------------------------------------------------------ #
    def _initial_state(
        self,
        user_input: str,
        memories: list[MemoryItem] | None = None,
        include_system_prompt: bool = True,
    ) -> _RunState:
        # `include_system_prompt` is False when a checkpointer already has this
        # thread's history: the static system prompt was added on turn 1 and
        # would otherwise re-accumulate (via the `messages` operator.add
        # reducer) on every subsequent turn. Per-turn memory context is still
        # added every time since it depends on this turn's query.
        prefix: list[Message] = []
        if include_system_prompt:
            prefix.append(Message(role="system", content=self._system_prompt))
        if memories:
            joined = "\n".join(f"- {m.text}" for m in memories)
            prefix.append(
                Message(role="system", content=f"Relevant memory about the user:\n{joined}")
            )
        return {
            "messages": [*prefix, Message(role="user", content=user_input)],
            "trace": [],
            "steps": 0,
            "answer": None,
            "pending": [],
        }

    async def _thread_has_history(self, config: dict) -> bool:
        """True if `config`'s thread already has persisted messages.

        Only meaningful with a checkpointer configured; `StateGraph.aget_state`
        raises without one, so callers must guard on `self._checkpointer`.
        """
        snapshot = await self._graph.aget_state(config)
        return bool(snapshot.values.get("messages"))

    async def _ensure_checkpointer_ready(self) -> None:
        # Materializing a `PendingSqliteCheckpointer` needs a running event
        # loop (see checkpoint.py), so it happens here, not in __init__. The
        # lock makes the one-time swap-in safe if two runs start concurrently
        # before it has completed; after that, `materialize` is a cheap no-op
        # (or re-runs the saver's own idempotent `setup()`).
        async with self._checkpointer_lock:
            materialized = await materialize_checkpointer(self._checkpointer)
            if materialized is not self._checkpointer:
                self._checkpointer = materialized
                self._graph.checkpointer = materialized

    async def aclose(self) -> None:
        """Release the checkpointer's resources (e.g. a sqlite connection's
        background thread). Safe to call whether or not a checkpointer was
        ever configured or materialized; a no-op in the default (Phase 2)
        single-shot setup.
        """
        await aclose_checkpointer(self._checkpointer)

    async def _retrieve(self, user_input: str, eval_mode: bool) -> list[MemoryItem]:
        # Eval mode is memory-isolated (deterministic); a memory failure must
        # never break the run.
        if self._memory is None or self._mem_scope is None or eval_mode:
            return []
        try:
            return await self._memory.search(
                self._mem_scope, self._mem_namespace, user_input, k=5
            )
        except Exception:
            logger.debug("memory retrieve failed", exc_info=True)
            return []

    async def _persist(self, user_input: str, answer: str | None, eval_mode: bool) -> None:
        if self._memory is None or self._mem_scope is None or eval_mode or not answer:
            return
        try:
            await self._memory.add(
                self._mem_scope,
                self._mem_namespace,
                [MemoryItem(text=f"User said: {user_input}\nAssistant answered: {answer}")],
            )
        except Exception:
            logger.debug("memory persist failed", exc_info=True)

    def _config(self, eval_mode: bool, thread_id: str) -> dict:
        temperature = 0.0 if eval_mode else self.manifest.model.temperature
        return {
            "configurable": {"thread_id": thread_id, "temperature": temperature},
            "recursion_limit": self.manifest.limits.max_steps * 2 + 5,
        }

    @staticmethod
    def _stopped_reason(state: dict, max_steps: int) -> str:
        if state.get("answer") is not None:
            return "answer"
        if state["steps"] >= max_steps:
            return "max_steps"
        return "no_action"

    def _enforce_guardrails(
        self, user_input: str, answer: str, step: int
    ) -> tuple[str, list[TraceEvent]]:
        """Run each configured guardrail over ``answer`` in order.

        Returns the final (possibly rewritten/refused) answer and a trace event
        per guardrail that actually acted — a guardrail that passes the answer
        through unchanged and reports no note is silent. Callers with no
        guardrails never reach here, so the no-guardrail path stays untouched.
        """
        events: list[TraceEvent] = []
        current = answer
        for guardrail in self._guardrails:
            outcome = guardrail.check(user_input, current)
            if outcome.note or outcome.answer != current:
                events.append(
                    TraceEvent(
                        step=step,
                        type="guardrail",
                        node=guardrail.name,
                        detail=outcome.note or "answer modified",
                        guardrail=guardrail.name,
                    )
                )
                current = outcome.answer
        return current, events

    # -- run APIs ----------------------------------------------------------- #
    async def arun(
        self, user_input: str, *, eval_mode: bool = False, thread_id: str = "default"
    ) -> RunResult:
        """Run to completion and return the final answer + trace."""
        memories = await self._retrieve(user_input, eval_mode)
        config = self._config(eval_mode, thread_id)
        include_system_prompt = True
        # Eval mode stays single-shot regardless of any configured
        # checkpointer: eval tasks reuse a stable thread_id per task
        # (`eval-<task.id>`), and eval reproducibility requires each run to
        # start fresh rather than resuming a prior eval's state.
        if self._checkpointer is not None and not eval_mode:
            await self._ensure_checkpointer_ready()
            include_system_prompt = not await self._thread_has_history(config)
        graph = self._eval_graph if eval_mode else self._graph
        token = _RUN_EVAL.set(eval_mode)
        try:
            final: dict[str, Any] = await asyncio.wait_for(
                graph.ainvoke(
                    self._initial_state(user_input, memories, include_system_prompt),
                    config,
                ),
                timeout=self.manifest.limits.wall_clock_s,
            )
        except TimeoutError as exc:
            raise AgentCoreError(
                f"run exceeded wall_clock_s={self.manifest.limits.wall_clock_s}"
            ) from exc
        finally:
            _RUN_EVAL.reset(token)
        result = RunResult(
            answer=final.get("answer"),
            steps=final["steps"],
            trace=final["trace"],
            stopped_reason=self._stopped_reason(final, self.manifest.limits.max_steps),
        )
        # Enforce output guardrails on the produced answer. The returned answer
        # (and anything persisted to memory) is the guardrailed one; guardrail
        # trace events are appended so the record shows what was changed.
        if self._guardrails and result.answer is not None:
            enforced, gr_events = self._enforce_guardrails(
                user_input, result.answer, result.steps
            )
            if gr_events:
                result = result.model_copy(
                    update={"answer": enforced, "trace": [*result.trace, *gr_events]}
                )
        await self._persist(user_input, result.answer, eval_mode)
        return result

    async def astream(
        self, user_input: str, *, eval_mode: bool = False, thread_id: str = "default"
    ):
        """Yield ``TraceEvent``s as the run progresses (for SSE).

        Bounded by ``limits.wall_clock_s``; on timeout a final ``limit`` event is
        emitted and the stream ends cleanly.
        """
        memories = await self._retrieve(user_input, eval_mode)
        config = self._config(eval_mode, thread_id)
        include_system_prompt = True
        # See `arun`: eval mode always stays single-shot, even with a
        # checkpointer configured.
        if self._checkpointer is not None and not eval_mode:
            await self._ensure_checkpointer_ready()
            include_system_prompt = not await self._thread_has_history(config)
        graph = self._eval_graph if eval_mode else self._graph
        answer: str | None = None
        last_step = 0
        token = _RUN_EVAL.set(eval_mode)
        try:
            async with asyncio.timeout(self.manifest.limits.wall_clock_s):
                async for update in graph.astream(
                    self._initial_state(user_input, memories, include_system_prompt),
                    config,
                    stream_mode="updates",
                ):
                    for node_output in update.values():
                        if node_output.get("steps") is not None:
                            last_step = node_output["steps"]
                        for event in node_output.get("trace", []):
                            if event.type == "answer":
                                answer = event.detail
                                # With guardrails configured, hold the raw
                                # answer back: guardrails run after the graph
                                # completes and the enforced answer is emitted
                                # then, so a blocked/rewritten answer never
                                # reaches the client. Without guardrails this
                                # branch is skipped and streaming is identical
                                # to before.
                                if self._guardrails:
                                    continue
                            yield event
            # Guardrail enforcement: run policies over the held answer, emit a
            # trace event for each that acted, then emit the enforced answer as
            # a final "answer" event (so SSE consumers that key off "answer"
            # record the guardrailed text, not the raw model output).
            if answer is not None and self._guardrails:
                enforced, gr_events = self._enforce_guardrails(
                    user_input, answer, last_step
                )
                for gr_event in gr_events:
                    yield gr_event
                answer = enforced
                yield TraceEvent(
                    step=last_step,
                    type="answer",
                    node="guardrails" if gr_events else "agent",
                    detail=answer,
                )
            # Graph ended normally. If it stopped without an answer (step budget
            # reached while a tool was still pending, or the model took no
            # action), emit an explicit terminal ``limit`` event so consumers
            # never see a silent, answer-less run.
            if answer is None:
                yield TraceEvent(
                    step=last_step,
                    type="limit",
                    node="runtime",
                    detail=(
                        f"stopped after {last_step} step(s) without an answer "
                        f"(max_steps={self.manifest.limits.max_steps} reached); "
                        "increase limits.max_steps to allow more tool calls"
                    ),
                )
        except TimeoutError:
            yield TraceEvent(
                step=-1,
                type="limit",
                node="runtime",
                detail=f"wall_clock_s={self.manifest.limits.wall_clock_s} exceeded",
            )
        finally:
            _RUN_EVAL.reset(token)
        await self._persist(user_input, answer, eval_mode)


class MCPServerBinding(NamedTuple):
    """A ``registries.mcp`` entry: a connector paired with that server's config.

    ``compile_agent`` auto-binds every ``mcp_servers`` name a manifest declares
    by calling ``connector.discover(config)`` and adapting the result into the
    agent's toolset (PRD Section 8.3 MCPConnector / Section 14.6 extension
    conformance — "connect an MCP server via config, zero core edits"). Only
    exercised when a manifest actually lists ``mcp_servers``: the default
    (empty list) path never constructs or calls a connector, so every existing
    manifest is unaffected.
    """

    connector: MCPConnector
    config: dict[str, Any]


def _run_sync(coro: Any) -> Any:
    """Drive an async coroutine to completion from sync code.

    ``MCPConnector.discover`` is async (it talks to a server process);
    ``compile_agent`` stays a plain sync function so every existing call site
    (tests, the eval harness, the API's ``/api/runs`` SSE generator) keeps
    working unchanged. When no loop is running, ``asyncio.run`` is the direct
    path; when one already is (the API calls ``compile_agent`` from inside its
    own running event loop), ``asyncio.run`` cannot nest inside it, so the
    coroutine is driven on a dedicated thread with its own fresh loop instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class _SubAgentArgs(BaseModel):
    input: str


class SubAgentTool(BaseTool):
    """Exposes a sub-agent to a supervisor as a callable tool (agents-as-tools).

    Delegation reuses the ordinary tool loop: the supervisor's model calls
    ``ask_<id>`` with an ``input``, which runs that sub-agent and returns its
    answer. The sub-agent's internal trace is summarized, not inlined (a nested
    trace is a future enhancement).
    """

    args_schema = _SubAgentArgs

    def __init__(self, agent_id: str, compiled: "CompiledAgent") -> None:
        self.name = f"ask_{agent_id}"
        self.description = f"Delegate a subtask to the '{agent_id}' sub-agent and get its answer."
        self._compiled = compiled

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        # Inherit the supervisor's eval_mode so sub-agents stay eval-isolated.
        result = await self._compiled.arun(args.input, eval_mode=_RUN_EVAL.get())
        meta = {"sub_agent_steps": result.steps, "stopped_reason": result.stopped_reason}
        if result.answer is None:  # sub-agent exhausted / did not answer
            return ToolResult(
                ok=False, output="", error=f"sub-agent stopped: {result.stopped_reason}", meta=meta
            )
        return ToolResult(ok=True, output=result.answer, meta=meta)


def compile_agent(
    manifest: AgentManifest,
    registries: Registries,
    agents: dict[str, AgentManifest] | None = None,
    _visiting: frozenset[str] = frozenset(),
    checkpointer: CheckpointerArg = None,
) -> CompiledAgent:
    """Resolve a manifest's references into a runnable ``CompiledAgent``.

    ``agents`` maps id -> manifest for any ``sub_agents`` the supervisor
    delegates to; each is compiled recursively and exposed as an ``ask_<id>``
    tool. Cycles are rejected. ``registries.get`` raises a clear error on any
    missing tool/model/prompt/memory reference.

    ``checkpointer`` opts the top-level compiled agent into durable multi-turn
    thread memory (Phase 5): pass an explicit saver (see ``checkpoint.py``),
    or leave it ``None`` to fall back to ``AGENTFORGE_CHECKPOINT_DB``. Either
    way the default (no arg, no env var) is unchanged from Phase 2:
    single-shot runs, no cross-run state bleed. Recursively compiled
    sub-agents never inherit a checkpointer, top-level arg or env: each
    ``ask_<id>`` call always runs with ``thread_id="default"`` (see
    ``SubAgentTool.run``), so persisting their state across supervisor calls
    would silently reintroduce that bleed for sub-agents.
    """
    if manifest.id in _visiting:
        raise AgentCoreError(f"sub-agent cycle detected at '{manifest.id}'")

    is_top_level = not _visiting
    resolved_checkpointer = checkpointer
    if resolved_checkpointer is None and is_top_level:
        resolved_checkpointer = checkpointer_from_env()

    provider = registries.models.get(manifest.model.provider)
    system_prompt = registries.prompts.get(manifest.prompt_ref)
    tools = {name: registries.tools.get(name) for name in manifest.tools}

    # MCP auto-binding (additive): a manifest with no `mcp_servers` (the
    # default for every pre-existing manifest) never touches this loop, so
    # behavior is unchanged unless a manifest opts in.
    for server_name in manifest.mcp_servers:
        binding = registries.mcp.get(server_name)
        for mcp_tool in _run_sync(binding.connector.discover(binding.config)):
            if mcp_tool.name in tools:
                raise AgentCoreError(
                    f"mcp tool '{mcp_tool.name}' from server '{server_name}' "
                    f"collides with an existing tool"
                )
            tools[mcp_tool.name] = mcp_tool

    for sub_id in manifest.sub_agents:
        if not agents or sub_id not in agents:
            raise UnknownReferenceError(f"sub_agent manifest '{sub_id}' was not provided")
        sub = compile_agent(agents[sub_id], registries, agents, _visiting | {manifest.id})
        sub_tool = SubAgentTool(sub_id, sub)
        if sub_tool.name in tools:
            raise AgentCoreError(
                f"sub-agent tool '{sub_tool.name}' collides with an existing tool"
            )
        tools[sub_tool.name] = sub_tool

    memory = (
        registries.memory.get(manifest.memory.provider)
        if manifest.memory is not None
        else None
    )
    # Resolve output guardrails fail-fast, exactly like tools/prompts: an
    # unknown guardrail name raises a clear error here rather than being
    # silently ignored at runtime.
    guardrails = [registries.guardrails.get(name) for name in manifest.guardrails]
    return CompiledAgent(
        manifest,
        provider,
        system_prompt,
        tools,
        memory=memory,
        checkpointer=resolved_checkpointer,
        guardrails=guardrails,
    )
