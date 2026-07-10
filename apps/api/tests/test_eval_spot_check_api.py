"""API tests for the llm_judge human spot-check hook (PRD 14.2, Gap G2).

Offline: the real judge (``eval_judge_fn``) is monkeypatched with an injected
fake ``JudgeFn`` so no model/API key is used, mirroring how the core tests
inject a fake judge.
"""

import app.main as main
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _echo_manifest() -> dict:
    return {
        "id": "echo_agent",
        "model": {"provider": "echo", "name": "test-model"},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": [],
    }


def _judge_dev_suite() -> dict:
    return {
        "id": "spot.dev",
        "manifest_id": "echo_agent",
        "split": "dev",
        "tasks": [
            {
                "id": "j1",
                "input": "describe an orchid in detail",
                "scoring_mode": "llm_judge",
                "rubric": ["mentions petals"],
                "pass_threshold": 0.6,
            }
        ],
    }


def _programmatic_held_out_suite() -> dict:
    return {
        "id": "spot.held_out",
        "manifest_id": "echo_agent",
        "split": "held_out",
        "tasks": [
            {
                "id": "h1",
                "input": "an unrelated held out sentence",
                "scoring_mode": "programmatic",
                "match_type": "exact",
                "expected": "an unrelated held out sentence",
            }
        ],
    }


def test_spot_check_endpoint_returns_judged_samples(monkeypatch):
    async def fake_judge(prompt: str) -> str:
        return "0.9"

    # Inject the fake judge so the llm_judge task scores offline.
    monkeypatch.setattr(main, "eval_judge_fn", fake_judge)

    resp = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "dev_suite": _judge_dev_suite(),
            "held_out_suite": _programmatic_held_out_suite(),
            "measure_flake": False,
        },
    )
    assert resp.status_code == 200
    report_id = resp.json()["report_id"]

    spot = client.get(f"/api/eval/{report_id}/spot-check")
    assert spot.status_code == 200
    body = spot.json()
    assert body["manifest_id"] == "echo_agent"
    # Only the llm_judge dev task is surfaced; the programmatic held-out task is not.
    assert [s["task_id"] for s in body["samples"]] == ["j1"]
    sample = body["samples"][0]
    assert sample["input"] == "describe an orchid in detail"
    assert sample["judge_score"] == 0.9
    assert sample["passed"] is True
    assert sample["review_status"] == "needs_review"


def test_spot_check_empty_for_non_judge_run():
    dev = {
        "id": "prog.dev",
        "manifest_id": "echo_agent",
        "split": "dev",
        "tasks": [
            {
                "id": "d1",
                "input": "inline dev phrase",
                "scoring_mode": "programmatic",
                "match_type": "exact",
                "expected": "inline dev phrase",
            }
        ],
    }
    resp = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "dev_suite": dev,
            "held_out_suite": _programmatic_held_out_suite(),
            "measure_flake": False,
        },
    )
    assert resp.status_code == 200
    report_id = resp.json()["report_id"]

    spot = client.get(f"/api/eval/{report_id}/spot-check")
    assert spot.status_code == 200
    assert spot.json()["samples"] == []


def test_spot_check_unknown_report_is_404():
    resp = client.get("/api/eval/does-not-exist/spot-check")
    assert resp.status_code == 404
