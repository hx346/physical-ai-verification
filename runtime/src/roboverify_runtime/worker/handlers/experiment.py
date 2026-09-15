"""experiment 任务处理器：payload = Experiment IR + system/environment/assets，
结果（聚合 + 敏感性 + 假设）写回 job payload.result，由平台侧摄取为证据。
backend=simulator（W4）：LHS 采样 → N 次 headless gz → 聚合 + SRC 敏感性。
"""

from __future__ import annotations

import json

import psycopg

from ...config import settings
from ...experiment.engine import run_experiment
from ...experiment.sim_backend import run_simulation_experiment
from ...logging_setup import get_logger
from ..registry import handle

log = get_logger("worker.handler.experiment")


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
        result = run_simulation_experiment(
            experiment=experiment, progress_cb=_progress_reporter(job.id))
    else:
        result = run_experiment(
            experiment=experiment,
            system=system,
            environment=payload.get("environment"),
            assets=payload.get("assets", []),
        )
    result["jobKey"] = job.job_key
    return result
