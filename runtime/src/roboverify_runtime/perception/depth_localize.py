"""深度图定位 v0（V0.5 W3）：深度帧 → 目标位姿假设（点云反投影 + 工作空间窗聚类质心）。

模块独立（输入深度图+相机几何 → 输出位姿假设），抓取序列只消费接口——
感知链与序列解耦（dev-plan 风险缓解项）。

坐标约定（SDFormat 相机，顶视安装 rpy=(0, π/2, 0)，光轴 +X_cam → 世界 -Z）：
  X_w = cam_x - d·(v - cv)/fy
  Y_w = cam_y - d·(u - cu)/fx
  Z_w = cam_z - d
（中心像素 = 相机正下方；符号约定经 E2E 对真值校验。）
d 为沿光轴深度（gz depth camera 语义）；fx = (w/2)/tan(hfov/2)。

噪声模型（显式可审，两层——单帧定位误差的诚实分解）：
- frame_bias：帧级深度偏置（ToF/结构光实测特性：温漂/曝光相关，单帧估计不
  被平均）——主导项。实验参数 depth_noise_mm 映射于此。
- per_pixel：逐像素 iid 高斯——被质心 √N 平均，次要项（默认 σ/10）。
"""

from __future__ import annotations

import math

import numpy as np


def intrinsics_from_fov(width: int, height: int, hfov_rad: float) -> dict:
    """水平 FOV + 分辨率 → fx/fy/cu/cv（方像素假设，gz 相机无 K 发布，几何自洽）。"""
    fx = (width / 2.0) / math.tan(hfov_rad / 2.0)
    return {"fx": fx, "fy": fx, "cu": (width - 1) / 2.0, "cv": (height - 1) / 2.0,
            "width": width, "height": height}


def apply_depth_noise(depth_m: np.ndarray, per_pixel_sigma_m: float,
                      frame_bias_m: float, rng: np.random.Generator) -> np.ndarray:
    """传感器噪声注入：帧偏置（全体像素同偏移）+ 逐像素 iid 高斯。

    无效像素（非有限/≤0）保持原样（过滤在 localize 内做，不在此编造数据）。
    """
    out = depth_m.astype(np.float32).copy()
    valid = np.isfinite(out) & (out > 0)
    out[valid] += frame_bias_m
    if per_pixel_sigma_m > 0:
        out[valid] += rng.normal(0.0, per_pixel_sigma_m, int(valid.sum())).astype(np.float32)
    return out


def localize_from_depth(depth_m: np.ndarray, cam: dict, workspace: dict,
                        stride: int = 2) -> dict | None:
    """深度图 → 目标位姿假设：反投影 → 世界系工作空间窗过滤 → 质心。

    workspace = {x_min,x_max,y_min,y_max,z_min,z_max}（世界系；顶视安装下
    z 带过滤天然剔除悬停夹爪与箱底（见 default_workspace 注释）。
    stride 降采样（感知精度受质心平均保护，2×2 抽 1 足够）。
    返回 None = 窗内无点（感知失败如实上抛，不编造位姿）。

    防御边界：z_min=0.036 高于箱底板顶面（0.03）仅 6mm——逐像素噪声须显著
    小于该保护带（本管线 σ/10 ≤ 1.5mm），否则箱底像素 3σ 尾部会泄入 z 窗
    拉偏质心（单测实测：σ=8mm 时质心被拖 45mm——超出 v0 语义，如实标注）。
    """
    h, w = depth_m.shape
    vs, us = np.mgrid[0:h:stride, 0:w:stride]
    d = depth_m[0:h:stride, 0:w:stride]
    valid = np.isfinite(d) & (d > 0.05) & (d < 10.0)
    if not valid.any():
        return None
    d_v = d[valid]
    u_v = us[valid].astype(np.float64)
    v_v = vs[valid].astype(np.float64)

    x = cam["x"] - d_v * (v_v - cam["cv"]) / cam["fy"]
    y = cam["y"] - d_v * (u_v - cam["cu"]) / cam["fx"]
    z = cam["z"] - d_v

    in_win = ((x >= workspace["x_min"]) & (x <= workspace["x_max"])
              & (y >= workspace["y_min"]) & (y <= workspace["y_max"])
              & (z >= workspace["z_min"]) & (z <= workspace["z_max"]))
    n = int(in_win.sum())
    if n < 32:  # <32 点视同无目标（噪声散点/零件出窗）
        return None
    # 质心 z 用窗口内最高 25% 点的均值（顶面估计——抓取 z 从顶面起算；
    # 全体质心会被裙边/侧壁点拉低）
    z_in = z[in_win]
    z_top = float(np.mean(np.sort(z_in)[max(0, int(n * 0.75)):]))
    return {
        "x": round(float(np.mean(x[in_win])), 5),
        "y": round(float(np.mean(y[in_win])), 5),
        "z_top": round(z_top, 5),
        "n_points": n,
        "depth_mean_m": round(float(np.mean(d_v[in_win])), 4),
    }


def default_workspace(bin_center_x: float = 0.5, bin_w_m: float = 0.6,
                      bin_d_m: float = 0.3) -> dict:
    """默认工作空间窗：箱内 XY + 零件 z 带。

    XY 内缩 = 板厚 + 40mm（相对壁内立面）：顶视透视下箱壁内立面（z 全高）
    会投影进箱内 XY 区域——容器实测 32k 壁面点 vs 零件 ~300 点，质心被拉偏
    180mm。零件生成保证边缘离壁内立面 ≥75mm（clear-size/2 恒为 75mm），
    内缩 40mm 后零件完整保留、壁面全剔除。
    z 带 [0.036, 0.25]：箱底板顶面在 z=0.03（板中心 0.02 + 半厚 0.01——容器
    实测踩过：恰在 z_min=0.03 边界，6k 底面点泄入拉偏质心）；最小零件顶面
    0.03+0.6×0.02=0.042——z_min=0.036 留 6mm 保护带剔除底面保留小件。
    z_max 0.25 剔除夹爪（≥0.40）。
    """
    inset = 0.02 + 0.04  # 板厚 + 安全内缩
    return {
        "x_min": bin_center_x - bin_w_m / 2 + inset,
        "x_max": bin_center_x + bin_w_m / 2 - inset,
        "y_min": -bin_d_m / 2 + inset,
        "y_max": bin_d_m / 2 - inset,
        "z_min": 0.036,
        "z_max": 0.25,
    }
