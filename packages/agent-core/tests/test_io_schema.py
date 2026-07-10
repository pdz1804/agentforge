"""Runtime enforcement of manifest ``io_schema`` (PRD Section 8.2).

A manifest's ``io_schema.input`` / ``io_schema.output`` declare the required
*shape* of the user input and the final answer. Enforcement is opt-in: a
manifest with no ``io_schema`` (or plain-text sides) runs exactly as before.
When a shape is declared, input is validated before the run and output after
guardrails; a mismatch raises a clear ``AgentCoreError`` naming the field.

Driven entirely offline (echo model + a fixed-answer provider), so these
exercise the real enforcement point in ``CompiledAgent`` with no API key or
network.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core import (
    AgentCoreError,
    ModelProvider,
    ModelResponse,
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


def _manifest(
    provider: str,
    *,
    io_schema: dict | None = None,
    guardrails: list[str] | None = None,
) -> dict:
    m: dict = {
        "id": "io_runner",
        "model": {"provider": provider, "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
    }
    if io_schema is not None:
        m["io_schema"] = io_schema
    if guardrails is not None:
        m["guardrails"] = guardrails
    return m


def _compile_echo(io_schema: dict | None = None):
    """Offline echo model: the answer is the user input verbatim."""
    registries = build_default_registries()
    manifest = load_manifest_dict(_manifest("echo", io_schema=io_schema))
    resolve_manifest(manifest, registries)
    return compile_agent(manifest, registries)


def _compile_fixed(answer: str, io_schema: dict | None = None, guardrails=None):
    registries = build_default_registries()
    registries.models.register("fixed", _FixedAnswerProvider(answer))
    manifest = load_manifest_dict(
        _manifest("fixed", io_schema=io_schema, guardrails=guardrails)
    )
    resolve_manifest(manifest, registries)
    return compile_agent(manifest, registries)


# --------------------------------------------------------------------------- #
# Input schema enforcement
# --------------------------------------------------------------------------- #
def test_input_schema_rejects_malformed_input():
    agent = _compile_echo({"input": "json_object"})
    with pytest.raises(AgentCoreError) as exc:
        asyncio.run(agent.arun("this is not json"))
    # The error names the failing side of the contract.
    assert "input" in str(exc.value).lower()


def test_input_schema_accepts_conforming_input():
    agent = _compile_echo({"input": "json_object"})
    # Echo returns the input verbatim; no output constraint, so it passes.
    result = asyncio.run(agent.arun('{"query": "roses"}'))
    assert result.answer == '{"query": "roses"}'
    assert result.stopped_reason == "answer"


def test_input_json_array_shape_rejects_non_array():
    agent = _compile_echo({"input": "json_array"})
    with pytest.raises(AgentCoreError):
        asyncio.run(agent.arun('{"not": "an array"}'))  # valid JSON, wrong shape


# --------------------------------------------------------------------------- #
# Output schema enforcement (after guardrails)
# --------------------------------------------------------------------------- #
def test_output_schema_rejects_non_conforming_answer():
    # The model answers with plain prose; the manifest requires JSON output.
    agent = _compile_fixed("here is your answer", io_schema={"output": "json"})
    with pytest.raises(AgentCoreError) as exc:
        asyncio.run(agent.arun("give me json"))
    assert "output" in str(exc.value).lower()


def test_output_schema_accepts_conforming_answer():
    agent = _compile_fixed('{"ok": true}', io_schema={"output": "json_object"})
    result = asyncio.run(agent.arun("give me json"))
    assert result.answer == '{"ok": true}'
    assert result.stopped_reason == "answer"


# --------------------------------------------------------------------------- #
# Unknown shape keyword fails fast at compile time
# --------------------------------------------------------------------------- #
def test_unknown_io_shape_fails_at_compile():
    with pytest.raises(AgentCoreError) as exc:
        _compile_echo({"input": "CoderRequest"})  # not in the shape vocabulary
    assert "not recognized" in str(exc.value)


# --------------------------------------------------------------------------- #
# Opt-in: no io_schema (and plain-text sides) are completely unchanged
# --------------------------------------------------------------------------- #
def test_no_io_schema_is_unchanged():
    agent = _compile_echo(io_schema=None)
    result = asyncio.run(agent.arun("not json at all"))
    assert result.answer == "not json at all"
    assert result.stopped_reason == "answer"


def test_plain_text_shape_imposes_no_constraint():
    # A declared "text" side is satisfied by any string — no validation runs.
    agent = _compile_echo({"input": "text", "output": "text"})
    result = asyncio.run(agent.arun("arbitrary prose, definitely not json"))
    assert result.answer == "arbitrary prose, definitely not json"


# --------------------------------------------------------------------------- #
# Composition with guardrails: guardrails run first, then output is validated
# --------------------------------------------------------------------------- #
def test_output_schema_composes_with_guardrails():
    # A clean JSON answer that no_secret_exfil leaves untouched still validates.
    agent = _compile_fixed(
        '{"note": "nothing secret here"}',
        io_schema={"output": "json_object"},
        guardrails=["no_secret_exfil"],
    )
    result = asyncio.run(agent.arun("give me json"))
    assert result.answer == '{"note": "nothing secret here"}'
    assert [e for e in result.trace if e.type == "guardrail"] == []


# --------------------------------------------------------------------------- #
# Streaming (SSE) enforcement
# --------------------------------------------------------------------------- #
def test_astream_input_schema_rejects_malformed_input():
    agent = _compile_echo({"input": "json_object"})

    async def collect():
        return [ev async for ev in agent.astream("still not json")]

    with pytest.raises(AgentCoreError):
        asyncio.run(collect())


def test_astream_output_schema_suppresses_malformed_answer():
    # Malformed output must raise before any "answer" event is emitted, so the
    # client never receives the non-conforming text.
    agent = _compile_fixed("plain prose", io_schema={"output": "json"})

    events: list = []

    async def collect():
        async for ev in agent.astream("give me json"):
            events.append(ev)

    with pytest.raises(AgentCoreError):
        asyncio.run(collect())
    assert not any(e.type == "answer" for e in events)


def test_astream_output_schema_emits_conforming_answer():
    agent = _compile_fixed('{"ok": 1}', io_schema={"output": "json_object"})

    async def collect():
        return [ev async for ev in agent.astream("give me json")]

    events = asyncio.run(collect())
    answer_events = [e for e in events if e.type == "answer"]
    assert len(answer_events) == 1
    assert answer_events[0].detail == '{"ok": 1}'
