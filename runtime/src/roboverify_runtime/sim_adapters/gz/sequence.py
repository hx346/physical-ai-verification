"""抓取序列（V0.3 W2）：gz 话题驱动的闭环速度控制 + 关节位置控制。

控制面（2026-09-15 容器实测定型）：
- 整体升降/平移：/model/gripper/cmd_vel（gz.msgs.Twist，VelocityControl）
- 指开合：/model/gripper/finger_{left,right}_joint/cmd（gz.msgs.Double，JointPositionController）
- 位姿反馈：/world/{world}/dynamic_pose/info（gz.msgs.Pose_V，W2 起持续订阅流式解析）
- 仿真时钟：/world/{world}/stats

闭环为 P 控制（速度 = kp × 误差，限幅）；每步带超时保护。
指标全部来自真实测量：零件位姿判定 pick_success，不预设结果。
"""

from __future__ import annotations

import re
import subprocess
import threading
import time

WORLD = "bin_picking"
KP = 2.0
V_MAX = 0.3
TOL = 0.004
LOOP_DT = 0.06
STEP_TIMEOUT_S = 10.0
POSE_TOPIC = f"/world/{WORLD}/dynamic_pose/info"

_NAME_RE = re.compile(r'name:\s*"([^"]+)"')
_POS_RE = re.compile(
    r"position\s*\{\s*x:\s*([-\d.eE+]+)\s+y:\s*([-\d.eE+]+)\s+z:\s*([-\d.eE+]+)")


class PoseStreamer:
    """持续订阅 dynamic_pose/info（W1 的单次冷订阅 ~2s/次是控制环低频根因）。"""

    def __init__(self) -> None:
        self._poses: dict[str, tuple[float, float, float]] = {}
        self._buf = ""
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            ["gz", "topic", "-e", "-t", POSE_TOPIC],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            while True:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                with self._lock:
                    self._buf = (self._buf + chunk)[-65536:]
                    for block in self._buf.split("pose {")[1:]:
                        m_name = _NAME_RE.search(block)
                        m_pos = _POS_RE.search(block)
                        if m_name and m_pos:
                            self._poses[m_name.group(1)] = tuple(
                                float(v) for v in m_pos.groups())
        except Exception:  # noqa: BLE001 — 后台线程任何异常都静默终止（调用方按无数据处理）
            pass

    def latest(self) -> dict[str, tuple[float, float, float]]:
        with self._lock:
            return dict(self._poses)

    def pose_of(self, name: str) -> tuple[float, float, float] | None:
        return self.latest().get(name)

    def close(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class GzClient:
    """gz topic CLI 的薄封装（容器内可用性已实测）。"""

    def __init__(self) -> None:
        self.poses = PoseStreamer()

    def close(self) -> None:
        self.poses.close()

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

    def pose_of(self, name: str) -> tuple[float, float, float] | None:
        return self.poses.pose_of(name)

    def sim_time(self) -> float:
        raw = self._run("-e", "-t", f"/world/{WORLD}/stats", "-n", "1", timeout_s=6.0)
        m = re.search(r"sim_time\s*\{\s*sec:\s*(\d+)\s+nsec:\s*(\d+)", raw)
        if not m:
            return -1.0
        return int(m.group(1)) + int(m.group(2)) * 1e-9


def _move_to(client: GzClient, target: tuple[float, float, float]) -> bool:
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
    """回 home→下降→闭合→提升→平移→放置→张开。返回真实测量指标。"""
    target = bundle["target"]
    place = bundle["place"]
    grip_pos = bundle["gripJointPos"]
    start_z = bundle.get("gripperStartZ", 0.45)

    # 位姿流就绪等待（订阅握手）
    for _ in range(30):
        if client.pose_of("gripper"):
            break
        time.sleep(0.5)

    t0 = client.sim_time()
    part0 = client.pose_of(target["name"])
    target_z_lift = (part0[2] if part0 else target["z"]) + 0.10

    # 1) 回 home（xy 取零件实时位置——warmup 期间可能已被扰动；z 回安全高度）
    live = client.pose_of(target["name"]) or part0 or (target["x"], target["y"], target["z"])
    _move_to(client, (live[0], live[1], start_z))
    # 2) 下降到抓取高度（指中心对零件中心：base z = part z + 0.075；xy 二次实时校正）
    live2 = client.pose_of(target["name"]) or live
    grasp_z = live2[2] + 0.075
    _move_to(client, (live2[0], live2[1], grasp_z))
    # 3) 力控渐进夹紧：use_force_commands=true 时 cmd 是力值（N）——
    #    W1-W2 曾误发位置值 0.027 当力（≈0.027N 零力，滑脱根因）。力来自 IR grasp_force_n。
    time.sleep(0.6)
    force = bundle.get("graspForceN", 40.0)
    for frac in (0.25, 0.5, 0.75, 1.0):
        client.pub_grip(force * frac)
        time.sleep(0.7)
    time.sleep(1.0)
    # 4) 提升
    _move_to(client, (target["x"], target["y"], start_z))
    time.sleep(0.5)
    part_lifted = client.pose_of(target["name"])
    picked = part_lifted is not None and part_lifted[2] > target_z_lift
    log.info("pick check", lifted_z=part_lifted, threshold=target_z_lift, picked=picked)
    # 5) 平移到放置点上方 → 下降 → 张开 → 回 home
    _move_to(client, (place["x"], place["y"], start_z))
    _move_to(client, (place["x"], place["y"], place["z"] + 0.075))
    client.pub_grip(-15.0)  # 负力张开（力控双向）
    time.sleep(1.0)
    client.pub_grip(0.0)
    _move_to(client, (place["x"], place["y"], start_z))
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
