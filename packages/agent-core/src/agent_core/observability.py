"""Run persistence + token/cost accounting (PRD Section G).

A ``RunRecord`` captures a completed run (status, answer, full trace, token
usage, cost). ``RunStore`` persists them; ``InMemoryRunStore`` is the tested
default (process-local, lost on restart). ``PostgresRunStore`` (PRD Phase 8)
implements the same interface durably, selected opt-in via
``select_run_store`` — unset env means the default (in-memory) is unchanged.
"""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod

import asyncpg
from pydantic import BaseModel, Field

from .runtime import TraceEvent

logger = logging.getLogger(__name__)

# Approximate USD per 1K tokens (input, output). Unknown models cost 0 (logged
# as such); refine as needed. Keeps cost visible without a pricing service.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (0.003, 0.015),
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "text-embedding-3-small": (0.00002, 0.0),
}


def usage_totals(trace: list[TraceEvent]) -> dict[str, int]:
    return {
        "input_tokens": sum(e.usage.get("input_tokens", 0) for e in trace),
        "output_tokens": sum(e.usage.get("output_tokens", 0) for e in trace),
    }


def token_cost(usage: dict[str, int], model: str) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    cost = (
        usage.get("input_tokens", 0) / 1000 * price_in
        + usage.get("output_tokens", 0) / 1000 * price_out
    )
    return round(cost, 6)


class RunRecord(BaseModel):
    id: str
    manifest_id: str
    model: str
    input: str
    status: str  # "completed" | "timeout" | "error"
    answer: str | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    created_at: str = ""
    # Per-user data isolation scaffold (additive). "public" is the same
    # sentinel `apps/api/app/auth.py` uses for DEFAULT_USER — every row
    # defaults to it, so unscoped reads (owner=None) and existing callers that
    # never pass owner are completely unaffected.
    owner: str = "public"


class RunStore(ABC):
    @abstractmethod
    async def save(self, record: RunRecord, owner: str = "public") -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(self, run_id: str, owner: str | None = None) -> RunRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def list(self, limit: int = 50, owner: str | None = None) -> list[RunRecord]:
        raise NotImplementedError


class InMemoryRunStore(RunStore):
    """Process-local, newest-first, bounded run store (dev/demo scale)."""

    def __init__(self, max_runs: int = 1000) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._order: list[str] = []
        self._max = max_runs

    async def save(self, record: RunRecord, owner: str = "public") -> None:
        # `owner` (not `record.owner`) is the authoritative value stamped on
        # the row — mirrors the write-path contract of the other two stores,
        # where the caller passes the record's fields plus owner separately.
        record = record.model_copy(update={"owner": owner})
        if record.id not in self._runs:
            self._order.append(record.id)
        self._runs[record.id] = record
        while len(self._order) > self._max:
            self._runs.pop(self._order.pop(0), None)

    async def get(self, run_id: str, owner: str | None = None) -> RunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        if owner is not None and record.owner != owner:
            return None
        return record

    async def list(self, limit: int = 50, owner: str | None = None) -> list[RunRecord]:
        if limit <= 0:  # guard: -0 slices to the whole list, negatives mis-window
            return []
        out: list[RunRecord] = []
        for run_id in reversed(self._order):
            record = self._runs[run_id]
            if owner is not None and record.owner != owner:
                continue
            out.append(record)
            if len(out) >= limit:
                break
        return out


# --------------------------------------------------------------------------- #
# Trace retention/sampling (PRD Phase 8, Open Q#6): cap how much trace a
# single run persists so one runaway agent (looping tools, huge outputs)
# can't blow up storage. Applied by PostgresRunStore before every write;
# InMemoryRunStore is untouched (it already bounds run *count*, and stays the
# tested default — no behavior change there).
# --------------------------------------------------------------------------- #
DEFAULT_MAX_TRACE_EVENTS = 500


def truncate_trace(
    trace: list[TraceEvent], max_events: int = DEFAULT_MAX_TRACE_EVENTS
) -> tuple[list[TraceEvent], bool]:
    """Cap ``trace`` to ``max_events``, keeping it useful for debugging.

    Keeps the earliest events (the setup/reasoning that usually matters most)
    plus the final event (the terminal ``answer``/``limit`` event that decides
    the run's outcome), and inserts a synthetic ``sampled`` ``TraceEvent`` in
    between recording how many events were dropped — so a truncated trace is
    always visibly marked as such, never silently incomplete.

    Returns ``(trace, False)`` unchanged when it already fits.
    """
    if max_events < 3:  # need room for >=1 head event + the marker + the tail
        raise ValueError("max_events must be >= 3")
    if len(trace) <= max_events:
        return list(trace), False
    head = trace[: max_events - 2]
    tail = trace[-1:]
    dropped = len(trace) - len(head) - len(tail)
    marker = TraceEvent(
        step=head[-1].step if head else 0,
        type="sampled",
        node="observability",
        detail=f"trace retention: {dropped} event(s) omitted (cap={max_events})",
    )
    return [*head, marker, *tail], True


