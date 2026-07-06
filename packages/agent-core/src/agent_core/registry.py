"""Pluggable registries — the mechanism behind the "extend without redesign"
guarantee (PRD Section 8.5).

A single generic ``Registry`` provides the shared ``register / get / list``
contract. ``Registries`` bundles the five registries the harness resolves a
manifest against. Adding a tool/model/memory backend is: implement the
interface, ``register`` it. No core edits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .errors import RegistrationError, UnknownReferenceError
from .interfaces import BaseTool, MemoryProvider, ModelProvider

T = TypeVar("T")


class Registry(Generic[T]):
    """A named key→object store with clear errors on misuse."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    def register(self, key: str, obj: T, *, overwrite: bool = False) -> None:
        if not key or not isinstance(key, str):
            raise RegistrationError(f"{self._kind} key must be a non-empty string")
        if key in self._items and not overwrite:
            raise RegistrationError(
                f"{self._kind} '{key}' is already registered "
                f"(pass overwrite=True to replace)"
            )
        self._items[key] = obj

    def get(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError:
            raise UnknownReferenceError(
                f"unknown {self._kind} '{key}'. "
                f"registered {self._kind}s: {self.list() or '[none]'}"
            ) from None

    def has(self, key: str) -> bool:
        return key in self._items

    def list(self) -> list[str]:
        return sorted(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class Registries:
    """The five registries a manifest is resolved against."""

    tools: Registry[BaseTool] = field(default_factory=lambda: Registry("tool"))
    prompts: Registry[str] = field(default_factory=lambda: Registry("prompt"))
    models: Registry[ModelProvider] = field(
        default_factory=lambda: Registry("model provider")
    )
    memory: Registry[MemoryProvider] = field(
        default_factory=lambda: Registry("memory provider")
    )
    # MCP registry stays generic until the connector lands (Phase 3).
    mcp: Registry[object] = field(default_factory=lambda: Registry("mcp server"))
