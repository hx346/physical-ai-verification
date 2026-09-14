"""内核端点测试：契约校验 + 真实判定语义。"""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from roboverify_runtime.main import app

client = TestClient(app)

_EXAMPLES = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def _load(path: str) -> dict:
    return yaml.safe_load((_EXAMPLES / path).read_text(encoding="utf-8"))


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "liveness_ok"


def test_verify_rgb_demo_fails_position() -> None:
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-1",
        "traceId": "trace-test-1",
        "requirements": _load("requirement/bin-picking.yaml"),
        "system": _load("system/bin-picking-rgb.yaml"),
        "environment": _load("environment/bin-picking.yaml"),
        "assets": _load("asset/seed.yaml"),
        "options": {"seed": 7},
    })
    assert resp.status_code == 200
    body = resp.json()
    items = {i["requirementId"]: i for i in body["items"]}
    assert items["R003"]["status"] == "FAIL"
    assert any("inputFingerprint" in w for w in body["warnings"])


def test_verify_without_assets_returns_unknown_with_warning() -> None:
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-2",
        "requirements": _load("requirement/bin-picking.yaml"),
        "system": _load("system/bin-picking-rgbd.yaml"),
    })
    assert resp.status_code == 200
    body = resp.json()
    assert any(i["status"] == "UNKNOWN" for i in body["items"])
    assert any("assets 未提供" in w for w in body["warnings"])


def test_verify_invalid_system_rejected_422() -> None:
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-3",
        "requirements": _load("requirement/bin-picking.yaml"),
        "system": {"id": "sys", "components": []},  # 缺 minItems 1，且缺 schemaVersion
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["ir"] == "system"


def test_verify_invalid_requirement_rejected_422() -> None:
    resp = client.post("/api/v1/verify", json={
        "requestId": "req-test-4",
        "requirements": [{"id": "R001", "metric": "not_a_metric", "operator": ">=", "value": 1}],
        "system": _load("system/bin-picking-rgbd.yaml"),
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["ir"] == "requirement"


def test_validate_endpoint() -> None:
    req0 = _load("requirement/bin-picking.yaml")[0]
    ok = client.post("/api/v1/validate", json={"ir": "requirement", "instance": req0})
    assert ok.status_code == 200 and ok.json()["valid"] is True

    bad = client.post("/api/v1/validate", json={"ir": "asset", "instance": {"id": "x"}})
    assert bad.status_code == 200 and bad.json()["valid"] is False
