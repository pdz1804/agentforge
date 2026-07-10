"""Agent manifest persistence + version history (Gap G4).

A manifest is *data* (see ``schema.py``): storing one is storing its validated
dict plus a store-assigned, monotonically increasing version number. Every
save appends a new version and never mutates an existing one, so the full
history of an agent id is retained and any two versions can be diffed.

``ManifestStore`` is the abstract contract; ``InMemoryManifestStore`` is the
tested default (process-local, lost on restart), mirroring the ``RunStore``
idiom in ``observability.py``. ``select_manifest_store`` picks the backend the
same opt-in way — today only the in-memory backend exists, so it is always
returned; a durable backend can slot in later without touching callers.
"""

from __future__ import annotations

import difflib
import json
import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ManifestVersion(BaseModel):
    """One stored version of a manifest.

    ``version`` is assigned by the store (not trusted from the client), so it
    is monotonic per ``manifest_id`` regardless of what the manifest dict's own
    ``version`` field says. ``manifest`` is the validated manifest dict exactly
    as accepted by the loader.
    """

    manifest_id: str
    version: int
    manifest: dict
    created_at: str = ""
    # Per-user data isolation scaffold (additive) — see RunRecord.owner in
    # observability.py for the full rationale; same "public" sentinel.
    owner: str = "public"


class ManifestStore(ABC):
    @abstractmethod
    async def save(
        self, manifest_id: str, manifest: dict, created_at: str = "", owner: str = "public"
    ) -> ManifestVersion:
        """Append a new version for ``manifest_id`` and return the stored record.

        The store assigns the next version number (latest + 1, starting at 1).
        """
        raise NotImplementedError

    @abstractmethod
    async def get(
        self, manifest_id: str, version: int | None = None, owner: str | None = None
    ) -> ManifestVersion | None:
        """Return one version (``None`` => the latest), or ``None`` if absent.

        ``owner`` (when not ``None``) additionally requires the returned
        version's ``owner`` to match, else ``None`` (a caller can't
        distinguish "wrong owner" from "doesn't exist").
        """
        raise NotImplementedError

    @abstractmethod
    async def list_ids(self, owner: str | None = None) -> list[str]:
        """Return every stored manifest id.

        ``owner`` (when not ``None``) filters to ids whose latest version
        belongs to that owner.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_versions(
        self, manifest_id: str, owner: str | None = None
    ) -> list[ManifestVersion]:
        """Return all versions for ``manifest_id``, oldest first ([] if absent).

        ``owner`` (when not ``None``) filters to versions belonging to that
        owner.
        """
        raise NotImplementedError


class InMemoryManifestStore(ManifestStore):
    """Process-local manifest store keyed by id, retaining every version."""

    def __init__(self) -> None:
        # id -> versions in ascending version order (append-only). The invariant
        # the rest of the store relies on: index i holds version i+1, and the
        # last element is always the latest.
        self._versions: dict[str, list[ManifestVersion]] = {}

    async def save(
        self, manifest_id: str, manifest: dict, created_at: str = "", owner: str = "public"
    ) -> ManifestVersion:
        history = self._versions.setdefault(manifest_id, [])
        record = ManifestVersion(
            manifest_id=manifest_id,
            version=len(history) + 1,
            manifest=manifest,
            created_at=created_at,
            owner=owner,
        )
        history.append(record)
        return record

    async def get(
        self, manifest_id: str, version: int | None = None, owner: str | None = None
    ) -> ManifestVersion | None:
        history = self._versions.get(manifest_id)
        if not history:
            return None
        if version is None:
            record = history[-1]
        elif version < 1 or version > len(history):
            return None
        else:
            record = history[version - 1]
        if owner is not None and record.owner != owner:
            return None
        return record

    async def list_ids(self, owner: str | None = None) -> list[str]:
        if owner is None:
            return list(self._versions.keys())
        return [
            manifest_id
            for manifest_id, history in self._versions.items()
            if history and history[-1].owner == owner
        ]

    async def list_versions(
        self, manifest_id: str, owner: str | None = None
    ) -> list[ManifestVersion]:
        history = self._versions.get(manifest_id, [])
        if owner is None:
            return list(history)
        return [v for v in history if v.owner == owner]


def diff_manifest_versions(
    older: ManifestVersion, newer: ManifestVersion
) -> dict:
    """Diff two stored manifest versions at both field and text granularity.

    Returns a mapping with:
    - ``from_version`` / ``to_version``: the two version numbers compared.
    - ``fields_changed``: per top-level key that differs, its ``from``/``to``
      values (``added``/``removed`` keys show the missing side as ``None``).
    - ``text_diff``: a unified diff of the pretty-printed JSON, so a UI can show
      an exact line-level view, not just which keys moved.
    """
    older_m = older.manifest
    newer_m = newer.manifest
    fields_changed: list[dict] = []
    for key in sorted(set(older_m) | set(newer_m)):
        before = older_m.get(key)
        after = newer_m.get(key)
        if before != after:
            fields_changed.append({"field": key, "from": before, "to": after})

    before_text = json.dumps(older_m, indent=2, sort_keys=True).splitlines()
    after_text = json.dumps(newer_m, indent=2, sort_keys=True).splitlines()
    text_diff = "\n".join(
        difflib.unified_diff(
            before_text,
            after_text,
            fromfile=f"v{older.version}",
            tofile=f"v{newer.version}",
            lineterm="",
        )
    )
    return {
        "from_version": older.version,
        "to_version": newer.version,
        "fields_changed": fields_changed,
        "text_diff": text_diff,
    }


def select_manifest_store() -> ManifestStore:
    """Choose the manifest store backend (mirrors ``select_run_store``).

    The in-memory backend is the only one today, so it is always returned; the
    seam exists so a durable backend can be added opt-in later without changing
    any caller.
    """
    return InMemoryManifestStore()
