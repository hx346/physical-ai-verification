"""指标分发与需求判定入口：Requirement IR × SystemSnapshot → VerdictItem。

判定语义：PASS / FAIL / UNKNOWN；UNKNOWN 是合法结论（输入缺失或模型缺失时），
禁止编造。所有假设显式列出并带 provenance（ADR-0004）。
"""

from __future__ import annotations

import math

from . import KERNEL_VERSION
from . import models_v01 as M
from .constraint import check_fov, check_payload, check_reach
from .observability import observability
from .snapshot import SystemSnapshot, build_snapshot
from .success import effective_sigma_mm, success_probability
from .timing import latency_budget
from .uncertainty import monte_carlo_percentiles, rss

_METRIC_POSITION = "position_accuracy"
_METRIC_CYCLE = "cycle_time"
_METRIC_SUCCESS = "picking_success_rate"
_METRIC_LATENCY = "end_to_end_latency"

_UNIT_MM = "mm"
_UNIT_S = "s"
_UNIT_RATIO = "ratio"
_UNIT_MS = "ms"


def verify_requirements(
    requirements: list[dict],
    system: dict,
    environment: dict | None = None,
    states: list[dict] | None = None,
    assets: list[dict] | None = None,
    options: dict | None = None,
) -> dict:
    snapshot = build_snapshot(system, assets or [])
    env = environment or {}
    options = options or {}
    mc_n = int(options.get("monte_carlo_n", M.MONTE_CARLO_N_DEFAULT))
    seed = options.get("seed")
    obs = observability(snapshot, states or [{"id": "object_pose"}])

    items = [_dispatch(req, snapshot, env, obs, mc_n, seed) for req in requirements]
    return {"items": items, "kernelVersion": KERNEL_VERSION}


def _dispatch(req: dict, snap: SystemSnapshot, env: dict, obs: dict, mc_n: int, seed) -> dict:
    metric = req.get("metric", "")
    if metric == _METRIC_POSITION:
        return _position_accuracy(req, snap, env, obs, mc_n, seed)
    if metric == _METRIC_CYCLE:
        return _cycle_time(req, snap, env)
    if metric == _METRIC_SUCCESS:
        return _success_rate(req, snap, env)
    if metric == _METRIC_LATENCY:
        return _latency(req, snap)
    if metric == "reach":
        return _wrap(req, check_reach(snap, env), _UNIT_S.replace("s", "m"))
    if metric == "payload":
        return _wrap(req, check_payload(snap, env), "kg")
    if metric in ("fov_coverage", "workspace_coverage"):
        return _wrap(req, check_fov(snap, env), "m")
    if metric in ("collision_free_rate", "orientation_accuracy"):
        return _unknown(req, ["simulation" if metric == "collision_free_rate" else "orientation_model"])
    return _unknown(req, [f"metric:{metric}"])


def _wrap(req: dict, result: dict, unit: str) -> dict:
    status = result["status"]
    return {
        "requirementId": req.get("id", "?"),
        "status": status,
        "method": "constraint_rule",
        "observed": result.get("observed"),
        "unit": unit,
        "percentile": req.get("percentile", "mean"),
        "detail": result.get("detail", ""),
        "missingInputs": result.get("missingInputs", []),
        "minProvenance": None,
        "contributors": [],
        "assumptions": [],
    }


def _unknown(req: dict, missing: list[str]) -> dict:
    return {
        "requirementId": req.get("id", "?"),
        "status": "UNKNOWN",
        "method": "not_covered",
        "observed": None,
        "unit": req.get("unit"),
        "percentile": req.get("percentile", "mean"),
        "detail": f"输入或模型缺失：{', '.join(missing)}；M2（仿真）/后续版本提供证据",
        "missingInputs": missing,
        "minProvenance": None,
        "contributors": [],
        "assumptions": [],
    }


def _camera_setup(snap: SystemSnapshot, assumptions: list[dict]) -> tuple[float, float] | None:
    """返回 (有效距离 m, 深度 1σ mm)；无相机或无误差信息 → None。"""
    cams = [c for c in snap.cameras if c.pose]
    if not cams:
        return None
    cam = cams[0]
    z = float(cam.pose.get("z", 1.0))
    if not cam.depth_available or not cam.depth_sigma_mm:
        sigma = M.MONOCULAR_DEPTH_SIGMA_RATIO * z * 1000.0
        assumptions.append({
            "name": "monocular_depth_sigma",
            "provenance": "literature",
            "note": f"单目深度 σ≈{M.MONOCULAR_DEPTH_SIGMA_RATIO * 100:.1f}%×距离（{z}m → {sigma:.2f}mm）",
        })
        return z, sigma
    d_ref_mm = cam.depth_ref_distance_mm or 700.0
    sigma = float(cam.depth_sigma_mm) * (z * 1000.0 / d_ref_mm)
    assumptions.append({
        "name": "depth_sigma_distance_extrapolation",
        "provenance": "datasheet",
        "note": f"σ_ref={cam.depth_sigma_mm}mm@{d_ref_mm}mm 线性外推至 {z * 1000:.0f}mm → {sigma:.2f}mm",
    })
    return z, sigma


