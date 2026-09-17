"""Real2Sim 校准 v1：多参数 MLE 估计（网格响应面 + 高斯似然，无 scipy 依赖）。

与 v0（least_squares.py 一维 sigma_scale 网格插值）的区别：同时在多个仿真参数上
拟合"仿真分布 ≈ 真机分布"（方案 §21/§22）。v1 固定两参数起步（如 depth_noise_mm ×
friction_coeff——W3/W4 敏感性先验：friction 主导、depth_noise 真实链杠杆臂 5-13%）。

架构：**前向仿真与估计器解耦**——本模块输入=参数网格点的仿真聚合（由 experiment
引擎编排产生，LHS/DAG 基础设施复用），估计器在响应面上做 MLE。指标键与仿真聚合/
真机 summary 归一键一致（pick_success_rate / position_error_mm_P95 /
perception_error_mm_mean——三族键归一教训，V0.8 W2）。

诚实边界：
- 不可辨识（响应面对某参数平坦/耦合）是合法结论——输出 identifiable=false 与
  per-param profile 95% CI，禁止硬给点估计当唯一答案；
- 观测必须带标准误（se>0，来自 Wilson CI/样本数），无 se 的指标跳过并记录
  （skippedMetrics），不编造观测不确定性；
- 最优点落在网格边界 = 外推信号（boundedParams），如实标注。

产出交由平台写 model_version（DRAFT→TESTING→ACTIVE，版本切换即回滚）。
"""

from __future__ import annotations

import math

import numpy as np

MODEL_BASIS = "sim-response-surface-v1"
NPARAMS = 2  # v1 固定两参数（通用化留 v2，见 dev-plan §14）
FINE_PER_AXIS = 121  # 响应面细网格（插值廉价，密扫代替优化器）
PROFILE_CHI2_95 = 3.841  # chi2(1, 0.95)——单参数 profile 置信区间阈值
UNIDENTIFIABLE_WIDTH_FRAC = 0.5  # profile CI 宽度超过参数范围 50% 即判不可辨识
HESSIAN_STEP_FRAC = 0.01  # 数值 Hessian 步长（参数范围的 1%）
COND_NUMBER_LIMIT = 1e3  # Hessian 条件数超限也判不可辨识（耦合方向退化）
EDGE_FRAC = 0.01  # 最优点距网格边界 <1% 范围视为触界


