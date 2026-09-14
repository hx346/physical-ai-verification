"""采样策略：LHS / 蒙特卡洛 / 网格 / 随机（numpy，固定种子可复现）。"""

from __future__ import annotations

import numpy as np


def lhs_uniform(n: int, dim: int, rng: np.random.Generator) -> np.ndarray:
    """拉丁超立方：每维分层（permutation + jitter），返回 (n, dim) 的 [0,1) 样本。"""
    u = (np.tile(np.arange(n), (dim, 1)).T + rng.random((n, dim))) / n
    for j in range(dim):
        u[:, j] = u[rng.permutation(n), j]
    return u


def mc_uniform(n: int, dim: int, rng: np.random.Generator) -> np.ndarray:
    return rng.random((n, dim))


def grid_uniform(n: int, dim: int) -> np.ndarray:
    """每维 n^(1/dim) 等分网格（样本数取整到完全网格）。"""
    per = max(2, int(round(n ** (1.0 / dim))))
    axes = [np.linspace(0.0, 1.0, per) for _ in range(dim)]
    mesh = np.meshgrid(*axes)
    return np.stack([m.ravel() for m in mesh], axis=1)


def sample(parameters: list[dict], method: str, n: int, seed: int | None) -> tuple[np.ndarray, list[str]]:
    """Experiment IR parameters → 样本矩阵 (n, k) 与参数名列表。

    支持 uniform（range / loguniform）、normal（mean/sigma）、choice（values）。
    """
    rng = np.random.default_rng(seed)
    names = [p["name"] for p in parameters]
    dim = len(parameters)

    if method == "grid":
        u = grid_uniform(n, dim)
    elif method == "lhs":
        u = lhs_uniform(n, dim, rng)
    else:  # monte_carlo / random
        u = mc_uniform(n, dim, rng)

    out = np.empty_like(u)
    for j, p in enumerate(parameters):
        dist = p.get("distribution", "uniform")
        if dist in ("uniform", "loguniform") and "range" in p:
            lo, hi = float(p["range"][0]), float(p["range"][1])
            if dist == "loguniform":
                out[:, j] = np.exp(np.log(lo) + u[:, j] * (np.log(hi) - np.log(lo)))
            else:
                out[:, j] = lo + u[:, j] * (hi - lo)
        elif dist == "normal":
            mean = float(p.get("mean", 0.0))
            sigma = float(p.get("sigma", 1.0))
            out[:, j] = mean + sigma * np.array([_inv_normal(x) for x in u[:, j]])
        elif dist == "choice":
            values = p.get("values", [0, 1])
            out[:, j] = [values[min(int(x * len(values)), len(values) - 1)] for x in u[:, j]]
        else:
            raise ValueError(f"unsupported distribution: {dist} (param {p['name']})")
    return out, names


def _inv_normal(p: float) -> float:
    """Acklam 逆正态近似（免 scipy 依赖，精度 ~1e-9，足够采样用）。"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = np.sqrt(-2 * np.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = np.sqrt(-2 * np.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
          ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
