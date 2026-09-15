"""W2 碰撞有效性单变量实验（dev-plan §10 V0.3-W2 终局，2026-09-15）。

待证假设：DART 接触求解在"力控 prismatic 指夹持 dynamic 盒零件"构型下失效
（W2 十轮诊断实见：指穿越零件空间而零件不动）。

实验设计（单变量纪律）：最小场景剔除一切干扰——
  - 零 g（零件悬浮在指间，无坠落/支撑干扰）
  - base 经 fixed joint 焊死到 world（无 base 运动、无 warmup 坠落）
  - 单零件、无 bin、无堆叠、无相机
  - 指与零件留 10mm 初始间隙（生产场景是零间隙贴面，会混入摩擦拖拽变量）
唯一变量 = 指闭合力。观测通道（全部真实测量，不预设结论）：
  - /world/probe/dynamic_pose/info：指 link 局部 x（=关节 q 的直接读数）+ 零件世界位姿
  - /world/probe/physics/contacts：接触对/法向力时间线

判定：
  - 指停在零件表面（link x ≈ ±0.05，内侧面 ±0.025）→ 接触响应存在
  - 指到达中缝（link x → ±0.001）且零件未动 → 接触失效（复现生产症状）
  - 两者之间的中间态 → 按数据说话（穿透深度/接触力定量记录）

变体：baseline（生产同构：缺省惯量=单位阵、ode 摩擦、dart）
      inertia（显式盒真实惯量）
      bullet（inertia + 引擎换 bullet）
      iters（inertia + dart solver iters 调大）
用法（容器内）：python3 collision_probe.py --variant baseline [--force 60]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

WORLD_NAME = "probe"
POSE_TOPIC = f"/world/{WORLD_NAME}/dynamic_pose/info"
# gz-sim8 Contact system 数据源=link 级 contact sensor（源码 Contact.cc 实证：
# 无 sensor 则无发布；/world/*/physics/contacts 话题不存在）
CONTACT_TOPICS = ["/gripper/finger_left/contact", "/gripper/finger_right/contact"]
HALF_OPEN = 0.06          # 指初始半间隙（内侧面 ±0.035，与零件面 ±0.025 留 10mm）
FINGER_X_HALF = 0.025     # 指 x 向半厚（0.05/2）
PART_HALF = 0.025         # 零件 x 向半宽（0.05/2）

WORLD_TEMPLATE = """<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="probe">
    <physics name="1ms" type="{engine}">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>{solver_block}
    </physics>
    <gravity>0 0 0</gravity>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>
    <light type="directional" name="sun">
      <pose>0 0 10 0 0 0</pose><direction>-0.5 0.1 -0.9</direction>
    </light>
    <model name="ground">
      <static>true</static>
      <pose>0 0 -0.01 0 0 0</pose>
      <link name="link">
        <collision name="coll"><geometry><plane><normal>0 0 1</normal><size>10 10</size></plane></geometry></collision>
      </link>
    </model>
    <model name="part_0">
      <pose>0 0 0.235 0 0 0</pose>
      <link name="link">
        {part_inertial}
        <collision name="coll"><geometry><box><size>0.05 0.05 0.03</size></box></geometry>
          <surface><friction><ode><mu>0.5</mu></ode></friction></surface></collision>
      </link>
    </model>
    <model name="gripper">
      <pose>0 0 0.31 0 0 0</pose>
      <link name="base">
        {base_inertial}
        <collision name="coll"><geometry><box><size>0.08 0.06 0.03</size></box></geometry></collision>
      </link>
      <link name="finger_left">
        <pose>-{half_open} 0 -0.075 0 0 0</pose>
        {finger_inertial}
        <collision name="coll">
          <geometry><box><size>0.05 0.012 0.12</size></box></geometry>
          <surface><friction><ode><mu>3.0</mu><mu2>2.8</mu2></ode></friction></surface>
        </collision>
        <sensor name="contacts" type="contact">
          <always_on>true</always_on>
          <update_rate>100</update_rate>
          <contact><collision>coll</collision><topic>/gripper/finger_left/contact</topic></contact>
        </sensor>
      </link>
      <link name="finger_right">
        <pose>{half_open} 0 -0.075 0 0 0</pose>
        {finger_inertial}
        <collision name="coll">
          <geometry><box><size>0.05 0.012 0.12</size></box></geometry>
          <surface><friction><ode><mu>3.0</mu><mu2>2.8</mu2></ode></friction></surface>
        </collision>
        <sensor name="contacts" type="contact">
          <always_on>true</always_on>
          <update_rate>100</update_rate>
          <contact><collision>coll</collision><topic>/gripper/finger_right/contact</topic></contact>
        </sensor>
      </link>
      <joint name="weld" type="fixed"><parent>world</parent><child>base</child></joint>
      <joint name="finger_left_joint" type="prismatic">
        <parent>base</parent><child>finger_left</child>
        <axis><xyz>1 0 0</xyz><limit><lower>0</lower><upper>0.059</upper></limit></axis>
      </joint>
      <joint name="finger_right_joint" type="prismatic">
        <parent>base</parent><child>finger_right</child>
        <axis><xyz>-1 0 0</xyz><limit><lower>0</lower><upper>0.059</upper></limit></axis>
      </joint>
      <plugin filename="gz-sim-joint-position-controller-system" name="gz::sim::systems::JointPositionController">
        <joint_name>finger_left_joint</joint_name>
        <use_force_commands>true</use_force_commands>
        <topic>/model/gripper/finger_left_joint/cmd</topic>
      </plugin>
      <plugin filename="gz-sim-joint-position-controller-system" name="gz::sim::systems::JointPositionController">
        <joint_name>finger_right_joint</joint_name>
        <use_force_commands>true</use_force_commands>
        <topic>/model/gripper/finger_right_joint/cmd</topic>
      </plugin>
    </model>
  </world>
