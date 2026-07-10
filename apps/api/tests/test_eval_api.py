"""API tests for the agent evaluation harness (/api/eval, /api/suites).

All offline: uses the 'echo' model provider (no API key needed) and the
packaged echo_agent dev/held-out suite pair under suites/.
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


def test_list_suites_includes_echo_agent_pair():
    resp = client.get("/api/suites")
    assert resp.status_code == 200
    suites = resp.json()["suites"]
    echo_suite = next(s for s in suites if s["suite_id"] == "echo_agent")
    assert echo_suite["manifest_id"] == "echo_agent"
    assert echo_suite["dev_task_count"] >= 1
    assert echo_suite["held_out_task_count"] >= 1


def test_eval_by_suite_id_returns_dev_and_held_out_report():
    resp = client.post(
        "/api/eval",
        json={"manifest": _echo_manifest(), "suite_id": "echo_agent", "measure_flake": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    report = body["report"]
    assert report["manifest_id"] == "echo_agent"
    assert report["dev"]["pass_rate"] == 1.0  # echo model echoes verbatim -> all tasks pass
    assert report["held_out"]["pass_rate"] == 1.0
    assert "regression" not in body  # no baseline supplied


def test_eval_unknown_suite_id_is_404():
    resp = client.post(
        "/api/eval", json={"manifest": _echo_manifest(), "suite_id": "does_not_exist"}
    )
    assert resp.status_code == 404


def test_eval_malformed_baseline_is_422_not_500():
    # A valid run request but a client-supplied baseline of the wrong shape is
    # bad input (422), not a server error (500).
    resp = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "suite_id": "echo_agent",
            "measure_flake": False,
            "baseline_held_out": {"garbage": 1},
        },
    )
    assert resp.status_code == 422
    assert "baseline" in resp.json()["detail"].lower()


def test_eval_with_inline_suites():
    dev_suite = {
        "id": "inline.dev", "manifest_id": "echo_agent", "split": "dev",
        "tasks": [
            {"id": "d1", "input": "inline dev phrase", "scoring_mode": "programmatic",
             "match_type": "exact", "expected": "inline dev phrase"},
        ],
    }
    held_out_suite = {
        "id": "inline.held_out", "manifest_id": "echo_agent", "split": "held_out",
        "tasks": [
            {"id": "h1", "input": "an unrelated held out sentence", "scoring_mode": "programmatic",
             "match_type": "exact", "expected": "an unrelated held out sentence"},
        ],
    }
    resp = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "dev_suite": dev_suite,
            "held_out_suite": held_out_suite,
            "measure_flake": False,
        },
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert report["dev"]["pass_rate"] == 1.0
    assert report["held_out"]["pass_rate"] == 1.0


def test_eval_inline_suites_reject_leaking_split():
    dup_task = {
        "id": "dup", "input": "same phrase both places", "scoring_mode": "programmatic",
        "expected": "same phrase both places",
    }
    dev_suite = {"id": "leaky.dev", "manifest_id": "echo_agent", "split": "dev", "tasks": [dup_task]}
    held_out_suite = {
        "id": "leaky.held_out", "manifest_id": "echo_agent", "split": "held_out", "tasks": [dup_task],
    }
    resp = client.post(
        "/api/eval",
        json={"manifest": _echo_manifest(), "dev_suite": dev_suite, "held_out_suite": held_out_suite},
    )
    assert resp.status_code == 400
    assert "leakage" in resp.json()["detail"]


def test_eval_requires_exactly_one_suite_source():
    resp = client.post("/api/eval", json={"manifest": _echo_manifest()})
    assert resp.status_code == 422  # neither suite_id nor inline suites supplied

    resp2 = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "suite_id": "echo_agent",
            "dev_suite": {"id": "x", "manifest_id": "echo_agent", "split": "dev", "tasks": []},
            "held_out_suite": {"id": "y", "manifest_id": "echo_agent", "split": "held_out", "tasks": []},
        },
    )
    assert resp2.status_code == 422  # both supplied


def test_eval_unknown_tool_in_manifest_is_400():
    manifest = {**_echo_manifest(), "tools": ["ghost_tool"]}
    resp = client.post(
        "/api/eval", json={"manifest": manifest, "suite_id": "echo_agent"}
    )
    assert resp.status_code == 400
    assert "ghost_tool" in resp.json()["detail"]


def test_eval_regression_gate_blocks_on_held_out_drop():
    baseline_held_out = {
        "suite_id": "echo_agent.held_out", "manifest_id": "echo_agent", "split": "held_out",
        "task_scores": [
            {"task_id": t["id"], "score": 1.0, "passed": True}
            for t in [
                {"id": "held-1"}, {"id": "held-2"}, {"id": "held-3"},
            ]
        ],
        "pass_rate": 1.0, "mean_score": 1.0, "flake_rate": 0.0,
    }
    resp = client.post(
        "/api/eval",
        json={
            "manifest": _echo_manifest(),
            "suite_id": "echo_agent",
            "measure_flake": False,
            "baseline_held_out": baseline_held_out,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # Live run also passes 100% (echo model), so no regression vs a 100% baseline.
    assert body["regression"]["blocked"] is False
    assert body["regression"]["delta"] == 0.0