# --------------------------------------------------------------------------- #
# Postgres-backed durability (PRD Phase 8) — opt-in, selected by
# `select_run_store`. Nothing here runs unless DATABASE_URL (or
# AGENTFORGE_RUN_STORE=postgres) is set, so existing deployments keep the
# in-memory store untouched.
# --------------------------------------------------------------------------- #
ENV_DATABASE_URL = "DATABASE_URL"
ENV_RUN_STORE = "AGENTFORGE_RUN_STORE"

DEFAULT_RETENTION_DAYS = 30
DEFAULT_RETENTION_ROWS = 5000

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    model TEXT NOT NULL,
    input TEXT NOT NULL,
    status TEXT NOT NULL,
    answer TEXT,
    trace JSONB NOT NULL,
    usage JSONB NOT NULL,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    owner TEXT NOT NULL DEFAULT 'public'
)
"""
_CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS runs_inserted_at_idx ON runs (inserted_at DESC)"
# Idempotent migration for a table created before the per-user scaffold: a
# pre-existing `runs` table gains the `owner` column (defaulted to the
# single-user sentinel) without any data loss or downtime.
_ALTER_TABLE_ADD_OWNER_SQL = (
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS owner TEXT NOT NULL DEFAULT 'public'"
)
_CREATE_OWNER_INDEX_SQL = "CREATE INDEX IF NOT EXISTS runs_owner_idx ON runs (owner)"


class PostgresRunStore(RunStore):
    """Durable run store backed by Postgres — runs survive process restart.

    Same ``save``/``get``/``list`` contract as ``InMemoryRunStore``, plus
    ``prune`` for retention. The ``runs`` table is created on first use (no
    separate migration step needed at this scale). Ordering uses a
    server-assigned ``inserted_at`` rather than the caller-supplied
    ``created_at`` string, so ``list``/``prune`` don't trust client clocks.
    """

    def __init__(self, dsn: str, max_trace_events: int = DEFAULT_MAX_TRACE_EVENTS) -> None:
        self._dsn = dsn
        self._max_trace_events = max_trace_events
        self._pool: asyncpg.Pool | None = None
        self._pool_lock = asyncio.Lock()

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is None:  # re-check: another task may have won the race
                pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
                async with pool.acquire() as conn:
                    await conn.execute(_CREATE_TABLE_SQL)
                    await conn.execute(_CREATE_INDEX_SQL)
                    # Idempotent: no-op on a fresh table (column already exists
                    # from _CREATE_TABLE_SQL) and safe to re-run every startup.
                    await conn.execute(_ALTER_TABLE_ADD_OWNER_SQL)
                    await conn.execute(_CREATE_OWNER_INDEX_SQL)
                self._pool = pool
        return self._pool

    async def save(self, record: RunRecord, owner: str = "public") -> None:
        pool = await self._ensure_pool()
        trace, sampled = truncate_trace(record.trace, self._max_trace_events)
        if sampled:
            logger.info(
                "run %s: trace sampled for storage (%d -> %d events)",
                record.id,
                len(record.trace),
                len(trace),
            )
        trace_json = json.dumps([e.model_dump(mode="json") for e in trace])
        usage_json = json.dumps(record.usage)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO runs
                    (id, manifest_id, model, input, status, answer,
                     trace, usage, cost_usd, created_at, owner)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11)
                ON CONFLICT (id) DO UPDATE SET
                    manifest_id = EXCLUDED.manifest_id,
                    model = EXCLUDED.model,
                    input = EXCLUDED.input,
                    status = EXCLUDED.status,
                    answer = EXCLUDED.answer,
                    trace = EXCLUDED.trace,
                    usage = EXCLUDED.usage,
                    cost_usd = EXCLUDED.cost_usd,
                    created_at = EXCLUDED.created_at,
                    owner = EXCLUDED.owner
                """,
                record.id,
                record.manifest_id,
                record.model,
                record.input,
                record.status,
                record.answer,
                trace_json,
                usage_json,
                record.cost_usd,
                record.created_at,
                owner,
            )

    async def get(self, run_id: str, owner: str | None = None) -> RunRecord | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if owner is None:
                row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM runs WHERE id = $1 AND owner = $2", run_id, owner
                )
        return self._row_to_record(row) if row is not None else None

    async def list(self, limit: int = 50, owner: str | None = None) -> list[RunRecord]:
        if limit <= 0:  # guard: matches InMemoryRunStore's -0/negative behavior
            return []
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if owner is None:
                rows = await conn.fetch(
                    "SELECT * FROM runs ORDER BY inserted_at DESC LIMIT $1", limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM runs WHERE owner = $1 ORDER BY inserted_at DESC LIMIT $2",
                    owner,
                    limit,
                )
        return [self._row_to_record(r) for r in rows]

    async def prune(
        self, max_age_days: int = DEFAULT_RETENTION_DAYS, max_rows: int = DEFAULT_RETENTION_ROWS
    ) -> int:
        """Delete runs older than ``max_age_days``, then trim to the ``max_rows``
        newest survivors. Returns the total row count deleted. Call this from
        an external scheduler (cron, etc.) — this store does not self-schedule.
        """
        pool = await self._ensure_pool()
        deleted = 0
        async with pool.acquire() as conn:
            tag = await conn.execute(
                "DELETE FROM runs WHERE inserted_at < now() - ($1 || ' days')::interval",
                str(max_age_days),
            )
            deleted += _rows_affected(tag)
            tag = await conn.execute(
                """
                DELETE FROM runs WHERE id IN (
                    SELECT id FROM runs ORDER BY inserted_at DESC OFFSET $1
                )
                """,
                max_rows,
            )
            deleted += _rows_affected(tag)
        return deleted

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _row_to_record(row: asyncpg.Record) -> RunRecord:
        return RunRecord(
            id=row["id"],
            manifest_id=row["manifest_id"],
            model=row["model"],
            input=row["input"],
            status=row["status"],
            answer=row["answer"],
            trace=[TraceEvent.model_validate(e) for e in json.loads(row["trace"])],
            usage=json.loads(row["usage"]),
            cost_usd=row["cost_usd"],
            created_at=row["created_at"],
            # Always present: `_ensure_pool` runs the idempotent ADD COLUMN
            # migration before any query can reach this method.
            owner=row["owner"],
        )


