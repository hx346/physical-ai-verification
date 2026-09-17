package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import org.slf4j.MDC;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 真机测试（只读采集链路）+ Real2Sim Gap + 校准版本管理（M4）。
 * 安全边界：本控制器不含任何控制命令下发（architecture.md §9）。
 */
@RestController
@RequestMapping("/api/realtest")
public class RealTestController {

    private static final int BATCH_SIZE = 500;
    private static final String MODEL_TYPE_SENSOR_ERROR = "sensor_error";

    private final JdbcTemplate jdbcTemplate;
    private final RuntimeClient runtimeClient;
    private final IrRepository irRepository;
    private final SimRealGapService simRealGapService;

    public RealTestController(JdbcTemplate jdbcTemplate, RuntimeClient runtimeClient,
                              IrRepository irRepository, SimRealGapService simRealGapService) {
        this.jdbcTemplate = jdbcTemplate;
        this.runtimeClient = runtimeClient;
        this.irRepository = irRepository;
        this.simRealGapService = simRealGapService;
    }

    public record ImportCsvRequest(String projectId, String csv, String note, String externalKey) {
    }

    /**
     * CSV 格式：ts(ISO-8601),metric,value 每行一条遥测（ROS 2 只读采集导出）。
     * externalKey（可选，V0.8 W1）：采集器幂等键——推送超时重试时同 key 返回
     * 已有会话不重复导入（V8 部分唯一索引）。坏行（ts/值不可解析）跳过并计数，
     * 不因一行手工编辑错误弃整批（缺字段跳过、不编造——采集器同语义）。
     */
    @PostMapping("/sessions")
    public Result<Map<String, Object>> importCsv(@RequestBody ImportCsvRequest request) {
        List<String> ids = jdbcTemplate.queryForList(
                "INSERT INTO real_test_session (project_id, source, note, external_key) "
                        + "VALUES (?::uuid, 'csv_import', ?, ?) "
                        + "ON CONFLICT (external_key) WHERE external_key IS NOT NULL DO NOTHING "
                        + "RETURNING id::text",
                String.class, request.projectId(), request.note(), request.externalKey());
        if (ids.isEmpty()) {  // 幂等命中：key 已存在——返回原会话，不重导遥测
            String existing = jdbcTemplate.queryForObject(
                    "SELECT id::text FROM real_test_session WHERE external_key = ?",
                    String.class, request.externalKey());
            return Result.ok(Map.of("sessionId", existing, "imported", 0, "duplicate", true));
        }
        String sessionId = ids.get(0);

        List<Object[]> batch = new ArrayList<>();
        int lines = 0;
        int skipped = 0;
        for (String line : request.csv().split("\\r?\\n")) {
            String[] cols = line.trim().split(",");
            if (cols.length != 3 || "ts".equals(cols[0])) {
                continue;
            }
            try {
                String ts = OffsetDateTime.parse(cols[0].trim()).toString();  // 校验+规范化
                double value = Double.parseDouble(cols[2].trim());
                if (!Double.isFinite(value)) {
                    throw new IllegalArgumentException("non-finite value");
                }
                batch.add(new Object[]{java.util.UUID.fromString(sessionId), ts,
                        cols[1].trim(), value});
            } catch (RuntimeException e) {  // 坏行跳过（如实计数，不编造）
                skipped++;
                continue;
            }
            lines++;
            if (batch.size() >= BATCH_SIZE) {
                flush(batch);
            }
        }
        flush(batch);
        Map<String, Object> out = new HashMap<>();
        out.put("sessionId", sessionId);
        out.put("imported", lines);
        out.put("skipped", skipped);
        return Result.ok(out);
    }

    /** 会话列表（含遥测行数/指标数）——管道演练断言与前端真机页共用。 */
    @GetMapping("/sessions")
    public Result<List<Map<String, Object>>> sessions(
            @RequestParam(required = false) String projectId) {
        String sql = "SELECT s.id::text, s.source, s.note, s.external_key, s.created_at::text, "
                + "COUNT(t.id) AS n_rows, COUNT(DISTINCT t.metric) AS n_metrics "
                + "FROM real_test_session s LEFT JOIN telemetry t ON t.session_id = s.id "
                + (projectId == null ? "" : "WHERE s.project_id = ?::uuid ")
                + "GROUP BY s.id ORDER BY s.created_at DESC LIMIT 50";
        Object[] args = projectId == null ? new Object[0] : new Object[]{projectId};
        return Result.ok(jdbcTemplate.query(sql, (rs, i) -> {
            Map<String, Object> row = new HashMap<>();
            row.put("id", rs.getString(1));
            row.put("source", rs.getString(2));
            row.put("note", rs.getString(3));
            row.put("externalKey", rs.getString(4));
            row.put("createdAt", rs.getString(5));
            row.put("nRows", rs.getLong(6));
            row.put("nMetrics", rs.getLong(7));
            return row;
        }, args));
    }

