package com.roboverify.platform.audit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * 审计：需求/配置/资产/证据的创建与变更必须落 audit_log。
 * 审计失败不阻断业务（记 error 日志），但不允许静默吞掉——必须可见。
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    private static final String TRACE_ID_KEY = "traceId";

    private final JdbcTemplate jdbcTemplate;

    public AuditService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void record(String userId, String action, String targetType, String targetId,
                       String beforeJson, String afterJson) {
        String traceId = MDC.get(TRACE_ID_KEY);
        try {
            jdbcTemplate.update(
                    "INSERT INTO audit_log (user_id, action, target_type, target_id, before, after, trace_id) "
                            + "VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?)",
                    userId, action, targetType, targetId, beforeJson, afterJson, traceId);
        } catch (Exception e) {
            log.error("audit insert failed, action={}, target={}:{}", action, targetType, targetId, e);
        }
    }
}
