"""Guardrails — output policies enforced on a run's final answer.

A manifest's ``guardrails: list[str]`` names policies that must vet the answer
before it reaches the user. Each name resolves (fail-fast, like tools/prompts)
to a registered :class:`Guardrail`; the runtime runs them in listed order after
the agent produces its answer. A guardrail either passes the answer through
unchanged, rewrites it (e.g. appends a disclaimer, redacts a secret), or
replaces it with a safe refusal.

Invariant: guardrails only ever see and shape the *final answer* string plus the
originating user input. They are pure, synchronous inspectors — no I/O, no
model calls — so enforcement is deterministic and adds no latency-bearing
awaits to the run loop. A manifest that lists no guardrails never constructs or
invokes any of this, so its behavior is byte-for-byte unchanged.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from pydantic import BaseModel


class GuardrailOutcome(BaseModel):
    """Result of running one guardrail over an answer.

    ``answer`` is the (possibly rewritten) answer to carry forward to the next
    guardrail. ``note``, when non-empty, is a short human-readable reason the
    guardrail acted — the runtime emits a trace event only when a guardrail
    reports a note or actually changed the answer, so a pass-through is silent.
    """

    answer: str
    note: str = ""


class Guardrail(ABC):
    """A named output policy applied to a run's final answer.

    Subclasses set ``name`` (the registry key a manifest references) and
    ``description``, then implement :meth:`check`. ``check`` is synchronous and
    side-effect free: it inspects ``user_input`` and ``answer`` and returns a
    :class:`GuardrailOutcome`. Return ``GuardrailOutcome(answer=answer)`` to
    pass through unchanged.
    """

    name: str
    description: str

    @abstractmethod
    def check(self, user_input: str, answer: str) -> GuardrailOutcome:
        """Inspect ``answer`` (with the originating ``user_input`` for context)
        and return the answer to carry forward, plus an optional note."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Built-in guardrails
# --------------------------------------------------------------------------- #
# A specific medical dosage is a number paired with a dosing unit
# (e.g. "500 mg", "2.5ml", "10 units", "5 IU"). Matching the number+unit pair
# (rather than any mention of a drug) keeps general medical discussion allowed
# while catching concrete "take N units" instructions that only a clinician
# should give.
_DOSAGE_UNIT = (
    r"mg|milligram(?:s)?|mcg|microgram(?:s)?|ug|"
    r"ml|milliliter(?:s)?|cc|"
    r"g|gram(?:s)?|"
    r"unit(?:s)?|iu|tablet(?:s)?|pill(?:s)?|capsule(?:s)?|drop(?:s)?|puff(?:s)?"
)
_DOSAGE_RE = re.compile(
    rf"\b\d+(?:\.\d+)?\s*(?:{_DOSAGE_UNIT})\b",
    re.IGNORECASE,
)

_DOSAGE_REFUSAL = (
    "I can't provide a specific medical dosage. Dosing depends on your "
    "individual situation and can be unsafe if wrong — please consult a "
    "licensed pharmacist or physician, or the medication's official leaflet, "
    "for the correct dose."
)


class NoMedicalDosageGuardrail(Guardrail):
    """Refuse answers that state a specific medical dosage.

    If the answer contains a number paired with a dosing unit (``500 mg``,
    ``2 tablets``, ``5 IU``, ...), the whole answer is replaced with a refusal
    that redirects the user to a qualified professional. General, dosage-free
    medical information passes through untouched.
    """

    name = "no_medical_dosage"
    description = "Replace answers giving specific medical dosages with a safe refusal."

    def check(self, user_input: str, answer: str) -> GuardrailOutcome:
        if _DOSAGE_RE.search(answer):
            return GuardrailOutcome(
                answer=_DOSAGE_REFUSAL,
                note="blocked: answer contained a specific medical dosage",
            )
        return GuardrailOutcome(answer=answer)


_DISCLAIMER = (
    "\n\n_This information is for educational purposes only and is not "
    "professional advice._"
)
# Detects a disclaimer already present so we never stack a second one. Keyed on
# the co-occurrence of an "educational/informational" phrase with a "not advice"
# phrase, which is what any reasonable disclaimer contains.
_HAS_EDUCATIONAL = re.compile(r"educational|informational|for information", re.IGNORECASE)
_HAS_NOT_ADVICE = re.compile(
    r"not (?:a substitute for |)?(?:professional |medical |legal |financial |)advice",
    re.IGNORECASE,
)


class EducationalDisclaimerGuardrail(Guardrail):
    """Ensure a short 'informational, not professional advice' disclaimer.

    If the answer does not already carry such a disclaimer, a one-line note is
    appended. Answers that already disclaim (in any phrasing that pairs an
    'educational/informational' cue with a 'not ... advice' cue) are left as-is
    so the disclaimer is never duplicated.
    """

    name = "educational_disclaimer"
    description = "Append a short educational disclaimer when the answer lacks one."

    def check(self, user_input: str, answer: str) -> GuardrailOutcome:
        already = _HAS_EDUCATIONAL.search(answer) and _HAS_NOT_ADVICE.search(answer)
        if already:
            return GuardrailOutcome(answer=answer)
        return GuardrailOutcome(
            answer=answer.rstrip() + _DISCLAIMER,
            note="appended educational disclaimer",
        )


# Obvious, high-confidence secret shapes. Kept deliberately narrow (well-known
# key prefixes + PEM headers) so ordinary prose is never mangled; this is a
# last-line redaction net on model output, not a general DLP scanner. It does
# NOT import the app-layer redaction utility — agent-core stays dependency-free
# of the API app.
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),                # OpenAI-style keys
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b"),           # Anthropic-style keys
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),                # GitHub PATs
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),        # GitHub fine-grained PATs
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),        # Slack tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                    # AWS access key ids
    re.compile(r"AIza[0-9A-Za-z_-]{35}\b"),                 # Google API keys
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),  # PEM keys
]
_REDACTION = "[REDACTED]"


class NoSecretExfilGuardrail(Guardrail):
    """Redact obvious secrets (API keys, tokens, private keys) from the answer.

    Each recognized credential shape is replaced with ``[REDACTED]`` so a model
    that happens to echo a leaked key never surfaces it verbatim. Narrowly
    scoped to well-known key prefixes and PEM headers to avoid corrupting
    ordinary text.
    """

    name = "no_secret_exfil"
    description = "Redact obvious secrets (API keys, tokens, private keys) from the answer."

    def check(self, user_input: str, answer: str) -> GuardrailOutcome:
        redacted = answer
        count = 0
        for pattern in _SECRET_PATTERNS:
            redacted, n = pattern.subn(_REDACTION, redacted)
            count += n
        if count:
            return GuardrailOutcome(
                answer=redacted,
                note=f"redacted {count} secret(s) from the answer",
            )
        return GuardrailOutcome(answer=answer)
