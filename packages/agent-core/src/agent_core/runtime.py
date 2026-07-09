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
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .errors import AgentCoreError, UnknownReferenceError
from .interfaces import (
    BaseTool,
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
    type: str  # "model" | "tool" | "answer" | "limit"
    node: str
    detail: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)


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
    ) -> None:
        self.manifest = manifest
        self._provider = provider
        self._system_prompt = system_prompt
        self._tools = tools
        self._memory = memory
        if manifest.memory is not None:
            self._mem_scope: Scope | None = Scope(manifest.memory.scope.value)
            self._mem_namespace = manifest.memory.namespace
        else:
            self._mem_scope = None
            self._mem_namespace = ""
        self._graph = self._build_graph()

    # -- graph construction ------------------------------------------------- #
    def _build_graph(self):
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
        # No durable checkpointer in Phase 2: runs are single-shot, so each run
        # starts from a fresh initial state and stays isolated (no cross-run
        # state bleed, no custom-type serialization). A SQLite/Postgres
        # checkpointer for multi-turn threads + resume lands with memory (Phase 5).
        return builder.compile()

    # -- helpers ------------------------------------------------------------ #
    def _initial_state(
        self, user_input: str, memories: list[MemoryItem] | None = None
    ) -> _RunState:
        system = [Message(role="system", content=self._system_prompt)]
        if memories:
            joined = "\n".join(f"- {m.text}" for m in memories)
            system.append(
                Message(role="system", content=f"Relevant memory about the user:\n{joined}")
            )
        return {
            "messages": [*system, Message(role="user", content=user_input)],
            "trace": [],
            "steps": 0,
            "answer": None,
            "pending": [],
        }

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

    # -- run APIs ----------------------------------------------------------- #
    async def arun(
        self, user_input: str, *, eval_mode: bool = False, thread_id: str = "default"
    ) -> RunResult:
        """Run to completion and return the final answer + trace."""
        memories = await self._retrieve(user_input, eval_mode)
        token = _RUN_EVAL.set(eval_mode)
        try:
            final: dict[str, Any] = await asyncio.wait_for(
                self._graph.ainvoke(
                    self._initial_state(user_input, memories),
                    self._config(eval_mode, thread_id),
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
        answer: str | None = None
        last_step = 0
        token = _RUN_EVAL.set(eval_mode)
        try:
            async with asyncio.timeout(self.manifest.limits.wall_clock_s):
                async for update in self._graph.astream(
                    self._initial_state(user_input, memories),
                    self._config(eval_mode, thread_id),
                    stream_mode="updates",
                ):
                    for node_output in update.values():
                        if node_output.get("steps") is not None:
                            last_step = node_output["steps"]
                        for event in node_output.get("trace", []):
                            if event.type == "answer":
                                answer = event.detail
                            yield event
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
) -> CompiledAgent:
    """Resolve a manifest's references into a runnable ``CompiledAgent``.

    ``agents`` maps id -> manifest for any ``sub_agents`` the supervisor
    delegates to; each is compiled recursively and exposed as an ``ask_<id>``
    tool. Cycles are rejected. ``registries.get`` raises a clear error on any
    missing tool/model/prompt/memory reference.
    """
    if manifest.id in _visiting:
        raise AgentCoreError(f"sub-agent cycle detected at '{manifest.id}'")

    provider = registries.models.get(manifest.model.provider)
    system_prompt = registries.prompts.get(manifest.prompt_ref)
    tools = {name: registries.tools.get(name) for name in manifest.tools}

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
    return CompiledAgent(manifest, provider, system_prompt, tools, memory=memory)
