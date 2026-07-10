"""Eval report + regression baseline persistence (Gap G5).

Two things get stored here:

- Every ``/api/eval`` run's ``DevHeldOutReport``, keyed by a generated id, so a
  report can be fetched again after the request that produced it is gone.
- A named regression *baseline* per manifest id — the held-out (and optional
  dev) ``EvalReport`` a future run's regression gate compares against. Storing
  it server-side means the client no longer has to ship ``baseline_held_out``
  inline on every eval; it can promote a stored report once and then gate
  against it (the inline path stays supported for back-compat).

``EvalReportStore`` is the abstract contract; ``InMemoryEvalReportStore`` is the
tested default, mirroring the ``RunStore`` idiom in ``observability.py``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel

from .eval import DevHeldOutReport, EvalReport, SpotCheckSample

logger = logging.getLogger(__name__)


class StoredEvalReport(BaseModel):
    """A persisted eval run: the full dev+held-out report plus its id."""

    id: str
    manifest_id: str
    report: DevHeldOutReport
    created_at: str = ""


class StoredBaseline(BaseModel):
    """A manifest's stored regression baseline.

    ``held_out`` is the split the regression gate scores against; ``dev`` is
    kept when available so the gate can also flag dev-only (overfitting) gains.
    ``source_report_id`` records which stored report it was promoted from.
    """

    manifest_id: str
    held_out: EvalReport
    dev: EvalReport | None = None
    source_report_id: str | None = None
    created_at: str = ""


class EvalReportStore(ABC):
    @abstractmethod
    async def save_report(
        self, report_id: str, report: DevHeldOutReport, created_at: str = ""
    ) -> StoredEvalReport:
        raise NotImplementedError

    @abstractmethod
    async def get_report(self, report_id: str) -> StoredEvalReport | None:
        raise NotImplementedError

    @abstractmethod
    async def set_baseline(self, baseline: StoredBaseline) -> None:
        """Store (replacing any existing) the regression baseline for a manifest."""
        raise NotImplementedError

    @abstractmethod
    async def get_baseline(self, manifest_id: str) -> StoredBaseline | None:
        raise NotImplementedError

    @abstractmethod
    async def save_spot_check(self, report_id: str, samples: list[SpotCheckSample]) -> None:
        """Store the llm_judge human-audit samples for a report (PRD 14.2).

        Kept in its own slot rather than folded into ``StoredEvalReport`` so the
        stored report's serialization is unchanged for non-judge runs.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_spot_check(self, report_id: str) -> list[SpotCheckSample]:
        """Return a report's spot-check samples, or ``[]`` if none/unknown."""
        raise NotImplementedError


class InMemoryEvalReportStore(EvalReportStore):
    """Process-local eval-report + baseline store (dev/demo scale)."""

    def __init__(self) -> None:
        self._reports: dict[str, StoredEvalReport] = {}
        # One baseline per manifest id; promoting again overwrites it, so the
        # gate always compares against the most recently promoted report.
        self._baselines: dict[str, StoredBaseline] = {}
        # Judge-scored samples awaiting human audit, keyed by report id. Held
        # apart from the stored report so a non-judge report's bytes are unchanged.
        self._spot_checks: dict[str, list[SpotCheckSample]] = {}

    async def save_report(
        self, report_id: str, report: DevHeldOutReport, created_at: str = ""
    ) -> StoredEvalReport:
        stored = StoredEvalReport(
            id=report_id,
            manifest_id=report.manifest_id,
            report=report,
            created_at=created_at,
        )
        self._reports[report_id] = stored
        return stored

    async def get_report(self, report_id: str) -> StoredEvalReport | None:
        return self._reports.get(report_id)

    async def set_baseline(self, baseline: StoredBaseline) -> None:
        self._baselines[baseline.manifest_id] = baseline

    async def get_baseline(self, manifest_id: str) -> StoredBaseline | None:
        return self._baselines.get(manifest_id)

    async def save_spot_check(self, report_id: str, samples: list[SpotCheckSample]) -> None:
        self._spot_checks[report_id] = list(samples)

    async def get_spot_check(self, report_id: str) -> list[SpotCheckSample]:
        return list(self._spot_checks.get(report_id, []))


def select_eval_report_store() -> EvalReportStore:
    """Choose the eval-report store backend (mirrors ``select_run_store``).

    Only the in-memory backend exists today, so it is always returned; the seam
    lets a durable backend be added opt-in later without changing callers.
    """
    return InMemoryEvalReportStore()
