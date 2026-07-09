"""Durable checkpointer construction for multi-turn thread memory (Phase 5).

Phase 2 shipped single-shot runs: ``compile_agent`` built a graph with no
checkpointer, so every ``arun``/``astream`` call started from fresh initial
state — no cross-run bleed, but also no short-term thread memory.

This module is opt-in: nothing here runs unless a caller explicitly passes a
checkpointer to ``compile_agent`` or sets ``AGENTFORGE_CHECKPOINT_DB``. When a
checkpointer is wired in, LangGraph keys persisted state by ``thread_id``
(``runtime._config`` already sets ``configurable.thread_id``), so runs on the
same thread resume prior state (multi-turn memory) while different
``thread_id``s stay isolated.
"""

import os
from dataclasses import dataclass

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Env var carrying a filesystem path (or ":memory:") for a durable, file-backed
# checkpointer. Unset by default so existing deployments keep single-shot runs.
ENV_CHECKPOINT_DB = "AGENTFORGE_CHECKPOINT_DB"


@dataclass(frozen=True)
class PendingSqliteCheckpointer:
    """A not-yet-constructed sqlite checkpointer.

    ``AsyncSqliteSaver.__init__`` binds an ``asyncio.Lock`` to the running
    event loop, so it must be built from inside async code. But
    ``compile_agent`` is a synchronous function, typically called at process
    startup before any event loop exists. This dataclass carries just the db
    path; ``materialize`` builds the real saver the first time an async run
    needs it (see ``CompiledAgent._ensure_checkpointer_ready``).
    """

    db_path: str


# The checkpointer a caller may pass to `compile_agent`: an already-usable
# saver (e.g. `InMemorySaver`, or an `AsyncSqliteSaver` a caller built
# themselves from async code), or a not-yet-built sqlite spec from this module.
CheckpointerArg = BaseCheckpointSaver | PendingSqliteCheckpointer | None


def in_memory_checkpointer() -> InMemorySaver:
    """A process-local checkpointer: thread resume within one process, nothing
    written to disk. Used by tests and by callers that only need in-process
    multi-turn memory (e.g. a single long-lived server process). Safe to
    construct synchronously — no event loop requirement.
    """
    return InMemorySaver()


def sqlite_checkpointer(db_path: str) -> PendingSqliteCheckpointer:
    """A durable, file-backed checkpointer surviving process restarts.

    ``db_path`` is a filesystem path (``":memory:"`` also works for an
    in-process-only sqlite db). Returns a spec rather than the real saver
    (see ``PendingSqliteCheckpointer``); the runtime materializes it lazily on
    first async use.
    """
    return PendingSqliteCheckpointer(db_path)


def checkpointer_from_env() -> CheckpointerArg:
    """Build a durable checkpointer spec from ``AGENTFORGE_CHECKPOINT_DB``, or
    return ``None`` if the env var is unset (default: no checkpointer).
    """
    db_path = os.environ.get(ENV_CHECKPOINT_DB)
    if not db_path:
        return None
    return sqlite_checkpointer(db_path)


async def materialize(checkpointer: CheckpointerArg) -> BaseCheckpointSaver | None:
    """Return a ready-to-use checkpointer for this run, or ``None``.

    Builds the real ``AsyncSqliteSaver`` (and awaits its ``setup()``, which
    lazily connects the underlying ``aiosqlite`` connection and creates
    tables) the first time a ``PendingSqliteCheckpointer`` is seen. Must run
    inside a running event loop. Idempotent to call repeatedly: an
    already-real checkpointer is returned as-is (after re-running its own
    self-guarded ``setup()``, if it has one), and a construction, once done,
    is remembered by the caller (see ``CompiledAgent._ensure_checkpointer_ready``)
    so this never rebuilds the connection.
    """
    if checkpointer is None:
        return None
    if isinstance(checkpointer, PendingSqliteCheckpointer):
        conn = aiosqlite.connect(checkpointer.db_path)
        checkpointer = AsyncSqliteSaver(conn)
    setup = getattr(checkpointer, "setup", None)
    if setup is not None:
        # AsyncSqliteSaver.setup() is internally idempotent (guarded by its
        # own lock + `is_setup` flag); safe to call before every run.
        await setup()
    return checkpointer


async def aclose(checkpointer: BaseCheckpointSaver | PendingSqliteCheckpointer | None) -> None:
    """Release resources a materialized checkpointer holds, if any.

    ``AsyncSqliteSaver`` runs its aiosqlite connection on a background
    worker thread; leaving it open past the owning event loop's lifetime
    leaks that thread. Safe to call on ``None``, a never-materialized
    ``PendingSqliteCheckpointer`` (no connection exists yet), or a saver
    with nothing to close (e.g. ``InMemorySaver``).
    """
    conn = getattr(checkpointer, "conn", None)
    close = getattr(conn, "close", None)
    if close is not None:
        await close()
