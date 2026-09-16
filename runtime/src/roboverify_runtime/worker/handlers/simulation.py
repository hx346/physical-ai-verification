"""simulation 任务处理器：Simulation IR → 适配器执行 → 指标结果。"""

from __future__ import annotations

import time

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
    t0 = time.monotonic()
    result = adapter.run(sim_ir, scene, float(sim_ir.get("timeout_s", DEFAULT_TIMEOUT_S)))
    wall_s = round(time.monotonic() - t0, 1)
    # 诚实标注：IR 请求的指标中哪些真正测到、哪些当前不可得（脚本化抓取序列 M2 后续实现，不编造）
    requested = sim_ir.get("metrics_to_collect") or []
    available = {m: ("measured" if m in result.metrics else "unavailable") for m in requested}
    log.info("simulation done", job_key=job.job_key, metrics=result.metrics, wall_s=wall_s)
    return {
        "metrics": result.metrics,
        "notes": result.notes,
        "logExcerpt": result.log_excerpt[-2000:],
        "sceneSdf": scene,
        "sceneSdfBytes": len(scene),
        "requestedMetrics": available,
        # V0.5 W1：DAG 批次收割单 run 耗时（批次 wall 曲线/DoD 吞吐核算）
        "wall_s": wall_s,
    }