def _grid_interp2(ax: np.ndarray, ay: np.ndarray, v: np.ndarray,
                  xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """规则网格双线性插值（向量化）。ax/ay 递增，v[i,j] 定义在 (ax[i], ay[j])；
    超范围 clamp 到边界值（boundedParams 由 fit 另行判定）。"""
    i = np.clip(np.searchsorted(ax, xs) - 1, 0, len(ax) - 2)
    j = np.clip(np.searchsorted(ay, ys) - 1, 0, len(ay) - 2)
    tx = np.clip((xs - ax[i]) / (ax[i + 1] - ax[i]), 0.0, 1.0)
    ty = np.clip((ys - ay[j]) / (ay[j + 1] - ay[j]), 0.0, 1.0)
    c00, c10 = v[np.ix_(i, j)], v[np.ix_(i + 1, j)]
    c01, c11 = v[np.ix_(i, j + 1)], v[np.ix_(i + 1, j + 1)]
    wx, wy = tx[:, None], ty[None, :]
    return c00 * (1 - wx) * (1 - wy) + c10 * wx * (1 - wy) \
        + c01 * (1 - wx) * wy + c11 * wx * wy


class _Surface:
    """参数网格 → 指标响应面。重建规则张量，缺网格点直接报错（不静默插补）。"""

    def __init__(self, param_grid: dict, sim_surface: list, metrics: list):
        self.names = list(param_grid)
        self.ax = [np.asarray(param_grid[n], dtype=float) for n in self.names]
        for n, a in zip(self.names, self.ax, strict=True):
            if len(a) < 2 or np.any(np.diff(a) <= 0):
                raise ValueError(f"param_grid.{n} 需 ≥2 个递增档位")
        self.metrics = list(metrics)
        shape = tuple(len(a) for a in self.ax)
        self.tensors = {m: np.full(shape, np.nan) for m in self.metrics}
        seen = np.zeros(shape, dtype=int)
        for point in sim_surface:
            p, mvals = point.get("params"), point.get("metrics")
            if p is None or mvals is None:
                raise ValueError("sim_surface 点缺 params/metrics")
            idx = []
            for n, a in zip(self.names, self.ax, strict=True):
                pos = np.where(np.isclose(a, float(p[n])))[0]
                if len(pos) != 1:
                    raise ValueError(f"参数 {n}={p[n]} 不在网格档位上")
                idx.append(int(pos[0]))
            for m in self.metrics:
                if m not in mvals:
                    raise ValueError(f"网格点 {p} 缺指标 {m}")
            seen[tuple(idx)] += 1
            for m in self.metrics:
                self.tensors[m][tuple(idx)] = float(mvals[m])
        if not np.all(seen == 1):
            raise ValueError(f"网格点不完整：{int((seen != 1).sum())} 个格缺值/重复")


def fit_multi_param(param_grid: dict, sim_surface: list, real_obs: dict,
                    weights: dict | None = None) -> dict:
    """两参数 MLE：网格响应面细扫 argmax + profile 95% CI + 不可辨识检测。

    real_obs: {metric: {"mean": μ, "se": σ}}，se>0 必填（无 se 的指标跳过记
    skippedMetrics——观测不确定性不可编造）。返回字段见模块 docstring。
    """
    if len(param_grid) != NPARAMS:
        raise ValueError(f"v1 固定 {NPARAMS} 参数，收到 {len(param_grid)}")

    skipped = sorted(m for m, o in real_obs.items()
                     if not (isinstance(o, dict) and o.get("se", 0) > 0))
    surface_metrics = {k for p in sim_surface for k in p.get("metrics", {})}
    metrics = [m for m, o in real_obs.items()
               if m not in skipped and m in surface_metrics
               and isinstance(o, dict) and o.get("se", 0) > 0]
    if not metrics:
        raise ValueError("无共同可拟合指标（全部缺响应面或缺 se）")

    # 权重不归一化：高斯似然中 se 已表达指标精度，权重仅作相对降权——
    # 归一化会等比放大全部 se（信息量被稀释），曾致 CI 假性放宽 1.4 倍
    mweights = {m: float((weights or {}).get(m, 1.0)) for m in metrics}

    surf = _Surface(param_grid, sim_surface, metrics)
    xs = [np.linspace(a[0], a[-1], FINE_PER_AXIS) for a in surf.ax]
    fine = {m: _grid_interp2(surf.ax[0], surf.ax[1], surf.tensors[m],
                             xs[0], xs[1]) for m in metrics}

    ll = np.zeros(fine[metrics[0]].shape)
    for m in metrics:
        z = (fine[m] - real_obs[m]["mean"]) / real_obs[m]["se"]
        ll -= 0.5 * mweights[m] * z * z
    bi, bj = np.unravel_index(np.argmax(ll), ll.shape)
    best = {surf.names[0]: float(xs[0][bi]), surf.names[1]: float(xs[1][bj])}
    ll_max = float(ll[bi, bj])

    n0, n1 = surf.names

    def ll_at(v0: float, v1: float) -> float:
        total = 0.0
        for m in metrics:
            pred = _grid_interp2(surf.ax[0], surf.ax[1], surf.tensors[m],
                                 np.array([v0]), np.array([v1]))[0, 0]
            z = (pred - real_obs[m]["mean"]) / real_obs[m]["se"]
            total -= 0.5 * mweights[m] * z * z
        return total

    # profile 95% CI：固定另一参数于最优，单参数扫描 logLik 下降 ≤3.841 的区间
    cis, unident, bounded = {}, [], []
    for name, k, other in ((n0, 0, best[n1]), (n1, 1, best[n0])):
        scan = xs[k]
        prof = np.array([ll_at(v, other) if k == 0 else ll_at(other, v)
                         for v in scan])
        # profile 判据：-2ΔlnL ≤ chi2(1,0.95)=3.841 → ΔlnL ≤ 1.92
        inside = np.where(prof >= ll_max - PROFILE_CHI2_95 / 2.0)[0]
        if len(inside) == 0:  # 窄峰：仅峰值点自身达标
            cis[name] = [best[name], best[name]]
        else:
            cis[name] = [float(scan[inside[0]]), float(scan[inside[-1]])]
        span = scan[-1] - scan[0]
        if (cis[name][1] - cis[name][0]) / span > UNIDENTIFIABLE_WIDTH_FRAC:
            unident.append(name)
        if abs(best[name] - scan[0]) <= span * EDGE_FRAC \
                or abs(scan[-1] - best[name]) <= span * EDGE_FRAC:
            bounded.append(name)

    # 数值 Hessian 条件数（平坦/耦合的第二个信号）
    h = [(a[-1] - a[0]) * HESSIAN_STEP_FRAC for a in surf.ax]
    b0, b1 = best[n0], best[n1]
    h00 = (ll_at(b0 + h[0], b1) + ll_at(b0 - h[0], b1) - 2 * ll_max) / (h[0] * h[0])
    h11 = (ll_at(b0, b1 + h[1]) + ll_at(b0, b1 - h[1]) - 2 * ll_max) / (h[1] * h[1])
    h01 = (ll_at(b0 + h[0], b1 + h[1]) - ll_at(b0 + h[0], b1 - h[1])
           - ll_at(b0 - h[0], b1 + h[1]) + ll_at(b0 - h[0], b1 - h[1])) \
        / (4 * h[0] * h[1])
    # logLik 的 Hessian 负定——条件数用绝对值（最小|λ|→0 表示平坦/耦合方向）
    ev = np.abs(np.linalg.eigvalsh(np.array([[h00, h01], [h01, h11]])))
    cond = float(ev[-1] / ev[0]) if ev[0] > 0 else math.inf
    if cond > COND_NUMBER_LIMIT and not unident:
        # 条件数只补标（profile 已按参数判过；两参数全耦合时补首个）
        unident.append(n0)

    preds, residuals = {}, {}
    for m in metrics:
        pred = _grid_interp2(surf.ax[0], surf.ax[1], surf.tensors[m],
                             np.array([b0]), np.array([b1]))[0, 0]
        preds[m] = round(float(pred), 4)
        residuals[m] = round(abs(pred - real_obs[m]["mean"]) / real_obs[m]["se"], 4)

    return {
        "params": {k: round(v, 4) for k, v in best.items()},
        "predictions": preds,
        "stdResiduals": residuals,
        "logLik": round(ll_max, 4),
        "identifiable": not unident,
        "unidentifiableParams": unident,
        "paramCis": {k: [round(x, 4) for x in v] for k, v in cis.items()},
        "boundedParams": bounded,
        "hessianCond": cond if math.isfinite(cond) else None,
        "surfacePoints": int(np.prod([len(a) for a in surf.ax])),
        "metricsUsed": metrics,
        "skippedMetrics": skipped,
        "weights": {m: round(v, 4) for m, v in mweights.items()},
        "modelBasis": MODEL_BASIS,
    }
