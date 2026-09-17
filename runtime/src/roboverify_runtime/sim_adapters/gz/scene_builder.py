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
    <!-- 接触事件流：Contact system 只发布 link 级 contact sensor 的话题（gz-sim8 源码实证），
         见 GRIPPER_TEMPLATE 指面的 /gripper/finger_*/contact -->
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
{bin}{parts}
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
        <inertial><mass>{mass}</mass><inertia><ixx>{ixx}</ixx><iyy>{iyy}</iyy><izz>{izz}</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
        <collision name="coll"><geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
          <surface><friction><ode><mu>{mu}</mu></ode></friction></surface></collision>
        <visual name="vis"><geometry><box><size>{sx} {sy} {sz}</size></box></geometry>
          <material><diffuse>0.75 0.75 0.78 1</diffuse></material></visual>
      </link>
    </model>"""


BIN_TEMPLATE = """    <model name="bin_floor">
      <static>true</static>
      <pose>{cx} 0 {t} 0 0 0</pose>
      <link name="link">
        <collision name="coll"><geometry><box><size>{bin_w} {bin_d} {t}</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>{bin_w} {bin_d} {t}</size></box></geometry>
          <material><diffuse>0.3 0.4 0.5 1</diffuse></material></visual>
      </link>
    </model>
    <model name="bin_wall_xp">
      <static>true</static>
      <pose>{wall_xp} 0 {wall_z} 0 0 0</pose>
      <link name="link">
        <collision name="coll"><geometry><box><size>{t} {bin_d} {bin_h}</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>{t} {bin_d} {bin_h}</size></box></geometry>
          <material><diffuse>0.35 0.45 0.55 1</diffuse></material></visual>
      </link>
    </model>
    <model name="bin_wall_xn">
      <static>true</static>
      <pose>{wall_xn} 0 {wall_z} 0 0 0</pose>
      <link name="link">
        <collision name="coll"><geometry><box><size>{t} {bin_d} {bin_h}</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>{t} {bin_d} {bin_h}</size></box></geometry>
          <material><diffuse>0.35 0.45 0.55 1</diffuse></material></visual>
      </link>
    </model>
    <model name="bin_wall_yp">
      <static>true</static>
      <pose>{cx} {wall_yp} {wall_z} 0 0 0</pose>
      <link name="link">
        <collision name="coll"><geometry><box><size>{inner_w} {t} {bin_h}</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>{inner_w} {t} {bin_h}</size></box></geometry>
          <material><diffuse>0.35 0.45 0.55 1</diffuse></material></visual>
      </link>
    </model>
    <model name="bin_wall_yn">
      <static>true</static>
      <pose>{cx} {wall_yn} {wall_z} 0 0 0</pose>
      <link name="link">
        <collision name="coll"><geometry><box><size>{inner_w} {t} {bin_h}</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>{inner_w} {t} {bin_h}</size></box></geometry>
          <material><diffuse>0.35 0.45 0.55 1</diffuse></material></visual>
      </link>
    </model>
