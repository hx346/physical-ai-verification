package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.job.JobQueueService;
import com.roboverify.platform.storage.ObjectStore;
import com.roboverify.platform.storage.StorageProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 仿真端点（M2）：Simulation IR → job_queue → gz sim-worker 执行 → 轮询摄取证据。
 * 摄取时归档 scene.sdf / run.log 到对象存储（ObjectStore SPI，默认 local，可切 SeaweedFS），
 * evidence.artifacts 引用 key——矩阵/报告可下钻（ADR-0005）。
 */
@RestController
@RequestMapping("/api/simulations")
public class SimulationController {

    private static final Logger log = LoggerFactory.getLogger(SimulationController.class);
    private static final String JOB_TYPE_SIMULATION = "simulation";

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final JobQueueService jobQueueService;
    private final ObjectStore objectStore;
    private final StorageProperties storageProperties;
    private final VerificationRuleService verificationRuleService;

    public SimulationController(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper,
                                JobQueueService jobQueueService, ObjectStore objectStore,
                                StorageProperties storageProperties,
                                VerificationRuleService verificationRuleService) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.jobQueueService = jobQueueService;
        this.objectStore = objectStore;
        this.storageProperties = storageProperties;
        this.verificationRuleService = verificationRuleService;
    }

    public record CreateRequest(
            @jakarta.validation.constraints.NotBlank(message = "projectId 不能为空") String projectId,
            @jakarta.validation.constraints.NotNull(message = "simulation 不能为空") Map<String, Object> simulation,
            String requirementKey) {
    }

    @PostMapping
    public Result<Map<String, Object>> create(@jakarta.validation.Valid @RequestBody CreateRequest request) {
        String projectId = request.projectId();
        // 短键（evidence.run_id 长度限制）：sim:项目前8:时间戳
        String jobKey = "sim:" + projectId.substring(0, Math.min(8, projectId.length()))
                + ":" + Long.toHexString(System.currentTimeMillis());
        ObjectNode payload = objectMapper.createObjectNode();
        payload.set("simulation", objectMapper.valueToTree(request.simulation()));
        payload.put("projectId", projectId);
        if (request.requirementKey() != null && !request.requirementKey().isBlank()) {
            payload.put("requirementKey", request.requirementKey());
        }
        // 仿真任务带 gz 能力要求：只有 sim-worker（ROBOVERIFY_WORKER_CAPABILITIES=gz）认领
        jobQueueService.enqueue(jobKey, JOB_TYPE_SIMULATION, payload.toString(), MDC.get("traceId"),
                "gz", (short) 60);
        return Result.ok(Map.of("jobKey", jobKey));
    }

    @GetMapping("/{jobKey}")
    public Result<Map<String, Object>> status(@PathVariable String jobKey) throws Exception {
        var job = jobQueueService.getByKey(jobKey);
        Map<String, Object> out = new HashMap<>();
        out.put("jobKey", jobKey);
        out.put("status", job.status());
        out.put("lastError", job.lastError());
        if ("SUCCEEDED".equals(job.status())) {
            Map<String, Object> ingested = ingestIfNeeded(jobKey);
            out.put("result", ingested.get("result"));
            out.put("evidenceId", ingested.get("evidenceId"));
        }
        return Result.ok(out);
    }

    @GetMapping("/projects/{projectId}")
    public Result<List<Map<String, Object>>> listByProject(@PathVariable String projectId) {
        return Result.ok(listEvidence("SELECT id, created_at::text, ir FROM evidence "
                + "WHERE type='simulation' AND ir->>'projectId'=? ORDER BY created_at DESC LIMIT 10", projectId));
    }

    /** 矩阵下钻：按需求键查关联仿真证据。 */
    @GetMapping("/requirements/{requirementKey}")
    public Result<List<Map<String, Object>>> listByRequirement(@PathVariable String requirementKey) {
        return Result.ok(listEvidence("SELECT id, created_at::text, ir FROM evidence "
                + "WHERE type='simulation' AND requirement_key=? ORDER BY created_at DESC LIMIT 10", requirementKey));
    }

    /** worker 完成后首次查询时摄取：结果 → evidence(type=simulation)，SDF/日志归档对象存储。幂等。 */
    private Map<String, Object> ingestIfNeeded(String jobKey) throws Exception {
        String payloadJson = jdbcTemplate.queryForObject(
                "SELECT payload::text FROM job_queue WHERE job_key=?", String.class, jobKey);
        JsonNode payload = objectMapper.readTree(payloadJson);
        JsonNode result = payload.path("result");
        Map<String, Object> out = new HashMap<>();
        out.put("result", objectMapper.convertValue(result, Map.class));
        String existingEvidence = payload.path("ingestedEvidenceId").asText("");
        if (!existingEvidence.isEmpty()) {
            out.put("evidenceId", existingEvidence);
            return out;
        }
        if (result.isMissingNode()) {
            return out;
        }

        String evidenceId = jdbcTemplate.queryForObject(
                "SELECT 'E' || lpad(nextval('evidence_seq')::text, 5, '0')", String.class);
        String projectId = payload.path("projectId").asText("");
        String requirementKey = payload.path("requirementKey").asText("");

        ObjectNode evidenceIr = objectMapper.createObjectNode();
        evidenceIr.put("schemaVersion", "0.1.0");
        evidenceIr.put("id", evidenceId);
        evidenceIr.put("type", "simulation");
        if (!requirementKey.isEmpty()) {
            evidenceIr.putArray("requirementRefs").add(requirementKey);
            // W3 仿真判定链：需求阈值 vs 仿真实测指标（系统判定，不来自任何 LLM；
            // provenance=simulation，与解析/实测维度并列展示）。映射显式可审，
            // 未映射/缺指标 → SIM_UNKNOWN（诚实降级，不猜）。
            JsonNode verdict = judgeSimulation(projectId, requirementKey, result.path("metrics"));
            if (verdict != null) {
                evidenceIr.set("simulationVerdict", verdict);
            }
        }
        evidenceIr.put("runRef", jobKey);
        evidenceIr.put("adapter", "gz-sim 8.10（headless ogre2）");
        evidenceIr.set("metrics", result.path("metrics"));
        evidenceIr.set("requestedMetrics", result.path("requestedMetrics"));
        evidenceIr.set("assumptions", result.path("notes"));
        evidenceIr.set("artifacts", archiveArtifacts(jobKey, result));
        evidenceIr.put("traceId", MDC.get("traceId") == null ? "" : MDC.get("traceId"));
        evidenceIr.put("projectId", projectId);
        evidenceIr.put("createdAt", java.time.OffsetDateTime.now().toString());

        jdbcTemplate.update(
                "INSERT INTO evidence (id, type, run_id, requirement_key, ir) VALUES (?, 'simulation', ?, ?, ?::jsonb)",
                evidenceId, jobKey, requirementKey.isEmpty() ? null : requirementKey, evidenceIr.toString());
        jdbcTemplate.update(
                "UPDATE job_queue SET payload = payload || ?::jsonb WHERE job_key=?",
                "{\"ingestedEvidenceId\":\"" + evidenceId + "\"}", jobKey);
        out.put("evidenceId", evidenceId);
        registerScenario(jobKey, result);
        return out;
    }

    /** V1.0 场景库填充：result 带 scenario echo（V0.9 参数化 v2 归档）时自动注册
     *  Scenario Registry（label=auto-sim-{jobKey} UNIQUE 幂等；复现=同 scenario+同 seed）。 */
    private void registerScenario(String jobKey, JsonNode result) {
        try {
            JsonNode scenario = result.path("scenario");
            if (!scenario.isObject() || scenario.isEmpty()) {
                return;
            }
            String scene = result.path("scene").asText(scenario.path("scene").asText("bin_picking"));
            jdbcTemplate.update(
                    "INSERT INTO scenario_instance (label, scene, scenario, tags, source_job_key, note) "
                            + "VALUES (?, ?, ?::jsonb, '[\"auto\"]'::jsonb, ?, ?) ON CONFLICT (label) DO NOTHING",
                    "auto-sim-" + jobKey, scene, scenario.toString(), jobKey,
                    "auto-registered at simulation ingestion");
            log.info("scenario auto-registered, jobKey={}, scene={}", jobKey, scene);
        } catch (Exception e) {
            log.warn("scenario 自动注册失败（不阻断摄取）jobKey={}", jobKey, e);
        }
    }

    /** 需求指标名 → 仿真指标名：V1.0 Track C 收敛至 VerificationRuleService
     *  （V13 表化 requirement-sim-metric-aliases，seed v1 逐键一致）。 */

    /**
     * W3 仿真判定链：需求阈值（requirement.ir 的 metric/operator/value）vs 仿真实测指标。
     * 系统判定，结论永不来自 LLM；映射未覆盖或指标缺失 → SIM_UNKNOWN（诚实降级）。
     * 单次运行的 percentile 检验不适用——如实标注，不冒充 P95。
     */
    private JsonNode judgeSimulation(String projectId, String requirementKey, JsonNode metrics) {
        JsonNode req;
        try {
            String irJson;
            if (projectId != null && projectId.matches("[0-9a-fA-F-]{36}")) {
                irJson = jdbcTemplate.queryForObject(
                        "SELECT ir::text FROM requirement WHERE req_key=? AND project_id=?::uuid",
                        String.class, requirementKey, projectId);
            } else {
                irJson = jdbcTemplate.queryForObject(
                        "SELECT ir::text FROM requirement WHERE req_key=? ORDER BY created_at DESC LIMIT 1",
                        String.class, requirementKey);
            }
            if (irJson == null) {
                return null;
            }
            req = objectMapper.readTree(irJson);
        } catch (Exception e) {
            log.warn("simulation verdict skipped, requirement lookup failed: {}: {}", requirementKey, e.getMessage());
            return null;
        }

        String reqMetric = req.path("metric").asText("");
        String op = req.path("operator").asText("");
        JsonNode valueNode = req.path("value");
        double threshold = valueNode.asDouble(Double.NaN);
        String simMetric = metrics.has(reqMetric) ? reqMetric
                : verificationRuleService.requirementSimAliases().getOrDefault(reqMetric, "");

        ObjectNode verdict = objectMapper.createObjectNode();
        verdict.put("provenance", "simulation");
        verdict.put("requirementKey", requirementKey);
        verdict.put("requirementMetric", reqMetric);
        verdict.put("operator", op);
        verdict.set("threshold", valueNode);
        verdict.put("unit", req.path("unit").asText(""));

        if (simMetric.isEmpty() || !metrics.has(simMetric)) {
            verdict.put("status", "SIM_UNKNOWN");
            verdict.put("reason", "需求指标 [" + reqMetric + "] 无仿真指标映射（显式映射表未覆盖）");
            return verdict;
        }
        if (op.isEmpty() || Double.isNaN(threshold)
                || !List.of("<=", "<", ">=", ">", "==").contains(op)) {
            verdict.put("status", "SIM_UNKNOWN");
            verdict.put("reason", "需求缺有效 operator/value 阈值");
            return verdict;
        }

        double observed = metrics.path(simMetric).asDouble();
        boolean pass = switch (op) {
            case "<=" -> observed <= threshold;
            case "<" -> observed < threshold;
            case ">=" -> observed >= threshold;
            case ">" -> observed > threshold;
            default -> Math.abs(observed - threshold) < 1e-9; // "=="
        };
        verdict.put("simMetric", simMetric);
        verdict.put("observed", observed);
        verdict.put("status", pass ? "SIM_PASS" : "SIM_FAIL");
        verdict.put("detail", String.format("%s %s %s%s（实测 %s%s）；单次仿真运行，percentile 检验不适用",
                simMetric, op, threshold, verdict.path("unit").asText(),
                observed, verdict.path("unit").asText()));
        log.info("simulation verdict: {} {} observed={} {} threshold={} {}",
                requirementKey, pass ? "SIM_PASS" : "SIM_FAIL", observed, simMetric, threshold, op);
        return verdict;
    }

    /** scene.sdf / run.log → /sim-logs/{jobKey}/…，失败降级（artifacts 省略，证据主体仍落库）。 */
    private ArrayNode archiveArtifacts(String jobKey, JsonNode result) {        ArrayNode artifacts = objectMapper.createArrayNode();
        putArtifact(artifacts, jobKey, "scene.sdf", result.path("sceneSdf").asText(""), "application/xml");
        putArtifact(artifacts, jobKey, "run.log", result.path("logExcerpt").asText(""), "text/plain");
        // V0.9 场景参数化 v2：scenario 回显归档（复现记录：同 scenario+同 seed → 同 SDF；
        // 旧 result 无此键，条件归档兼容）
        if (result.path("scenario").isObject()) {
            putArtifact(artifacts, jobKey, "scenario.json", result.path("scenario").toString(),
                    "application/json");
        }
        return artifacts;
    }

    private void putArtifact(ArrayNode artifacts, String jobKey, String filename, String content, String mediaType) {
        if (content == null || content.isEmpty()) {
            return;
        }
        // jobKey 含 ":"（Windows 文件系统非法字符），对象 key 规范化替换
        // key 不带前导斜杠：LocalFs 视绝对路径为非法（2026-09-15 回归抓出），跨存储规范统一
        String key = "sim-logs/" + jobKey.replace(":", "-") + "/" + filename;
        try {
            byte[] body = content.getBytes(StandardCharsets.UTF_8);
            objectStore.put(key, new ByteArrayInputStream(body), body.length, mediaType);
            ObjectNode artifact = objectMapper.createObjectNode();
            artifact.put("name", filename);
            artifact.put("store", storeName());
            artifact.put("key", key);
            artifact.put("mediaType", mediaType);
            artifacts.add(artifact);
            log.info("simulation artifact archived, key={}, bytes={}", key, body.length);
        } catch (Exception e) {
            // 存储不可用不阻断证据落库（evidence 主体含 metrics/logExcerpt）
            log.warn("artifact archive skipped, key={}: {}", key, e.getMessage());
        }
    }

    private String storeName() {
        return switch (storageProperties.getType()) {
            case "seaweed-s3" -> "seaweedfs";
            case "seafile-webdav" -> "seafile";
            default -> "local";
        };
    }

    private List<Map<String, Object>> listEvidence(String sql, String arg) {
        return jdbcTemplate.query(sql, (rs, i) -> {
            Map<String, Object> row = new HashMap<>();
            row.put("evidenceId", rs.getString(1));
            row.put("createdAt", rs.getString(2));
            try {
                row.put("ir", objectMapper.readValue(rs.getString(3), Map.class));
            } catch (Exception e) {
                row.put("ir", Map.of());
            }
            return row;
        }, arg);
    }
}
