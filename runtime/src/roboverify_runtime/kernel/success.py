"""抓取成功率概率模型（显式假设的 logistic 形式，供 verify 与实验引擎共用）。

success = sigmoid(A - B*occlusion - C * sigma_eff * OBJECT_SIZE_NORM / object_size_mm)

系数定义在 models_v01（SUCCESS_MODEL_VERSION），未校准（M4 Real2Sim 校准替换）。
"""

from __future__ import annotations

import math

from . import models_v01 as M


def effective_sigma_mm(depth_sigma_mm: float, occlusion: float) -> float:
    """有效定位误差：深度误差 + 遮挡引起的额外不确定（遮挡使匹配不稳定）。"""
    return depth_sigma_mm * (1.0 + 0.5 * occlusion)


def success_probability(
    sigma_eff_mm: float,
    occlusion: float,
    object_size_mm: float = M.OBJECT_SIZE_NORM_MM,
) -> float:
    x = (
        M.SUCCESS_A
        - M.SUCCESS_B * occlusion
        - M.SUCCESS_C * sigma_eff_mm * (M.OBJECT_SIZE_NORM_MM / max(object_size_mm, 1.0))
    )
    return 1.0 / (1.0 + math.exp(-x))
