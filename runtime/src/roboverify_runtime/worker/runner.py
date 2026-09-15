"""Worker 主循环：认领 → 短事务标记 RUNNING → 处理（不持 DB 事务）→ 短事务回写。"""

from __future__ import annotations

import threading
import time

import psycopg

from ..config import settings
from ..logging_setup import get_logger, setup_logging
from . import handlers  # noqa: F401  导入即注册处理器（在 registry 中登记）
from .queue import claim_next_job, complete_job, fail_job, heartbeat, recover_timed_out
from .registry import get_handler, registered_types

log = get_logger("worker.runner")

RECOVER_INTERVAL_S = 60.0


def _heartbeat_loop(job_id: int, stop: threading.Event) -> None:
    """handler 运行期间独立连接续期 timeout_at（防 recover_timed_out 误回收）。

    claim 只在认领时设一次 timeout_at（TTL 300s）——单次仿真 ~60s 擦边安全，
    但批量仿真实验（W4，~1h）必被回收重跑。心跳线程用独立连接（psycopg3
    connection 非线程安全，不能与主循环共用）。
    """
    interval = max(5.0, min(settings.worker_lock_ttl_s / 3.0, 60.0))
    try:
        with psycopg.connect(settings.database_url) as conn:
            while not stop.wait(interval):
                with conn.transaction():
                    heartbeat(conn, job_id)
    except Exception:  # noqa: BLE001 — 心跳线程任何异常终止即告警留痕
        log.warning("heartbeat loop stopped, job may be recovered", job_id=job_id)


def run_forever(worker_id: str = "worker-1") -> None:
    setup_logging(settings.log_level)
    capabilities = [c.strip() for c in settings.worker_capabilities.split(",") if c.strip()]
    log.info("worker starting", worker_id=worker_id, handlers=registered_types() or ["<none>"],
             capabilities=capabilities or ["<any>"])
    last_recover = time.monotonic()
    with psycopg.connect(settings.database_url) as conn:
        while True:
            if time.monotonic() - last_recover > RECOVER_INTERVAL_S:
                with conn.transaction():
                    recover_timed_out(conn)
                last_recover = time.monotonic()

            with conn.transaction():
                job = claim_next_job(conn, worker_id, capabilities)
            if job is None:
                time.sleep(settings.worker_poll_interval_s)
                continue

            log.info("job claimed", job_id=job.id, job_key=job.job_key, type=job.type)
            handler = get_handler(job.type)
            hb_stop = threading.Event()
            hb = threading.Thread(target=_heartbeat_loop, args=(job.id, hb_stop), daemon=True)
            hb.start()
            try:
                # 处理器在事务外运行（长任务禁止持 DB 事务）；完成/失败用短事务回写
                if handler is None:
                    result = {"note": f"no handler for type={job.type}"}
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
            finally:
                hb_stop.set()


if __name__ == "__main__":
    run_forever()
