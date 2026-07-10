"""Guardrail registry, fail-fast resolution, and runtime enforcement.

Driven entirely offline by a scripted model provider (no API key / network), so
these exercise the real enforcement point in ``CompiledAgent`` rather than a
mock of it.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core import (
    EducationalDisclaimerGuardrail,
    GuardrailOutcome,
    ModelProvider,
    ModelResponse,
    NoMedicalDosageGuardrail,
    NoSecretExfilGuardrail,
    UnknownReferenceError,
    build_default_registries,
    compile_agent,
    load_manifest_dict,
    resolve_manifest,
)


class _FixedAnswerProvider(ModelProvider):
    """Answers with a fixed string on the first turn — no tools, no network."""

    provider = "fixed"

    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def complete(self, messages, tools=None, **cfg) -> ModelResponse:
        return ModelResponse(text=self._answer)


def _manifest(guardrails: list[str] | None = None) -> dict:
    m = {
        "id": "guarded",
        "model": {"provider": "fixed", "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
    }
    if guardrails is not None:
        m["guardrails"] = guardrails
    return m


def _compile(answer: str, guardrails: list[str] | None = None):
    registries = build_default_registries()
    registries.models.register("fixed", _FixedAnswerProvider(answer))
    manifest = load_manifest_dict(_manifest(guardrails))
    resolve_manifest(manifest, registries)
    return compile_agent(manifest, registries)


# --------------------------------------------------------------------------- #
# Registry + fail-fast resolution
# --------------------------------------------------------------------------- #
def test_default_registries_include_builtin_guardrails():
    registries = build_default_registries()
    assert registries.guardrails.list() == [
        "educational_disclaimer",
        "no_medical_dosage",
        "no_secret_exfil",
    ]


def test_unknown_guardrail_reference_fails_fast():
    registries = build_default_registries()
    manifest = load_manifest_dict(_manifest(["does_not_exist"]))
    with pytest.raises(UnknownReferenceError) as exc:
        resolve_manifest(manifest, registries)
    assert "does_not_exist" in str(exc.value)
    assert "guardrail" in str(exc.value)


def test_unknown_guardrail_also_fails_at_compile():
    # `compile_agent` resolves guardrails itself (like tools/prompts), so a bad
    # name is caught even if the caller skipped `resolve_manifest`.
    registries = build_default_registries()
    registries.models.register("fixed", _FixedAnswerProvider("hi"))
    manifest = load_manifest_dict(_manifest(["ghost"]))
    with pytest.raises(UnknownReferenceError):
        compile_agent(manifest, registries)


# --------------------------------------------------------------------------- #
# Runtime enforcement
# --------------------------------------------------------------------------- #
def test_no_medical_dosage_blocks_dosage_answer():
    agent = _compile(
        "You should take 500 mg of ibuprofen every 8 hours.",
        guardrails=["no_medical_dosage"],
    )
    result = asyncio.run(agent.arun("how much ibuprofen?"))

    assert "500 mg" not in result.answer
    assert "consult" in result.answer.lower()
    guardrail_events = [e for e in result.trace if e.type == "guardrail"]
    assert guardrail_events and guardrail_events[0].guardrail == "no_medical_dosage"


def test_no_medical_dosage_passes_through_dosage_free_answer():
    original = "Ibuprofen is a common anti-inflammatory; ask your pharmacist about dosing."
    agent = _compile(original, guardrails=["no_medical_dosage"])
    result = asyncio.run(agent.arun("tell me about ibuprofen"))

    assert result.answer == original
    assert [e for e in result.trace if e.type == "guardrail"] == []


def test_educational_disclaimer_is_appended_when_absent():
    agent = _compile("Roses prefer full sun.", guardrails=["educational_disclaimer"])
    result = asyncio.run(agent.arun("how much sun for roses?"))

    assert "educational purposes" in result.answer.lower()
    assert result.answer.startswith("Roses prefer full sun.")


def test_educational_disclaimer_not_duplicated():
    already = (
        "Roses prefer full sun. This is for informational purposes only and is "
        "not professional advice."
    )
    agent = _compile(already, guardrails=["educational_disclaimer"])
    result = asyncio.run(agent.arun("roses?"))

    assert result.answer == already
    assert [e for e in result.trace if e.type == "guardrail"] == []


def test_no_secret_exfil_redacts_keys():
    agent = _compile(
        "Sure, your token is sk-abcdefghijklmnop1234 — keep it safe.",
        guardrails=["no_secret_exfil"],
    )
    result = asyncio.run(agent.arun("what's my key?"))

    assert "sk-abcdefghijklmnop1234" not in result.answer
    assert "[REDACTED]" in result.answer


def test_guardrails_run_in_listed_order():
    # A dosage answer with both guardrails: dosage refusal fires first, then the
    # disclaimer is appended to the refusal.
    agent = _compile(
        "Take 2 tablets daily.",
        guardrails=["no_medical_dosage", "educational_disclaimer"],
    )
    result = asyncio.run(agent.arun("dosage?"))

    assert "2 tablets" not in result.answer
    assert "consult" in result.answer.lower()
    assert "educational purposes" in result.answer.lower()
    nodes = [e.node for e in result.trace if e.type == "guardrail"]
    assert nodes == ["no_medical_dosage", "educational_disclaimer"]


# --------------------------------------------------------------------------- #
# The no-guardrail path is unchanged
# --------------------------------------------------------------------------- #
def test_guardrail_free_manifest_is_unchanged():
    original = "You should take 500 mg of ibuprofen every 8 hours."
    # No `guardrails` key at all — must behave exactly as before this feature.
    agent = _compile(original, guardrails=None)
    result = asyncio.run(agent.arun("dose?"))

    assert result.answer == original
    assert result.stopped_reason == "answer"
    assert all(e.type != "guardrail" for e in result.trace)
    assert all(e.guardrail == "" for e in result.trace)


# --------------------------------------------------------------------------- #
# Streaming enforcement (SSE): raw answer suppressed, enforced answer emitted
# --------------------------------------------------------------------------- #
def test_astream_suppresses_raw_answer_and_emits_enforced():
    agent = _compile(
        "You should take 500 mg of ibuprofen every 8 hours.",
        guardrails=["no_medical_dosage"],
    )

    async def collect():
        return [ev async for ev in agent.astream("dose?")]

    events = asyncio.run(collect())
    answer_events = [e for e in events if e.type == "answer"]
    guardrail_events = [e for e in events if e.type == "guardrail"]

    # Exactly one answer event survives, and it carries the enforced text — the
    # raw dosage answer was never yielded to the stream.
    assert len(answer_events) == 1
    assert "500 mg" not in answer_events[0].detail
    assert "consult" in answer_events[0].detail.lower()
    assert guardrail_events and guardrail_events[0].guardrail == "no_medical_dosage"
    for e in events:
        assert "500 mg" not in e.detail


def test_astream_without_guardrails_streams_raw_answer():
    original = "You should take 500 mg of ibuprofen every 8 hours."
    agent = _compile(original, guardrails=None)

    async def collect():
        return [ev async for ev in agent.astream("dose?")]

    events = asyncio.run(collect())
    answer_events = [e for e in events if e.type == "answer"]
    assert len(answer_events) == 1
    assert answer_events[0].detail == original


# --------------------------------------------------------------------------- #
# Guardrail unit behavior (pure, synchronous)
# --------------------------------------------------------------------------- #
def test_guardrail_check_is_pure_and_synchronous():
    outcome = NoMedicalDosageGuardrail().check("q", "take 5 ml now")
    assert isinstance(outcome, GuardrailOutcome)
    assert outcome.note

    passthrough = NoSecretExfilGuardrail().check("q", "nothing secret here")
    assert passthrough.answer == "nothing secret here"
    assert passthrough.note == ""

    disc = EducationalDisclaimerGuardrail().check("q", "plain answer")
    assert disc.note and "educational" in disc.answer.lower()
