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


def build_world_sdf(sim_ir: dict, environment: dict | None = None) -> str:
    """Simulation IR（+环境引用数据）→ SDF world 文本。"""
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
    for i in range(n_parts):
        size_m = rng.uniform(0.02, 0.08) if "object_size_mm" not in overrides \
            else overrides["object_size_mm"] / 1000.0
        parts.append(PART_TEMPLATE.format(
            idx=i,
            x=round(0.5 + rng.uniform(-bin_w / 2 + 0.05, bin_w / 2 - 0.05), 4),
            y=round(rng.uniform(-bin_d / 2 + 0.05, bin_d / 2 - 0.05), 4),
            z=round(0.05 + 0.12 * rng.random(), 4),
            roll=round(rng.uniform(-0.3, 0.3), 3),
            pitch=round(rng.uniform(-0.3, 0.3), 3),
            yaw=round(rng.uniform(-3.14, 3.14), 3),
            sx=round(size_m, 4), sy=round(size_m, 4), sz=round(size_m * 0.6, 4),
            mass=round(rng.uniform(0.05, 0.8), 3),
            mu=overrides.get("friction_coeff", 0.5),
        ))

    sensor = (sim_ir.get("sensors") or [{}])[0]
    pose = sensor.get("pose") or {"x": 0.5, "y": 0.0, "z": 0.85, "pitch": 90, "yaw": 0}
    import math

    fov_deg = (sensor.get("params") or {}).get("fov_deg", 87)

    return WORLD_TEMPLATE.format(
        bin_w=round(bin_w, 3), bin_d=round(bin_d, 3), bin_h=bin_h,
        parts="\n".join(parts),
        cam_x=pose.get("x", 0.5), cam_y=pose.get("y", 0.0), cam_z=pose.get("z", 0.85),
        cam_pitch_rad=round(math.radians(-(pose.get("pitch", 90) - 90)), 4),
        cam_yaw_rad=round(math.radians(pose.get("yaw", 0)), 4),
        fov_rad=round(2 * math.atan(math.tan(math.radians(fov_deg) / 2)), 4),
    )
