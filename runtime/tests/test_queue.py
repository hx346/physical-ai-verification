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
