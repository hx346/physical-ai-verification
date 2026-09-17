"""V1.0 校准引擎 v1：多参数 MLE——参数恢复 / 不可辨识 / 诚实边界（纯函数）。"""

from __future__ import annotations

import pytest

from roboverify_runtime.calibration.multi_param import fit_multi_param

GRID = {"depth_noise_mm": [0.0, 2.0, 5.0, 8.0, 10.0],
        "friction_coeff": [0.1, 0.3, 0.5, 0.7, 0.9]}


def surface(a: float, b: float, b_dep: float = 1.0) -> dict:
    """合成前向：P95 主依赖 depth（定位误差）、pick 主依赖 friction（成功率）——
    两指标信息正交（梯度夹角大），可辨识性健康。b_dep=0 模拟 friction 平坦场景。"""
    return {
        "params": {"depth_noise_mm": a, "friction_coeff": b},
        "metrics": {
            "pick_success_rate": 0.95 - 0.005 * a - 0.5 * b_dep * b,
            "position_error_mm_P95": 10.0 + 12.0 * a + 15.0 * b_dep * b,
        },
    }


def make_surface(b_dep: float = 1.0) -> list:
    return [surface(a, b, b_dep) for a in GRID["depth_noise_mm"]
            for b in GRID["friction_coeff"]]


def obs_at(a: float, b: float, b_dep: float = 1.0,
           noise: dict | None = None) -> dict:
    m = surface(a, b, b_dep)["metrics"]
    out = {}
    for k, v in m.items():
        mean = v + (noise or {}).get(k, 0.0)
        # se 口径对齐真机样本量（n~20）：成功率 Wilson≈0.03、P95 由样本散布≈8mm
        out[k] = {"mean": mean, "se": 0.03 if k == "pick_success_rate" else 8.0}
    return out


def test_recover_known_params_within_10pct():
    """DoD：合成数据（已知参数+小噪声）拟合恢复参数 ≤10% 偏差（相对参数范围）。"""
    real = obs_at(5.0, 0.5, noise={"pick_success_rate": 0.005,
                                   "position_error_mm_P95": 5.0})
    r = fit_multi_param(GRID, make_surface(), real)
    assert r["identifiable"] is True
    assert r["params"]["depth_noise_mm"] == pytest.approx(5.0, abs=1.0)  # 范围 10 的 10%
    assert r["params"]["friction_coeff"] == pytest.approx(0.5, abs=0.08)  # 范围 0.8 的 10%
    assert r["metricsUsed"] == ["pick_success_rate", "position_error_mm_P95"]
    assert r["skippedMetrics"] == []
    assert r["modelBasis"] == "sim-response-surface-v1"
    # 预测残差应小（标准化残差 < 3）
    assert all(v < 3.0 for v in r["stdResiduals"].values())


def test_unidentifiable_flat_param_flagged():
    """响应面不随 friction 变化 → profile CI 覆盖全范围 → 不可辨识如实标记。"""
    real = obs_at(4.0, 0.55, b_dep=0.0)
    r = fit_multi_param(GRID, make_surface(b_dep=0.0), real)
    assert r["identifiable"] is False
    assert "friction_coeff" in r["unidentifiableParams"]
    ci = r["paramCis"]["friction_coeff"]
    assert (ci[1] - ci[0]) / 0.8 > 0.5  # CI 宽度超范围 50%
    ci_d = r["paramCis"]["depth_noise_mm"]
    assert (ci_d[1] - ci_d[0]) / 10.0 <= 0.5  # 可辨识参数 CI 合理收紧


def test_missing_se_metric_skipped_not_fabricated():
    """无 se 的指标跳过并记录，不编造观测不确定性。"""
    real = obs_at(5.0, 0.5)
    real["latency_ms"] = {"mean": 40.0}  # 缺 se
    r = fit_multi_param(GRID, make_surface(), real)
    assert r["skippedMetrics"] == ["latency_ms"]
    assert "latency_ms" not in r["metricsUsed"]


def test_incomplete_grid_rejected():
    """网格点缺失直接报错，不静默插补。"""
    pts = make_surface()[:-1]  # 挖掉一个格
    with pytest.raises(ValueError, match="网格点不完整"):
        fit_multi_param(GRID, pts, obs_at(5.0, 0.5))


def test_deterministic_same_input_same_output():
    real = obs_at(6.0, 0.35)
    a = fit_multi_param(GRID, make_surface(), real)
    b = fit_multi_param(GRID, make_surface(), real)
    assert a == b


def test_out_of_surface_marks_bounded():
    """真机观测超出响应面包络 → 最优触边界，如实标注 boundedParams。"""
    real = obs_at(0.0, 0.1)
    real["pick_success_rate"]["mean"] = 1.05  # 高于全网格任何点
    r = fit_multi_param(GRID, make_surface(), real)
    assert len(r["boundedParams"]) == 2  # 角点最优 = 两参数都触界
    assert r["params"]["depth_noise_mm"] == 0.0
    assert r["params"]["friction_coeff"] == 0.1
