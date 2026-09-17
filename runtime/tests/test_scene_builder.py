"""V0.9 场景参数化 v2：确定性 / 参数化 / 默认值兼容（纯函数，不进 gz）。"""

from __future__ import annotations

from roboverify_runtime.sim_adapters.gz.scene_builder import build_scene_bundle


def base_ir() -> dict:
    return {
        "schemaVersion": "0.2.0",
        "id": "sim-test",
        "scene": "bin_picking",
        "robot": {"type": "gantry_gripper"},
        "environment": {"seed": 42, "overrides": {"n_parts": 1, "object_size_mm": 50}},
        "script": {"type": "scripted_pick"},
    }


def test_deterministic_same_ir_same_sdf():
    """复现语义：同 scenario + 同 seed → SDF 与 scenario 回显逐位一致。"""
    a = build_scene_bundle(base_ir())
    b = build_scene_bundle(base_ir())
    assert a["sdf"] == b["sdf"]
    assert a["scenario"] == b["scenario"]


def test_scenario_echo_defaults_match_v1():
    """缺省 scenario：回显值 = 历史硬编码值（行为与 0.1.0 逐位一致）。"""
    sc = build_scene_bundle(base_ir())["scenario"]
    assert sc["bin"]["width_mm"] == 600.0
    assert sc["bin"]["depth_mm"] == 300.0
    assert sc["bin"]["height_m"] == 0.3
    assert sc["bin"]["wall_thickness_mm"] == 20.0
    assert sc["bin"]["center_x"] == 0.5
    assert sc["part_spawn"] == {"y_halfspan": 0.03, "z_min": 0.05, "z_span": 0.12}
    assert sc["place"] == {"x": 1.2, "y": 0.0, "z": 0.05}
    assert sc["ground_z"] == -0.01
    assert sc["seed"] == 42
    assert sc["n_parts"] == 1


def test_place_inside_bin_flips_surface_z():
    """放置点进箱 → place_surface_z = 箱底板顶 + 0.01（W4 场景真值链）。"""
    ir = base_ir()
    ir["environment"]["scenario"] = {
        "bin": {"center_x": 0.6},
        "place": {"x": 0.6, "y": 0.0},
    }
    b = build_scene_bundle(ir)
    assert b["scenario"]["bin"]["center_x"] == 0.6
    assert b["placeSurfaceZ"] == 0.03  # t=0.02 + 0.01
    assert b["sdf"] != build_scene_bundle(base_ir())["sdf"]


def test_grasp_geometry_immune_to_scenario():
    """夹爪/抓取几何是校准过的系统配置——scenario 只改场景，不改抓取参数。"""
    ir = base_ir()
    ir["environment"]["scenario"] = {"place": {"x": 0.3}}
    b = build_scene_bundle(ir)
    base = build_scene_bundle(base_ir())
    for key in ("gripMode", "graspForceN", "gripperStartZ", "halfOpen",
                "graspOffset", "gripJointPos"):
        assert b[key] == base[key], key


def test_env_bin_legacy_path_still_works():
    """Environment IR 旧路径 env['bin'] 继续生效（scenario 优先，缺省回落）。"""
    bundle = build_scene_bundle(base_ir(), environment={"bin": {"width_mm": 800}})
    assert bundle["scenario"]["bin"]["width_mm"] == 800.0
    ir = base_ir()
    ir["environment"]["scenario"] = {"bin": {"width_mm": 500}}
    bundle2 = build_scene_bundle(ir, environment={"bin": {"width_mm": 800}})
    assert bundle2["scenario"]["bin"]["width_mm"] == 500.0  # scenario 覆盖 env