    /** 单会话逐指标聚合（samples/mean/P50/P95——与 runtime summarize_telemetry 同形）。 */
    @GetMapping("/sessions/{id}/summary")
    public Result<Map<String, Object>> summary(@PathVariable String id) {
        Map<String, Object> metrics = new HashMap<>();
        jdbcTemplate.query(
                "SELECT metric, COUNT(*), AVG(value), "
                        + "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value), "
                        + "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) "
                        + "FROM telemetry WHERE session_id = ?::uuid GROUP BY metric ORDER BY metric",
                rs -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("samples", rs.getInt(2));
                    m.put("mean", rs.getDouble(3));
                    m.put("P50", rs.getDouble(4));
                    m.put("P95", rs.getDouble(5));
                    metrics.put(rs.getString(1), m);
                }, id);
        Map<String, Object> resp = new HashMap<>();
        resp.put("sessionId", id);
        resp.put("metrics", metrics);
        return Result.ok(resp);
    }

    public record GapRequest(String sessionId, Map<String, Double> simSummary) {
    }

    @PostMapping("/gap")
    public Result<Map<String, Object>> gap(@RequestBody GapRequest request) {
        return Result.ok(runtimeClient.realtestGap(request.sessionId(), request.simSummary()));
    }

    /**
     * 会话 Gap（V0.8 W2）：sim 侧由服务端从项目最新实验/仿真证据派生——
     * 前端真机页与报告 Gap 章节共用 SimRealGapService 单一实现。
     */
    @GetMapping("/sessions/{id}/gap")
    public Result<Map<String, Object>> sessionGap(@PathVariable String id) {
        List<String> projects = jdbcTemplate.queryForList(
                "SELECT project_id::text FROM real_test_session WHERE id = ?::uuid",
                String.class, id);
        if (projects.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "会话不存在：id=" + id);
        }
        return Result.ok(simRealGapService.gapForSession(id, projects.get(0)));
    }

    public record CalibrateRequest(
            String systemConfigId,
            Double observedSuccessMean,
            Double occlusion,
            Double objectSizeMm
    ) {
    }

    /** 校准：拟合 depth_sigma_scale → model_version(DRAFT)；激活走 /models/{id}/activate。 */
    @PostMapping("/calibrate")
    public Result<Map<String, Object>> calibrate(@RequestBody CalibrateRequest request) {
        Map<String, Object> system = readMap(irRepository.findSystem(request.systemConfigId()).toString());

        List<String> assetIds = new ArrayList<>();
        ((List<Map<String, Object>>) system.get("components")).forEach(
                c -> assetIds.add(String.valueOf(c.get("assetId"))));
        List<Map<String, Object>> assets = new ArrayList<>();
        if (!assetIds.isEmpty()) {
            String placeholders = String.join(",", assetIds.stream().map(a -> "?").toList());
            assets = jdbcTemplate.query(
                    "SELECT ir FROM asset WHERE id IN (" + placeholders + ")",
                    (rs, i) -> readMap(rs.getString("ir")), assetIds.toArray());
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("system", system);
        payload.put("assets", assets);
        payload.put("observedSuccessMean", request.observedSuccessMean());
        payload.put("occlusion", request.occlusion() == null ? 0.35 : request.occlusion());
        payload.put("objectSizeMm", request.objectSizeMm() == null ? 50.0 : request.objectSizeMm());
        Map<String, Object> fit = runtimeClient.calibrate(payload);

        String cameraAsset = firstCameraAssetId(system);
        String modelId = jdbcTemplate.queryForObject(
                "INSERT INTO model_version (model_type, target_asset, version, lifecycle, params) "
                        + "VALUES (?, ?, ?, 'DRAFT', ?::jsonb) RETURNING id::text",
                String.class, MODEL_TYPE_SENSOR_ERROR, cameraAsset,
                "v" + System.currentTimeMillis(),
                toJson(fit));
        fit.put("modelVersionId", modelId);
        fit.put("lifecycle", "DRAFT");
        return Result.ok(fit);
    }

    @GetMapping("/models")
    public Result<List<Map<String, Object>>> models() {
        return Result.ok(jdbcTemplate.query(
                "SELECT id::text, model_type, target_asset, version, lifecycle, created_at::text "
                        + "FROM model_version ORDER BY created_at DESC LIMIT 20",
                (rs, i) -> {
                    Map<String, Object> row = new HashMap<>();
                    row.put("id", rs.getString(1));
                    row.put("modelType", rs.getString(2));
                    row.put("targetAsset", rs.getString(3));
                    row.put("version", rs.getString(4));
                    row.put("lifecycle", rs.getString(5));
                    row.put("createdAt", rs.getString(6));
                    return row;
                }));
    }

    /** 版本状态机：DRAFT→TESTING→ACTIVE（旧 ACTIVE 自动 DEPRECATED；回滚=再激活旧版本）。 */
    @PostMapping("/models/{id}/activate")
    public Result<Void> activate(@PathVariable String id) {
        String target = jdbcTemplate.queryForObject(
                "SELECT target_asset FROM model_version WHERE id=?::uuid", String.class, id);
        jdbcTemplate.update(
                "UPDATE model_version SET lifecycle='DEPRECATED' WHERE target_asset=? AND lifecycle='ACTIVE'",
                target);
        jdbcTemplate.update(
                "UPDATE model_version SET lifecycle='ACTIVE', activated_at=now() WHERE id=?::uuid", id);
        return Result.ok();
    }

    private void flush(List<Object[]> batch) {
        if (batch.isEmpty()) {
            return;
        }
        jdbcTemplate.batchUpdate(
                "INSERT INTO telemetry (session_id, ts, metric, value) VALUES (?::uuid, ?::timestamptz, ?, ?)",
                batch);
        batch.clear();
    }

    private String firstCameraAssetId(Map<String, Object> system) {
        Object components = system.get("components");
        if (components instanceof List<?> list) {
            for (Object c : list) {
                if (c instanceof Map<?, ?> cm && String.valueOf(cm.get("type")).contains("camera")) {
                    return String.valueOf(cm.get("assetId"));
                }
            }
        }
        return "unknown-camera";
    }

    private Map<String, Object> readMap(String json) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private String toJson(Object o) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }
}