def _position_accuracy(req: dict, snap: SystemSnapshot, env: dict, obs: dict, mc_n: int, seed) -> dict:
    assumptions: list[dict] = []
    setup = _camera_setup(snap, assumptions)
    if setup is None:
        return _unknown(req, ["system.cameras[with mountPose]"])
    _z, sigma_depth = setup

    object_pose_obs = obs.get("object_pose", {})
    not_observable = object_pose_obs.get("verdict") == "not_observable"

    parts: dict[str, float] = {"depth_error": sigma_depth}
    if snap.hand_eye_translation_mm:
        parts["hand_eye_residual"] = float(snap.hand_eye_translation_mm)
    rep = snap.robot_param("repeatability_mm")
    if rep and rep.value:
        parts["robot_repeatability"] = float(rep.value)
    absacc = snap.robot_param("absolute_accuracy_mm")
    if absacc and absacc.value:
        parts["robot_absolute_accuracy"] = float(absacc.value)
        assumptions.append({
            "name": "robot_absolute_accuracy",
            "provenance": "datasheet",
            "note": "厂商宣称值，偏乐观，待实测",
        })

    sigma_total, shares = rss(parts)
    mc = monte_carlo_percentiles(parts, n=mc_n, seed=seed if seed is not None else 42)
    percentile = req.get("percentile", "mean")
    observed = mc.get(percentile if percentile in mc else "P95", mc["P95"])

    threshold = float(req.get("value", 0.0))
    operator = req.get("operator", "<=")
    status = _compare(observed, operator, threshold)
    if not_observable:
        status = "FAIL"

    contributors = sorted(
        ({"name": k, "share": round(v, 3)} for k, v in shares.items()),
        key=lambda c: -c["share"],
    )[:5]

    detail = (
        f"误差预算 RSS σ={sigma_total:.3f}mm；{percentile}={observed:.2f}mm（MC n={mc['samples']}，"
        f"CI95=[{mc['ci95'][0]:.2f},{mc['ci95'][1]:.2f}]）"
    )
    if not_observable:
        detail = f"度量深度不可直接观测（{object_pose_obs.get('reason', '')}）；" + detail

    return {
        "requirementId": req.get("id", "?"),
        "status": status,
        "method": "rss_monte_carlo",
        "observed": round(observed, 3),
        "unit": _UNIT_MM,
        "percentile": percentile,
        "detail": detail,
        "missingInputs": [],
        "minProvenance": _min_prov(snap, assumptions),
        "contributors": contributors,
        "assumptions": assumptions,
        "ci95": mc["ci95"],
        "samples": mc["samples"],
    }


def _cycle_time(req: dict, snap: SystemSnapshot, env: dict) -> dict:
    assumptions: list[dict] = []
    budget = latency_budget(snap)
    for a in budget["assumptions"]:
        assumptions.append({"name": "latency_default", "provenance": "literature", "note": a})

    v = snap.robot_param("max_tcp_speed_mm_s")
    bin_ = env.get("bin")
    if v is None or not bin_:
        return _unknown(req, ["robot.max_tcp_speed_mm_s" if v is None else "environment.bin"])
    speed = float(v.value) / 1000.0
    diag = math.hypot(bin_.get("width_mm", 0), bin_.get("height_mm", 0)) / 1000.0
    move = M.MOVE_SEGMENTS * (diag + M.SEGMENT_CLEARANCE_M) / speed
    grasp = 2.0 * M.GRASP_CLOSE_TIME_S
    perceive = budget["total_ms"] / 1000.0 + M.PERCEPTION_OVERHEAD_S
    assumptions.append({
        "name": "cycle_path_model",
        "provenance": "literature",
        "note": (f"{M.MOVE_SEGMENTS} 段移动×(对角线{diag:.2f}m+{M.SEGMENT_CLEARANCE_M}m)/{speed:.1f}m/s "
                 f"+ 2×夹爪 {M.GRASP_CLOSE_TIME_S}s + 开销 {M.PERCEPTION_OVERHEAD_S}s"),
    })
    total = move + grasp + perceive
    percentile = req.get("percentile", "mean")
    threshold = float(req.get("value", 0.0))
    return {
        "requirementId": req.get("id", "?"),
        "status": _compare(total, req.get("operator", "<="), threshold),
        "method": "timing_budget_path_model",
        "observed": round(total, 3),
        "unit": _UNIT_S,
        "percentile": percentile,
        "detail": f"感知 {perceive:.2f}s + 移动 {move:.2f}s + 抓放 {grasp:.2f}s；时延分段 {budget['stages']}",
        "missingInputs": [],
        "minProvenance": _min_prov(snap, assumptions),
        "contributors": [
            {"name": "move", "share": round(move / total, 3)},
            {"name": "grasp", "share": round(grasp / total, 3)},
            {"name": "perceive", "share": round(perceive / total, 3)},
        ],
        "assumptions": assumptions,
    }


