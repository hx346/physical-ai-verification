package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Reality DB 查询面（V1.0 §14 Track B，方案 §23）：设备×环境×任务×指标分布。
 * "这种数据以后比 Prompt 有价值得多"——护城河资产的最小落库。
 *
 * 三入口：
 * ① POST /observations/from-session/{id}：真机会话聚合自动派生（external_key
 *    = reality-session-{sessionId}-{metric} 幂等，重推跳过）；派生上下文
 *    （设备/环境/任务）由录入者声明——会话本身不含设备元数据（V0.8 设计，如实）。
 * ② POST /observations：手工录入（文献先验 literature / 实测 measured），可关联
 *    V9 failure_record（source_failure_id——"失败+修正"入查询面）。
 * ③ GET /observations：过滤查询（deviceModel/metric/task/provenance），failure
 *    关联 LEFT JOIN 展开。
 *
 * provenance CHECK 强校验（literature/measured/calibrated）——calibrated 级由
 * Track D 校准 ACTIVE 回写产生，本控制器不手填。
 */
@RestController
@RequestMapping("/api/reality")
public class RealityController {

    private static final Logger log = LoggerFactory.getLogger(RealityController.class);
    private static final List<String> PROVENANCE_VALUES = List.of("literature", "measured", "calibrated");

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public RealityController(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    /** 会话派生上下文：由录入者声明（会话不含设备元数据）。task 必填。 */
    public record FromSessionRequest(String deviceModel, Map<String, Object> environment, String task) {
    }

    public record ManualRequest(String deviceModel, Map<String, Object> environment, String task,
                                String metric, Double mean, Double p50, Double p95, Integer samples,
                                String provenance, Long sourceFailureId, String note) {
    }

    /** 真机会话 → 指标分布观测（逐指标一行，幂等 external_key）。 */
    @PostMapping("/observations/from-session/{sessionId}")
    public Result<Map<String, Object>> fromSession(@PathVariable String sessionId,
                                                   @RequestBody FromSessionRequest request) {
        if (request.task() == null || request.task().isBlank()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "task 不能为空（会话不含任务元数据，由录入者声明）");
        }
        Integer sessions = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM real_test_session WHERE id=?::uuid",
                Integer.class, sessionId);
        if (sessions == null || sessions == 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "会话不存在: " + sessionId);
        }
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT metric, count(*)::int AS n, avg(value) AS mean, "
                        + "percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS p50, "
                        + "percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95 "
                        + "FROM telemetry WHERE session_id=?::uuid GROUP BY metric ORDER BY metric",
                sessionId);
        if (rows.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "会话无遥测行，无可派生观测");
        }

        String envJson = objectMapper.valueToTree(
                request.environment() == null ? Map.of() : request.environment()).toString();
        int created = 0, skipped = 0;
        List<Map<String, Object>> obs = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            String metric = String.valueOf(row.get("metric"));
            String extKey = "reality-session-" + sessionId + "-" + metric;
            // ON CONFLICT DO NOTHING（部分唯一索引推断不稳，无目标形式覆盖任一冲突）
            int n = jdbcTemplate.update(
                    "INSERT INTO reality_observation (device_model, environment, task, metric, "
                            + "mean, p50, p95, samples, provenance, source_session_id, external_key, note) "
                            + "VALUES (?, ?::jsonb, ?, ?, ?, ?, ?, ?, 'measured', ?::uuid, ?, ?) "
                            + "ON CONFLICT DO NOTHING",
                    request.deviceModel(), envJson, request.task().trim(), metric,
                    row.get("mean"), row.get("p50"), row.get("p95"),
                    ((Number) row.get("n")).intValue(), sessionId, extKey,
                    "derived from session " + sessionId);
            if (n > 0) {
                created++;
                obs.add(obsRow(metric, row.get("mean"), row.get("p50"), row.get("p95"),
                        ((Number) row.get("n")).intValue(), "measured"));
            } else {
                skipped++;
            }
        }
        log.info("reality observations derived from session {}: created={}, skipped={}",
                sessionId, created, skipped);
        Map<String, Object> out = new HashMap<>();
        out.put("created", created);
        out.put("skipped", skipped);
        out.put("observations", obs);
        return Result.ok(out);
    }

    /** 手工录入（文献先验/实测/failure 关联）。calibrated 级走 Track D 回写，此处拒绝。 */
    @PostMapping("/observations")
    public Result<Map<String, Object>> create(@RequestBody ManualRequest request) {
        if (isBlank(request.task()) || isBlank(request.metric())) {
            throw new BizException(ErrorCode.BAD_REQUEST, "task/metric 不能为空");
        }
        if (request.samples() == null || request.samples() <= 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "samples 须 > 0");
        }
        if (isBlank(request.provenance()) || !PROVENANCE_VALUES.contains(request.provenance())) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "provenance 须为 " + PROVENANCE_VALUES + " 之一");
        }
        if ("calibrated".equals(request.provenance())) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "calibrated 级由校准 ACTIVE 回写产生（Track D），不支持手工录入");
        }
        if (request.mean() == null && request.p50() == null && request.p95() == null) {
            throw new BizException(ErrorCode.BAD_REQUEST, "mean/p50/p95 至少一个非空");
        }
        if (request.sourceFailureId() != null) {
            Integer failures = jdbcTemplate.queryForObject(
                    "SELECT count(*) FROM failure_record WHERE id=?",
                    Integer.class, request.sourceFailureId());
            if (failures == null || failures == 0) {
                throw new BizException(ErrorCode.BAD_REQUEST,
                        "failure_record 不存在: " + request.sourceFailureId());
            }
        }
        String id = jdbcTemplate.queryForObject(
                "INSERT INTO reality_observation (device_model, environment, task, metric, "
                        + "mean, p50, p95, samples, provenance, source_failure_id, note) "
                        + "VALUES (?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id::text",
                String.class, request.deviceModel(),
                objectMapper.valueToTree(request.environment() == null
                        ? Map.of() : request.environment()).toString(),
                request.task().trim(), request.metric().trim(),
                request.mean(), request.p50(), request.p95(), request.samples(),
                request.provenance(), request.sourceFailureId(), request.note());
        Map<String, Object> out = new HashMap<>();
        out.put("id", id);
        out.put("provenance", request.provenance());
        out.put("metric", request.metric());
        return Result.ok(out);
    }

    /** 分布查询（全过滤项可选；failure 关联 LEFT JOIN 展开修正语境）。 */
    @GetMapping("/observations")
    public Result<List<Map<String, Object>>> list(
            @RequestParam(required = false) String deviceModel,
            @RequestParam(required = false) String metric,
            @RequestParam(required = false) String task,
            @RequestParam(required = false) String provenance,
            @RequestParam(required = false, defaultValue = "50") int limit) {
        StringBuilder sql = new StringBuilder(
                "SELECT ro.id::text, ro.device_model, ro.environment::text AS environment, ro.task, "
                        + "ro.metric, ro.mean, ro.p50, ro.p95, ro.samples, ro.provenance, "
                        + "ro.source_session_id::text AS sourceSessionId, "
                        + "ro.source_failure_id, fr.failure_mode, fr.correction, ro.note, "
                        + "ro.created_at::text AS createdAt "
                        + "FROM reality_observation ro "
                        + "LEFT JOIN failure_record fr ON fr.id = ro.source_failure_id WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (deviceModel != null && !deviceModel.isBlank()) {
            sql.append(" AND ro.device_model = ?");
            args.add(deviceModel.trim());
        }
        if (metric != null && !metric.isBlank()) {
            sql.append(" AND ro.metric = ?");
            args.add(metric.trim());
        }
        if (task != null && !task.isBlank()) {
            sql.append(" AND ro.task = ?");
            args.add(task.trim());
        }
        if (provenance != null && !provenance.isBlank()) {
            sql.append(" AND ro.provenance = ?");
            args.add(provenance.trim());
        }
        sql.append(" ORDER BY ro.created_at DESC LIMIT ?");
        args.add(Math.min(Math.max(limit, 1), 200));
        return Result.ok(jdbcTemplate.query(sql.toString(), (rs, i) -> {
            Map<String, Object> m = new HashMap<>();
            m.put("id", rs.getString("id"));
            m.put("deviceModel", rs.getString("device_model"));
            m.put("environment", readEnv(rs.getString("environment")));
            m.put("task", rs.getString("task"));
            m.put("metric", rs.getString("metric"));
            m.put("mean", getDouble(rs, "mean"));
            m.put("p50", getDouble(rs, "p50"));
            m.put("p95", getDouble(rs, "p95"));
            m.put("samples", rs.getInt("samples"));
            m.put("provenance", rs.getString("provenance"));
            m.put("sourceSessionId", rs.getString("sourceSessionId"));
            long failureId = rs.getLong("source_failure_id");
            if (!rs.wasNull()) {
                m.put("sourceFailureId", failureId);
                m.put("failureMode", rs.getString("failure_mode"));
                m.put("correction", rs.getString("correction"));
            }
            m.put("note", rs.getString("note"));
            m.put("createdAt", rs.getString("createdAt"));
            return m;
        }, args.toArray()));
    }

    private Object readEnv(String json) {
        try {
            return objectMapper.readValue(json == null ? "{}" : json, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private static Object getDouble(java.sql.ResultSet rs, String col) throws java.sql.SQLException {
        double v = rs.getDouble(col);
        return rs.wasNull() ? null : v;
    }

    private static Map<String, Object> obsRow(String metric, Object mean, Object p50, Object p95,
                                              int samples, String provenance) {
        Map<String, Object> m = new HashMap<>();
        m.put("metric", metric);
        m.put("samples", samples);
        m.put("provenance", provenance);
        return m;
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
