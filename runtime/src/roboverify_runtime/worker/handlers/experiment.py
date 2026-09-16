"""experiment 任务处理器：payload = Experiment IR + system/environment/assets，
结果（聚合 + 敏感性 + 假设）写回 job payload.result，由平台侧摄取为证据。

backend=analytic：解析内核本地求值。
backend=simulator（V0.5 W1 DAG）：
  父任务只做编排——LHS 采样 → 展开 N 个 simulation 子 job（幂等键
  {parent}:run:{i}，requires=gz，多 sim-worker SKIP LOCKED 并行认领）→
  轮询收割 → aggregate_runs 聚合 + SRC。
  断点续跑：父任务重跑时子 job ON CONFLICT 复用（已 SUCCEEDED 的不重跑）。
  父任务 requires=orchestrator（普通 worker），不得被 sim-worker 认领——
  单 sim-worker 场景下父任务占住唯一 gz 槽等子任务会自我饿死。
"""

from __future__ import annotations

import json
import time

import psycopg

from ...config import settings
from ...experiment.engine import run_experiment
from ...experiment.sampling import sample
from ...experiment.sim_backend import AGG_METRICS, aggregate_runs, build_run_sim_ir
from ...logging_setup import get_logger
from ..queue import enqueue_job, fetch_jobs
from ..registry import handle

log = get_logger("worker.handler.experiment")

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED"})
# 子任务先于后续新批次被认领（priority 数值小者优先；父任务为 60）
SUB_JOB_PRIORITY = 55
_RUN_METRIC_WHITELIST = frozenset(AGG_METRICS) | {"pick_sequence_error", "descend_failed"}


def _progress_reporter(job_id: int):
    """每 run 完成后把 {done,total} 写进 job payload.progress（批次进度可见）。

    进度是可观测性增强而非实验本体：DB 异常只告警一次后停写，不再尝试。
    """
    dead = False

    def report(done: int, total: int) -> None:
        nonlocal dead
        if dead:
            return
        try:
            with psycopg.connect(settings.database_url) as conn:
                conn.execute(
                    "UPDATE job_queue SET payload = payload || %s::jsonb, "
                    "updated_at = now() WHERE id = %s",
                    (json.dumps({"progress": {"done": done, "total": total}}), job_id))
        except Exception as e:  # noqa: BLE001 — 进度失败静默（实验本体不受影响）
            log.warning("progress report failed, stopping reports", error=str(e))
            dead = True

    return report


def _batch_deadline_s(template: dict, n: int) -> float:
    """批次兜底时限：显式配置（simulation.batch_deadline_s）优先；
    默认覆盖最坏情形（单 worker 串行 n × 单次超时 × 1.2，下限 30min）——
    无 sim-worker 在线时父任务不得永久挂起，收割部分结果如实标注。"""
    cfg = template.get("batch_deadline_s")
    if cfg:
        return float(cfg)
    per_run = float(template.get("timeout_s", 120.0))
    return max(1800.0, 1.2 * n * per_run)


def _harvest_runs(jobs: dict[str, dict], sub_keys: list[str]) -> tuple[list[dict], bool]:
    """收割子任务结果 → run 记录列表（与串行路径同构，纯函数可单测）。

    返回 (runs, deadline_exceeded)：非终态/缺失子任务（超时收割时）计为
    failed run 并置 deadline_exceeded——不掩盖部分完成事实。
    """
    runs: list[dict] = []
    deadline_exceeded = False
    for i, key in enumerate(sub_keys):
        j = jobs.get(key, {"status": "MISSING", "payload": {}, "lastError": None})
        rec = {"i": i, "params": j["payload"].get("params"),
               "graspNoise": j["payload"].get("graspNoise")}
        if j["status"] == "SUCCEEDED":
            result = j["payload"].get("result", {})
            metrics = result.get("metrics", {})
            rec["metrics"] = {k: v for k, v in metrics.items() if k in _RUN_METRIC_WHITELIST}
            if result.get("wall_s") is not None:
                rec["wall_s"] = result["wall_s"]
        elif j["status"] in ("QUEUED", "RUNNING", "MISSING"):
            deadline_exceeded = True
            rec["error"] = f"batch deadline exceeded (sub-job {j['status']})"
        else:
            rec["error"] = (j.get("lastError") or f"sub-job {j['status']}")[:300]
        runs.append(rec)
    return runs, deadline_exceeded


