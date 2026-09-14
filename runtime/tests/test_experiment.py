"""实验引擎测试：LHS 分层性 + Demo 语义（敏感性排名 + 相机位姿改进）。"""

from pathlib import Path

import numpy as np
import pytest

from roboverify_runtime.experiment.engine import run_experiment
from roboverify_runtime.experiment.sampling import lhs_uniform

_EX = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def _load(p: str):
    import yaml

    return yaml.safe_load((_EX / p).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def demo_ctx():
    return {
        "experiment": _load("experiment/bin-picking-1000.yaml"),
        "system": _load("system/bin-picking-rgbd.yaml"),
        "environment": _load("environment/bin-picking.yaml"),
        "assets": _load("asset/seed.yaml"),
    }


def test_lhs_stratification() -> None:
    rng = np.random.default_rng(1)
    u = lhs_uniform(1000, 4, rng)
    # 每维分 10 层，每层应约 100 个样本（容差 ±25%）
    for j in range(4):
        counts, _ = np.histogram(u[:, j], bins=10, range=(0, 1))
        assert counts.min() > 75 and counts.max() < 125


def test_experiment_runs_and_aggregates(demo_ctx) -> None:
    exp = dict(demo_ctx["experiment"])
    exp["sampling"] = {**exp["sampling"], "n": 200}  # 测试用小样本
    result = run_experiment(exp, demo_ctx["system"], demo_ctx["environment"], demo_ctx["assets"])
    agg = result["aggregates"]
    assert agg["samples"] == 200
    assert 0.0 <= agg["success_rate_mean"] <= 1.0
    assert agg["success_rate_P5"] <= agg["success_rate_P50"] <= agg["success_rate_P95"]
    assert agg["accuracy_p95_mean_mm"] > 0


def test_sensitivity_ranks_occlusion_or_depth_top(demo_ctx) -> None:
    exp = dict(demo_ctx["experiment"])
    exp["sampling"] = {**exp["sampling"], "n": 200}
    result = run_experiment(exp, demo_ctx["system"], demo_ctx["environment"], demo_ctx["assets"])
    top2 = {s["name"] for s in result["sensitivity"][:2]}
    assert top2 & {"occlusion_percent", "depth_noise_mm", "object_size_mm"}, (
        f"主导因子应在遮挡/深度噪声/零件尺寸中，实际 top2={top2}"
    )


def test_lower_camera_improves_success(demo_ctx) -> None:
    """相机更近（0.65m vs 0.95m）→ σ 更小 → 平均成功率更高（相机位姿研究的基础）。"""
    import copy

    exp = dict(demo_ctx["experiment"])
    exp["sampling"] = {**exp["sampling"], "n": 200}

    low = copy.deepcopy(demo_ctx["system"])
    high = copy.deepcopy(demo_ctx["system"])
    for c in high["components"]:
        if c["id"] == "cam-overhead-1":
            c["mountPose"]["z"] = 0.95

    r_low = run_experiment(exp, low, demo_ctx["environment"], demo_ctx["assets"])["aggregates"]
    r_high = run_experiment(exp, high, demo_ctx["environment"], demo_ctx["assets"])["aggregates"]
    assert r_low["success_rate_mean"] > r_high["success_rate_mean"]
    assert r_low["accuracy_p95_mean_mm"] < r_high["accuracy_p95_mean_mm"]
