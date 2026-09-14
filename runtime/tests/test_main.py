"""内核端点测试：契约校验 + UNKNOWN 语义（M0 内核未实现时的唯一合法判定）。"""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from roboverify_runtime.main import app

client = TestClient(app)


def _load(path: str) -> dict:
    base = Path(__file__).resolve().parents[2] / "schemas" / "examples"
    return yaml.safe_load((base / path).read_text(encoding="utf-8"))


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "liveness_ok"


def test_verify_valid_demo_payload_returns_unknown() -> None:
    requirements = _load("requirement/bin-picking.yaml")
    system = _load("system/bin-picking-rgbd.yaml")
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-1",
        "traceId": "trace-test-1",
        "requirements": requirements,
        "system": system,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["requestId"] == "req-test-1"
    assert len(body["items"]) == len(requirements)
    assert all(item["status"] == "UNKNOWN" for item in body["items"])
    assert all(item["missingInputs"] == ["kernel"] for item in body["items"])
    assert any("inputFingerprint" in w for w in body["warnings"])


def test_verify_invalid_system_rejected_422() -> None:
    requirements = _load("requirement/bin-picking.yaml")
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-2",
        "requirements": requirements,
        "system": {"id": "sys", "components": []},  # 缺 minItems 1，且缺 schemaVersion
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["ir"] == "system"


def test_verify_invalid_requirement_rejected_422() -> None:
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-3",
        "requirements": [{"id": "R001", "metric": "not_a_metric", "operator": ">=", "value": 1}],
        "system": _load("system/bin-picking-rgbd.yaml"),
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["ir"] == "requirement"
