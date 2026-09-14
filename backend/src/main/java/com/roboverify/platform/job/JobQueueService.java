package com.roboverify.platform.job;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;

/**
 * 任务队列投递与查询。幂等：job_key 唯一索引 + ON CONFLICT DO NOTHING，
 * 重复投递直接复用已有任务。消费侧（Python worker）用 FOR UPDATE SKIP LOCKED 认领。
 */
@Service
public class JobQueueService {

    private static final Logger log = LoggerFactory.getLogger(JobQueueService.class);

    private static final String ENQUEUE_SQL = """
            INSERT INTO job_queue (job_key, type, payload, priority, trace_id, requires)
            VALUES (?, ?, ?::jsonb, ?, ?, ?)
            ON CONFLICT (job_key) DO NOTHING
            """;

    private static final String SELECT_BY_KEY = """
            SELECT id, job_key, type, status, priority, attempts, max_attempts,
                   timeout_at, locked_by, last_error, trace_id, created_at, updated_at
            FROM job_queue WHERE job_key = ?
            """;

    private static final short DEFAULT_PRIORITY = 100;

    private final JdbcTemplate jdbcTemplate;

    public JobQueueService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    /** @return true=新任务已入队；false=job_key 已存在（幂等复用） */
    public boolean enqueue(String jobKey, String type, String payloadJson, String traceId) {
        return enqueue(jobKey, type, payloadJson, traceId, null, DEFAULT_PRIORITY);
    }

    /** requires 非空时任务只被具备该能力的 worker 认领（如 simulation → gz）。 */
    public boolean enqueue(String jobKey, String type, String payloadJson, String traceId,
                           String requires, short priority) {
        int inserted = jdbcTemplate.update(ENQUEUE_SQL, jobKey, type, payloadJson, priority, traceId, requires);
        if (inserted == 0) {
            log.info("job already exists, jobKey={}", jobKey);
        } else {
            log.info("job enqueued, jobKey={}, type={}, requires={}", jobKey, type, requires);
        }
        return inserted > 0;
    }

    public JobRecord getByKey(String jobKey) {
        var records = jdbcTemplate.query(SELECT_BY_KEY, (rs, i) -> new JobRecord(
                rs.getLong("id"), rs.getString("job_key"), rs.getString("type"), rs.getString("status"),
                rs.getShort("priority"), rs.getShort("attempts"), rs.getShort("max_attempts"),
                rs.getObject("timeout_at", OffsetDateTime.class), rs.getString("locked_by"),
                rs.getString("last_error"), rs.getString("trace_id"),
                rs.getObject("created_at", OffsetDateTime.class), rs.getObject("updated_at", OffsetDateTime.class)
        ), jobKey);
        if (records.isEmpty()) {
            throw new BizException(ErrorCode.JOB_NOT_FOUND);
        }
        return records.getFirst();
    }
}
