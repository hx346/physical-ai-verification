package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.Result;
import org.slf4j.MDC;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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

    public RealTestController(JdbcTemplate jdbcTemplate, RuntimeClient runtimeClient,
                              IrRepository irRepository) {
        this.jdbcTemplate = jdbcTemplate;
        this.runtimeClient = runtimeClient;
        this.irRepository = irRepository;
    }

    public record ImportCsvRequest(String projectId, String csv, String note) {
    }

    /** CSV 格式：ts(ISO),metric,value 每行一条遥测（ROS 2 只读采集导出）。 */
    @PostMapping("/sessions")
    public Result<Map<String, Object>> importCsv(@RequestBody ImportCsvRequest request) {
        String sessionId = jdbcTemplate.queryForObject(
                "INSERT INTO real_test_session (project_id, source, note) VALUES (?::uuid, 'csv_import', ?) "
                        + "RETURNING id::text",
                String.class, request.projectId(), request.note());

        List<Object[]> batch = new ArrayList<>();
        int lines = 0;
        for (String line : request.csv().split("\\r?\\n")) {
            String[] cols = line.trim().split(",");
            if (cols.length != 3 || "ts".equals(cols[0])) {
                continue;
            }
            batch.add(new Object[]{java.util.UUID.fromString(sessionId), cols[0].trim(),
                    cols[1].trim(), Double.parseDouble(cols[2].trim())});
            lines++;
            if (batch.size() >= BATCH_SIZE) {
                flush(batch);
            }
        }
        flush(batch);
        return Result.ok(Map.of("sessionId", sessionId, "imported", lines));
    }

    public record GapRequest(String sessionId, Map<String, Double> simSummary) {
    }

    @PostMapping("/gap")
    public Result<Map<String, Object>> gap(@RequestBody GapRequest request) {
        return Result.ok(runtimeClient.realtestGap(request.sessionId(), request.simSummary()));
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
