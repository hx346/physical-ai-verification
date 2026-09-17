"""V1.0 Track A' 校准编排：逐点聚合 / 网格展开 / 注册（纯函数，不进 gz/DB）。"""

from __future__ import annotations

import pytest

from roboverify_runtime.calibration.multi_param import fit_multi_param
from roboverify_runtime.worker.handlers.calibration import _aggregate_points
from roboverify_runtime.worker.registry import get_handler, registered_types


def run_rec(point: int, metrics: dict | None, **extra) -> dict:
    rec = {"i": point, "params": {"__pointIndex": point,
                                  "depth_noise_mm": 5.0, "friction_coeff": 0.5},
           "graspNoise": [0, 0, 0]}
    rec.update(extra)
    if metrics is not None:
        rec["metrics"] = metrics
    return rec


def test_aggregate_points_groups_and_keys():
    """同点 runs 聚成仿真聚合键族；P95 用 95 分位而非均值。"""
    runs = [
        run_rec(0, {"pick_success": 1.0, "position_error_mm": 10.0,
                    "perception_error_mm": 1.0}),
        run_rec(0, {"pick_success": 0.0, "position_error_mm": 100.0,
                    "perception_error_mm": 2.0}),
        run_rec(1, {"pick_success": 1.0, "position_error_mm": 12.0}),
        run_rec(1, None, error="sub-job FAILED"),  # 失败 run 计数不进聚合
    ]
    surface = _aggregate_points(runs, [{"depth_noise_mm": 5.0, "friction_coeff": 0.5},
                                       {"depth_noise_mm": 10.0, "friction_coeff": 0.3}])
    assert len(surface) == 2
    pt0 = surface[0]["metrics"]
    assert pt0["pick_success_rate"] == pytest.approx(0.5)
    assert pt0["perception_error_mm_mean"] == pytest.approx(1.5)
    # P95 在 [10,100] 两样本上 = 95.5（numpy 线性插值），非均值 55
    assert pt0["position_error_mm_P95"] == pytest.approx(95.5)
    assert surface[1]["runs"] == 1 and surface[1]["failedRuns"] == 1


def test_aggregate_points_all_failed_dropped_not_fabricated():
    """全失败点剔除（缺格交 fit 拒收）；无 __pointIndex 的孤儿 run 忽略。"""
    runs = [
        run_rec(0, {"pick_success": 1.0, "position_error_mm": 10.0}),
        run_rec(1, None, error="dead"),
        {"i": 99, "params": {}, "graspNoise": None},  # 孤儿
    ]
    surface = _aggregate_points(runs, [{"a": 1.0, "b": 0.1}, {"a": 2.0, "b": 0.2}])
    assert len(surface) == 1 and surface[0]["params"]["a"] == 1.0


def test_aggregate_then_fit_end_to_end_synthetic():
    """收割产物 → 聚合 → fit 全链（合成）：恢复已知参数（编排侧集成验证）。"""
    grid = {"depth_noise_mm": [0.0, 5.0, 10.0], "friction_coeff": [0.1, 0.5, 0.9]}
    points = [{"depth_noise_mm": a, "friction_coeff": b}
              for a in grid["depth_noise_mm"] for b in grid["friction_coeff"]]
    runs = []
    for idx, pt in enumerate(points):
        for _ in range(4):  # 每点 4 run，指标=前向真值+微小扰动
            m = {"pick_success": 0.95 - 0.005 * pt["depth_noise_mm"] - 0.5 * pt["friction_coeff"],
                 "position_error_mm": 10.0 + 12.0 * pt["depth_noise_mm"] + 15.0 * pt["friction_coeff"]}
            runs.append(run_rec(idx, {k: v + 0.01 * idx for k, v in m.items()}))
    surface = _aggregate_points(runs, points)
    assert len(surface) == 9
    real = {"pick_success_rate": {"mean": 0.69, "se": 0.03},
            "position_error_mm_P95": {"mean": 71.0, "se": 8.0}}
    r = fit_multi_param(grid, surface, real)
    assert r["identifiable"] is True
    assert r["params"]["depth_noise_mm"] == pytest.approx(5.0, abs=1.0)
    assert r["params"]["friction_coeff"] == pytest.approx(0.5, abs=0.08)


def test_handler_registered():
    """calibration handler 注册且类型可路由（runner 启动即 import）。"""
    import roboverify_runtime.worker.handlers  # noqa: F401
    assert "calibration" in registered_types()
    assert callable(get_handler("calibration"))
