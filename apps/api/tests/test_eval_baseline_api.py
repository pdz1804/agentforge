"""API tests for eval report persistence + stored-baseline regression (Gap G5).

Offline: uses the 'echo' model provider and the packaged echo_agent suite pair.
"""

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


def test_eval_persists_report_and_is_fetchable():
    resp = client.post(
        "/api/eval",
        json={"manifest": _echo_manifest(), "suite_id": "echo_agent", "measure_flake": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    report_id = body["report_id"]
    assert report_id

    fetched = client.get(f"/api/eval/{report_id}")
    assert fetched.status_code == 200
    stored = fetched.json()
    assert stored["id"] == report_id
    assert stored["manifest_id"] == "echo_agent"
    assert stored["report"]["held_out"]["pass_rate"] == 1.0


def test_fetch_missing_report_is_404():
    assert client.get("/api/eval/does_not_exist").status_code == 404


def test_regression_gate_against_stored_baseline():
    # 1) Run eval, capture the report id.
    run = client.post(
        "/api/eval",
        json={"manifest": _echo_manifest(), "suite_id": "echo_agent", "measure_flake": False},
    ).json()
    report_id = run["report_id"]

    # 2) Promote that report's held-out split to the manifest's baseline.
    promo = client.post(f"/api/eval/{report_id}/promote")
    assert promo.status_code == 200
    assert promo.json()["manifest_id"] == "echo_agent"

    # 3) A fresh eval gated against the STORED baseline (no inline baseline).
    gated = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "suite_id": "echo_agent",
            "measure_flake": False,
            "use_stored_baseline": True,
        },
    )
    assert gated.status_code == 200
    regression = gated.json()["regression"]
    assert regression["blocked"] is False  # echo passes 100% vs 100% baseline
    assert regression["delta"] == 0.0


def test_use_stored_baseline_without_one_is_404():
    # Use inline suites under a fresh manifest id that has no stored baseline.
    dev_suite = {
        "id": "nobaseline.dev", "manifest_id": "nobaseline_agent", "split": "dev",
        "tasks": [
            {"id": "d1", "input": "dev phrase", "scoring_mode": "programmatic",
             "match_type": "exact", "expected": "dev phrase"},
        ],
    }
    held_out_suite = {
        "id": "nobaseline.held_out", "manifest_id": "nobaseline_agent", "split": "held_out",
        "tasks": [
            {"id": "h1", "input": "held out phrase", "scoring_mode": "programmatic",
             "match_type": "exact", "expected": "held out phrase"},
        ],
    }
    manifest = {**_echo_manifest(), "id": "nobaseline_agent"}
    resp = client.post(
        "/api/eval",
        json={
            "manifest": manifest,
            "dev_suite": dev_suite,
            "held_out_suite": held_out_suite,
            "measure_flake": False,
            "use_stored_baseline": True,
        },
    )
    assert resp.status_code == 404
    assert "baseline" in resp.json()["detail"].lower()


def test_inline_baseline_still_takes_precedence():
    # Back-compat: inline baseline path unchanged and wins over stored.
    baseline_held_out = {
        "suite_id": "echo_agent.held_out", "manifest_id": "echo_agent", "split": "held_out",
        "task_scores": [{"task_id": "held-1", "score": 1.0, "passed": True}],
        "pass_rate": 1.0, "mean_score": 1.0, "flake_rate": 0.0,
    }
    resp = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "suite_id": "echo_agent",
            "measure_flake": False,
            "baseline_held_out": baseline_held_out,
            "use_stored_baseline": True,  # ignored because inline is supplied
        },
    )
    assert resp.status_code == 200
    assert resp.json()["regression"]["blocked"] is False
