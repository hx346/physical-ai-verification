package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 失败取证库（V0.9 Evidence & Failure Intelligence，方案 §26）。
 * 每条记录 = failure → root_cause → correction → outcome 四元组 + 溯源
 * （source 区分 sim|real|manual；evidence_id 关联证据链；trace 存探针方法/指纹等）。
 * 存量 W2/W4 取证由 Flyway V10 seed 回填，本接口只管增量。
 */
@RestController
@RequestMapping("/api/failures")
public class FailureController {

    private static final Set<String> SEVERITIES = Set.of("low", "medium", "high", "critical");
    private static final Set<String> SOURCES = Set.of("sim", "real", "manual");

    private final JdbcTemplate jdbcTemplate;

    public FailureController(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public record CreateFailureRequest(
            String projectId,
            String externalKey,
            String failureMode,
            String failureDesc,
            String rootCause,
            String correction,
            String outcome,
            String severity,
            String source,
            String evidenceId,
            Map<String, Object> trace,
            String detectedAt
    ) {
    }

    /**
     * 录入失败取证。externalKey 幂等（V9 部分唯一索引）：同 key 重放返回已有
     * 记录 duplicate=true，不重复入库（回填脚本可安全重跑）。
     */
    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody CreateFailureRequest request) {
        if (request.failureMode() == null || request.failureMode().isBlank()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "failureMode 不能为空");
        }
        String severity = request.severity() == null ? "medium" : request.severity();
        String source = request.source() == null ? "manual" : request.source();
        if (!SEVERITIES.contains(severity)) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "severity 取值须为 low|medium|high|critical，实际：" + severity);
        }
        if (!SOURCES.contains(source)) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "source 取值须为 sim|real|manual，实际：" + source);
        }
        String detectedAt = null;
        if (request.detectedAt() != null && !request.detectedAt().isBlank()) {
            try {
                detectedAt = OffsetDateTime.parse(request.detectedAt().trim()).toString();
            } catch (RuntimeException e) {
                throw new BizException(ErrorCode.BAD_REQUEST, "detectedAt 须为 ISO-8601");
            }
        }

        List<String> ids = jdbcTemplate.queryForList(
                "INSERT INTO failure_record (project_id, external_key, failure_mode, failure_desc, "
                        + "root_cause, correction, outcome, severity, source, evidence_id, trace, detected_at) "
                        + "VALUES (?::uuid, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?::timestamptz) "
                        + "ON CONFLICT (external_key) WHERE external_key IS NOT NULL DO NOTHING "
                        + "RETURNING id::text",
                String.class,
                blankToNull(request.projectId()), blankToNull(request.externalKey()),
                request.failureMode().trim(), blankToNull(request.failureDesc()),
                blankToNull(request.rootCause()), blankToNull(request.correction()),
                blankToNull(request.outcome()), severity, source,
                blankToNull(request.evidenceId()), toJson(request.trace()), detectedAt);
        if (ids.isEmpty()) {  // 幂等命中：key 已存在——返回原记录，不重复入库
            String existing = jdbcTemplate.queryForObject(
                    "SELECT id::text FROM failure_record WHERE external_key = ?",
                    String.class, request.externalKey());
            return Result.ok(Map.of("failureId", existing, "duplicate", true));
        }
        return Result.ok(Map.of("failureId", ids.get(0), "duplicate", false));
    }

    /** 列表（新→旧，默认 100 条）——回填核对与前端 Failure 章节共用。 */
    @GetMapping
    public Result<List<Map<String, Object>>> list(
            @RequestParam(required = false) String projectId,
            @RequestParam(required = false, defaultValue = "100") int limit) {
        int safeLimit = Math.min(Math.max(limit, 1), 500);
        String sql = "SELECT id::text, project_id::text, external_key, failure_mode, failure_desc, "
                + "root_cause, correction, outcome, severity, source, evidence_id, trace, "
                + "detected_at::text, created_at::text "
                + "FROM failure_record "
                + (projectId == null || projectId.isBlank() ? "" : "WHERE project_id = ?::uuid ")
                + "ORDER BY created_at DESC LIMIT " + safeLimit;
        Object[] args = projectId == null || projectId.isBlank() ? new Object[0] : new Object[]{projectId};
        return Result.ok(jdbcTemplate.query(sql, FailureController::mapRow, args));
    }

    @GetMapping("/{id}")
    public Result<Map<String, Object>> get(@PathVariable long id) {
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT id::text, project_id::text, external_key, failure_mode, failure_desc, "
                        + "root_cause, correction, outcome, severity, source, evidence_id, trace, "
                        + "detected_at::text, created_at::text "
                        + "FROM failure_record WHERE id = ?",
                FailureController::mapRow, id);
        if (rows.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "failure 记录不存在：id=" + id);
        }
        return Result.ok(rows.get(0));
    }

    private static Map<String, Object> mapRow(java.sql.ResultSet rs, int i) throws java.sql.SQLException {
        Map<String, Object> row = new HashMap<>();
        row.put("id", rs.getString(1));
        row.put("projectId", rs.getString(2));
        row.put("externalKey", rs.getString(3));
        row.put("failureMode", rs.getString(4));
        row.put("failureDesc", rs.getString(5));
        row.put("rootCause", rs.getString(6));
        row.put("correction", rs.getString(7));
        row.put("outcome", rs.getString(8));
        row.put("severity", rs.getString(9));
        row.put("source", rs.getString(10));
        row.put("evidenceId", rs.getString(11));
        row.put("trace", readJson(rs.getString(12)));
        row.put("detectedAt", rs.getString(13));
        row.put("createdAt", rs.getString(14));
        return row;
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }

    private static String toJson(Object o) {
        if (o == null) {
            return null;
        }
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
        } catch (Exception e) {
            throw new BizException(ErrorCode.BAD_REQUEST, "trace 不是合法 JSON 结构");
        }
    }

    private static Map<String, Object> readJson(String json) {
        if (json == null) {
            return null;
        }
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
        } catch (Exception e) {
            return null;  // trace 损坏不阻断列表（列表是核查面，不是判定面）
        }
    }
}