"""


GRIPPER_TEMPLATE = """    <model name="gripper">
      <pose>{gx} {gy} {gz} 0 0 0</pose>
      <link name="base">
        <!-- 龙门架重力补偿（2026-09-15 W2 终局）：dynamic 夹爪无指令即自由坠落，
             0.3s 撞 bin 姿态歪斜且无姿态控制不可修复；link 级关重力=顶装龙门语义，
             零速指令精确悬停（model 级 <gravity> 无效，实测）。零件重力照常。 -->
        <gravity>0</gravity>
        <inertial><mass>2.0</mass><inertia><ixx>7.5e-4</ixx><iyy>1.217e-3</iyy><izz>1.667e-3</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
        <collision name="coll"><geometry><box><size>0.08 0.06 0.03</size></box></geometry></collision>
        <visual name="vis"><geometry><box><size>0.08 0.06 0.03</size></box></geometry>
          <material><diffuse>0.2 0.2 0.25 1</diffuse></material></visual>
      </link>
      <link name="finger_left">
        <gravity>0</gravity>
        <pose>-{half_open} 0 {finger_pz} 0 0 0</pose>
        <inertial><mass>0.2</mass><inertia><ixx>9.07e-6</ixx><iyy>4.83e-5</iyy><izz>4.41e-5</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
        <collision name="coll">
          <geometry><box><size>0.05 0.012 {finger_len}</size></box></geometry>
          <surface><friction><ode><mu>3.0</mu><mu2>2.8</mu2></ode></friction></surface>
        </collision>
        <visual name="vis"><geometry><box><size>0.05 0.012 {finger_len}</size></box></geometry>
          <material><diffuse>0.85 0.55 0.1 1</diffuse></material></visual>
        <sensor name="contacts" type="contact">
          <always_on>true</always_on>
          <update_rate>100</update_rate>
          <contact><collision>coll</collision><topic>/gripper/finger_left/contact</topic></contact>
        </sensor>
      </link>
      <link name="finger_right">
        <gravity>0</gravity>
        <pose>{half_open} 0 {finger_pz} 0 0 0</pose>
        <inertial><mass>0.2</mass><inertia><ixx>9.07e-6</ixx><iyy>4.83e-5</iyy><izz>4.41e-5</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>
        <collision name="coll">
          <geometry><box><size>0.05 0.012 {finger_len}</size></box></geometry>
          <surface><friction><ode><mu>3.0</mu><mu2>2.8</mu2></ode></friction></surface>
        </collision>
        <visual name="vis"><geometry><box><size>0.05 0.012 {finger_len}</size></box></geometry>
          <material><diffuse>0.85 0.55 0.1 1</diffuse></material></visual>
        <sensor name="contacts" type="contact">
          <always_on>true</always_on>
          <update_rate>100</update_rate>
          <contact><collision>coll</collision><topic>/gripper/finger_right/contact</topic></contact>
        </sensor>
      </link>
      <joint name="finger_left_joint" type="prismatic">
        <parent>base</parent><child>finger_left</child>
        <axis><xyz>1 0 0</xyz><limit><lower>0</lower><upper>{lim}</upper></limit></axis>
      </joint>
      <joint name="finger_right_joint" type="prismatic">
        <parent>base</parent><child>finger_right</child>
        <axis><xyz>-1 0 0</xyz><limit><lower>0</lower><upper>{lim}</upper></limit></axis>
      </joint>
      <!-- 整体速度控制（worker 发 /model/gripper/cmd_vel，gz.msgs.Twist）-->
      <plugin filename="gz-sim-velocity-control-system" name="gz::sim::systems::VelocityControl"/>
      <!-- 关节控制（model 级）：/model/gripper/finger_*_joint/cmd，gz.msgs.Double。
           V0.5 W4 双模式：use_force_commands=true（cmd=力 N，W1-W3 定型）/
           false（cmd=关节位置 m，位置伺服夹持——释放无累积法向力突释，弹飞根治候选） -->
      <plugin filename="gz-sim-joint-position-controller-system"
              name="gz::sim::systems::JointPositionController">
        <joint_name>finger_left_joint</joint_name>
        <use_force_commands>{use_force}</use_force_commands>
        <topic>/model/gripper/finger_left_joint/cmd</topic>
      </plugin>
      <plugin filename="gz-sim-joint-position-controller-system"
              name="gz::sim::systems::JointPositionController">
        <joint_name>finger_right_joint</joint_name>
        <use_force_commands>{use_force}</use_force_commands>
        <topic>/model/gripper/finger_right_joint/cmd</topic>
      </plugin>
    </model>"""


def build_scene_bundle(sim_ir: dict, environment: dict | None = None) -> dict:
    """场景束：SDF 文本 + 抓取序列元数据（目标零件/放置点/指间隙）。

    夹爪方案（2026-09-15 定型）：dynamic 两指 prismatic 关节夹爪——
    整体升降走 VelocityControl（/model/gripper/cmd_vel，gz.msgs.Twist），
    指开合走 JointPositionController（/model/gripper/finger_*_joint/cmd，gz.msgs.Double）。
    指面高摩擦挤压零件，提升靠摩擦夹持（DART 求解）；失败即真实失败，
    pick_success 由零件实际位姿判定，不预设。set_pose/pose_cmd 对本场景不生效（已实测排除）。

    W2 终局修正（2026-09-15 碰撞单变量实验，deploy/sim/collision_probe.py）：
    ① 所有 link 显式 <inertia>——缺省时 SDF 默认单位阵（比真实值大 ~4 个数量级），
      DART LCP 病态致接触互踢弹跳（原"接触求解失效"假设被证伪，接触检测从未缺失）；
    ② 空心料箱（原实心箱让零件生成在固体内部，深穿透弹射=warmup 弹飞根因）；
    ③ 指间隙 +0.06 留 5mm 净空（原 +0.05 零间隙贴面）；
    ④ 指面 contact sensor（/gripper/finger_*/contact）= collision_count 数据源
      （gz-sim8 Contact system 只发布 contact sensor 话题，源码实证）。
    """
    import math

    env = environment or {}
    # V0.9 场景参数化 v2：scenario 块（simulation IR environment.scenario，schema 0.2.0）。
    # 只参数化场景级自由度（箱体/零件分布/放置点），默认值 = 历史硬编码值——
    # 不传 scenario 时与 v1 行为逐位一致（W4 回归基线不破坏）。夹爪/抓取几何是
    # 校准过的系统配置（W2/W4），不作为场景参数，但全量回显进 scenario echo
    # 供复现审计。env["bin"]（Environment IR 旧路径）保留，scenario 优先。
    scenario = ((sim_ir.get("environment") or {}).get("scenario") or {})
    sc_bin = scenario.get("bin") or {}
    bin_ = env.get("bin") or {}
    bin_w = float(sc_bin.get("width_mm", bin_.get("width_mm", 600))) / 1000.0
    bin_d = float(sc_bin.get("depth_mm", bin_.get("height_mm", 300))) / 1000.0
    bin_h = float(sc_bin.get("height_m", 0.3))
    bin_cx = float(sc_bin.get("center_x", 0.5))
    sc_spawn = scenario.get("part_spawn") or {}
    spawn_y_halfspan = float(sc_spawn.get("y_halfspan", 0.03))
    spawn_z_min = float(sc_spawn.get("z_min", 0.05))
    spawn_z_span = float(sc_spawn.get("z_span", 0.12))
    sc_place = scenario.get("place") or {}
    place_x = float(sc_place.get("x", 1.2))
    place_y = float(sc_place.get("y", 0.0))

    # 空心料箱（五面：底板 + 四壁）——W2 实心箱让零件生成在固体内部，
    # DART 深穿透弹射是"warmup 零件弹飞 0.7m"根因之一
    t = float(sc_bin.get("wall_thickness_mm", 20)) / 1000.0  # 板厚（默认 20mm）
    wx = bin_w / 2 - t / 2
    wy = bin_d / 2 - t / 2
    wall_z = round(t + bin_h / 2, 4)
    bin_sdf = BIN_TEMPLATE.format(
        bin_w=round(bin_w, 3), bin_d=round(bin_d, 3), bin_h=bin_h, t=t,
        wall_xp=round(bin_cx + wx, 4), wall_xn=round(bin_cx - wx, 4),
        wall_yp=round(wy, 4), wall_yn=round(-wy, 4), wall_z=wall_z,
        inner_w=round(bin_w - 2 * t, 3), cx=bin_cx)

    seed = (sim_ir.get("environment") or {}).get("seed", 42)
    overrides = (sim_ir.get("environment") or {}).get("overrides") or {}
    rng = random.Random(seed)

    # 零件数可由 IR 覆盖：W2 里程碑=单件箱内抓取（物理验证）；密集堆抓取需
    # 感知+规划（rgbd 相机已就位），归 V0.4——24 件盲抓实测会被闭合扰动压沉目标
    n_parts = int(overrides.get("n_parts", 24))
    parts = []
    part_meta = []
    for i in range(n_parts):
        size_m = rng.uniform(0.02, 0.08) if "object_size_mm" not in overrides \
            else overrides["object_size_mm"] / 1000.0
        # 生成边距按夹爪足印预算：半开(size/2+0.05) + 指 x 半厚 0.025——
        # 否则贴壁零件会让下降的指插进箱壁（W2 第 16 轮实测：指-壁重叠 19mm 卡死）
        clear = size_m / 2 + 0.075
        x = round(bin_cx + rng.uniform(-(bin_w / 2 - t - clear), bin_w / 2 - t - clear), 4)
        # y 向收紧（默认 ±0.03）：抓取序列沿 y 侧向下刀需箱内偏位空间（|y|+0.05 偏位 ≤ 0.09）
        y = round(rng.uniform(-spawn_y_halfspan, spawn_y_halfspan), 4)
        z = round(spawn_z_min + spawn_z_span * rng.random(), 4)
        mass = round(overrides.get("part_mass_kg", rng.uniform(0.05, 0.8)), 3)
        s, sz_m = round(size_m, 4), round(size_m * 0.6, 4)
        parts.append(PART_TEMPLATE.format(
            idx=i, x=x, y=y, z=z,
            # 平放生成（roll=pitch=0，yaw 随机）：倾斜姿态的横向轮廓会超出指间隙
            # （W2 第 17 轮实测：指落在倾斜零件肩部，差 2.4cm 不收敛）；
            # 随机姿态/倾斜件抓取归 V0.4 感知规划
            roll=0, pitch=0,
            yaw=round(rng.uniform(-3.14, 3.14), 3),
            sx=s, sy=s, sz=sz_m,
            mass=mass,
            ixx=f"{mass / 12 * (s * s + sz_m * sz_m):.3e}",
            iyy=f"{mass / 12 * (s * s + sz_m * sz_m):.3e}",
            izz=f"{mass / 6 * (s * s):.3e}",
            mu=overrides.get("friction_coeff", 0.5),
        ))
        part_meta.append({"idx": i, "x": x, "y": y, "z": z, "size_m": round(size_m, 4)})

    # 目标：最高零件（最上层，遮挡/堆叠干扰最小）；放置点：料箱旁空地（默认）
    target = max(part_meta, key=lambda p: p["z"])
    place = {"x": place_x, "y": place_y, "z": 0.05}
    # 放置面支撑高度（V0.5 W4 弹飞根治的关键场景事实）：地面 plane 在 z=-0.01
    # （非 0！），箱内底板顶 t+0.01——零件真实静止 z = 支撑面 + 半高。放置点在
    # 箱外空地 → -0.01。释放闭环按此触地，否则零件悬空 ~10mm 开指，60N
    # 穿透回弹直接把重件打飞 360mm（六策略同值的真因）。
    in_bin = (abs(place["x"] - bin_cx) <= bin_w / 2) and (abs(place["y"]) <= bin_d / 2)
    place_surface_z = (t + 0.01) if in_bin else -0.01

    # 夹爪初始：目标正上方 0.45m，指间隙 = 目标宽 + 0.10（下降通道净空——
    # W2 第 19 轮实测：DART 接触 margin ~5mm 内即生效，指贴零件顶角 2.6mm 就会
    # 被接触力顶住无法下降；+0.10 让指离角点 2cm+，闭合时才侧向接触）
    gap_open = target["size_m"] + 0.10  # gap_margin=0.10（W2 第 19 轮校准，系统配置非场景参数）
    gripper_z = 0.45
    half_open_v = round(gap_open / 2, 4)
    # 指长 0.02（约零件半高）：抓上半侧——指底高于支撑面，不插箱底/不撞堆下层
    # （W2 第 11 轮教训：指长 0.12 下降后指底穿透箱底板 z=-0.023，接触全为指-箱底互撞）
    finger_len = 0.02
    finger_pz = -0.03
    # V0.5 W4：夹持模式（script.params.grasp_control）；position = 关节位置伺服
    grip_mode = str(((sim_ir.get("script") or {}).get("params") or {})
                    .get("grasp_control", "force")).lower()
    use_force = "true" if grip_mode != "position" else "false"
    fingers = GRIPPER_TEMPLATE.format(
        gx=target["x"], gy=target["y"], gz=gripper_z,
        half_open=half_open_v, lim=round(half_open_v - 0.001, 4),
        finger_len=finger_len, finger_pz=finger_pz, use_force=use_force)

    sensor = (sim_ir.get("sensors") or [{}])[0]
    pose = sensor.get("pose") or {"x": 0.5, "y": 0.0, "z": 0.85, "pitch": 90, "yaw": 0}
    fov_deg = (sensor.get("params") or {}).get("fov_deg", 87)

    cam_x = pose.get("x", 0.5)
    cam_y = pose.get("y", 0.0)
    cam_z = pose.get("z", 0.85)
    cam_pitch_rad = round(math.radians(-(pose.get("pitch", 90) - 90)), 4)
    fov_rad = round(2 * math.atan(math.tan(math.radians(fov_deg) / 2)), 4)

    sdf = WORLD_TEMPLATE.format(
        bin=bin_sdf,
        parts="\n".join(parts),
        fingers=fingers,
        cam_x=cam_x, cam_y=cam_y, cam_z=cam_z,
        cam_pitch_rad=cam_pitch_rad,
        cam_yaw_rad=round(math.radians(pose.get("yaw", 0)), 4),
        fov_rad=fov_rad,
    )
    half_grip = (target["size_m"] - 0.002) / 2.0  # 闭合半间隙：1mm 挤压量
    grasp_force_n = float(((sim_ir.get("script") or {}).get("params") or {}).get("grasp_force_n", 40))
    # W4 实验引擎：感知定位误差实例（per-run 采样后经 overrides 传入；默认零噪声）
    noise_xyz = overrides.get("graspNoiseXYZ") or (0.0, 0.0, 0.0)

    # V0.5 W3 感知链配置：enabled 时序列走深度定位（控制目标不读真值）。
    # v0 仅支持顶视相机（rpy y=+90°，光轴 -Z）——反投影几何按此约定（见
    # perception/depth_localize.py）；非顶视配置 fail-fast，不静默给错几何。
    perception_cfg = None
    perception_ir = sim_ir.get("perception") or {}
    if perception_ir.get("enabled"):
        if abs(cam_pitch_rad - math.pi / 2) > 0.01:
            raise ValueError(
                "perception v0 仅支持顶视相机（IR sensor pose pitch=0）；"
                f"当前 cam_pitch_rad={cam_pitch_rad}")
        from ...perception import default_workspace, intrinsics_from_fov

        perception_cfg = {
            "enabled": True,
            "topic": perception_ir.get("topic", "/camera/rgbd/depth_image"),
            "depth_noise_mm": float(perception_ir.get("depth_noise_mm", 0.0)),
            "rng_seed": int(perception_ir.get("rng_seed", seed * 1009 + 17)),
            "camera": {**intrinsics_from_fov(1280, 720, fov_rad),
                       "x": cam_x, "y": cam_y, "z": cam_z},
            "workspace": default_workspace(0.5, bin_w, bin_d),
        }

    # V0.9 场景参数化 v2：resolved scenario 全量回显——复现记录
    # （同 scenario + 同 seed → SDF 逐位一致；gz 物理轨迹非位级确定已如实记录，
    # 复现语义 = 参数逐位一致，非轨迹一致）。固定几何（夹爪/抓取/地面）是
    # 系统配置与世界常量，一并回显供审计，但不随 scenario 参数化。
    scenario_echo = {
        "schema_version": "0.1.0",
        "bin": {"width_mm": round(bin_w * 1000, 1), "depth_mm": round(bin_d * 1000, 1),
                "height_m": bin_h, "wall_thickness_mm": round(t * 1000, 1),
                "center_x": bin_cx},
        "part_spawn": {"y_halfspan": spawn_y_halfspan,
                       "z_min": spawn_z_min, "z_span": spawn_z_span},
        "place": {"x": place_x, "y": place_y, "z": 0.05},
        "ground_z": -0.01,
        "place_surface_z": round(place_surface_z, 4),
        "seed": seed,
        "overrides": overrides,
        "n_parts": n_parts,
        "fixed_gripper": {"gripper_z": gripper_z, "gap_margin": 0.10,
                          "finger_len": finger_len, "finger_pz": finger_pz,
                          "grasp_offset_base": 0.027},
        "camera": {"x": cam_x, "y": cam_y, "z": cam_z,
                   "pitch": pose.get("pitch", 90), "yaw": pose.get("yaw", 0),
                   "fov_deg": fov_deg},
    }

    return {
        "scenario": scenario_echo,
        "placeSurfaceZ": round(place_surface_z, 4),
        "gripMode": "position" if grip_mode == "position" else "force",
        "perception": perception_cfg,
        "graspNoise": (float(noise_xyz[0]), float(noise_xyz[1]), float(noise_xyz[2])),
        "graspForceN": grasp_force_n,
        "sdf": sdf,
        "target": {"name": f"part_{target['idx']}", **{k: target[k] for k in ("x", "y", "z", "size_m")}},
        "place": place,
        "gripperStartZ": gripper_z,
        "halfOpen": round(gap_open / 2, 4),
        # base z 与零件中心差 = base 半高 0.015 + margin 0.006 + 零件半高 0.3s：
        # 指跨（base-0.04..base-0.02）对准零件上半侧面，base 底高于零件顶 margin 以上
        "graspOffset": round(0.027 + 0.3 * target["size_m"], 4),
        "partNames": [f"part_{m['idx']}" for m in part_meta],
        "gripJointPos": round(gap_open / 2 - half_grip, 4),  # 关节指令值（闭合）
    }


def build_world_sdf(sim_ir: dict, environment: dict | None = None) -> str:
    """兼容入口：仅返回 SDF 文本（抓取序列用 build_scene_bundle）。"""
    return build_scene_bundle(sim_ir, environment)["sdf"]
