"""时延预算：camera → network → inference → planning → controller → gripper 逐段累加。"""

from __future__ import annotations

from . import models_v01 as M
from .snapshot import SystemSnapshot

STAGE_CAMERA = "camera"
STAGE_NETWORK = "network"
STAGE_INFERENCE = "inference"
STAGE_PLANNING = "planning"
STAGE_CONTROLLER = "controller"
STAGE_GRIPPER = "gripper"


def latency_budget(snapshot: SystemSnapshot) -> dict:
    """返回 {stages: {name: ms}, total_ms, assumptions: [str]}。缺失段用假设默认值并声明。"""
    stages: dict[str, float] = {}
    assumptions: list[str] = []

    cam_latencies = [c.latency_ms for c in snapshot.cameras if c.latency_ms is not None]
    if cam_latencies:
        stages[STAGE_CAMERA] = max(cam_latencies)  # 取最慢相机
    else:
        stages[STAGE_CAMERA] = M.INFERENCE_LATENCY_MS_DEFAULT  # 占位，见 assumptions
        assumptions.append("camera latency 缺失，用假设默认值")

    stages[STAGE_NETWORK] = snapshot.network_latency_ms if snapshot.network_latency_ms is not None else 0.0
    if snapshot.network_latency_ms is None:
        assumptions.append("network latency 缺失，按 0 计")

    stages[STAGE_INFERENCE] = M.INFERENCE_LATENCY_MS_DEFAULT
    assumptions.append(f"inference latency = 假设默认 {M.INFERENCE_LATENCY_MS_DEFAULT:.0f}ms")
    stages[STAGE_PLANNING] = M.PLANNING_LATENCY_MS_DEFAULT
    assumptions.append(f"planning latency = 假设默认 {M.PLANNING_LATENCY_MS_DEFAULT:.0f}ms")

    controller = snapshot.robot_param("controller_latency_ms")
    stages[STAGE_CONTROLLER] = float(controller.value) if controller else 0.0

    gripper_latency = snapshot.gripper_param("control_latency_ms")
    stages[STAGE_GRIPPER] = float(gripper_latency.value) if gripper_latency else 0.0

    total = sum(stages.values())
    return {"stages": stages, "total_ms": total, "assumptions": assumptions}