</sdf>
"""

# 缺省惯量（生产同构）：<inertia> 缺省 = 单位阵——物理上失真（0.2kg 指 vs 1 kg·m² 转动惯量）
INERTIAL_DEFAULT = "<inertial><mass>{m}</mass></inertial>"
# 显式真实盒惯量：I = m/12·(b²+c²) 等
INERTIAL_BOX = ("<inertial><mass>{m}</mass><inertia>"
                "<ixx>{ixx}</ixx><iyy>{iyy}</iyy><izz>{izz}</izz>"
                "<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>")

_NAME_RE = re.compile(r'name:\s*"([^"]+)"')
_POS_RE = re.compile(r"position\s*\{([^}]*)\}")
_AXIS_RE = re.compile(r"\b([xyz]):\s*([-\d.eE+]+)")


def _parse_vec(inner: str) -> tuple[float, float, float]:
    """protobuf 文本格式省略零值字段（实见 position { z: 0.235 }），逐轴可选解析。"""
    axes = dict(_AXIS_RE.findall(inner))
    return (float(axes.get("x", 0.0)), float(axes.get("y", 0.0)),
            float(axes.get("z", 0.0)))


class PoseStreamer:
    """复用 W2 定型的流式位姿订阅（dynamic_pose/info）。"""

    def __init__(self) -> None:
        self._poses: dict[str, tuple[float, float, float]] = {}
        self._buf = ""
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            ["gz", "topic", "-e", "-t", POSE_TOPIC],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        threading.Thread(target=self._loop, daemon=True).start()

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
        except Exception:
            pass

    def pose_of(self, name: str) -> tuple[float, float, float] | None:
        with self._lock:
            return self._poses.get(name)

    def close(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class ContactStreamer:
    """两指 contact sensor 话题流式统计：接触条目计数 + 接触对 + 最近 wrench。"""

    def __init__(self, topics: list[str]) -> None:
        self.total = 0
        self.pairs: dict[tuple[str, str], int] = {}
        self.last_force: tuple[float, float, float] | None = None
        self._lock = threading.Lock()
        self._procs = []
        for topic in topics:
            proc = subprocess.Popen(
                ["gz", "topic", "-e", "-t", topic],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            self._procs.append(proc)
            threading.Thread(target=self._loop, args=(proc,), daemon=True).start()

    def _loop(self, proc) -> None:
        buf = ""
        try:
            while True:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                buf = (buf + chunk)[-262144:]
                blocks = buf.split("contact {")[1:]
                for block in blocks:
                    if "}" not in block:
                        continue  # 尾部残块，等下一批
                    with self._lock:
                        self.total += 1
                        names = _NAME_RE.findall(block)
                        pair = (names[0] if len(names) > 0 else "?",
                                names[1] if len(names) > 1 else "?")
                        self.pairs[pair] = self.pairs.get(pair, 0) + 1
                        m_f = re.search(r"body_1_force\s*\{([^}]*)\}", block)
                        if m_f:
                            self.last_force = _parse_vec(m_f.group(1))
        except Exception:
            pass

    def snapshot(self) -> tuple[int, dict, tuple | None]:
        with self._lock:
            return self.total, dict(self.pairs), self.last_force

    def close(self) -> None:
        for proc in self._procs:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


def build_world(variant: str) -> str:
    explicit = variant in ("inertia", "bullet", "iters")
    finger_inertial = (INERTIAL_BOX.format(m=0.2, ixx="2.424e-4", iyy="2.817e-4", izz="4.407e-5")
                       if explicit else INERTIAL_DEFAULT.format(m=0.2))
    part_inertial = (INERTIAL_BOX.format(m=0.3, ixx="8.5e-5", iyy="8.5e-5", izz="1.25e-4")
                     if explicit else INERTIAL_DEFAULT.format(m=0.3))
    base_inertial = (INERTIAL_BOX.format(m=2.0, ixx="7.5e-4", iyy="1.217e-3", izz="1.667e-3")
                     if explicit else INERTIAL_DEFAULT.format(m=2.0))
    engine = "bullet" if variant == "bullet" else "ignored"
    solver_block = "\n      <solver><iters>200</iters></solver>" if variant == "iters" else ""
    return WORLD_TEMPLATE.format(
        engine=engine, solver_block=solver_block, half_open=f"{HALF_OPEN}",
        finger_inertial=finger_inertial, part_inertial=part_inertial,
        base_inertial=base_inertial)


def gz(*args: str, timeout_s: float = 8.0) -> str:
    try:
        proc = subprocess.run(["gz", *args], capture_output=True, text=True,
                              timeout=timeout_s)
        return proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="baseline",
                    choices=["baseline", "inertia", "bullet", "iters"])
    ap.add_argument("--force", type=float, default=60.0)
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--hold", type=float, default=4.0)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="rv-probe-") as tmp:
        world = Path(tmp) / "probe.sdf"
        world.write_text(build_world(args.variant), encoding="utf-8")
        server = subprocess.Popen(
            ["gz", "sim", "-s", "-r", "--iterations", str(10 ** 9), str(world)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # 订阅器必须在 server 话题就绪后创建：gz topic -e 对不存在话题会立即退出
        # （生产序列因悬停轰炸天然延后 ~7s 未踩到；容器手动实测确认根因）
        time.sleep(3.0)
        poses = PoseStreamer()
        contacts = ContactStreamer(CONTACT_TOPICS)
        try:
            # 位姿流就绪等待（订阅握手）
            ready = False
            for _ in range(30):
                if poses.pose_of("finger_left") is not None:
                    ready = True
                    break
                time.sleep(0.5)
            print(f"[probe] variant={args.variant} pose_stream_ready={ready}")
            if not ready:
                print("[probe] FAIL: 位姿流未就绪（gz 未起或话题缺失）")
                return 2

            time.sleep(args.settle)
            fl0 = poses.pose_of("finger_left")[0]
            fr0 = poses.pose_of("finger_right")[0]
            p0 = poses.pose_of("part_0")
            print(f"[probe] t0: fL_x={fl0:+.4f} fR_x={fr0:+.4f} part={p0}")

            # 渐进闭合（与生产序列一致：25/50/75/100% 力）
            t_start = time.monotonic()
            for frac in (0.25, 0.5, 0.75, 1.0):
                for side in ("left", "right"):
                    gz("topic", "-t", f"/model/gripper/finger_{side}_joint/cmd",
                       "--msgtype", "gz.msgs.Double", "-p", f"data: {args.force * frac}",
                       "--num", "1")
                time.sleep(0.7)

            end = time.monotonic() + args.hold
            while time.monotonic() < end:
                time.sleep(0.5)
                fl = poses.pose_of("finger_left")
                fr = poses.pose_of("finger_right")
                part = poses.pose_of("part_0")
                n, pairs, last_f = contacts.snapshot()
                top_pair = max(pairs.items(), key=lambda kv: kv[1])[0] if pairs else None
                print(f"[probe] t=+{time.monotonic() - t_start:4.1f}s "
                      f"fL_x={fl[0]:+.4f} fR_x={fr[0]:+.4f} part={part} "
                      f"contacts={n} top={top_pair} F={last_f}")

            # 终局判定
            fl = poses.pose_of("finger_left")[0]
            fr = poses.pose_of("finger_right")[0]
            part = poses.pose_of("part_0")
            n, pairs, _ = contacts.snapshot()
            inner_left = fl + FINGER_X_HALF   # 左指内侧面位置
            inner_right = fr - FINGER_X_HALF
            print("\n[probe] ===== VERDICT =====")
            print(f"[probe] finger inner faces: L={inner_left:+.4f} R={inner_right:+.4f} "
                  f"(零件面应在 ±{PART_HALF})")
            print(f"[probe] part final={part} start={p0}")
            print(f"[probe] contacts total={n} pairs={pairs}")
            stopped = abs(inner_left + PART_HALF) < 0.003 and abs(inner_right - PART_HALF) < 0.003
            penetrated = abs(inner_left) < 0.005 or abs(inner_right) < 0.005
            if stopped:
                print("[probe] 结论：指停在零件表面 → 接触响应存在")
            elif penetrated:
                print("[probe] 结论：指穿透到中缝且零件未动 → 接触失效（复现生产症状）")
            else:
                print(f"[probe] 结论：中间态（穿透 {-inner_left - PART_HALF:+.4f}m），按上述定量数据判定")
            return 0
        finally:
            poses.close()
            contacts.close()
            server.terminate()
            try:
                out, _ = server.communicate(timeout=20)
                tail = (out or "")[-2500:]
                if tail.strip():
                    print("\n[probe] --- gz server output tail ---\n" + tail)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    sys.exit(main())
