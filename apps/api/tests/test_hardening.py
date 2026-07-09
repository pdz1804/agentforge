"""Hardening tests (PRD Phase 11): opt-in API-key auth, per-IP rate limiting,
and secret redaction. All auth/rate-limit tests restore the default (no env
set) state afterward, since the rest of the test suite depends on that
default-open behavior.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import rate_limit
from app.main import _error_event, app
from app.redaction import RedactingLogFilter, redact_secrets

client = TestClient(app)


def _echo_run_body(input_text: str = "hi") -> dict:
    return {
        "manifest": {
            "id": "hardening_runner",
            "model": {"provider": "echo", "name": "test-model"},
            "prompt_ref": "prompts/echo_agent.md",
            "tools": [],
        },
        "input": input_text,
    }


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # Every test in this file (and the wider suite, since buckets are
    # process-global) starts and ends with a clean slate.
    rate_limit.reset_rate_limits()
    yield
    rate_limit.reset_rate_limits()


# --------------------------------------------------------------------------- #
# Auth: default-open (no AGENTFORGE_API_KEY) behavior must be unchanged.
# --------------------------------------------------------------------------- #
def test_runs_open_by_default_without_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)
    resp = client.post("/api/runs", json=_echo_run_body())
    assert resp.status_code == 200
    assert client.get("/api/runs").status_code == 200


def test_memory_open_by_default_without_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)
    resp = client.get("/api/memory")
    assert resp.status_code == 200


def test_health_tools_validate_suites_never_require_a_key_even_when_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    # Read-only public endpoints stay open regardless of AGENTFORGE_API_KEY.
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        assert client.get("/health").status_code == 200
        assert client.get("/api/tools").status_code == 200
        assert client.get("/api/suites").status_code == 200
        assert (
            client.post(
                "/api/agents/validate",
                json={
                    "manifest": {
                        "id": "demo",
                        "model": {"provider": "echo", "name": "x"},
                        "prompt_ref": "prompts/echo_agent.md",
                        "tools": [],
                    }
                },
            ).status_code
            == 200
        )
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


# --------------------------------------------------------------------------- #
# Auth: when AGENTFORGE_API_KEY is set, protected endpoints require it.
# --------------------------------------------------------------------------- #
def test_runs_post_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        no_key = client.post("/api/runs", json=_echo_run_body())
        assert no_key.status_code == 401

        wrong_key = client.post(
            "/api/runs", json=_echo_run_body(), headers={"X-API-Key": "wrong"}
        )
        assert wrong_key.status_code == 401

        right_key = client.post(
            "/api/runs", json=_echo_run_body(), headers={"X-API-Key": "s3cret-key"}
        )
        assert right_key.status_code == 200

        bearer = client.post(
            "/api/runs",
            json=_echo_run_body(),
            headers={"Authorization": "Bearer s3cret-key"},
        )
        assert bearer.status_code == 200
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_runs_history_reads_require_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)
    run_id = json.loads(
        client.post("/api/runs", json=_echo_run_body()).text.splitlines()[0].removeprefix("data: ")
    )["run_id"]

    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        assert client.get("/api/runs").status_code == 401
        assert client.get("/api/runs", headers={"X-API-Key": "s3cret-key"}).status_code == 200

        assert client.get(f"/api/runs/{run_id}").status_code == 401
        assert (
            client.get(f"/api/runs/{run_id}", headers={"X-API-Key": "s3cret-key"}).status_code
            == 200
        )

        assert client.get(f"/api/runs/{run_id}/export").status_code == 401
        assert (
            client.get(
                f"/api/runs/{run_id}/export", headers={"X-API-Key": "s3cret-key"}
            ).status_code
            == 200
        )
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_memory_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        assert client.get("/api/memory").status_code == 401
        assert client.get("/api/memory", headers={"X-API-Key": "s3cret-key"}).status_code == 200
        assert client.post("/api/memory", json={"text": "x"}).status_code == 401
        assert (
            client.post(
                "/api/memory", json={"text": "x"}, headers={"X-API-Key": "s3cret-key"}
            ).status_code
            == 200
        )
        assert client.delete("/api/memory", params={"id": "nope"}).status_code == 401
        assert (
            client.delete(
                "/api/memory", params={"id": "nope"}, headers={"X-API-Key": "s3cret-key"}
            ).status_code
            == 200
        )
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_index_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        resp = client.post("/api/index", json={"doc_id": "d1", "text": "x"})
        assert resp.status_code == 401
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_sandbox_exec_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        resp = client.post("/api/sandbox/exec", json={"code": "print(1)"})
        assert resp.status_code == 401
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


def test_eval_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_API_KEY", "s3cret-key")
    try:
        resp = client.post(
            "/api/eval",
            json={
                "manifest": {
                    "id": "echo_agent",
                    "model": {"provider": "echo", "name": "test-model"},
                    "prompt_ref": "prompts/echo_agent.md",
                    "tools": [],
                },
                "suite_id": "echo_agent",
                "measure_flake": False,
            },
        )
        assert resp.status_code == 401
    finally:
        monkeypatch.delenv("AGENTFORGE_API_KEY", raising=False)


# --------------------------------------------------------------------------- #
# Rate limiting: generous default doesn't trip normal use; a tight override
# (via env) does trip and returns 429.
# --------------------------------------------------------------------------- #
def test_runs_rate_limit_returns_429_when_exceeded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_RATE_LIMIT_RUNS_PER_MIN", "2")
    try:
        first = client.post("/api/runs", json=_echo_run_body("a"))
        second = client.post("/api/runs", json=_echo_run_body("b"))
        third = client.post("/api/runs", json=_echo_run_body("c"))
        assert first.status_code != 429
        assert second.status_code != 429
        assert third.status_code == 429
    finally:
        monkeypatch.delenv("AGENTFORGE_RATE_LIMIT_RUNS_PER_MIN", raising=False)


def test_sandbox_rate_limit_returns_429_when_exceeded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTFORGE_RATE_LIMIT_SANDBOX_PER_MIN", "1")
    try:
        first = client.post("/api/sandbox/exec", json={"code": "print(1)"})
        second = client.post("/api/sandbox/exec", json={"code": "print(1)"})
        assert first.status_code != 429
        assert second.status_code == 429
    finally:
        monkeypatch.delenv("AGENTFORGE_RATE_LIMIT_SANDBOX_PER_MIN", raising=False)


def test_runs_default_rate_limit_does_not_trip_normal_use():
    # Default is generous (60/min) — a handful of quick calls must never 429.
    for i in range(5):
        resp = client.post("/api/runs", json=_echo_run_body(f"normal use {i}"))
        assert resp.status_code != 429


# --------------------------------------------------------------------------- #
# Secret redaction.
# --------------------------------------------------------------------------- #
def test_redact_secrets_scrubs_provider_keys():
    text = (
        "failed with ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwx "
        "and OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwx "
        "and TAVILY_API_KEY=tvly-1234567890abcdef"
    )
    redacted = redact_secrets(text)
    assert "sk-ant-abcdefghijklmnopqrstuvwx" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwx" not in redacted
    assert "tvly-1234567890abcdef" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_secrets_scrubs_bearer_token():
    text = "Authorization: Bearer sk-live-abcdefgh12345678"
    redacted = redact_secrets(text)
    assert "abcdefgh12345678" not in redacted


def test_redact_secrets_scrubs_generic_key_value_pairs():
    text = 'config: {"api_key": "abcd1234efgh5678"}'
    redacted = redact_secrets(text)
    assert "abcd1234efgh5678" not in redacted
    assert "api_key" in redacted  # key name preserved, only the value scrubbed


def test_redact_secrets_leaves_ordinary_text_untouched():
    text = "the run completed with 5 tool calls"
    assert redact_secrets(text) == text


def test_error_event_redacts_key_in_detail():
    # Proves a key present in an error's detail never survives into the SSE
    # payload sent to the client.
    event = _error_event("upstream failed, key=sk-abcdefghijklmnop was rejected")
    assert "sk-abcdefghijklmnop" not in event
    payload = json.loads(event.removeprefix("data: ").strip())
    assert payload["type"] == "error"
    assert "[REDACTED]" in payload["detail"]


def test_run_trace_stream_redacts_secret_in_tool_output(monkeypatch: pytest.MonkeyPatch):
    # A model provider whose "tool output" (echoed via the answer) contains a
    # leaked key must never reach the client verbatim in the SSE trace.
    from agent_core import ModelProvider

    from app.main import registries as app_registries

    class _LeakyProvider(ModelProvider):
        provider = "hardening_leaky"

        async def complete(self, messages, tools=None, **cfg):
            from agent_core import ModelResponse

            return ModelResponse(
                text="here is the key: sk-abcdefghijklmnopqrstuvwx",
                usage={"input_tokens": 1, "output_tokens": 1},
            )

    if "hardening_leaky" not in app_registries.models:
        app_registries.models.register("hardening_leaky", _LeakyProvider())

    resp = client.post(
        "/api/runs",
        json={
            "manifest": {
                "id": "leaky_runner",
                "model": {"provider": "hardening_leaky", "name": "x"},
                "prompt_ref": "prompts/echo_agent.md",
                "tools": [],
            },
            "input": "leak it",
        },
    )
    assert resp.status_code == 200
    assert "sk-abcdefghijklmnopqrstuvwx" not in resp.text
    assert "[REDACTED]" in resp.text


def test_redacting_log_filter_scrubs_log_record_message():
    import logging

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="auth failed with api_key=abcd1234secretvalue",
        args=(),
        exc_info=None,
    )
    RedactingLogFilter().filter(record)
    assert "abcd1234secretvalue" not in record.getMessage()
