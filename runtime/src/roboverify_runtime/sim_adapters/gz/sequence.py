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
    V0.5 W3：capture_depth——D 命令单帧深度落盘（帧 ~3.7MB 走文件不走 stdout）。
    行协议见 gz_bridge.cc 头注释。桥不可用时 GzClient 回退 CLI 三件套。
    """

    def __init__(self) -> None:
        self._poses: dict[str, tuple[float, float, float]] = {}
        self._count = 0
        self._depth_reply: str | None = None
        self._depth_evt = threading.Event()
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
                elif parts[0] in ("D_OK", "D_ERR"):
                    with self._lock:
                        self._depth_reply = line.strip()
                    self._depth_evt.set()
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

    def capture_depth(self, topic: str, path: str, timeout_s: float = 6.0) -> tuple[int, int] | None:
        """单帧深度捕获：D 命令 → 桥落盘 → D_OK (w,h)。失败/超时返回 None。"""
        with self._lock:
            self._depth_reply = None
        self._depth_evt.clear()
        try:
            self._proc.stdin.write(f"D {topic} {path}\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            return None
        if not self._depth_evt.wait(timeout_s):
            return None
        with self._lock:
            reply = self._depth_reply
        if reply is None or not reply.startswith("D_OK"):
            return None
        parts = reply.split()
        return int(parts[1]), int(parts[2])

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

    def capture_depth(self, topic: str, path: str, timeout_s: float = 6.0) -> tuple[int, int] | None:
        """深度捕获仅桥路径支持（CLI 文本解析对 float32 帧不实际）——
        无桥返回 None，感知层如实失败，不静默降级。"""
        if self._bridge is None:
            return None
        return self._bridge.capture_depth(topic, path, timeout_s)

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
        err = [t - c for t, c in zip(target, cur, strict=False)]
        if max(abs(e) for e in err) < TOL:
            client.pub_twist(0, 0, HOVER_VZ)
            return True
        v = [max(-CTRL_V, min(CTRL_V, CTRL_KP * e)) for e in err]
        client.pub_twist(*v)
        time.sleep(0.15)
    client.pub_twist(0, 0, HOVER_VZ)
    return False


# V0.5 W3：夹爪 base 高于零件顶面的余量（= W2/W4 定型 graspOffset 的顶面形式
# 0.027+0.3s 相对中心 = 0.027 相对顶面）——感知路径从感知顶面直接起算
GRASP_TOP_MARGIN = 0.027


def _perceive_target(client: GzClient, bundle: dict, log) -> dict | None:
    """V0.5 W3 感知定位：standby（避遮挡）→ 单帧深度 → 噪声 → 反投影质心。

    深度噪声（诚实两层模型，见 perception/depth_localize.py 模块注释）：
    帧偏置 N(0,σ) 主导（单帧估计不被平均）+ 逐像素 iid σ/10 次要。
    per-run rng_seed 由实验引擎注入（DAG/串行逐位一致可复现）。
    失败返回 None（窗内无点/捕获失败），调用方如实记 perception_failed。
    """
    import os
    import tempfile

    import numpy as np

    from ...perception import apply_depth_noise, localize_from_depth

    p = bundle["perception"]
    # 1) standby：夹爪先移到放置点上方（顶视相机下夹爪悬停在目标上方会挡零件；
    #    z 带过滤剔除的是夹爪像素，但被遮挡的零件像素已丢失——必须物理避让）
    _move_to(client, (bundle["place"]["x"], bundle["place"]["y"],
                      bundle.get("gripperStartZ", 0.45)))
    # 2) 单帧捕获（桥 D 命令落盘 float32 帧）
    path = os.path.join(tempfile.gettempdir(), f"rv-depth-{os.getpid()}.bin")
    dims = client.capture_depth(p["topic"], path, timeout_s=6.0)
    if dims is None:
        log.error("depth capture failed", topic=p["topic"])
        return None
    w, h = dims
    depth = np.fromfile(path, dtype=np.float32)
    os.unlink(path)
    if depth.size < w * h:
        log.error("depth frame truncated", expected=w * h, got=depth.size)
        return None
    depth = depth[:w * h].reshape(h, w)
    # 3) 噪声注入 + 4) 反投影质心定位
    sigma_m = float(p.get("depth_noise_mm", 0.0)) / 1000.0
    rng = np.random.default_rng(int(p.get("rng_seed", 7)))
    bias = float(rng.normal(0.0, sigma_m)) if sigma_m > 0 else 0.0
    noisy = apply_depth_noise(depth, sigma_m / 10.0, bias, rng)
    result = localize_from_depth(noisy, p["camera"], p["workspace"])
    if result is None:
        log.error("perception found no points in workspace")
    else:
        log.info("perceived target", sigma_mm=round(sigma_m * 1000, 2),
                 bias_mm=round(bias * 1000, 2), **result)
    return result


def _descend_until(client: GzClient, part_name: str, stop_z: float,
                   timeout_s: float = 25.0, vz: float = -0.04):
    """低速闭环下降（V0.5 W4 释放弹飞根治核心）：vz=-0.04，按零件实时 z 停止。

    位置分步/单步 _move_to 的硬停（0.25m/s→0 一步内 ~25g）已被探针矩阵证伪：
    向下减速度 > μg（μ=3 ⇒ 3g）零件即从指间滑脱坠落，又被下降的夹爪撞飞。
    0.04m/s 恒速 + 按实测 z 停止——急停减速度 ~4g 量级且接触压痕微小，
    同时消除夹持偏移（零件在指间的高度随运输动态漂 ±13mm）对标称计算的依赖。
    """
    deadline = time.monotonic() + timeout_s
    client.pub_twist(0, 0, vz)
    last = None
    while time.monotonic() < deadline:
        time.sleep(0.06)
        last = client.pose_of(part_name)
        if last is not None and last[2] <= stop_z:
            break
    client.pub_twist(0, 0, HOVER_VZ)
    return last


def run_pick_sequence(client: GzClient, bundle: dict, log) -> dict[str, float]:
    """感知（V0.5 W3 enabled 时）→ home→下降→闭合→提升→平移→放置→张开。

    感知路径：控制目标（aim xy / grasp z）完全来自深度定位，不读零件真值；
    真值仅用于判定（pick_success/position_error/perception_error）——失败是
    真实物理失败。非感知路径保持 W4 语义：真值+注入噪声做控制目标。
    """
    target = bundle["target"]
    place = bundle["place"]
    start_z = bundle.get("gripperStartZ", 0.45)
    grasp_offset = bundle.get("graspOffset", 0.033)
    perception = bundle.get("perception") or {}

    # 位姿流就绪等待（订阅握手）
    for _ in range(30):
        if client.pose_of("gripper"):
            break
        time.sleep(0.5)

    # 目标选择（判定对象）：抓取时刻的实时堆顶件
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
    perception_error_mm: float | None = None

    if perception.get("enabled"):
        # ---- V0.5 W3 感知路径：aim/grasp_z 来自深度定位（含 standby 避遮挡）----
        perceived = _perceive_target(client, bundle, log)
        truth0 = client.pose_of(tgt_name) or part0
        if perceived is None:
            # 感知失败（窗内无点/捕获失败）：真实失败快速收尾，不编造位姿
            client.contacts.reset()
            _move_to(client, (place["x"], place["y"], start_z))
            t1 = client.sim_time()
            return {
                "pick_success": 0.0,
                "cycle_time_s": round(max(0.0, t1 - t0), 3) if t0 >= 0 and t1 >= 0 else -1.0,
                "collision_count": 0.0,
                "perception_failed": 1.0,
            }
        aim_x, aim_y = perceived["x"], perceived["y"]
        grasp_z = perceived["z_top"] + GRASP_TOP_MARGIN
        perception_error_mm = round(
            1000.0 * ((aim_x - truth0[0]) ** 2 + (aim_y - truth0[1]) ** 2) ** 0.5, 3)
        log.info("perception error", perception_error_mm=perception_error_mm,
                 truth=truth0, perceived=(aim_x, aim_y, perceived["z_top"]))
    else:
        # ---- W4 注入路径：真值 + per-run 固定噪声实例做控制目标 ----
        nx, ny, nz = bundle.get("graspNoise", (0.0, 0.0, 0.0))
        live = client.pose_of(tgt_name) or part0
        aim_x, aim_y = live[0] + nx, live[1] + ny
        grasp_z = live[2] + grasp_offset + nz

    # 1) 回 home（感知路径从 standby 平移到 aim 上方；注入路径 xy 取实时位置）
    _move_to(client, (aim_x, aim_y, start_z))
    # 2) 侧向下刀沿 y 轴（W2 第 24 轮定型）：指开合沿 x——沿 y 贴身滑入零件侧带时
    #    x 向间隙仍在，指不碰零件任何面 → 平移精确居中 → 对称力闭合。
    #    （沿 x approach 会被开口侧指面顶住停在差 clearance 处→偏斜抓取→挤飞；
    #      沿 z 下插会被顶面接触顶住停在指底=零件顶面。）
    offs_y = (1.0 if aim_y >= 0 else -1.0) * min(LATERAL_OFFS, 0.09 - abs(aim_y))
    lateral_ok = _move_to(client, (aim_x, aim_y + offs_y, grasp_z))
    approach_ok = _move_to(client, (aim_x, aim_y, grasp_z))
    log.info("descend done", lateral_ok=lateral_ok, approach_ok=approach_ok,
             gripper=client.pose_of("gripper"), part=client.pose_of(tgt_name),
             target_grasp_z=round(grasp_z, 4), lateral_y=round(offs_y, 4),
             aim=(round(aim_x, 4), round(aim_y, 4)))
    if not (lateral_ok and approach_ok):
        # 下刀未到位（定位误差过大被零件顶住等）：真实失败，快速收尾——
        # 跳过闭合/提升/放置（真实机器人也不会闭爪），回 home 结束 cycle。
        # 否则后续每步各吃 25s 超时，失败 run wall 从 ~60s 拖到 ~196s（W4 实测）。
        client.contacts.reset()
        _move_to(client, (aim_x, aim_y, start_z))
        t1 = client.sim_time()
        final = client.pose_of(tgt_name)
        metrics = {
            "pick_success": 0.0,
            "cycle_time_s": round(max(0.0, t1 - t0), 3) if t0 >= 0 and t1 >= 0 else -1.0,
            "collision_count": 0.0,
            "descend_failed": 1.0,
        }
        if perception_error_mm is not None:
            metrics["perception_error_mm"] = perception_error_mm
        if final is not None:
            metrics["position_error_mm"] = round(
                1000.0 * ((final[0] - place["x"]) ** 2 + (final[1] - place["y"]) ** 2) ** 0.5, 3)
            metrics["placed_height_m"] = round(final[2], 4)
        log.info("descend failed, fast-finish cycle", aim=(round(aim_x, 4), round(aim_y, 4)))
        return metrics
    # 3) 渐进夹紧。force 模式：cmd=力值（N），力来自 IR grasp_force_n
    #    （W1-W2 曾误发位置值 0.027 当力（≈0.027N 零力，滑脱根因））。
    #    position 模式（V0.5 W4）：cmd=关节位置（m），从 half_open 斜坡到闭合位
    #    gripJointPos——位置伺服夹持，接触力=伺服刚度×位置误差，无 60N 定值压深。
    time.sleep(0.6)
    client.contacts.reset()  # collision_count 计数窗口：闭合→提升
    force = bundle.get("graspForceN", 40.0)
    half_open = float(bundle.get("halfOpen", 0.05))
    grip_closed = float(bundle.get("gripJointPos", half_open * 0.6))
    if bundle.get("gripMode") == "position":
        for frac in (0.25, 0.5, 0.75, 1.0):
            client.pub_grip(half_open + frac * (grip_closed - half_open))
            time.sleep(0.7)
    else:
        for frac in (0.25, 0.5, 0.75, 1.0):
            client.pub_grip(force * frac)
            time.sleep(0.7)
    time.sleep(1.0)
    # 注：保持力降档（60→15N 减接触储能）实测两难——弹飞仅部分缓解且降档扰动
    # 令部分零件脱夹（pick_success 回归）。全程保持抓取力，弹飞残余归 V0.4
    # （位置控制夹持 / SDF 软接触参数——DART 力控+突释的数值特性）。
    # 4) 提升（回 aim 上方——两条路径的控制目标一致）
    _move_to(client, (aim_x, aim_y, start_z))
    time.sleep(0.5)
    part_lifted = client.pose_of(tgt_name)
    picked = part_lifted is not None and part_lifted[2] > target_z_lift
    collision_count = client.contacts.total()
    log.info("pick check", lifted_z=part_lifted, threshold=target_z_lift, picked=picked,
             collision_count=collision_count)
    # 5) 平移到放置点上方 → 低释放 → 缓脱张开 → 回 home
    # W4 放置优化（轨迹诊断定位两段根因）：①原释放高度零件底悬空 ~35mm 自由落体
    # 弹跳；②-15N 瞬时张爪时指面摩擦把零件沿 x 弹飞 376mm（E00189-91 实测
    # ~370mm 的真因，非"落体弹跳"）。修复：零件底 ~2mm 干涉触地（地面支撑）
    # + 小力渐进脱接触（-1.5/-3/-6N 缓脱后指已离零件，才 -15N 全开）。
    part_half_h = 0.3 * float(target.get("size_m") or 0.04)
    # W4 探针：释放干涉 2mm→8mm（零挤压假设验证——360mm 弹飞与力级/泄压时长
    # 全无关，疑似 2mm 干涉把零件压入地面+指夹中部所致的侧向挤出）
    release_z = round(part_half_h + 0.008 + grasp_offset, 4)
    _move_to(client, (place["x"], place["y"], start_z))
    # W4 闭环触地释放（弹飞根治）：按零件实时位姿分步下降到零件底≈触地
    # （half_h+3mm 内），不按标称 release_z 硬压——刚性夹持下硬压把零件压入
    # 地面（地面接触储能），开指瞬间侧向射出 ~350mm（与夹持力 25/60N、泄压
    # 1.2/3.0s、干涉 2/8mm 全无关——W4 探针矩阵实证；压入 10mm 时重件射出
    # 与指开合同向反向）。触地后零件由地面支撑，开指仅 ≤3mm 自由落差。
    # 两段式释放下降（按真实支撑面触地）：①粗移动单步到零件底 25mm 悬空
    # （硬停发生在高空，向下滑脱被余量吸收）；②低速闭环按零件实测 z 降到
    # 真实静止高度 +2mm（placeSurfaceZ 来自场景真值——地面 plane 在 z=-0.01，
    # 曾按 0 计算致零件悬空 10mm 开指，60N 穿透回弹打飞重件 360mm）。
    surface_z = float(bundle.get("placeSurfaceZ", -0.01))
    rest_z = surface_z + part_half_h
    cur = client.pose_of(tgt_name)
    if cur is not None:
        coarse_gz = round(start_z - (cur[2] - rest_z - 0.025), 4)
        coarse_gz = max(release_z, min(start_z, coarse_gz))
        _move_to(client, (place["x"], place["y"], coarse_gz))
    touchdown = _descend_until(client, tgt_name, rest_z + 0.008)
    touchdown = _descend_until(client, tgt_name, rest_z + 0.002,
                               timeout_s=15.0, vz=-0.02) or touchdown
    log.info("touchdown", part=touchdown, rest_z=round(rest_z, 4),
             gripper=client.pose_of("gripper"))
    # 释放。force 模式（泄压渐进开，0.1s 级轨迹诊断实锤的第三段根因缓解）：
    #   闭合 60N 持续压在接触内积累 penetration 势能，任何开力（哪怕 -1.5N）
    #   松指瞬间 DART 将其弹出 2.4m/s——先零力泄压再小力渐进张开。重零件残余
    #   弹飞（~370mm）= DART 力控+突释数值特性（V0.3 终局保留项，本 W4 根治）。
    # position 模式（V0.5 W4）：cmd 斜坡回 half_open——位置伺服回程无累积法向
    #   力突释，接触分离由伺服位移平滑驱动（无泄压两难）。
    if bundle.get("gripMode") == "position":
        for frac in (0.33, 0.66, 1.0):
            client.pub_grip(grip_closed + frac * (half_open - grip_closed))
            time.sleep(0.6)
        time.sleep(0.5)
    else:
        # W4 泄压时长探针定值：0 力 3.0s——接触弹簧完全卸载（N→0 ⇒ 摩擦→0）
        # 后再开指，开指摩擦冲量 ∫μN dt 最小（1.2s 时残余法向力仍在拖拽，重件 360mm）
        # 释放段全程零件轨迹采样（W4 诊断：两个不同种子同落 0.8405——点采样定位不了击飞时刻）
        release_traj: list[tuple] = []

        def _sample_traj(duration_s: float, step_s: float = 0.2) -> None:
            n_steps = int(duration_s / step_s)
            for _ in range(n_steps):
                time.sleep(step_s)
                p = client.pose_of(tgt_name)
                if p is not None:
                    release_traj.append((round(p[0], 3), round(p[1], 3), round(p[2], 3)))

        # 准静态卸载（W4 终版）：力 60→0 一跳时穿透储能瞬间释放（回弹冲量
        # ∝ 储能，与质量无关——小轻件被甩 508mm；地面摩擦 0.5mg 对 0.1kg 件
        # 仅 0.5N 拦不住）。渐降让接触准静态松弛（指随零件回弹连续跟进），
        # 无突释冲量。总时长 ≈ 原一跳+3s 等待。
        for f in (45.0, 30.0, 18.0, 10.0, 5.0, 2.0, 0.0):
            client.pub_grip(f)
            _sample_traj(0.5)
        for f in (-0.75, -1.5, -3.0, -6.0):
            client.pub_grip(f)
            _sample_traj(0.8)
        _sample_traj(0.5)  # 缓脱后零件已由地面支撑、指-零件接触分离
        client.pub_grip(-15.0)
        _sample_traj(0.8)
        client.pub_grip(0.0)
        _sample_traj(0.5)
        log.info("grip fully open", part=client.pose_of(tgt_name),
                 traj=release_traj)
    # 回退前对准：零件实际落点常偏心（感知/夹持残余 ±20mm），全张指（半开 0.09）
    # 内缘可与零件缘重叠——先横移使基座正对零件（两侧间隙最大化 ~25mm），
    # 再垂直上升（W4 重件 6 策略同值 360mm 的真因：上升时指扫零件顶）
    rested = client.pose_of(tgt_name)
    gp = client.pose_of("gripper")
    if rested is not None and gp is not None:
        _move_to(client, (rested[0], rested[1], gp[2]))  # 纯 XY 居中（保持释放高度）
        log.info("centered over part", part=client.pose_of(tgt_name),
                 gripper=client.pose_of("gripper"))
        _move_to(client, (rested[0], rested[1], start_z))
        log.info("retreated", part=client.pose_of(tgt_name),
                 gripper=client.pose_of("gripper"))
    else:
        _move_to(client, (place["x"], place["y"], start_z))
        log.info("retreated (no part)", part=client.pose_of(tgt_name))
    t1 = client.sim_time()

    final = client.pose_of(tgt_name)
    metrics: dict[str, float] = {
        "pick_success": 1.0 if picked else 0.0,
        "cycle_time_s": round(max(0.0, t1 - t0), 3) if t0 >= 0 and t1 >= 0 else -1.0,
        # 闭合→提升窗口两指 contact sensor 话题的接触条目数（每步每指累计）
        "collision_count": float(collision_count),
    }
    if perception_error_mm is not None:
        metrics["perception_error_mm"] = perception_error_mm
    if final is not None:
        metrics["position_error_mm"] = round(
            1000.0 * ((final[0] - place["x"]) ** 2 + (final[1] - place["y"]) ** 2) ** 0.5, 3)
        metrics["placed_height_m"] = round(final[2], 4)
    return metrics
