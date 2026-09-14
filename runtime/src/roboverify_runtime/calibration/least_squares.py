"""Real2Sim 校准 v0（M4）：一维参数拟合（网格 + 线性插值，无需 scipy）。

拟合 sigma_scale：sim_success(sigma_base × scale) ≈ observed success_rate_mean。
产出的参数交由平台写入 model_version（DRAFT→TESTING→ACTIVE，版本切换即回滚）。
"""

from __future__ import annotations

import numpy as np

from ..kernel import models_v01 as M
from ..kernel.success import effective_sigma_mm, success_probability

SCALE_GRID = np.linspace(0.5, 3.0, 51)
DEFAULT_OCCLUSION = 0.35
DEFAULT_SIZE_MM = 50.0


def calibrate_sigma_scale(
    base_sigma_mm: float,
    observed_success_mean: float,
    occlusion: float = DEFAULT_OCCLUSION,
    object_size_mm: float = DEFAULT_SIZE_MM,
) -> dict:
    """网格扫 sigma_scale，插值命中实测成功率；返回拟合结果与残差。"""
    sigmas = base_sigma_mm * SCALE_GRID
    predicted = np.array([
        success_probability(effective_sigma_mm(s, occlusion), occlusion, object_size_mm)
        for s in sigmas
    ])

    target = float(np.clip(observed_success_mean, 0.0, 1.0))
    # predicted 随 scale 单调递减，反转后单调递增以配合 interp
    scale = float(np.interp(target, predicted[::-1], SCALE_GRID[::-1]))
    pred_at_scale = float(np.interp(scale, SCALE_GRID, predicted))
    return {
        "paramName": "depth_sigma_scale",
        "sigmaScale": round(scale, 4),
        "predictedSuccess": round(pred_at_scale, 4),
        "observedSuccess": round(target, 4),
        "residual": round(abs(pred_at_scale - target), 4),
        "gridSize": int(SCALE_GRID.size),
        "modelBasis": M.SUCCESS_MODEL_VERSION,
    }
