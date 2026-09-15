"""sim_backend 测试（无 gz 依赖部分）：SRC 排名、Wilson CI、聚合结构、run 失败隔离。

仿真求值部分（N 次 headless gz）不进单测——W4 用容器实测验证（DoD ≥50 次）。
"""

from __future__ import annotations

import numpy as np

from roboverify_runtime.experiment.sim_backend import _aggregate, _src, _wilson


def test_src_ranks_dominant_factor_top():
    """合成数据：success = 1{noise > 阈值} 类 sigmoid 响应，depth_noise 应排第一。"""
    rng = np.random.default_rng(7)
    n = 400
    X = rng.random((n, 3))
    names = ["depth_noise_mm", "object_size_mm", "friction_coeff"]
    # 深度噪声主导：sigmoid 阈值响应；其余因子微弱
    z = 12.0 * (X[:, 0] - 0.5) + 0.3 * (X[:, 1] - 0.5) + rng.normal(0, 0.2, n)
    y = 1.0 / (1.0 + np.exp(-z))
    ranking, r2 = _src(X, names, y)
    assert ranking[0]["name"] == "depth_noise_mm"
    assert ranking[0]["share"] > 0.5
    assert r2 is not None and r2 > 0.5


def test_src_degenerate_response_is_honest():
    """响应无方差（全成功）→ 排名不可判如实标注，不编造。"""
    X = np.random.default_rng(3).random((50, 2))
    ranking, r2 = _src(X, ["a", "b"], np.ones(50))
    assert all(s["share"] == 0.0 for s in ranking)
    assert "不可判" in ranking[0]["note"]
    assert r2 is None


def test_wilson_interval_covers_point_estimate():
    lo, hi = _wilson(45, 50)
    assert lo <= 0.9 <= hi
    assert 0.7 < lo < 0.9 < hi < 1.0
    # 边界：全失败 / 全成功 / 零样本
    assert _wilson(0, 10)[1] < 0.35
    assert _wilson(10, 10)[0] > 0.65
    assert _wilson(0, 0) is None


def _fake_runs(success_by_noise: list[tuple[float, float]]) -> list[dict]:
    """(depth_noise_mm, pick_success) → run 记录（其余指标固定可聚）。"""
    return [{"i": i, "params": {"depth_noise_mm": d, "object_size_mm": 40.0,
                                "friction_coeff": 0.5,
                                "illumination_lux": 2400.0,
                                "occlusion_percent": 35.0,
                                "network_latency_ms": 20.0},
             "graspNoise": [0.0, 0.0, 0.0],
             "metrics": {"pick_success": s, "cycle_time_s": 30.0 + d,
                         "position_error_mm": 5.0 + 30.0 * d,
                         "collision_count": 100.0},
             "wall_s": 60.0}
            for i, (d, s) in enumerate(success_by_noise)]


def test_aggregate_structure_and_failed_isolation():
    runs = _fake_runs([(0.0, 1.0), (5.0, 1.0), (10.0, 0.0), (15.0, 0.0), (25.0, 0.0)])
    runs.append({"i": 5, "params": {}, "error": "gz server failed", "wall_s": 3.0})
    experiment = {"sampling": {"method": "lhs", "n": 6}, "id": "exp-test"}
    X = np.array([[r["params"].get("depth_noise_mm", 0.0),
                   r["params"].get("object_size_mm", 40.0),
                   r["params"].get("friction_coeff", 0.5)] for r in runs])
    out = _aggregate(experiment, runs, ["depth_noise_mm", "object_size_mm",
                                        "friction_coeff"], X, 400.0)
    agg = out["aggregates"]
    assert agg["samples"] == 6
    assert agg["completed"] == 5
    assert agg["failed"] == 1
    assert agg["pick_success_rate"] == 0.4
    assert agg["wall_total_s"] == 400.0
    assert agg["wall_per_run_s_mean"] == round(400.0 / 6, 1)
    lo, hi = agg["pick_success_rate_ci95_wilson"]
    assert lo <= 0.4 <= hi
    # 失败 run 已剔除：cycle_time 均值不含 wall-only 失败项
    assert agg["cycle_time_s_mean"] == 30.0 + (0 + 5 + 10 + 15 + 25) / 5
    # 敏感性：position_error 与 depth_noise 完全线性 → 该因子 share 最大
    assert out["sensitivityPositionError"][0]["name"] == "depth_noise_mm"
    assert out["sensitivity"][0]["name"] == "depth_noise_mm"
    assert out["backend"] == "simulator"
    assert out["rSquared"]["position_error_mm"] == 1.0
