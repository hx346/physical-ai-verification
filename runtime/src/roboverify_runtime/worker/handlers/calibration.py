"""calibration 任务处理器（V1.0 Track A'）：真机观测 + 参数网格 → 多参数 MLE。

编排复用 experiment DAG 模式（V0.5 W1）：网格点 × repeats 展开 simulation 子 job
（幂等键 {parent}:pt{p}:run{r}，requires=gz，多 sim-worker 并行）→ 轮询收割 →
逐点聚合（每点=固定参数组合的仿真分布，聚合键族与 experiment 聚合一致）→
fit_multi_param（进程内调用——前向仿真与估计器解耦，V1.0 §14 Track A）。

与 experiment 的区别：参数不做 LHS 采样（网格笛卡尔积固定值，每点多 run 出分布）；
聚合按点分组而非全批；结果不产生 evidence（平台摄取写 model_version DRAFT）。

诚实边界：
- 某网格点 run 全失败 → 该点从响应面剔除；缺格超限 fit_multi_param 拒收
  （网格点不完整 ValueError → job FAILED），不静默插补；
- real_obs 由平台侧从 telemetry 聚合并附 se（成功率正态 se / P95 正态近似，
  计算与假设标注在 CalibrationController），fit 侧再校验 se>0。
"""

from __future__ import annotations

import itertools
import time

import numpy as np
import psycopg

from ...calibration.multi_param import fit_multi_param
from ...config import settings
from ...experiment.sim_backend import build_run_sim_ir
from ...logging_setup import get_logger
from ..queue import enqueue_job, fetch_jobs
from ..registry import handle
from .experiment import (
    SUB_JOB_PRIORITY,
    TERMINAL_STATUSES,
    _batch_deadline_s,
    _harvest_runs,
    _progress_reporter,
)

log = get_logger("worker.handler.calibration")

# 单 run 指标 → 点聚合键（仿真聚合键族；fit 的指标键与真机 summary 归一键一致）
_POINT_METRICS = {"pick_success": "pick_success_rate",
                  "position_error_mm": "position_error_mm_P95",
                  "perception_error_mm": "perception_error_mm_mean"}
DEFAULT_RUNS_PER_POINT = 6  # 与 W4 n=6 探针基线同口径


def _aggregate_points(runs: list[dict], grid_points: list[dict]) -> list[dict]:
    """收割 runs（_harvest_runs 产物）→ 每网格点聚合 {params, metrics, runs, failedRuns}。

    纯函数可单测。某点 run 全失败 → 剔除该点（缺失格交由 fit 拒收，不编造聚合）。
    """
    by_point: dict[int, list[dict]] = {}
    for rec in runs:
        idx = (rec.get("params") or {}).get("__pointIndex")
        if idx is None:
            continue
        by_point.setdefault(int(idx), []).append(rec)

    surface = []
    for idx, pt in enumerate(grid_points):
        recs = by_point.get(idx, [])
        with_metrics = [r["metrics"] for r in recs if r.get("metrics")]
        if not with_metrics:
            log.warning("calibration grid point all-failed", point=idx, params=pt)
            continue
        metrics = {}
        for src, dst in _POINT_METRICS.items():
            vals = [float(m[src]) for m in with_metrics if m.get(src) is not None]
            if not vals:  # 该指标全缺（如无感知链模板）→ 不出该键，fit 联立时自然跳过
                continue
            arr = np.asarray(vals)
            metrics[dst] = round(float(arr.mean() if not dst.endswith("P95")
                                       else np.percentile(arr, 95)), 6)
        surface.append({"params": dict(pt), "metrics": metrics,
                        "runs": len(with_metrics), "failedRuns": len(recs) - len(with_metrics)})
    return surface


@handle("calibration")
def run(job) -> dict:
    payload = job.payload
    experiment = payload["experiment"]
    template = experiment.get("simulation") or {}
    if not template:
        raise ValueError("calibration 任务缺少 simulation 模板")
    param_grid: dict = payload["paramGrid"]
    repeats = int(payload.get("runsPerPoint", DEFAULT_RUNS_PER_POINT))
    seed = int(experiment.get("sampling", {}).get("seed", 20260914))
    real_obs = payload["realObs"]

    names = list(param_grid)
    grid_points = [dict(zip(names, pt, strict=True))
                   for pt in itertools.product(*(param_grid[n] for n in names))]
    total = len(grid_points) * repeats
    log.info("calibration batch start", job_key=job.job_key,
             points=len(grid_points), repeats=repeats, total=total)

    # 展开：每点 repeats 个子 job（参数=网格固定值；噪声实例 per-run 派生自全局 i，
    # 同点不同 run 噪声独立——分布语义正确）
    sub_keys = [f"{job.job_key}:pt{p}:run{r}"
                for p in range(len(grid_points)) for r in range(repeats)]
    with psycopg.connect(settings.database_url) as conn:
        with conn.transaction():
            i = 0
            for p, pt in enumerate(grid_points):
                for _ in range(repeats):
                    row = {**{k: float(v) for k, v in pt.items()},
                           "__pointIndex": p}
                    sim_ir = build_run_sim_ir(template, row, i, seed)
                    enqueue_job(conn, sub_keys[i], "simulation", {
                        "simulation": sim_ir,
                        "parentJobKey": job.job_key,
                        "runIndex": i,
                        "params": {"__pointIndex": p,
                                   **{k: round(float(v), 4) for k, v in pt.items()}},
                        "graspNoise": sim_ir["environment"]["overrides"].get("graspNoiseXYZ", (0, 0, 0)),
                    }, requires="gz", priority=SUB_JOB_PRIORITY)
                    i += 1
        pre = fetch_jobs(conn, sub_keys)
    reused = sum(1 for j in pre.values() if j["status"] == "SUCCEEDED")
    if reused:
        log.info("resuming calibration batch, reusing completed runs",
                 job_key=job.job_key, reused=reused, total=total)

    report = _progress_reporter(job.id)
    report(reused, total)
    deadline_s = _batch_deadline_s(template, total)
    t0 = time.monotonic()
    with psycopg.connect(settings.database_url, autocommit=True) as poll_conn:
        while True:
            jobs = fetch_jobs(poll_conn, sub_keys)
            done = sum(1 for j in jobs.values() if j["status"] in TERMINAL_STATUSES)
            report(done, total)
            if done >= total:
                break
            if time.monotonic() - t0 > deadline_s:
                log.warning("calibration batch deadline exceeded, harvesting partial",
                            job_key=job.job_key, done=done, total=total)
                break
            time.sleep(settings.dag_poll_interval_s)
    wall = time.monotonic() - t0

    runs, deadline_exceeded = _harvest_runs(jobs, sub_keys)
    surface = _aggregate_points(runs, grid_points)
    completed = sum(1 for r in runs if r.get("metrics"))

    fit = fit_multi_param(param_grid, surface, real_obs)  # 缺格 → ValueError → FAILED
    fit["surface"] = surface
    fit["aggregates"] = {"points": len(grid_points), "surfacePoints": len(surface),
                         "repeats": repeats, "completed": completed,
                         "failed": len(runs) - completed, "reusedRuns": reused,
                         "wall_total_s": round(wall, 1)}
    if deadline_exceeded:
        fit["aggregates"]["deadlineExceeded"] = True
    log.info("calibration done", job_key=job.job_key,
             identifiable=fit["identifiable"], params=fit["params"],
             points=len(surface), wall_s=round(wall, 1))
    return fit