def _run_simulator_dag(job) -> dict:
    payload = job.payload
    experiment = payload["experiment"]
    template = experiment.get("simulation") or {}
    if not template:
        raise ValueError("backend=simulator 实验缺少 simulation 模板")
    sampling = experiment["sampling"]
    n = int(sampling["n"])
    seed = int(sampling.get("seed", 20260914))

    # 采样只做一次（父任务）：子任务载荷携带已实例化的参数与噪声
    X, names = sample(experiment["parameters"], sampling.get("method", "lhs"), n, seed)

    sub_keys = [f"{job.job_key}:run:{i}" for i in range(n)]
    with psycopg.connect(settings.database_url) as conn:
        with conn.transaction():
            for i in range(n):
                row = {k: float(v) for k, v in zip(names, X[i], strict=False)}
                sim_ir = build_run_sim_ir(template, row, i, seed)
                enqueue_job(conn, sub_keys[i], "simulation", {
                    "simulation": sim_ir,
                    "parentJobKey": job.job_key,
                    "runIndex": i,
                    "params": {k: round(v, 4) for k, v in row.items()},
                    "graspNoise": sim_ir["environment"]["overrides"]["graspNoiseXYZ"],
                }, requires="gz", priority=SUB_JOB_PRIORITY)
        # 断点续跑复用计数：展开后即刻已完成的子任务 = 上次批次遗留成果
        pre = fetch_jobs(conn, sub_keys)
    reused = sum(1 for j in pre.values() if j["status"] == "SUCCEEDED")
    if reused:
        log.info("resuming batch, reusing completed runs",
                 job_key=job.job_key, reused=reused, total=n)

    report = _progress_reporter(job.id)
    report(reused, n)
    deadline_s = _batch_deadline_s(template, n)
    t_batch = time.monotonic()
    # 单连接轮询（autocommit 只读，避免每 5s 重建连接）
    with psycopg.connect(settings.database_url, autocommit=True) as poll_conn:
        while True:
            jobs = fetch_jobs(poll_conn, sub_keys)
            done = sum(1 for j in jobs.values() if j["status"] in TERMINAL_STATUSES)
            report(done, n)
            if done >= n:
                break
            if time.monotonic() - t_batch > deadline_s:
                log.warning("batch deadline exceeded, harvesting partial results",
                            job_key=job.job_key, done=done, total=n, deadline_s=deadline_s)
                break
            time.sleep(settings.dag_poll_interval_s)
    batch_wall = time.monotonic() - t_batch

    runs, deadline_exceeded = _harvest_runs(jobs, sub_keys)
    result = aggregate_runs(experiment, runs, names, X, batch_wall)
    result["aggregates"]["reusedRuns"] = reused
    if deadline_exceeded:
        result["aggregates"]["deadlineExceeded"] = True
    log.info("sim experiment batch done", job_key=job.job_key,
             completed=result["aggregates"]["completed"], failed=result["aggregates"]["failed"],
             reused=reused, wall_s=result["aggregates"]["wall_total_s"])
    return result


@handle("experiment")
def run(job) -> dict:
    payload = job.payload
    experiment = payload.get("experiment")
    system = payload.get("system")
    if not experiment or not system:
        raise ValueError("experiment job 缺少 experiment/system payload")
    log.info("experiment running", job_key=job.job_key,
             n=experiment.get("sampling", {}).get("n"),
             backend=experiment.get("backend", "analytic"))
    if experiment.get("backend") == "simulator":
        result = _run_simulator_dag(job)
    else:
        result = run_experiment(
            experiment=experiment,
            system=system,
            environment=payload.get("environment"),
            assets=payload.get("assets", []),
        )
    result["jobKey"] = job.job_key
    return result
