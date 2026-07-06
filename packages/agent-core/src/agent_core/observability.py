"""Run persistence + token/cost accounting (PRD Section G).

A ``RunRecord`` captures a completed run (status, answer, full trace, token
usage, cost). ``RunStore`` persists them; ``InMemoryRunStore`` is the tested
default (a Postgres-backed store implements the same interface later).
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from .runtime import TraceEvent

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


class RunStore(ABC):
    @abstractmethod
    async def save(self, record: RunRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(self, run_id: str) -> RunRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def list(self, limit: int = 50) -> list[RunRecord]:
        raise NotImplementedError


class InMemoryRunStore(RunStore):
    """Process-local, newest-first, bounded run store (dev/demo scale)."""

    def __init__(self, max_runs: int = 1000) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._order: list[str] = []
        self._max = max_runs

    async def save(self, record: RunRecord) -> None:
        if record.id not in self._runs:
            self._order.append(record.id)
        self._runs[record.id] = record
        while len(self._order) > self._max:
            self._runs.pop(self._order.pop(0), None)

    async def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def list(self, limit: int = 50) -> list[RunRecord]:
        if limit <= 0:  # guard: -0 slices to the whole list, negatives mis-window
            return []
        return [self._runs[i] for i in reversed(self._order[-limit:])]
