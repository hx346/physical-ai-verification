"""不确定性引擎：RSS 解析合成 + Monte Carlo 分位数 + bootstrap 置信区间 + 贡献度分解。"""

from __future__ import annotations

import numpy as np

from . import models_v01 as M

# 折叠正态 |X|（X~N(0,σ)）的分位数 z：P(|X|≤zσ)=p → z=Φ⁻¹((1+p)/2)
PERCENTILE_Z = {"P50": 0.6745, "P90": 1.6449, "P95": 1.959963985, "P99": 2.5758, "mean": 0.798, "max": 3.0}


def rss(sigma_parts: dict[str, float]) -> tuple[float, dict[str, float]]:
    """各独立误差源 1σ 合成（RSS）；返回 (sigma_total, 各源贡献占比)。"""
    var = {k: s * s for k, s in sigma_parts.items() if s and s > 0}
    total_var = sum(var.values())
    sigma_total = float(np.sqrt(total_var)) if total_var > 0 else 0.0
    shares = {k: v / total_var for k, v in var.items()} if total_var > 0 else {}
    return sigma_total, shares


def monte_carlo_percentiles(
    sigma_parts: dict[str, float],
    n: int = M.MONTE_CARLO_N_DEFAULT,
    seed: int | None = None,
    bias: dict[str, float] | None = None,
) -> dict:
    """各源 ~ N(bias_i, sigma_i) 独立采样求和；输出分位数与 bootstrap CI（固定种子可复现）。"""
    rng = np.random.default_rng(seed)
    keys = [k for k in sigma_parts if sigma_parts.get(k, 0) or (bias or {}).get(k)]
    if not keys:
        return {"P50": 0.0, "P90": 0.0, "P95": 0.0, "samples": 0, "ci95": None}
    sigmas = np.array([sigma_parts.get(k, 0.0) for k in keys], dtype=float)
    biases = np.array([(bias or {}).get(k, 0.0) for k in keys], dtype=float)
    draws = rng.normal(biases, sigmas, size=(n, len(keys))).sum(axis=1)
    draws = np.abs(draws)

    p50, p90, p95 = (float(np.percentile(draws, q)) for q in (50, 90, 95))

    # bootstrap CI for P95
    boot = np.empty(M.BOOTSTRAP_N, dtype=float)
    boot_rng = np.random.default_rng(None if seed is None else seed + 1)
    for i in range(M.BOOTSTRAP_N):
        sample = boot_rng.choice(draws, size=n, replace=True)
        boot[i] = np.percentile(sample, 95)
    ci = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))

    return {"P50": p50, "P90": p90, "P95": p95, "samples": n, "ci95": ci, "mean": float(draws.mean())}


def analytic_percentile(sigma_total: float, percentile: str) -> float:
    """正态假设 |X| 的分位数近似（快速路径，与 MC 交叉校验用）。"""
    z = PERCENTILE_Z.get(percentile, 0.0)
    return abs(sigma_total * z) if percentile != "mean" else sigma_total