def _rows_affected(command_tag: str) -> int:
    """Parse asyncpg's ``"DELETE 5"``-style command tag into a row count."""
    parts = command_tag.split()
    return int(parts[-1]) if parts and parts[-1].isdigit() else 0


async def postgres_reachable(dsn: str, timeout_s: float = 2.0) -> bool:
    """Quick connectivity probe, used by ``select_run_store`` and by tests to
    decide whether to skip Postgres-dependent cases.
    """
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=timeout_s)
    except Exception:  # noqa: BLE001 — any failure (auth, network, timeout) means "not reachable"
        return False
    await conn.close()
    return True


def select_run_store() -> RunStore:
    """Choose the run store from env (PRD Phase 8).

    Default (neither env var set) is unchanged: ``InMemoryRunStore``. Setting
    ``DATABASE_URL`` (or ``AGENTFORGE_RUN_STORE=postgres``) opts into
    ``PostgresRunStore`` — but only when Postgres actually answers at
    startup; a misconfigured or unreachable DB logs a warning and falls back
    to in-memory rather than breaking API startup.
    """
    dsn = os.environ.get(ENV_DATABASE_URL, "").strip()
    opted_in = bool(dsn) or os.environ.get(ENV_RUN_STORE, "").strip().lower() == "postgres"
    if not opted_in:
        return InMemoryRunStore()
    if not dsn:
        logger.warning(
            "%s=postgres set but %s is empty; falling back to in-memory run store",
            ENV_RUN_STORE,
            ENV_DATABASE_URL,
        )
        return InMemoryRunStore()
    try:
        reachable = asyncio.run(postgres_reachable(dsn))
    except RuntimeError:
        # Already inside a running event loop (e.g. imported from async code) —
        # can't run a nested asyncio.run(); fail safe rather than crash startup.
        logger.warning("cannot probe Postgres from a running event loop; using in-memory run store")
        return InMemoryRunStore()
    if not reachable:
        logger.warning(
            "%s set but Postgres is unreachable at startup; falling back to in-memory run store",
            ENV_DATABASE_URL,
        )
        return InMemoryRunStore()
    return PostgresRunStore(dsn)
