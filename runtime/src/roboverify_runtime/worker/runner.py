"""Worker 主循环：认领 → 短事务标记 RUNNING → 处理（不持 DB 事务）→ 短事务回写。"""

from __future__ import annotations

import time

import psycopg

from ..config import settings
from ..logging_setup import get_logger, setup_logging
from .queue import claim_next_job, complete_job, fail_job, recover_timed_out

log = get_logger("worker.runner")

_HANDLERS: dict[str, object] = {}  # M2 注册 "simulation"，M3 "experiment"，M4 "calibration"

RECOVER_INTERVAL_S = 60.0


def handle(job_type: str):
    """处理器注册装饰器（M2+ 使用）。"""
    def register(fn):
        _HANDLERS[job_type] = fn
        return fn
    return register


def run_forever(worker_id: str = "worker-1") -> None:
    setup_logging(settings.log_level)
    log.info("worker starting", worker_id=worker_id, handlers=sorted(_HANDLERS) or ["<none>"])
    last_recover = time.monotonic()
    with psycopg.connect(settings.database_url) as conn:
        while True:
            if time.monotonic() - last_recover > RECOVER_INTERVAL_S:
                with conn.transaction():
                    recover_timed_out(conn)
                last_recover = time.monotonic()

            with conn.transaction():
                job = claim_next_job(conn, worker_id)
            if job is None:
                time.sleep(settings.worker_poll_interval_s)
                continue

            log.info("job claimed", job_id=job.id, job_key=job.job_key, type=job.type)
            handler = _HANDLERS.get(job.type)
            try:
                # 处理器在事务外运行（长任务禁止持 DB 事务）；完成/失败用短事务回写
                if handler is None:
                    result = {"note": f"no handler for type={job.type} in M0"}
                    log.warning("no handler, job marked done", job_key=job.job_key, type=job.type)
                else:
                    result = handler(job)
                with conn.transaction():
                    payload = result if isinstance(result, dict) else {"result": str(result)}
                    complete_job(conn, job.id, payload)
            except Exception as e:  # noqa: BLE001 — worker 兜底必须吞一切异常并留痕
                log.error("job failed", job_key=job.job_key, error=str(e), exc_info=True)
                with conn.transaction():
                    fail_job(conn, job.id, str(e))
