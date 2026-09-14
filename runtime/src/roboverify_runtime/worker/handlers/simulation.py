"""simulation 任务处理器：Simulation IR → 适配器执行 → 指标结果。"""

from __future__ import annotations

from ...logging_setup import get_logger
from ...sim_adapters import get_adapter
from ..registry import handle

log = get_logger("worker.handler.simulation")

DEFAULT_TIMEOUT_S = 120.0


@handle("simulation")
def run(job) -> dict:
    payload = job.payload
    sim_ir = payload.get("simulation")
    if not sim_ir:
        raise ValueError("simulation job 缺少 simulation payload")
    adapter = get_adapter("gz")
    scene = adapter.build_scene(sim_ir)
    result = adapter.run(sim_ir, scene, float(sim_ir.get("timeout_s", DEFAULT_TIMEOUT_S)))
    log.info("simulation done", job_key=job.job_key, metrics=result.metrics)
    return {
        "metrics": result.metrics,
        "notes": result.notes,
        "logExcerpt": result.log_excerpt[-2000:],
        "sceneSdfBytes": len(scene),
    }
