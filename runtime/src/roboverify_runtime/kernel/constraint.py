"""规则类判定：reach / payload / FOV 覆盖（区间比较，无随机性）。"""

from __future__ import annotations

import math

from . import models_v01 as M
from .snapshot import SystemSnapshot


def required_reach_m(environment: dict | None) -> float | None:
    """覆盖料箱最远角落所需半径：基座偏移 + 料箱对角线/2。"""
    if not environment or not environment.get("bin"):
        return None
    b = environment["bin"]
    w = b.get("width_mm", 0) / 1000.0
    d = b.get("height_mm", 0) / 1000.0  # IR 中 height 为俯视深度
    return M.ROBOT_BASE_OFFSET_M + math.hypot(w, d) / 2.0


def check_reach(snapshot: SystemSnapshot, environment: dict | None) -> dict:
    reach = snapshot.robot_param("reach_mm")
    need = required_reach_m(environment)
    if reach is None or need is None:
        missing = ["robot.reach_mm"] if reach is None else ["environment.bin"]
        return {"status": "UNKNOWN", "missingInputs": missing}
    have = float(reach.value) / 1000.0
    return {
        "status": "PASS" if have >= need else "FAIL",
        "observed": round(have, 3),
        "detail": f"需求可达 {need:.3f}m（含基座偏移 {M.ROBOT_BASE_OFFSET_M}m 假设），机器人 {have:.3f}m",
    }


def check_payload(snapshot: SystemSnapshot, environment: dict | None) -> dict:
    payload = snapshot.robot_param("payload_kg")
    parts = (environment or {}).get("parts") or []
    masses = []
    for p in parts:
        mg = (p.get("mass_g") or {}).get("max")
        if mg:
            masses.append(mg / 1000.0)
    if payload is None or not masses:
        missing = ["robot.payload_kg"] if payload is None else ["environment.parts.mass_g"]
        return {"status": "UNKNOWN", "missingInputs": missing}
    have = float(payload.value)
    need = max(masses)
    return {
        "status": "PASS" if have >= need else "FAIL",
        "observed": have,
        "detail": f"最重零件 {need:.3f}kg vs 负载 {have:.1f}kg（未计夹爪重量，保守项见假设）",
    }


def check_fov(snapshot: SystemSnapshot, environment: dict | None) -> dict:
    bin_ = (environment or {}).get("bin") or {}
    if not snapshot.cameras or not bin_:
        missing = ["system.cameras"] if not snapshot.cameras else ["environment.bin"]
        return {"status": "UNKNOWN", "missingInputs": missing}
    cam = snapshot.cameras[0]
    z = (cam.pose or {}).get("z")
    fov = cam.fov_deg
    if z is None or fov is None:
        missing = ["camera.mountPose.z"] if z is None else ["camera.fov_deg"]
        return {"status": "UNKNOWN", "missingInputs": missing}
    # 俯视相机在高度 z、视场角 fov 下可覆盖宽度
    covered_w = 2.0 * float(z) * math.tan(math.radians(float(fov) / 2.0))
    need_w = bin_.get("width_mm", 0) / 1000.0
    need_d = bin_.get("height_mm", 0) / 1000.0
    ok = covered_w >= max(need_w, need_d)
    return {
        "status": "PASS" if ok else "FAIL",
        "observed": round(covered_w, 3),
        "detail": (f"相机高度 {z}m 视场角 {fov}° 覆盖 {covered_w:.2f}m "
                   f"vs 料箱最大边 {max(need_w, need_d):.2f}m"),
    }
