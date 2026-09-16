"""队列认领测试：仅在提供真实 PG 时执行（ROBOVERIFY_TEST_PG=1），CI M0 跳过。"""

import json
import os
import uuid

import pytest

from roboverify_runtime.config import settings
from roboverify_runtime.worker.queue import claim_next_job, complete_job

pytestmark = pytest.mark.skipif(
    os.environ.get("ROBOVERIFY_TEST_PG") != "1",
    reason="需要本地 PostgreSQL（ROBOVERIFY_TEST_PG=1 开启）",
)


def test_claim_marks_running_and_idempotent_complete() -> None:
    import psycopg

    job_key = f"test:{uuid.uuid4()}"
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO job_queue (job_key, type, payload) VALUES (%s, 'noop', %s::jsonb) "
                "ON CONFLICT (job_key) DO NOTHING",
                (job_key, json.dumps({"hello": "world"})),
            )
        with conn.transaction():
            job = claim_next_job(conn, "test-worker")
        assert job is not None and job.type == "noop"
        # SKIP LOCKED：并发认领不得拿到同一行（此处验证已认领行不再可认领）
        with conn.transaction():
            again = claim_next_job(conn, "test-worker")
            # 队列中可能还有其他 QUEUED 任务，只断言不是同一个 job
            assert again is None or again.id != job.id
        with conn.transaction():
            complete_job(conn, job.id, {"done": True})
        with conn.cursor() as cur:
            cur.execute("SELECT status, payload->'result'->>'done' FROM job_queue WHERE id=%s", (job.id,))
            status, done = cur.fetchone()
        assert status == "SUCCEEDED" and done == "true"
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_queue WHERE id=%s", (job.id,))


def test_enqueue_and_fetch_for_dag() -> None:
    """V0.5 W1 DAG 原语：幂等投递 + 按键收割查询。"""
    import psycopg

    from roboverify_runtime.worker.queue import enqueue_job, fetch_jobs

    base = f"test-dag:{uuid.uuid4()}"
    keys = [f"{base}:run:{i}" for i in range(3)]
    with psycopg.connect(settings.database_url) as conn:
        with conn.transaction():
            for i, k in enumerate(keys):
                inserted = enqueue_job(conn, k, "simulation",
                                       {"runIndex": i, "params": {"a": 1.0}},
                                       requires="gz", priority=55)
                assert inserted is True
        # 幂等：重复投递不覆盖已有行
        with conn.transaction():
            assert enqueue_job(conn, keys[0], "simulation", {"clobber": True}) is False
        got = fetch_jobs(conn, keys)
        assert set(got) == set(keys)
        assert got[keys[0]]["payload"]["params"] == {"a": 1.0}  # 未被 clobber
        assert all(v["status"] == "QUEUED" for v in got.values())
        assert fetch_jobs(conn, []) == {}
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_queue WHERE job_key = ANY(%s)", (keys,))
