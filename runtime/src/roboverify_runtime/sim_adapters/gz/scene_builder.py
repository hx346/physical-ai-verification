"""Simulation IR → gz-sim SDF 场景生成（真实可写入 .sdf 的文本）。

范围（V0.1 bin_picking）：地面 + 料箱（盒）+ 随机堆叠零件（按 seed）+ 顶装深度相机。
机器人以简化 6 轴模型盒体占位（URDF 由资产库提供后替换，见 TODO）。
"""

from __future__ import annotations

import random

WORLD_TEMPLATE = """<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="bin_picking">
    <physics name="1ms" type="ignored">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <gravity>0 0 -9.8</gravity>
    <!-- gz-sim systems：缺 Physics 不步进；缺 Sensors 则 rgbd 相机不实例化（2026-09-15 实测抓出） -->
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <!-- 接触事件流（/world/bin_picking/physics/contacts）：夹持判定与碰撞计数的数据源 -->
    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.8 0.8 0.8 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>
    <model name="ground">
      <static>true</static>
      <pose>0 0 -0.01 0 0 0</pose>
      <link name="link">
        <collision name="coll">
          <geometry><plane><normal>0 0 1</normal><size>10 10</size></plane></geometry>
        </collision>
        <visual name="vis">
          <geometry><plane><normal>0 0 1</normal><size>10 10</size></plane></geometry>
        </visual>
      </link>
    </model>
    <model name="bin">
      <static>true</static>
      <pose>0.5 0 0 0 0 0</pose>
      <link name="link">
        <collision name="coll">
          <geometry><box><size>{bin_w} {bin_d} {bin_h}</size></box></geometry>
        </collision>
        <visual name="vis"><geometry><box><size>{bin_w} {bin_d} {bin_h}</size></box></geometry>
          <material><diffuse>0.3 0.4 0.5 1</diffuse></material></visual>
      </link>
    </model>
{parts}
{fingers}
    <model name="camera_mount">
      <static>true</static>
      <pose>{cam_x} {cam_y} {cam_z} 0 {cam_pitch_rad} {cam_yaw_rad}</pose>
      <link name="link">
        <sensor name="rgbd_camera" type="rgbd_camera">
          <update_rate>30</update_rate>
          <topic>camera/rgbd</topic>
          <camera name="front">
            <horizontal_fov>{fov_rad}</horizontal_fov>
            <image><width>1280</width><height>720</height></image>
            <clip><near>0.1</near><far>10</far></clip>
          </camera>
        </sensor>
      </link>
    </model>
  </world>
</sdf>
"""

PART_TEMPLATE = """    <model name="part_{idx}">
      <pose>{x} {y} {z} {roll} {pitch} {yaw}</pose>
      <link name="link">
        <inertial><mass>{mass}</mass></inertial>
        <collision name="coll"><geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
          <surface><friction><ode><mu>{mu}</mu></ode></friction></surface></collision>
        <visual name="vis"><geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
          <material><diffuse>0.75 0.75 0.78 1</diffuse></material></visual>
      </link>
    </model>"""


GRIPPER_TEMPLATE = """    <model name="gripper">
      <pose>{gx} {gy} {gz} 0 0 0</pose>
      <link name="base">
        <inertial><mass>2.0</mass></inertial>
        <collision name="coll"><geometry><box><size>0.08 0.06 0.03</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>0.08 0.06 0.03</size></box></geometry>
          <material><diffuse>0.2 0.2 0.25 1</diffuse></material></visual>
      </link>
      <link name="finger_left">
        <pose>-{half_open} 0 -0.075 0 0 0</pose>
        <inertial><mass>0.2</mass></inertial>
        <collision name="coll">
          <geometry><box><size>0.05 0.012 0.12</size></box></geometry>
          <surface><friction><ode><mu>3.0</mu><mu2>2.8</mu2></ode></friction></surface>
        </collision>
        <visual name="vis"><geometry><box><size>0.05 0.012 0.12</size></box></geometry>
          <material><diffuse>0.85 0.55 0.1 1</diffuse></material></visual>
      </link>
      <link name="finger_right">
        <pose>{half_open} 0 -0.075 0 0 0</pose>
        <inertial><mass>0.2</mass></inertial>
        <collision name="coll">
          <geometry><box><size>0.05 0.012 0.12</size></box></geometry>
          <surface><friction><ode><mu>3.0</mu><mu2>2.8</mu2></ode></friction></surface>
        </collision>
        <visual name="vis"><geometry><box><size>0.05 0.012 0.12</size></box></geometry>
          <material><diffuse>0.85 0.55 0.1 1</diffuse></material></visual>
      </link>
      <joint name="finger_left_joint" type="prismatic">
        <parent>base</parent><child>finger_left</child>
        <axis><xyz>1 0 0</xyz><limit><lower>0</lower><upper>0.06</upper></limit></axis>
      </joint>
      <joint name="finger_right_joint" type="prismatic">
        <parent>base</parent><child>finger_right</child>
        <axis><xyz>-1 0 0</xyz><limit><lower>0</lower><upper>0.06</upper></limit></axis>
      </joint>
      <!-- 整体速度控制（worker 发 /model/gripper/cmd_vel，gz.msgs.Twist）-->
      <plugin filename="gz-sim-velocity-control-system" name="gz::sim::systems::VelocityControl"/>
      <!-- 关节位置控制（model 级）：/model/gripper/finger_*_joint/cmd，gz.msgs.Double -->
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
    </model>"""


