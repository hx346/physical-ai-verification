"""实验引擎：参数空间采样 → 逐样本解析求值 → 聚合 + 一阶 Sobol 敏感性。

证据语义（原则二）：所有数值来自显式模型计算；模型假设在 assumptions 中声明。
"""

from __future__ import annotations

import numpy as np

from ..kernel import models_v01 as M
from ..kernel.snapshot import build_snapshot
from .sampling import sample

# Sobol 敏感性分析的基础样本量（Saltelli 展开后约 N×(2k+2) 次求值）
SENSITIVITY_BASE_N = 256


def _camera_sigma(system: dict, assets: list[dict]) -> tuple[float, float] | None:
    """返回 (相机高度 m, 基准深度 σ mm)；无有效相机 → None。"""
    snap = build_snapshot(system, assets)
    cams = [c for c in snap.cameras if c.pose]
    if not cams:
        return None
    cam = cams[0]
    z = float(cam.pose.get("z", 1.0))
    if not cam.depth_available or not cam.depth_sigma_mm:
        return z, M.MONOCULAR_DEPTH_SIGMA_RATIO * z * 1000.0
    d_ref_mm = cam.depth_ref_distance_mm or 700.0
    return z, float(cam.depth_sigma_mm) * (z * 1000.0 / d_ref_mm)


def _param_names(X: np.ndarray, names: list[str]) -> dict[str, np.ndarray]:
    return {name: X[:, j] for j, name in enumerate(names)}


def evaluate_success(
    X: np.ndarray,
    names: list[str],
    base_sigma_mm: float,
    base_z_m: float,
    object_size_base_mm: float,
) -> np.ndarray:
    """逐样本成功率（向量化 logistic 模型）。"""
    cols = _param_names(X, names)

    occlusion = np.clip(cols.get("occlusion_percent", np.full(X.shape[0], 35.0)) / 100.0, 0.0, 1.0)
    extra_noise = cols.get("depth_noise_mm", np.zeros(X.shape[0]))
    illum = cols.get("illumination_lux", np.zeros(X.shape[0]))
    # 强光反射假设：深度噪声随照度线性增加，最大 +2mm（假设，见 assumptions）
    illum_noise = 2.0 * np.clip(illum / 50000.0, 0.0, 1.0)
    size = cols.get("object_size_mm", np.full(X.shape[0], object_size_base_mm))
    friction = cols.get("friction_coeff", np.full(X.shape[0], 0.5))

    sigma_depth = base_sigma_mm + extra_noise + illum_noise
    sigma_eff = sigma_depth * (1.0 + 0.5 * occlusion)
    # 摩擦系数影响抓取裕度（假设：低摩擦线性惩罚，最大 -2.5）
    a_eff = M.SUCCESS_A - 2.5 * np.clip(1.0 - friction, 0.0, 1.0)

    size_factor = M.OBJECT_SIZE_NORM_MM / np.maximum(size, 1.0)
    x = a_eff - M.SUCCESS_B * occlusion - M.SUCCESS_C * sigma_eff * size_factor
    return 1.0 / (1.0 + np.exp(-x))


def evaluate_accuracy_p95(X: np.ndarray, names: list[str], sigma_parts_base: dict[str, float]) -> np.ndarray:
    """逐样本位置精度 P95（折叠正态 1.96σ）。"""
    cols = _param_names(X, names)
    extra = cols.get("depth_noise_mm", np.zeros(X.shape[0]))
    illum = cols.get("illumination_lux", np.zeros(X.shape[0]))
    illum_noise = 2.0 * np.clip(illum / 50000.0, 0.0, 1.0)

    sigma2 = 0.0
    for name, s in sigma_parts_base.items():
        base = s
        if name == "depth_error":
            base = np.sqrt(s * s) + extra + illum_noise
        sigma2 = sigma2 + base * base
    return 1.959963985 * np.sqrt(sigma2)


