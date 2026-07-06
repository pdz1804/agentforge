"""Typed error hierarchy for agent-core.

Clear, actionable error messages are a core contract of the harness: a manifest
that references something unregistered must fail fast and say exactly what is
missing, not blow up deep inside the runtime.
"""

from __future__ import annotations


class AgentCoreError(Exception):
    """Base class for every error raised by agent-core."""


class RegistrationError(AgentCoreError):
    """Raised on an invalid or duplicate registry registration."""


class UnknownReferenceError(AgentCoreError):
    """Raised when a manifest references a key absent from a registry."""


class ManifestValidationError(AgentCoreError):
    """Raised when a manifest fails schema validation."""