def build_scene_bundle(sim_ir: dict, environment: dict | None = None) -> dict:
    """场景束：SDF 文本 + 抓取序列元数据（目标零件/放置点/指间隙）。

    夹爪方案（2026-09-15 定型）：dynamic 两指 prismatic 关节夹爪——
    整体升降走 VelocityControl（/model/gripper/vel_cmd，gz.msgs.Twist），
    指开合走 JointPositionController（/model/gripper/finger_*_joint/cmd，gz.msgs.Double）。
    指面高摩擦挤压零件，提升靠摩擦夹持（DART 求解）；失败即真实失败，
    pick_success 由零件实际位姿判定，不预设。set_pose/pose_cmd 对本场景不生效（已实测排除）。
    """
    import math

    env = environment or {}
    bin_ = env.get("bin") or {"width_mm": 600, "height_mm": 300, "depth_mm": 400}
    bin_w = bin_.get("width_mm", 600) / 1000.0
    bin_d = bin_.get("height_mm", 300) / 1000.0
    bin_h = 0.3

    seed = (sim_ir.get("environment") or {}).get("seed", 42)
    overrides = (sim_ir.get("environment") or {}).get("overrides") or {}
    rng = random.Random(seed)

    n_parts = 24
    parts = []
    part_meta = []
    for i in range(n_parts):
        size_m = rng.uniform(0.02, 0.08) if "object_size_mm" not in overrides \
            else overrides["object_size_mm"] / 1000.0
        x = round(0.5 + rng.uniform(-bin_w / 2 + 0.05, bin_w / 2 - 0.05), 4)
        y = round(rng.uniform(-bin_d / 2 + 0.05, bin_d / 2 - 0.05), 4)
        z = round(0.05 + 0.12 * rng.random(), 4)
        parts.append(PART_TEMPLATE.format(
            idx=i, x=x, y=y, z=z,
            roll=round(rng.uniform(-0.3, 0.3), 3),
            pitch=round(rng.uniform(-0.3, 0.3), 3),
            yaw=round(rng.uniform(-3.14, 3.14), 3),
            sx=round(size_m, 4), sy=round(size_m, 4), sz=round(size_m * 0.6, 4),
            mass=round(rng.uniform(0.05, 0.8), 3),
            mu=overrides.get("friction_coeff", 0.5),
        ))
        part_meta.append({"idx": i, "x": x, "y": y, "z": z, "size_m": round(size_m, 4)})

    # 目标：最高零件（最上层，遮挡/堆叠干扰最小）；放置点：料箱旁空地
    target = max(part_meta, key=lambda p: p["z"])
    place = {"x": 1.2, "y": 0.0, "z": 0.05}

    # 夹爪初始：目标正上方 0.45m，指张开间隙 = 目标宽 + 0.05（关节行程 0.05 封口）
    gap_open = target["size_m"] + 0.05
    gripper_z = 0.45
    fingers = GRIPPER_TEMPLATE.format(
        gx=target["x"], gy=target["y"], gz=gripper_z,
        half_open=round(gap_open / 2, 4))

    sensor = (sim_ir.get("sensors") or [{}])[0]
    pose = sensor.get("pose") or {"x": 0.5, "y": 0.0, "z": 0.85, "pitch": 90, "yaw": 0}
    fov_deg = (sensor.get("params") or {}).get("fov_deg", 87)

    sdf = WORLD_TEMPLATE.format(
        bin_w=round(bin_w, 3), bin_d=round(bin_d, 3), bin_h=bin_h,
        parts="\n".join(parts),
        fingers=fingers,
        cam_x=pose.get("x", 0.5), cam_y=pose.get("y", 0.0), cam_z=pose.get("z", 0.85),
        cam_pitch_rad=round(math.radians(-(pose.get("pitch", 90) - 90)), 4),
        cam_yaw_rad=round(math.radians(pose.get("yaw", 0)), 4),
        fov_rad=round(2 * math.atan(math.tan(math.radians(fov_deg) / 2)), 4),
    )
    half_grip = (target["size_m"] - 0.002) / 2.0  # 闭合半间隙：1mm 挤压量（渐进闭合防弹飞）
    return {
        "sdf": sdf,
        "target": {"name": f"part_{target['idx']}", **{k: target[k] for k in ("x", "y", "z", "size_m")}},
        "place": place,
        "gripperStartZ": gripper_z,
        "halfOpen": round(gap_open / 2, 4),
        "gripJointPos": round(gap_open / 2 - half_grip, 4),  # 关节指令值（闭合）
    }


def build_world_sdf(sim_ir: dict, environment: dict | None = None) -> str:
    """兼容入口：仅返回 SDF 文本（抓取序列用 build_scene_bundle）。"""
    return build_scene_bundle(sim_ir, environment)["sdf"]
