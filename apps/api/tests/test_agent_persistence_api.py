"""API tests for manifest persistence + versioning + diff (Gap G4).

Offline: uses the 'echo' model provider (no API key). The store is a
process-local singleton on the app, so each test uses a distinct manifest id
to avoid version bleed between tests.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _manifest(manifest_id: str, temperature: float = 0.2, tools: list | None = None) -> dict:
    return {
        "id": manifest_id,
        "model": {"provider": "echo", "name": "test-model", "temperature": temperature},
        "prompt_ref": "prompts/echo_agent.md",
        "tools": tools or [],
    }


def test_crud_roundtrip_versioning_and_diff():
    mid = "persist_crud"

    # Create v1.
    resp = client.post("/api/agents", json={"manifest": _manifest(mid, 0.2)})
    assert resp.status_code == 200
    assert resp.json()["version"] == 1

    # Update -> v2 (change temperature + add a tool).
    resp = client.put(
        f"/api/agents/{mid}",
        json={"manifest": _manifest(mid, 0.7, tools=["echo"])},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    # GET latest is v2; GET ?version=1 is v1.
    latest = client.get(f"/api/agents/{mid}").json()
    assert latest["version"] == 2
    assert latest["manifest"]["model"]["temperature"] == 0.7
    v1 = client.get(f"/api/agents/{mid}", params={"version": 1}).json()
    assert v1["version"] == 1
    assert v1["manifest"]["model"]["temperature"] == 0.2

    # Version history lists both, oldest first.
    versions = client.get(f"/api/agents/{mid}/versions").json()
    assert [v["version"] for v in versions["versions"]] == [1, 2]

    # Diff v1 -> v2 shows the changed fields.
    diff = client.get(f"/api/agents/{mid}/diff", params={"from": 1, "to": 2}).json()
    assert diff["from_version"] == 1 and diff["to_version"] == 2
    changed = {c["field"] for c in diff["fields_changed"]}
    assert changed == {"model", "tools"}
    assert "echo" in diff["text_diff"]

    # The listing includes this id with its latest version.
    agents = client.get("/api/agents").json()["agents"]
    entry = next(a for a in agents if a["id"] == mid)
    assert entry["latest_version"] == 2


def test_create_rejects_invalid_manifest():
    resp = client.post("/api/agents", json={"manifest": {"id": "bad", "tools": ["ghost"]}})
    assert resp.status_code == 400


def test_update_rejects_id_mismatch():
    mid = "persist_mismatch"
    client.post("/api/agents", json={"manifest": _manifest(mid)})
    resp = client.put(f"/api/agents/{mid}", json={"manifest": _manifest("other_id")})
    assert resp.status_code == 400
    assert "does not match" in resp.json()["detail"]


def test_get_and_diff_missing_are_404():
    assert client.get("/api/agents/nope").status_code == 404
    assert client.get("/api/agents/nope/versions").status_code == 404
    assert client.get("/api/agents/nope/diff", params={"from": 1, "to": 2}).status_code == 404


def test_validate_endpoint_still_public_and_working():
    # The pre-existing stateless validate route is unchanged by G4.
    resp = client.post("/api/agents/validate", json={"manifest": _manifest("validate_check")})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "id": "validate_check", "error": None}
