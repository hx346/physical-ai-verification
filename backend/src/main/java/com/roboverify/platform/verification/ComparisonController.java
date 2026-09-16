package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
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
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * V0.5 W2 对照实验：同实验参数（同 seed/n/方法）× 多系统配置臂，逐指标并列 + 差值。
 *
 * 配对采样：seed 固定（ExperimentLaunchService.EXPERIMENT_SEED），run i 在各臂的
 * 参数实例与噪声实例相同——解析臂下差异归因系统配置（demo 第二幕平台化）。
 * 诚实边界：仿真臂当前模板不随 systemConfig 变化（感知链归 W3），其对照差异≈0
 * 是映射边界而非物理结论——随对照结果显式标注。
 */
@RestController
@RequestMapping("/api/experiments/comparisons")
public class ComparisonController {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(ComparisonController.class);
    private static final int MAX_ARMS = 5;

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final ExperimentLaunchService launchService;

    public ComparisonController(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper,
                                ExperimentLaunchService launchService) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.launchService = launchService;
    }

    public record CreateComparisonRequest(
            String projectId,
            List<String> systemConfigIds,
            Integer n,
            String method,
            String backend,
            String label
    ) {
    }

    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody CreateComparisonRequest request) {
        if (request.systemConfigIds() == null || request.systemConfigIds().size() < 2
                || request.systemConfigIds().size() > MAX_ARMS
                || request.systemConfigIds().stream().distinct().count() != request.systemConfigIds().size()) {
            throw new BizException(ErrorCode.BAD_REQUEST);
        }
        boolean simulator = "simulator".equalsIgnoreCase(request.backend());
        // 每臂同参数同 seed 投递（launch 内部校验 system 存在性，不存在即抛错）
        ArrayNode arms = objectMapper.createArrayNode();
        for (int i = 0; i < request.systemConfigIds().size(); i++) {
            String systemConfigId = request.systemConfigIds().get(i);
            String jobKey = launchService.launch(request.projectId(), systemConfigId,
                    request.n(), request.method(), request.backend());
            ObjectNode arm = arms.addObject();
            arm.put("systemConfigId", systemConfigId);
            arm.put("jobKey", jobKey);
            arm.put("index", i);
        }
        String comparisonKey = "cmp:" + ExperimentLaunchService.shortKey(request.projectId())
                + ":" + Long.toHexString(System.currentTimeMillis());
        jdbcTemplate.update(
                "INSERT INTO experiment_comparison (comparison_key, project_id, label, backend, arms) "
                        + "VALUES (?, ?::uuid, ?, ?, ?::jsonb)",
                comparisonKey, request.projectId(), request.label(),
                simulator ? "simulator" : "analytic", arms.toString());
        log.info("comparison created, comparisonKey={}, arms={}", comparisonKey, arms.size());
        return Result.ok(Map.of("comparisonKey", comparisonKey,
                "arms", objectMapper.convertValue(arms, List.class)));
    }

    @GetMapping("/{comparisonKey}")
    public Result<Map<String, Object>> status(@PathVariable String comparisonKey) throws Exception {
        Map<String, Object> row = loadComparison(comparisonKey);
        JsonNode arms = objectMapper.readTree((String) row.get("arms"));
        String backend = (String) row.get("backend");

        List<Map<String, Object>> armStatuses = new ArrayList<>();
        boolean allDone = true;
        boolean anyFailed = false;
        for (JsonNode arm : arms) {
            Map<String, Object> a = loadArm(arm.path("jobKey").asText(),
                    arm.path("systemConfigId").asText());
            armStatuses.add(a);
            String s = (String) a.get("status");
            if (!"SUCCEEDED".equals(s)) {
                allDone = false;
                if ("FAILED".equals(s) || "TIMEOUT".equals(s)) {
                    anyFailed = true;
                }
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("comparisonKey", comparisonKey);
        out.put("label", row.get("label"));
        out.put("backend", backend);
        out.put("createdAt", row.get("created_at"));
        out.put("arms", armStatuses);
        out.put("status", allDone ? "SUCCEEDED" : anyFailed ? "FAILED" : "RUNNING");
        if (allDone) {
            String evidenceId = (String) row.get("evidence_id");
            if (evidenceId == null || evidenceId.isEmpty()) {
                evidenceId = ingestComparison(comparisonKey, backend, armStatuses);
            }
            out.put("comparison", buildComparison(backend, armStatuses));
            out.put("evidenceId", evidenceId);
        }
        return Result.ok(out);
    }

    @GetMapping("/projects/{projectId}")
    public Result<List<Map<String, Object>>> listByProject(@PathVariable String projectId) {
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT comparison_key, label, backend, created_at::text, evidence_id, arms "
                        + "FROM experiment_comparison WHERE project_id=?::uuid ORDER BY id DESC LIMIT 20",
                (rs, i) -> {
                    Map<String, Object> r = new HashMap<>();
                    r.put("comparisonKey", rs.getString(1));
                    r.put("label", rs.getString(2));
                    r.put("backend", rs.getString(3));
                    r.put("createdAt", rs.getString(4));
                    r.put("evidenceId", rs.getString(5));
                    try {
                        r.put("armCount", objectMapper.readTree(rs.getString(6)).size());
                    } catch (Exception e) {
                        r.put("armCount", 0);
                    }
                    return r;
                }, projectId);
        return Result.ok(rows);
    }

    /** 单臂状态：job 状态/进度/结果（结果在时已含 ingestedEvidenceId）。 */
    private Map<String, Object> loadArm(String jobKey, String systemConfigId) throws Exception {
        Map<String, Object> arm = new LinkedHashMap<>();
        arm.put("systemConfigId", systemConfigId);
        arm.put("jobKey", jobKey);
        List<String[]> rows = jdbcTemplate.query(
                "SELECT status, payload::text, last_error FROM job_queue WHERE job_key=?",
                (rs, i) -> new String[]{rs.getString(1), rs.getString(2), rs.getString(3)}, jobKey);
        if (rows.isEmpty()) {
            arm.put("status", "MISSING");
            return arm;
        }
        String[] row = rows.getFirst();
        arm.put("status", row[0]);
        JsonNode payload = objectMapper.readTree(row[1] == null ? "{}" : row[1]);
        JsonNode progress = payload.path("progress");
        if (progress.isObject()) {
            arm.put("progress", objectMapper.convertValue(progress, Map.class));
        }
        if ("SUCCEEDED".equals(row[0])) {
            arm.put("result", objectMapper.convertValue(payload.path("result"), Map.class));
            String ev = payload.path("ingestedEvidenceId").asText("");
            if (!ev.isEmpty()) {
                arm.put("evidenceId", ev);
            }
        } else if (row[2] != null) {
            arm.put("lastError", row[2]);
        }
        return arm;
    }

    /** 全臂完成后摄取对照证据（type=comparison）——幂等（evidence_id 列标记）。 */
    private String ingestComparison(String comparisonKey, String backend,
                                    List<Map<String, Object>> armStatuses) {
        Map<String, Object> comparison = buildComparison(backend, armStatuses);
        String projectId = jdbcTemplate.queryForObject(
                "SELECT project_id::text FROM experiment_comparison WHERE comparison_key=?",
                String.class, comparisonKey);
        String evidenceId = jdbcTemplate.queryForObject(
                "SELECT 'E' || lpad(nextval('evidence_seq')::text, 5, '0')", String.class);
        ObjectNode ir = objectMapper.createObjectNode();
        ir.put("schemaVersion", "0.1.0");
        ir.put("id", evidenceId);
        ir.put("type", "comparison");
        ir.putArray("requirementRefs").add("R001").add("R003");
        ir.put("runRef", comparisonKey);
        ir.put("comparisonKey", comparisonKey);
        ir.put("backend", backend);
        ir.put("projectId", projectId);
        ir.set("comparison", objectMapper.valueToTree(comparison));
        ir.put("traceId", MDC.get("traceId") == null ? "" : MDC.get("traceId"));
        ir.put("createdAt", java.time.OffsetDateTime.now().toString());
        jdbcTemplate.update(
                "INSERT INTO evidence (id, type, run_id, requirement_key, ir) "
                        + "VALUES (?, 'comparison', ?, 'R001', ?::jsonb)",
                evidenceId, comparisonKey, ir.toString());
        jdbcTemplate.update(
                "UPDATE experiment_comparison SET evidence_id=? WHERE comparison_key=?",
                evidenceId, comparisonKey);
        log.info("comparison ingested, comparisonKey={}, evidenceId={}", comparisonKey, evidenceId);
        return evidenceId;
    }

    /** 对照载荷：逐臂指标并列（统一解析/仿真两套聚合口径）+ 相对首臂差值 + 假设清单。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> buildComparison(String backend, List<Map<String, Object>> armStatuses) {
        List<Map<String, Object>> metricsTable = new ArrayList<>();
        for (Map<String, Object> arm : armStatuses) {
            Map<String, Object> result = (Map<String, Object>) arm.get("result");
            Map<String, Object> aggregates = result == null ? Map.of()
                    : (Map<String, Object>) result.getOrDefault("aggregates", Map.of());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("systemConfigId", arm.get("systemConfigId"));
            m.put("jobKey", arm.get("jobKey"));
            m.put("evidenceId", arm.get("evidenceId"));
            for (MetricDef def : metricDefs(backend)) {
                Object value = aggregates.get(def.key);
                m.put(def.key, value);
                if (def.ciKey != null) {
                    m.put(def.ciKey, aggregates.get(def.ciKey));
                }
            }
            m.put("samples", aggregates.get("samples"));
            metricsTable.add(m);
        }
        // 差值相对首臂（基准）
        List<Map<String, Object>> deltas = new ArrayList<>();
        List<MetricDef> defs = metricDefs(backend);
        Map<String, Object> base = metricsTable.getFirst();
        for (int i = 1; i < metricsTable.size(); i++) {
            Map<String, Object> arm = metricsTable.get(i);
            Map<String, Object> d = new LinkedHashMap<>();
            d.put("systemConfigId", arm.get("systemConfigId"));
            d.put("vs", base.get("systemConfigId"));
            for (MetricDef def : defs) {
                Object a0 = base.get(def.key);
                Object a1 = arm.get(def.key);
                if (a0 instanceof Number x0 && a1 instanceof Number x1) {
                    double diff = x1.doubleValue() - x0.doubleValue();
                    d.put(def.key, round(diff));
                    d.put(def.key + "__better", diff == 0 ? null
                            : (diff > 0) == def.higherIsBetter ? arm.get("systemConfigId")
                            : base.get("systemConfigId"));
                }
            }
            deltas.add(d);
        }

        List<Map<String, String>> assumptions = new ArrayList<>();
        assumptions.add(Map.of("name", "paired_sampling", "provenance", "design",
                "note", "同 seed/n/方法投递：run i 在各臂的参数实例与噪声实例相同（配对采样），"
                        + "差异归因系统配置而非采样波动"));
        if ("simulator".equals(backend)) {
            assumptions.add(Map.of("name", "sim_template_identity", "provenance", "design",
                    "note", "仿真模板当前不随 systemConfig 变化（感知闭环归 V0.5 W3）——"
                            + "仿真臂对照差异≈0 是映射边界，非物理结论"));
        } else {
            assumptions.add(Map.of("name", "analytic_model", "provenance", "design",
                    "note", "解析臂差异来自系统配置驱动的误差链模型（假设未校准，ADR-0004 水位规则适用）"));
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("metricKeys", defs.stream().map(d -> d.key).toList());
        out.put("metricLabels", metricLabels(backend));
        out.put("arms", metricsTable);
        out.put("deltas", deltas);
        out.put("assumptions", assumptions);
        return out;
    }

    private record MetricDef(String key, String label, boolean higherIsBetter, String ciKey) {
    }

    private List<MetricDef> metricDefs(String backend) {
        if ("simulator".equals(backend)) {
            return List.of(
                    new MetricDef("pick_success_rate", "抓取成功率", true,
                            "pick_success_rate_ci95_wilson"),
                    new MetricDef("position_error_mm_P95", "定位误差 P95 (mm)", false, null),
                    new MetricDef("cycle_time_s_mean", "循环时间均值 (s)", false, null));
        }
        return List.of(
                new MetricDef("success_rate_mean", "成功率均值", true, null),
                new MetricDef("success_rate_P5", "成功率 P5", true, null),
                new MetricDef("accuracy_p95_mean_mm", "定位精度 P95 均值 (mm)", false, null));
    }

    private Map<String, String> metricLabels(String backend) {
        Map<String, String> labels = new LinkedHashMap<>();
        for (MetricDef d : metricDefs(backend)) {
            labels.put(d.key, d.label);
        }
        return labels;
    }

    private static double round(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    private Map<String, Object> loadComparison(String comparisonKey) {
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT comparison_key, project_id::text, label, backend, arms, evidence_id, "
                        + "created_at::text FROM experiment_comparison WHERE comparison_key=?",
                (rs, i) -> {
                    Map<String, Object> r = new HashMap<>();
                    r.put("comparison_key", rs.getString(1));
                    r.put("project_id", rs.getString(2));
                    r.put("label", rs.getString(3));
                    r.put("backend", rs.getString(4));
                    r.put("arms", rs.getString(5));
                    r.put("evidence_id", rs.getString(6));
                    r.put("created_at", rs.getString(7));
                    return r;
                }, comparisonKey);
        if (rows.isEmpty()) {
            throw new BizException(ErrorCode.JOB_NOT_FOUND);
        }
        return rows.getFirst();
    }
}
