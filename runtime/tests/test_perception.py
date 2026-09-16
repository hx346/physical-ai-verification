"""V0.5 W3 感知定位纯函数测试：反投影几何/质心定位/噪声语义/工作空间过滤。

合成深度图按顶视相机几何正向生成（已知真值），验证定位输出与假设语义——
不依赖 gz（端到端用容器实测，dev-plan DoD）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from roboverify_runtime.perception import (
    apply_depth_noise,
    default_workspace,
    intrinsics_from_fov,
    localize_from_depth,
)

W, H = 640, 480  # 生产 1280×720 的 1/2（几何不变）；40mm 件 ≥16×16px，stride2 后过 32 点阈值
HFOV = math.radians(87)
CAM = intrinsics_from_fov(W, H, HFOV)
CAM.update({"x": 0.5, "y": 0.0, "z": 0.85})
WS = default_workspace()


def render_topdown(part_xy=(0.55, -0.03), part_size_m=0.04, part_center_z=0.10,
                   floor_z=0.02) -> np.ndarray:
    """按顶视相机几何正向渲染深度图：零件顶面矩形 + 箱底平面（part_xy 为世界坐标）。

    零件像素按顶面平面投影判定（真实相机语义：顶面矩形在顶面深度平面成像）；
    相机系：X_w = cam_x - d(v-cv)/fy；Y_w = cam_y - d(u-cu)/fx；Z_w = cam_z - d。
    """
    sy = part_size_m * 0.6
    top_z = part_center_z + sy / 2
    vs, us = np.mgrid[0:H, 0:W]
    d_floor = CAM["z"] - floor_z
    d_top = np.float32(CAM["z"] - top_z)
    x_top = CAM["x"] - d_top * (vs - CAM["cv"]) / CAM["fy"]
    y_top = CAM["y"] - d_top * (us - CAM["cu"]) / CAM["fx"]
    depth = np.where((abs(x_top - part_xy[0]) <= part_size_m / 2)
                     & (abs(y_top - part_xy[1]) <= part_size_m / 2),
                     d_top, np.float32(d_floor)).astype(np.float32)
    return depth


def test_localize_recovers_part_center_and_top():
    depth = render_topdown()
    out = localize_from_depth(depth, CAM, WS)
    assert out is not None
    assert out["n_points"] > 64
    assert abs(out["x"] - 0.55) < 0.002
    assert abs(out["y"] - (-0.03)) < 0.002
    assert abs(out["z_top"] - 0.112) < 0.004  # 顶面 z（sy/2=0.012）


def test_localize_no_target_returns_none():
    # 空深度（全部无效）→ None，不编造
    depth = np.full((H, W), 0.0, dtype=np.float32)
    assert localize_from_depth(depth, CAM, WS) is None
    # 零件移出工作空间窗 → None
    depth = render_topdown(part_xy=(1.0, 0.0))  # 出窗
    assert localize_from_depth(depth, CAM, WS) is None


def test_workspace_filters_gripper_band():
    # 悬停夹爪（z≥0.40）在零件旁边：z 带 [0.03,0.25] 剔除其像素，定位不受污染。
    # （夹爪正对零件上方 = 物理遮挡，零件像素已丢失——那正是序列先 standby
    #   移开夹爪的原因，此处验证的是非遮挡共视时的过滤语义）
    depth = render_topdown()
    vs, us = np.mgrid[0:H, 0:W]
    d_grip = np.float32(CAM["z"] - 0.42)
    x_g = CAM["x"] - d_grip * (vs - CAM["cv"]) / CAM["fy"]
    y_g = CAM["y"] - d_grip * (us - CAM["cu"]) / CAM["fx"]
    depth = np.where((abs(x_g - 0.65) < 0.05) & (abs(y_g + 0.03) < 0.05),
                     d_grip, depth).astype(np.float32)
    out = localize_from_depth(depth, CAM, WS)
    assert out is not None and abs(out["x"] - 0.55) < 0.003


def test_frame_bias_moves_centroid_noise_averages_out():
    """噪声语义：帧偏置直接移动反投影点（1:1 传播）；逐像素 iid 被质心平均。"""
    depth = render_topdown()
    rng = np.random.default_rng(42)
    # 帧偏置 +10mm：零件像素深度 +0.01 → XY 中心偏移 ≈ 偏置 × (离轴像素距/焦距)
    biased = apply_depth_noise(depth, 0.0, 0.010, rng)
    out0 = localize_from_depth(depth, CAM, WS)
    out1 = localize_from_depth(biased, CAM, WS)
    assert out0 and out1
    dx = out1["x"] - out0["x"]
    lateral_factor = abs(0.55 - CAM["x"]) / (CAM["z"] - 0.112)  # 顶面离轴比
    assert 0.5 * lateral_factor * 0.010 < abs(dx) < 2.0 * lateral_factor * 0.010
    assert out1["z_top"] < out0["z_top"]  # 深度变大 → z 变小
    # 逐像素 iid（1.2mm = 管线上限：depth_noise 15mm 的 σ/10 次要项）：
    # 质心误差远小于 σ（√N 平均）。注：σ 再放大（如 8mm）会把箱底像素（z=0.02）
    # 3σ 尾部推进 z 窗 [0.03,0.25]——z_min 对箱底只有 10mm 保护，超出管线
    # 自身噪声机制的场景不属于本 v0 语义（见 depth_localize 防御注释）
    noisy = apply_depth_noise(depth, 0.0012, 0.0, rng)
    out2 = localize_from_depth(noisy, CAM, WS)
    assert abs(out2["x"] - out0["x"]) < 0.0005
    assert abs(out2["y"] - out0["y"]) < 0.0005


def test_apply_depth_noise_preserves_invalid_pixels():
    depth = render_topdown()
    depth[0, 0] = np.float32(np.nan)
    out = apply_depth_noise(depth, 0.005, 0.01, np.random.default_rng(1))
    assert np.isnan(out[0, 0])  # 无效像素不编造


@pytest.mark.parametrize("part_xy", [(0.5, 0.0), (0.68, 0.06), (0.32, -0.07)])
def test_localize_across_bin(part_xy):
    depth = render_topdown(part_xy=part_xy)
    out = localize_from_depth(depth, CAM, WS)
    assert out is not None
    assert abs(out["x"] - part_xy[0]) < 0.003
    assert abs(out["y"] - part_xy[1]) < 0.003
