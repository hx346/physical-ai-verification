"""FastAPI 入口：同步内核端点（platform-runtime 契约见 schemas/openapi/）。"""

import hashlib
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from .config import settings
from .kernel import KERNEL_VERSION, registry
from .logging_setup import get_logger, setup_logging, trace_id_var
from .schema_loader import IR_NAMES, validate

log = get_logger("runtime")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings.log_level)
    log.info("runtime starting", kernel_version=KERNEL_VERSION, schema_dir=str(settings.schema_dir))
    yield
    log.info("runtime stopped")


app = FastAPI(title="RoboVerify Engineering Runtime", version=KERNEL_VERSION, lifespan=lifespan)


class VerifyRequest(BaseModel):
    requestId: str
    traceId: str | None = None
    requirements: list[dict]
    system: dict
    environment: dict | None = None
    states: list[dict] | None = None
    assets: list[dict] | None = None
    options: dict | None = None


class VerifyResponse(BaseModel):
    requestId: str
    traceId: str | None
    kernelVersion: str
    items: list[dict]
    warnings: list[str] = []


@app.get("/health")
def health() -> dict:
    return {"status": "liveness_ok"}


@app.get("/ready")
def ready() -> dict:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return {"status": "ready", "db": "up"}
    except psycopg.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"db unavailable: {e}") from e


@app.post("/api/v1/validate", response_model_exclude_none=True)
def validate_ir(body: dict) -> dict:
    """IR 校验（平台导入数据时调用；LLM 草稿同样必须过这里）。"""
    ir = body.get("ir")
    instance = body.get("instance")
    if ir not in IR_NAMES or not isinstance(instance, dict):
        raise HTTPException(status_code=400, detail={"error": "body: {ir, instance}"})
    errors = validate(ir, instance)
    return {"ir": ir, "valid": not errors, "errors": errors[:10]}


@app.post("/api/v1/verify", response_model=VerifyResponse)
def verify(
    payload: VerifyRequest,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> VerifyResponse:
    # traceId 透传：显式字段 > 请求头
    trace_id_var.set(payload.traceId or x_trace_id or "")
    started = time.perf_counter()

    # 契约校验：system / requirements / assets 必须过 IR Schema（LLM 或手工输入都不可绕过）
    system_errors = validate("system", payload.system)
    if system_errors:
        raise HTTPException(status_code=422, detail={"ir": "system", "errors": system_errors[:5]})
    for req in payload.requirements:
        req_errors = validate("requirement", req)
        if req_errors:
            raise HTTPException(
                status_code=422,
                detail={"ir": "requirement", "id": req.get("id"), "errors": req_errors[:5]},
            )
    for asset in payload.assets or []:
        asset_errors = validate("asset", asset)
        if asset_errors:
            raise HTTPException(
                status_code=422,
                detail={"ir": "asset", "id": asset.get("id"), "errors": asset_errors[:5]},
            )

    fingerprint = hashlib.sha256(
        payload.model_dump_json(exclude={"requestId", "traceId"}).encode("utf-8")
    ).hexdigest()

    # 真实内核：判定来自公式 / RSS / 蒙特卡洛，绝不来自 LLM（原则二）
    result = registry.verify_requirements(
        requirements=payload.requirements,
        system=payload.system,
        environment=payload.environment,
        states=payload.states,
        assets=payload.assets,
        options=payload.options,
    )

    warnings = [f"inputFingerprint={fingerprint}"]
    if not payload.assets:
        warnings.append("assets 未提供：涉及资产参数的指标将返回 UNKNOWN")

    log.info(
        "verify handled",
        requestId=payload.requestId,
        requirements=len(payload.requirements),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return VerifyResponse(
        requestId=payload.requestId,
        traceId=payload.traceId,
        kernelVersion=result["kernelVersion"],
        items=result["items"],
        warnings=warnings,
    )


class GapRequest(BaseModel):
    sessionId: str
    simSummary: dict[str, float]


@app.post("/api/v1/realtest/gap")
def realtest_gap(payload: GapRequest) -> dict:
    """真机遥测聚合 + 与仿真分布的逐指标 Gap（M4）。"""
    from .realtest.gap import gap_report, summarize_telemetry

    real = summarize_telemetry(payload.sessionId)
    if not real:
        raise HTTPException(status_code=404, detail={"error": "session 无遥测数据"})
    # 实验聚合键 → gap 指标键映射（success_rate_mean ↔ picking_success_rate）
    sim = {
        "picking_success_rate": payload.simSummary.get("success_rate_mean"),
        "position_error_mm": payload.simSummary.get("accuracy_p95_mean_mm"),
    }
    return {"sessionId": payload.sessionId, "real": real, "gap": gap_report(real, sim)}


class CalibrationRequest(BaseModel):
    system: dict
    environment: dict | None = None
    assets: list[dict] | None = None
    observedSuccessMean: float
    occlusion: float = 0.35
    objectSizeMm: float = 50.0


@app.post("/api/v1/calibration/run")
def calibration_run(payload: CalibrationRequest) -> dict:
    """Real2Sim 校准 v0：拟合 depth_sigma_scale，平台侧落 model_version(DRAFT)。"""
    from .calibration.least_squares import calibrate_sigma_scale
    from .experiment.engine import _camera_sigma

    setup = _camera_sigma(payload.system, payload.assets or [])
    if setup is None:
        raise HTTPException(status_code=422, detail={"error": "system 无有效相机"})
    _z, base_sigma = setup
    return calibrate_sigma_scale(
        base_sigma_mm=base_sigma,
        observed_success_mean=payload.observedSuccessMean,
        occlusion=payload.occlusion,
        object_size_mm=payload.objectSizeMm,
    )
