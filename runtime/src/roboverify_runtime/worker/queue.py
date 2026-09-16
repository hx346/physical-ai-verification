"""job_queue 消费：FOR UPDATE SKIP LOCKED 认领 + 心跳 + 幂等完成（docs/architecture.md §6）。

状态机：QUEUED → RUNNING → SUCCEEDED / FAILED（attempts < max_attempts 时重入队）/ TIMEOUT。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("worker.queue")


@dataclass
class ClaimedJob:
    id: int
    job_key: str
    type: str
    payload: dict
    attempts: int
    max_attempts: int


def claim_next_job(conn: psycopg.Connection, worker_id: str,
                   capabilities: list[str] | None = None) -> ClaimedJob | None:
    """在调用方事务内认领一个任务并置 RUNNING；无任务返回 None。
    能力路由：requires 非空的任务只被具备该能力的 worker 认领。"""
    if capabilities is None:
        capabilities = [c.strip() for c in settings.worker_capabilities.split(",") if c.strip()]
    caps = capabilities
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '3s'")
        cur.execute(
            """
            WITH next_job AS (
                SELECT id FROM job_queue
                WHERE status = 'QUEUED'
                  AND (requires IS NULL OR requires = ANY(%s))
                ORDER BY priority, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE job_queue j
            SET status = 'RUNNING', locked_by = %s, locked_at = now(),
                timeout_at = now() + make_interval(secs => %s), updated_at = now()
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.id, j.job_key, j.type, j.payload, j.attempts, j.max_attempts
            """,
            (caps, worker_id, settings.worker_lock_ttl_s),
        )
        row = cur.fetchone()
        if row is None:
            return None
        payload = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        return ClaimedJob(id=row[0], job_key=row[1], type=row[2],
                          payload=payload, attempts=row[4], max_attempts=row[5])


def enqueue_job(conn: psycopg.Connection, job_key: str, job_type: str, payload: dict,
                requires: str | None = None, priority: int = 100) -> bool:
    """投递（幂等 job_key，与 Java JobQueueService 同语义）。

    V0.5 W1 DAG 编排：experiment 父任务展开 simulation 子任务时使用——
    父任务重跑时已完成子任务 ON CONFLICT DO NOTHING，天然断点续跑。
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO job_queue (job_key, type, payload, priority, requires) "
            "VALUES (%s, %s, %s::jsonb, %s, %s) ON CONFLICT (job_key) DO NOTHING",
            (job_key, job_type, json.dumps(payload, ensure_ascii=False), priority, requires))
        return cur.rowcount > 0


def fetch_jobs(conn: psycopg.Connection, job_keys: list[str]) -> dict[str, dict]:
    """按键批量取任务状态/载荷（DAG 收割轮询）。返回 job_key → {status, payload, lastError}。"""
    if not job_keys:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT job_key, status, payload, last_error FROM job_queue WHERE job_key = ANY(%s)",
            (job_keys,))
        rows = cur.fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        payload = r[2] if isinstance(r[2], dict) else json.loads(r[2])
        out[r[0]] = {"status": r[1], "payload": payload, "lastError": r[3]}
    return out


def complete_job(conn: psycopg.Connection, job_id: int, result: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET status='SUCCEEDED', updated_at=now(), last_error=NULL, "
            "payload = payload || %s::jsonb WHERE id=%s",
            (json.dumps({"result": result}, ensure_ascii=False), job_id),
        )


def fail_job(conn: psycopg.Connection, job_id: int, error: str) -> None:
    """失败：未超次重入队（QUEUED），超次置 FAILED（人工处理，V0.1 不做自动死信）。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE job_queue
            SET attempts = attempts + 1,
                status = CASE WHEN attempts + 1 >= max_attempts THEN 'FAILED' ELSE 'QUEUED' END,
                last_error = %s, locked_by = NULL, locked_at = NULL, timeout_at = NULL, updated_at = now()
            WHERE id = %s
            """,
            (error[:2000], job_id),
        )


def heartbeat(conn: psycopg.Connection, job_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET timeout_at = %s, updated_at = now() WHERE id = %s AND status = 'RUNNING'",
            (datetime.now(timezone.utc) + timedelta(seconds=settings.worker_lock_ttl_s), job_id),
        )


def recover_timed_out(conn: psycopg.Connection) -> int:
    """巡检：心跳超时的 RUNNING 任务重入队（超过 max_attempts 置 FAILED）。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE job_queue
            SET attempts = attempts + 1,
                status = CASE WHEN attempts + 1 >= max_attempts THEN 'FAILED' ELSE 'QUEUED' END,
                last_error = 'heartbeat timeout, recovered', locked_by = NULL, locked_at = NULL,
                timeout_at = NULL, updated_at = now()
            WHERE status = 'RUNNING' AND timeout_at < now()
            """
        )
        recovered = cur.rowcount
    if recovered:
        log.warning("recovered timed-out jobs", count=recovered)
    return recovered