def _success_rate(req: dict, snap: SystemSnapshot, env: dict) -> dict:
    assumptions: list[dict] = [{
        "name": "success_model",
        "provenance": "literature",
        "note": (f"logistic 模型 {M.SUCCESS_MODEL_VERSION}（未校准）："
                 f"A={M.SUCCESS_A}, B={M.SUCCESS_B}, C={M.SUCCESS_C}"),
    }]
    setup = _camera_setup(snap, assumptions)
    if setup is None:
        return _unknown(req, ["system.cameras[with mountPose]"])
    _z, sigma_depth = setup

    occ = ((env.get("occlusion") or {}).get("percent") or {})
    occlusion = (occ.get("min", 0) + occ.get("max", 0)) / 2.0 / 100.0
    sizes = [p.get("size_mm") for p in (env.get("parts") or []) if p.get("size_mm")]
    size_mm = ((sizes[0]["min"] + sizes[0]["max"]) / 2.0) if sizes else M.OBJECT_SIZE_NORM_MM

    sigma_eff = effective_sigma_mm(sigma_depth, occlusion)
    p = success_probability(sigma_eff, occlusion, size_mm)
    threshold = float(req.get("value", 0.0))
    return {
        "requirementId": req.get("id", "?"),
        "status": _compare(p, req.get("operator", ">="), threshold),
        "method": "logistic_model_analytic",
        "observed": round(p, 4),
        "unit": _UNIT_RATIO,
        "percentile": req.get("percentile", "mean"),
        "detail": (
            f"σ_eff={sigma_eff:.2f}mm（σ_depth={sigma_depth:.2f}×遮挡因子），遮挡率 {occlusion:.2f}，"
            f"零件 {size_mm:.0f}mm → p={p:.4f}（模型未校准，实验引擎给出分布后以实验证据为准）"
        ),
        "missingInputs": [],
        "minProvenance": _min_prov(snap, assumptions),
        "contributors": [
            _occlusion_share(occlusion, sigma_eff, size_mm, p),
        ],
        "assumptions": assumptions,
    }


def _latency(req: dict, snap: SystemSnapshot) -> dict:
    assumptions: list[dict] = []
    budget = latency_budget(snap)
    for a in budget["assumptions"]:
        assumptions.append({"name": "latency_default", "provenance": "literature", "note": a})
    total = budget["total_ms"]
    threshold = float(req.get("value", 0.0))
    return {
        "requirementId": req.get("id", "?"),
        "status": _compare(total, req.get("operator", "<="), threshold),
        "method": "latency_budget",
        "observed": round(total, 2),
        "unit": _UNIT_MS,
        "percentile": req.get("percentile", "mean"),
        "detail": f"分段(ms)：{budget['stages']} → 合计 {total:.1f}ms",
        "missingInputs": [],
        "minProvenance": _min_prov(snap, assumptions),
        "contributors": sorted(
            ({"name": k, "share": round(v / total, 3)} for k, v in budget["stages"].items()),
            key=lambda c: -c["share"],
        )[:6],
        "assumptions": assumptions,
    }


def _occlusion_share(occlusion: float, sigma_eff: float, size_mm: float, p: float) -> float:
    """成功率失败预算中遮挡项占比（logistic 线性项之比；p>=0.5 时无失败预算，记 0）。"""
    if p >= 0.5:
        return 0.0
    size_factor = M.OBJECT_SIZE_NORM_MM / max(size_mm, 1.0)
    denom = (M.SUCCESS_A - M.SUCCESS_C * sigma_eff * size_factor - M.SUCCESS_B * occlusion)
    if denom <= 0:
        return 1.0
    return round(M.SUCCESS_B * occlusion / denom, 3)


def _compare(observed: float, operator: str, threshold: float) -> str:
    if operator == ">=":
        return "PASS" if observed >= threshold else "FAIL"
    if operator == ">":
        return "PASS" if observed > threshold else "FAIL"
    if operator == "<=":
        return "PASS" if observed <= threshold else "FAIL"
    if operator == "<":
        return "PASS" if observed < threshold else "FAIL"
    return "PASS" if observed == threshold else "FAIL"


def _min_prov(snap: SystemSnapshot, assumptions: list[dict]) -> str | None:
    from .snapshot import PROVENANCE_RANK

    provs = [p.provenance for p in snap.params if p.provenance]
    provs += [a["provenance"] for a in assumptions if a.get("provenance")]
    if not provs:
        return None
    return min(provs, key=lambda x: PROVENANCE_RANK.get(x, -1))
