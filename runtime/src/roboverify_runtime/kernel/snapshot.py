"""系统快照：System IR + Asset Registry → 内核可用的参数视图，逐参数追踪 provenance。"""

from __future__ import annotations

from dataclasses import dataclass, field

PROVENANCE_RANK = {"datasheet": 0, "literature": 1, "measured": 2, "calibrated": 3}


@dataclass
class Param:
    name: str
    value: object
    provenance: str
    asset_id: str = ""
    note: str = ""
    conditions: dict = field(default_factory=dict)


@dataclass
class CameraView:
    component_id: str
    asset_id: str
    pose: dict
    depth_available: bool | None
    depth_sigma_mm: float | None
    depth_sigma_ref_mm: float | None
    depth_ref_distance_mm: float | None
    fov_deg: float | None
    latency_ms: float | None
    params: list[Param] = field(default_factory=list)


@dataclass
class SystemSnapshot:
    system_id: str
    robot: dict[str, Param]
    cameras: list[CameraView]
    gripper: dict[str, Param]
    network_latency_ms: float | None
    hand_eye_translation_mm: float | None
    params: list[Param] = field(default_factory=list)  # 全量，供 provenance 统计

    def min_provenance(self) -> str | None:
        used = [p.provenance for p in self.params if p.provenance]
        if not used:
            return None
        return min(used, key=lambda x: PROVENANCE_RANK.get(x, -1))

    def robot_param(self, name: str) -> Param | None:
        return self.robot.get(name)

    def gripper_param(self, name: str) -> Param | None:
        return self.gripper.get(name)


def _asset_params(asset: dict) -> dict[str, Param]:
    """Asset IR 的 params 数组 → {name: Param}（保留 conditions，如标称距离）。"""
    out: dict[str, Param] = {}
    for p in asset.get("params", []):
        out[p["name"]] = Param(
            name=p["name"],
            value=p.get("value"),
            provenance=p.get("provenance", "datasheet"),
            asset_id=asset.get("id", ""),
            note=p.get("note", ""),
            conditions=p.get("conditions", {}) or {},
        )
    return out


def build_snapshot(system: dict, assets: list[dict]) -> SystemSnapshot:
    assets_by_id = {a.get("id"): a for a in assets}
    all_params: list[Param] = []

    robot: dict[str, Param] = {}
    gripper: dict[str, Param] = {}
    cameras: list[CameraView] = []

    for comp in system.get("components", []):
        asset = assets_by_id.get(comp.get("assetId"))
        if asset is None:
            continue  # 资产缺失 → 相关指标 UNKNOWN（missingInputs 由 registry 汇报）
        params = _asset_params(asset)
        all_params.extend(params.values())
        ctype = comp.get("type")
        if ctype == "robot":
            robot = params
        elif ctype in ("camera", "depth_camera"):
            depth_sigma = params.get("depth_sigma_mm")
            cameras.append(
                CameraView(
                    component_id=comp.get("id", ""),
                    asset_id=comp.get("assetId", ""),
                    pose=comp.get("mountPose", {}) or {},
                    depth_available=_value(params, "depth_available"),
                    depth_sigma_mm=depth_sigma.value if depth_sigma else None,
                    depth_sigma_ref_mm=depth_sigma.value if depth_sigma else None,
                    depth_ref_distance_mm=(depth_sigma.conditions.get("distance_mm")
                                           if depth_sigma else None),
                    fov_deg=_value(params, "fov_deg"),
                    latency_ms=_value(params, "latency_ms"),
                    params=list(params.values()),
                )
            )
        elif ctype == "gripper":
            gripper = params

    hand_eye = None
    for calib in system.get("calibrations", []):
        if calib.get("type") == "hand_eye" and calib.get("residual"):
            hand_eye = calib["residual"].get("translation_mm")

    network = (system.get("network") or {}).get("latency_ms")

    return SystemSnapshot(
        system_id=system.get("id", ""),
        robot=robot,
        cameras=cameras,
        gripper=gripper,
        network_latency_ms=network,
        hand_eye_translation_mm=hand_eye,
        params=all_params,
    )


def _value(params: dict[str, Param], name: str) -> object | None:
    p = params.get(name)
    return None if p is None else p.value