def run_experiment(
    experiment: dict,
    system: dict,
    environment: dict | None,
    assets: list[dict],
) -> dict:
    """完整实验：采样 → 求值 → 聚合 → 敏感性。返回可直接入 evidence 的结果结构。"""
    params = experiment["parameters"]
    sampling = experiment["sampling"]
    n = int(sampling["n"])
    seed = sampling.get("seed", 20260914)

    setup = _camera_sigma(system, assets)
    if setup is None:
        raise ValueError("system 无有效相机（mountPose/资产缺失），无法实验")
    base_z, base_sigma = setup

    env = environment or {}
    sizes = [p.get("size_mm") for p in (env.get("parts") or []) if p.get("size_mm")]
    size_base = ((sizes[0]["min"] + sizes[0]["max"]) / 2.0) if sizes else M.OBJECT_SIZE_NORM_MM

    X, names = sample(params, sampling.get("method", "lhs"), n, seed)
    success = evaluate_success(X, names, base_sigma, base_z, size_base)

    # 精度基线：与 kernel/registry 相同的误差源定义（单一来源是 snapshot + 本函数共享的 parts 结构）
    from ..kernel.snapshot import build_snapshot
    snap = build_snapshot(system, assets)
    parts = {"depth_error": base_sigma}
    if snap.hand_eye_translation_mm:
        parts["hand_eye_residual"] = float(snap.hand_eye_translation_mm)
    rep = snap.robot_param("repeatability_mm")
    if rep and rep.value:
        parts["robot_repeatability"] = float(rep.value)
    absacc = snap.robot_param("absolute_accuracy_mm")
    if absacc and absacc.value:
        parts["robot_absolute_accuracy"] = float(absacc.value)

    accuracy_p95 = evaluate_accuracy_p95(X, names, parts)

    aggregates = {
        "samples": int(n),
        "method": sampling.get("method", "lhs"),
        "success_rate_mean": float(success.mean()),
        "success_rate_P5": float(np.percentile(success, 5)),
        "success_rate_P50": float(np.percentile(success, 50)),
        "success_rate_P95": float(np.percentile(success, 95)),
        "accuracy_p95_mean_mm": float(accuracy_p95.mean()),
        "accuracy_p95_P95_mm": float(np.percentile(accuracy_p95, 95)),
        "pass_fraction_success_ge_098": float((success >= 0.98).mean()),
    }

    sensitivity = _sensitivity(params, names, base_sigma, base_z, size_base)

    return {
        "experimentId": experiment.get("id", ""),
        "aggregates": aggregates,
        "sensitivity": sensitivity,
        "assumptions": [
            {"name": "success_model", "provenance": "literature",
             "note": f"logistic {M.SUCCESS_MODEL_VERSION} 未校准"},
            {"name": "illumination_noise", "provenance": "literature",
             "note": "照度 0~50000lux 线性增加深度噪声至多 +2mm（假设）"},
            {"name": "friction_margin", "provenance": "literature",
             "note": "摩擦系数低于 1 时线性惩罚抓取裕度至多 -2.5（假设）"},
        ],
        "baseSigmaMm": round(base_sigma, 4),
        "cameraHeightM": base_z,
    }


def _sensitivity(params: list[dict], names: list[str], base_sigma: float,
                 base_z: float, size_base: float) -> list[dict]:
    """一阶 Sobol（Saltelli 采样 + 方差分解，SALib）。"""
    try:
        from SALib.analyze import sobol
        from SALib.sample import sobol as sobol_sample
    except ImportError:
        return [{"name": "<salib-unavailable>", "share": 0.0, "note": "SALib 未安装，敏感性不可用"}]

    problem = {
        "num_vars": len(params),
        "names": names,
        "bounds": [_bounds(p) for p in params],
    }
    Xs = sobol_sample.sample(problem, SENSITIVITY_BASE_N, seed=20260914)
    Ys = evaluate_success(np.asarray(Xs), names, base_sigma, base_z, size_base)
    Si = sobol.analyze(problem, Ys, print_to_console=False)
    ranking = sorted(
        ({"name": name, "share": 0.0 if np.isnan(s) else max(float(s), 0.0)}
         for name, s in zip(names, Si["S1"], strict=True)),
        key=lambda d: -d["share"],
    )
    return ranking


def _bounds(p: dict) -> list[float]:
    if "range" in p:
        return [float(p["range"][0]), float(p["range"][1])]
    if p.get("distribution") == "normal":
        mean = float(p.get("mean", 0.0))
        sigma = float(p.get("sigma", 1.0))
        return [mean - 3 * sigma, mean + 3 * sigma]
    values = p.get("values", [0, 1])
    return [float(min(values)), float(max(values))]
