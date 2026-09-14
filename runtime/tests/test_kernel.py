"""内核单元测试：闭式解交叉校验 + Demo 双配置语义（RGB FAIL / RGB-D PASS）。"""

from pathlib import Path

import pytest

from roboverify_runtime.kernel.registry import verify_requirements
from roboverify_runtime.kernel.uncertainty import monte_carlo_percentiles, rss

_EX = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def _load(p: str):
    import yaml

    return yaml.safe_load((_EX / p).read_text(encoding="utf-8"))


def _by_id(items: list[dict]) -> dict:
    return {i["requirementId"]: i for i in items}


@pytest.fixture(scope="module")
def demo_assets() -> list[dict]:
    return _load("asset/seed.yaml")


@pytest.fixture(scope="module")
def demo_env() -> dict:
    return _load("environment/bin-picking.yaml")


def test_rss_closed_form() -> None:
    sigma, shares = rss({"a": 3.0, "b": 4.0})
    assert sigma == pytest.approx(5.0)  # 3-4-5
    assert shares["a"] == pytest.approx(9 / 25)
    assert shares["b"] == pytest.approx(16 / 25)


def test_monte_carlo_matches_analytic_within_tolerance() -> None:
    parts = {"depth": 2.0, "hand_eye": 0.8, "robot": 0.5}
    sigma, _ = rss(parts)
    mc = monte_carlo_percentiles(parts, n=50_000, seed=7)
    # |X| 折叠正态的 P95 = 1.96σ，容差 3%
    assert mc["P95"] == pytest.approx(1.959963985 * sigma, rel=0.03)


def test_demo_rgb_config_fails_position_accuracy(demo_assets, demo_env) -> None:
    reqs = _load("requirement/bin-picking.yaml")
    out = verify_requirements(reqs, _load("system/bin-picking-rgb.yaml"), demo_env,
                              assets=demo_assets, options={"seed": 7})
    items = _by_id(out["items"])
    pos = items["R003"]
    assert pos["status"] == "FAIL"
    assert pos["unit"] == "mm"
    assert pos["ci95"] is not None or pos["samples"] > 0
    # 单目路径的主要贡献必须是深度不可观测/单目误差
    assert pos["contributors"][0]["name"] == "depth_error"


def test_demo_rgbd_config_passes_position_accuracy(demo_assets, demo_env) -> None:
    reqs = _load("requirement/bin-picking.yaml")
    out = verify_requirements(reqs, _load("system/bin-picking-rgbd.yaml"), demo_env,
                              assets=demo_assets, options={"seed": 7})
    items = _by_id(out["items"])
    assert items["R003"]["status"] == "PASS"
    assert items["R003"]["observed"] < 3.0  # mm
    assert items["R001"]["status"] == "PASS"  # 成功率（模型值，M3 实验覆盖）


def test_latency_budget_sums_stages(demo_assets, demo_env) -> None:
    reqs = _load("requirement/bin-picking.yaml")
    out = verify_requirements(reqs, _load("system/bin-picking-rgbd.yaml"), demo_env, assets=demo_assets)
    lat = _by_id(out["items"])["R004"]
    assert lat["method"] == "latency_budget"
    assert lat["observed"] > 0
    # 贡献度份额之和应接近 1（各段时延占比）
    assert sum(c["share"] for c in lat["contributors"]) == pytest.approx(1.0, abs=0.02)


def test_missing_assets_returns_unknown(demo_env) -> None:
    reqs = _load("requirement/bin-picking.yaml")
    out = verify_requirements(reqs, _load("system/bin-picking-rgbd.yaml"), demo_env, assets=[])
    unknown = [i for i in out["items"] if i["status"] == "UNKNOWN"]
    assert unknown, "无资产时应返回 UNKNOWN 而非编造"


def test_collision_free_is_unknown_pending_simulation(demo_assets, demo_env) -> None:
    reqs = [{"schemaVersion": "0.1.0", "id": "R099", "metric": "collision_free_rate",
             "operator": ">=", "value": 0.99}]
    out = verify_requirements(reqs, _load("system/bin-picking-rgbd.yaml"), demo_env, assets=demo_assets)
    item = out["items"][0]
    assert item["status"] == "UNKNOWN"
    assert "simulation" in item["missingInputs"]
