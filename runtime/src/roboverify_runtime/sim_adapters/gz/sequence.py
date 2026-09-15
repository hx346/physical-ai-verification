"""抓取序列（V0.3 W2）：gz 话题驱动的闭环速度控制 + 关节位置控制。

控制面（2026-09-15 容器实测定型）：
- 整体升降/平移：/model/gripper/cmd_vel（gz.msgs.Twist，VelocityControl）
- 指开合：/model/gripper/finger_{left,right}_joint/cmd（gz.msgs.Double，JointPositionController）
- 位姿反馈：/world/{world}/dynamic_pose/info（gz.msgs.Pose_V，W2 起持续订阅流式解析）
- 接触计数：/gripper/finger_{left,right}/contact（contact sensor，W2 终局接入 collision_count）
- 仿真时钟：/world/{world}/stats

闭环为 P 控制（速度 = kp × 误差，限幅）；每步带超时保护。
指标全部来自真实测量：零件位姿判定 pick_success，不预设结果。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time

WORLD = "bin_picking"
KP = 2.0
V_MAX = 0.3
TOL = 0.008  # 收敛容差 8mm：夹持自定心（闭合把零件挤向中心），无需毫米级
COARSE_BAND = 0.06
FINE_V = 0.02
LOOP_DT = 0.06
STEP_TIMEOUT_S = 25.0
# 连续 P 控制：gz-bridge 下延迟 ≤63ms（W3 实测）可用正常增益；
# CLI 回退路径同参数仍欠阻尼——回退时如实超时失败，不静默降级
CTRL_KP = 2.0
CTRL_V = 0.25
# 悬停升速补偿（W2 终局实测）：dartsim 对模型级 LinearVelocityCmd 的实现是步首置
# 速度、重力仍积分 g·dt——若夹爪受重力，零速指令下恒定下沉 0.0098 m/s（实测吻合）。
# 现夹爪 link 级 <gravity>0</gravity>（龙门架重力补偿），零速即精确悬停，补偿归零保留开关。
HOVER_VZ = 0.0
# 侧向下刀偏移：先降后平移，避开零件顶面上方的 margin 接触带（见 run_pick_sequence 注释）
LATERAL_OFFS = 0.10
POSE_TOPIC = f"/world/{WORLD}/dynamic_pose/info"

_NAME_RE = re.compile(r'name:\s*"([^"]+)"')
_POS_RE = re.compile(r"position\s*\{([^}]*)\}")
_AXIS_RE = re.compile(r"\b([xyz]):\s*([-\d.eE+]+)")
CONTACT_TOPICS = ("/gripper/finger_left/contact", "/gripper/finger_right/contact")


def _parse_vec(inner: str) -> tuple[float, float, float]:
    """protobuf 文本格式省略零值字段（实测 position { z: 0.235 }，x/y=0 不打印），
    逐轴可选解析——W2 曾因要求 x/y/z 齐备而漏读一切恰在坐标轴上的实体。"""
    axes = dict(_AXIS_RE.findall(inner))
    return (float(axes.get("x", 0.0)), float(axes.get("y", 0.0)),
            float(axes.get("z", 0.0)))


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
                            self._poses[m_name.group(1)] = _parse_vec(m_pos.group(1))
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


class ContactCounter:
    """两指 contact sensor 话题计数（collision_count 指标数据源）。

    gz-sim8 Contact system 只为 link 级 contact sensor 发布话题且仅在
    有接触时发消息（源码 Contact.cc 实证）——话题在场景加载即广播，
    订阅器不会因"暂无接触"而退出。
    """

    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()
        self._procs = []
        for topic in CONTACT_TOPICS:
            proc = subprocess.Popen(
                ["gz", "topic", "-e", "-t", topic],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            self._procs.append(proc)
            threading.Thread(target=self._loop, args=(proc,), daemon=True).start()

    def _loop(self, proc) -> None:
        buf = ""
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buf = (buf + chunk)[-131072:]
                n = buf.count("contact {")
                if n:
                    with self._lock:
                        self._count += n
                    # 消费已计数的 marker：只保留最后一个（可能残缺的）块的内容
                    idx = buf.rfind("contact {")
                    buf = buf[idx + len("contact {"):]
        except Exception:  # noqa: BLE001 — 后台线程异常静默终止（计为无接触）
            pass

    def reset(self) -> None:
        with self._lock:
            self._count = 0

    def total(self) -> int:
        with self._lock:
            return self._count

    def close(self) -> None:
        for proc in self._procs:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


class TwistPublisher:
    """后台 5Hz 持续发布当前期望速度（W2 第 28 轮定型）。

    one-shot 发布（每次 gz topic subprocess ~0.3s）+ 位姿流滞后 ~1s 下，
    "发完即睡"的控制律必然过冲或爬行（第 22-27 轮五轮实测）。持续重发让
    速度指令永不过期滞留，主线程即时改期望值即得低延迟连续控制。
    """

    def __init__(self) -> None:
        self._v: tuple[float, float, float] = (0.0, 0.0, HOVER_VZ)
        self._stop = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def set(self, vx: float, vy: float, vz: float) -> None:
        with self._lock:
            self._v = (vx, vy, vz)

    def _loop(self) -> None:
        while not self._stop:
            with self._lock:
                vx, vy, vz = self._v
            try:
                subprocess.run(
                    ["gz", "topic", "-t", "/model/gripper/cmd_vel",
                     "--msgtype", "gz.msgs.Twist",
                     "-p", f"linear {{ x: {vx} y: {vy} z: {vz} }}", "--num", "1"],
                    capture_output=True, timeout=4)
            except (subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(0.12)

    def close(self) -> None:
        self.set(0.0, 0.0, HOVER_VZ)
        time.sleep(0.3)  # 让停机指令可靠送达再退出
        self._stop = True


class GzBridge:
    """进程内 gz-transport 桥客户端（deploy/sim/gz_bridge.cc，V0.3 W3）。

    实测：位姿 0.2s 就绪、cmd→运动延迟 ≤63ms、233 行/s——CLI one-shot 的
    ~0.3s 发布死区与 ~1s 位姿滞后一并消除（W2 终局定性的运动传输瓶颈）。
    行协议见 gz_bridge.cc 头注释。桥不可用时 GzClient 回退 CLI 三件套。
    """

    def __init__(self) -> None:
        self._poses: dict[str, tuple[float, float, float]] = {}
        self._count = 0
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            ["gz-bridge", WORLD],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            for line in self._proc.stdout:
                parts = line.split()
                if parts[0] == "P" and len(parts) == 5:
                    with self._lock:
                        self._poses[parts[1]] = (
                            float(parts[2]), float(parts[3]), float(parts[4]))
                elif parts[0] == "C" and len(parts) == 3:
                    with self._lock:
                        self._count += int(parts[1]) + int(parts[2])
        except Exception:  # noqa: BLE001 — 桥异常静默终止（调用方按无数据处理）
            pass

    # ---- 统一接口：与 PoseStreamer/ContactCounter/TwistPublisher 同形 ----
    def pose_of(self, name: str) -> tuple[float, float, float] | None:
        with self._lock:
            return self._poses.get(name)

    def reset(self) -> None:
        with self._lock:
            self._count = 0

    def total(self) -> int:
        with self._lock:
            return self._count

    def set(self, vx: float, vy: float, vz: float) -> None:
        try:
            self._proc.stdin.write(f"{vx} {vy} {vz}\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            pass  # 桥已退出：速度指令丢失，序列后续按无反馈超时如实记录

    def close(self) -> None:
        try:
            self._proc.stdin.close()
        except (OSError, ValueError):
            pass
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class GzClient:
    """控制面客户端：优先 gz-bridge（进程内低延迟），无桥回退 gz topic CLI 三件套。"""

    def __init__(self) -> None:
        if shutil.which("gz-bridge"):
            self._bridge: GzBridge | None = GzBridge()
            self.poses = self._bridge
            self.contacts = self._bridge
            self.twist = self._bridge
        else:
            self._bridge = None
            self.poses = PoseStreamer()
            self.contacts = ContactCounter()
            self.twist = TwistPublisher()

    def close(self) -> None:
        self.twist.close()
        self.poses.close()
        self.contacts.close()

    def _run(self, *args: str, timeout_s: float = 8.0) -> str:
        try:
            proc = subprocess.run(["gz", "topic", *args], capture_output=True,
                                  text=True, timeout=timeout_s)
            return proc.stdout or ""
        except (subprocess.TimeoutExpired, OSError):
            return ""

    def pub_twist(self, vx: float, vy: float, vz: float) -> None:
        self.twist.set(vx, vy, vz)  # 即时：由 5Hz 持续发布线程送出

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
    """分步机动到目标位（W2 第 22 轮定型）。

    连续 P 速度控制在 CLI 发布 ~0.3s 死区下欠阻尼发散（实测 runaway 至 x=2.11，
    接触对全是 finger↔bin_floor/bin_wall）。改为分步：发速度→定时→急停→读位姿→
    校正，每步行程有界（MOVE_V×MOVE_DT），结构上无积分发散。急停后零速指令
    精确悬停（夹爪已关重力）。超时返回 False（不中断序列，真实失败如实记录）。
    """
    deadline = time.monotonic() + STEP_TIMEOUT_S
    while time.monotonic() < deadline:
        cur = client.pose_of("gripper")
        if cur is None:
            time.sleep(0.1)
            continue
        err = [t - c for t, c in zip(target, cur)]
        if max(abs(e) for e in err) < TOL:
            client.pub_twist(0, 0, HOVER_VZ)
            return True
        v = [max(-CTRL_V, min(CTRL_V, CTRL_KP * e)) for e in err]
        client.pub_twist(*v)
        time.sleep(0.15)
    client.pub_twist(0, 0, HOVER_VZ)
    return False


def run_pick_sequence(client: GzClient, bundle: dict, log) -> dict[str, float]:
    """回 home→下降→闭合→提升→平移→放置→张开。返回真实测量指标。"""
    target = bundle["target"]
    place = bundle["place"]
    grip_pos = bundle["gripJointPos"]
    start_z = bundle.get("gripperStartZ", 0.45)
    grasp_offset = bundle.get("graspOffset", 0.033)

    # 位姿流就绪等待（订阅握手）
    for _ in range(30):
        if client.pose_of("gripper"):
            break
        time.sleep(0.5)

    # 目标选择：抓取时刻的实时堆顶件（生成时"最高件"沉降后可能被埋——
    # W2 第 11 轮实测：spawn 最高件落到箱底被其他件覆盖，按 spawn 位姿必夹空）
    part_names = bundle.get("partNames") or [target["name"]]
    live_parts = {n: p for n, p in
                  ((n, client.pose_of(n)) for n in part_names) if p}
    tgt_name = max(live_parts, key=lambda n: live_parts[n][2]) \
        if live_parts else target["name"]
    log.info("target selected", name=tgt_name,
             n_visible=len(live_parts),
             z=live_parts.get(tgt_name, (None, None, None))[2])

    t0 = client.sim_time()
    part0 = client.pose_of(tgt_name) or (target["x"], target["y"], target["z"])
    target_z_lift = part0[2] + 0.10

    # 1) 回 home（xy 取零件实时位置——warmup 期间可能已被扰动；z 回安全高度）
    live = client.pose_of(tgt_name) or part0
    _move_to(client, (live[0], live[1], start_z))
    # 2) 侧向下刀沿 y 轴（W2 第 24 轮定型）：指开合沿 x——沿 y 贴身滑入零件侧带时
    #    x 向间隙仍在，指不碰零件任何面 → 平移精确居中 → 对称力闭合。
    #    （沿 x approach 会被开口侧指面顶住停在差 clearance 处→偏斜抓取→挤飞；
    #      沿 z 下插会被顶面接触顶住停在指底=零件顶面。）
    live2 = client.pose_of(tgt_name) or live
    grasp_z = live2[2] + grasp_offset
    offs_y = (1.0 if live2[1] >= 0 else -1.0) * min(LATERAL_OFFS, 0.09 - abs(live2[1]))
    lateral_ok = _move_to(client, (live2[0], live2[1] + offs_y, grasp_z))
    approach_ok = _move_to(client, (live2[0], live2[1], grasp_z))
    log.info("descend done", lateral_ok=lateral_ok, approach_ok=approach_ok,
             gripper=client.pose_of("gripper"), part=live2,
             target_grasp_z=round(grasp_z, 4), lateral_y=round(offs_y, 4))
    # 3) 力控渐进夹紧：use_force_commands=true 时 cmd 是力值（N）——
    #    W1-W2 曾误发位置值 0.027 当力（≈0.027N 零力，滑脱根因）。力来自 IR grasp_force_n。
    time.sleep(0.6)
    client.contacts.reset()  # collision_count 计数窗口：闭合→提升
    force = bundle.get("graspForceN", 40.0)
    for frac in (0.25, 0.5, 0.75, 1.0):
        client.pub_grip(force * frac)
        time.sleep(0.7)
    time.sleep(1.0)
    # 4) 提升
    _move_to(client, (live[0], live[1], start_z))
    time.sleep(0.5)
    part_lifted = client.pose_of(tgt_name)
    picked = part_lifted is not None and part_lifted[2] > target_z_lift
    collision_count = client.contacts.total()
    log.info("pick check", lifted_z=part_lifted, threshold=target_z_lift, picked=picked,
             collision_count=collision_count)
    # 5) 平移到放置点上方 → 下降 → 张开 → 回 home
    _move_to(client, (place["x"], place["y"], start_z))
    _move_to(client, (place["x"], place["y"], place["z"] + grasp_offset))
    client.pub_grip(-15.0)  # 负力张开（力控双向）
    time.sleep(1.0)
    client.pub_grip(0.0)
    _move_to(client, (place["x"], place["y"], start_z))
    t1 = client.sim_time()

    final = client.pose_of(tgt_name)
    metrics: dict[str, float] = {
        "pick_success": 1.0 if picked else 0.0,
        "cycle_time_s": round(max(0.0, t1 - t0), 3) if t0 >= 0 and t1 >= 0 else -1.0,
        # 闭合→提升窗口两指 contact sensor 话题的接触条目数（每步每指累计）
        "collision_count": float(collision_count),
    }
    if final is not None:
        metrics["position_error_mm"] = round(
            1000.0 * ((final[0] - place["x"]) ** 2 + (final[1] - place["y"]) ** 2) ** 0.5, 3)
        metrics["placed_height_m"] = round(final[2], 4)
    return metrics
