"""FastAPI 入口：同步内核端点（platform-runtime 契约见 schemas/openapi/）。"""

import hashlib
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from .config import settings
from .logging_setup import get_logger, setup_logging, trace_id_var
from .schema_loader import validate

log = get_logger("runtime")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings.log_level)
    log.info("runtime starting", kernel_version=settings.kernel_version,
             schema_dir=str(settings.schema_dir))
    yield
    log.info("runtime stopped")


app = FastAPI(title="RoboVerify Engineering Runtime", version=settings.kernel_version, lifespan=lifespan)


class VerifyRequest(BaseModel):
    requestId: str
    traceId: str | None = None
    requirements: list[dict]
    system: dict
    environment: dict | None = None
    states: list[dict] | None = None
    assets: list[dict] | None = None
    options: dict | None = None


class VerdictItem(BaseModel):
    requirementId: str
    status: str  # PASS / FAIL / UNKNOWN
    method: str
    detail: str
    missingInputs: list[str] = []


class VerifyResponse(BaseModel):
    requestId: str
    traceId: str | None
    kernelVersion: str
    items: list[VerdictItem]
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


@app.post("/api/v1/verify", response_model=VerifyResponse)
def verify(
    payload: VerifyRequest,
    request: Request,
    x_trace_id: str | None = Header(default=None),
) -> VerifyResponse:
    # traceId 透传：显式字段 > 请求头 > 新生成
    trace_id_var.set(payload.traceId or x_trace_id or request.state.__dict__.get("traceId", ""))
    started = time.perf_counter()

    # 契约校验：system / requirements 必须过 IR Schema（LLM 或手工输入都不可绕过）
    warnings: list[str] = []
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

    fingerprint = hashlib.sha256(
        (payload.model_dump_json(exclude={"requestId", "traceId"})).encode("utf-8")
    ).hexdigest()

    # M0：内核未实现，全部返回 UNKNOWN（合法结论，禁止编造 PASS/FAIL）
    items = [
        VerdictItem(
            requirementId=r.get("id", "?"),
            status="UNKNOWN",
            method="not-implemented",
            detail="M0 骨架：解析式内核在 M1 实现（constraint/uncertainty/timing/observability）",
            missingInputs=["kernel"],
        )
        for r in payload.requirements
    ]
    warnings.append(f"inputFingerprint={fingerprint}")

    log.info("verify handled", requestId=payload.requestId, requirements=len(payload.requirements),
             elapsed_ms=round((time.perf_counter() - started) * 1000, 2))
    return VerifyResponse(
        requestId=payload.requestId,
        traceId=payload.traceId,
        kernelVersion=settings.kernel_version,
        items=items,
        warnings=warnings,
    )
