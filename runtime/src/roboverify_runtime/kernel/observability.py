"""可观测性分析：State IR 需求 vs 系统传感器能力 → 直接/部分/不可观测。"""

from __future__ import annotations

from .snapshot import SystemSnapshot

OBS_DIRECT = "directly_observable"
OBS_PARTIAL = "partially_observable"
OBS_NOT = "not_observable"

# 状态 → 判定规则（V0.1 范围内与传感器能力的映射）
_STATE_RULES = {
    "object_pose": "depth",
    "metric_depth": "depth",
    "robot_pose": "encoder",
    "end_effector_pose": "encoder",
    "obstacle_geometry": "depth",
    "contact_force": "force",
    "grasp_state": "gripper_feedback",
    "object_velocity": "depth",
}


def observability(snapshot: SystemSnapshot, states: list[dict]) -> dict:
    """对 State IR 中每个状态给出可观测性判定。

    force / gripper_feedback 依赖夹爪反馈能力（V0.1 资产里以 feedback 参数表达）。
    """
    has_depth = any(c.depth_available for c in snapshot.cameras)
    gripper_feedback = None
    fb = snapshot.gripper_param("feedback")
    if fb is not None:
        gripper_feedback = "none" not in str(fb.value).lower()
    # 力传感器：V0.1 资产目录未含 F/T 传感器，暂按夹爪力反馈推断
    has_force = bool(gripper_feedback)

    results: dict[str, dict] = {}
    for state in states:
        sid = state.get("id", "?")
        rule = _STATE_RULES.get(sid)
        if rule is None:
            results[sid] = {"verdict": OBS_PARTIAL, "reason": "V0.1 无该状态的判定规则，需仿真/真机证据"}
            continue
        if rule == "depth":
            verdict = OBS_DIRECT if has_depth else OBS_NOT
            reason = "存在深度相机" if has_depth else "仅有 2D 相机，度量深度不可直接观测"
        elif rule == "encoder":
            verdict, reason = OBS_DIRECT, "机器人本体编码器提供"
        elif rule == "force":
            verdict = OBS_DIRECT if has_force else OBS_NOT
            reason = "夹爪带力/位反馈" if has_force else "无 F/T 传感器且夹爪无反馈，接触力不可观测"
        elif rule == "gripper_feedback":
            verdict = OBS_DIRECT if gripper_feedback else OBS_NOT
            reason = "夹爪反馈可用" if gripper_feedback else "夹爪无反馈（如真空吸盘）"
        else:
            verdict, reason = OBS_PARTIAL, "规则缺失"
        results[sid] = {"verdict": verdict, "reason": reason}
    return results
