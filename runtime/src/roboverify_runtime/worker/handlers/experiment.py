"""experiment 任务处理器：payload = Experiment IR + system/environment/assets，
结果（聚合 + 敏感性 + 假设）写回 job payload.result，由平台侧摄取为证据。
backend=simulator（W4）：LHS 采样 → N 次 headless gz → 聚合 + SRC 敏感性。
"""

from __future__ import annotations

from ...experiment.engine import run_experiment
from ...experiment.sim_backend import run_simulation_experiment
from ...logging_setup import get_logger
from ..registry import handle

log = get_logger("worker.handler.experiment")


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
        result = run_simulation_experiment(experiment=experiment)
    else:
        result = run_experiment(
            experiment=experiment,
            system=system,
            environment=payload.get("environment"),
            assets=payload.get("assets", []),
        )
    result["jobKey"] = job.job_key
    return result
