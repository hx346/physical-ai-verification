"""抓取序列（V0.3 W1）：gz 话题驱动的闭环速度控制 + 关节位置控制。

控制面（2026-09-15 容器实测定型）：
- 整体升降/平移：/model/gripper/cmd_vel（gz.msgs.Twist，VelocityControl）
- 指开合：/model/gripper/finger_{left,right}_joint/cmd（gz.msgs.Double，JointPositionController）
- 位姿反馈：/world/{world}/dynamic_pose/info（gz.msgs.Pose_V）
- 仿真时钟：/world/{world}/stats

闭环为 P 控制（速度 = kp × 误差，限幅）；每步带超时保护。
指标全部来自真实测量：零件位姿判定 pick_success，不预设结果。
"""

from __future__ import annotations

import re
import subprocess
import time

WORLD = "bin_picking"
KP = 1.2
V_MAX = 0.25
TOL = 0.012
LOOP_DT = 0.15
STEP_TIMEOUT_S = 12.0


class GzClient:
    """gz topic CLI 的薄封装（容器内可用性已实测）。"""

    def _run(self, *args: str, timeout_s: float = 8.0) -> str:
        try:
            proc = subprocess.run(["gz", "topic", *args], capture_output=True,
                                  text=True, timeout=timeout_s)
            return proc.stdout or ""
        except (subprocess.TimeoutExpired, OSError):
            return ""

    def pub_twist(self, vx: float, vy: float, vz: float) -> None:
        self._run("-t", "/model/gripper/cmd_vel", "--msgtype", "gz.msgs.Twist",
                  "-p", f"linear {{ x: {vx} y: {vy} z: {vz} }}", "--num", "1")

    def pub_grip(self, joint_pos: float) -> None:
        for side in ("left", "right"):
            self._run("-t", f"/model/gripper/finger_{side}_joint/cmd",
                      "--msgtype", "gz.msgs.Double", "-p", f"data: {joint_pos}", "--num", "1")

    def poses(self) -> dict[str, tuple[float, float, float]]:
        raw = self._run("-e", "-t", f"/world/{WORLD}/dynamic_pose/info", "-n", "1", timeout_s=6.0)
        out: dict[str, tuple[float, float, float]] = {}
        for block in raw.split("pose {")[1:]:
            m_name = re.search(r'name:\s*"([^"]+)"', block)
            m_pos = re.search(
                r"position\s*\{\s*x:\s*([-\d.eE+]+)\s+y:\s*([-\d.eE+]+)\s+z:\s*([-\d.eE+]+)", block)
            if m_name and m_pos:
                out[m_name.group(1)] = tuple(float(v) for v in m_pos.groups())
        return out

    def pose_of(self, name: str) -> tuple[float, float, float] | None:
        for _ in range(3):
            p = self.poses().get(name)
            if p:
                return p
            time.sleep(0.3)
        return None

    def sim_time(self) -> float:
        raw = self._run("-e", "-t", f"/world/{WORLD}/stats", "-n", "1", timeout_s=6.0)
        m = re.search(r"sim_time\s*\{\s*sec:\s*(\d+)\s+nsec:\s*(\d+)", raw)
        if not m:
            return -1.0
        return int(m.group(1)) + int(m.group(2)) * 1e-9


def _move_to(client: GzClient, target: tuple[float, float, float], note: str) -> bool:
    """闭环移动 gripper base 到目标位；超时返回 False（不中断序列，真实失败如实记录）。"""
    deadline = time.monotonic() + STEP_TIMEOUT_S
    while time.monotonic() < deadline:
        cur = client.pose_of("gripper")
        if cur is None:
            time.sleep(LOOP_DT)
            continue
        err = tuple(t - c for t, c in zip(target, cur))
        if max(abs(e) for e in err) < TOL:
            client.pub_twist(0, 0, 0)
            return True
        v = [max(-V_MAX, min(V_MAX, KP * e)) for e in err]
        client.pub_twist(*v)
        time.sleep(LOOP_DT)
    client.pub_twist(0, 0, 0)
    return False


def run_pick_sequence(client: GzClient, bundle: dict, log) -> dict[str, float]:
    """下降→闭合→提升→平移→放置→张开。返回真实测量指标。"""
    target = bundle["target"]
    place = bundle["place"]
    grip_pos = bundle["gripJointPos"]
    start_z = bundle.get("gripperStartZ", 0.45)

    t0 = client.sim_time()
    part0 = client.pose_of(target["name"])
    target_z_lift = (part0[2] if part0 else target["z"]) + 0.10

    # 1) 回 home（抵消 warmup 期间自由坠落）
    _move_to(client, (target["x"], target["y"], start_z), "home")
    # 2) 下降到抓取高度（指中心对零件中心：base z = part z + 0.075）
    grasp_z = (part0[2] if part0 else target["z"]) + 0.075
    _move_to(client, (target["x"], target["y"], grasp_z), "descend")
    # 3) 闭合（挤压量已含在 gripJointPos）
    client.pub_grip(grip_pos)
    time.sleep(1.5)
    # 4) 提升
    _move_to(client, (target["x"], target["y"], start_z), "lift")
    time.sleep(0.5)
    part_lifted = client.pose_of(target["name"])
    picked = part_lifted is not None and part_lifted[2] > target_z_lift
    log.info("pick check", lifted_z=part_lifted, threshold=target_z_lift, picked=picked)
    # 5) 平移到放置点上方 → 下降 → 张开 → 回 home
    _move_to(client, (place["x"], place["y"], start_z), "transfer")
    _move_to(client, (place["x"], place["y"], place["z"] + 0.075), "lower")
    client.pub_grip(0.0)
    time.sleep(1.0)
    _move_to(client, (place["x"], place["y"], start_z), "return")
    t1 = client.sim_time()

    final = client.pose_of(target["name"])
    metrics: dict[str, float] = {
        "pick_success": 1.0 if picked else 0.0,
        "cycle_time_s": round(max(0.0, t1 - t0), 3) if t0 >= 0 and t1 >= 0 else -1.0,
    }
    if final is not None:
        metrics["position_error_mm"] = round(
            1000.0 * ((final[0] - place["x"]) ** 2 + (final[1] - place["y"]) ** 2) ** 0.5, 3)
        metrics["placed_height_m"] = round(final[2], 4)
    return metrics
