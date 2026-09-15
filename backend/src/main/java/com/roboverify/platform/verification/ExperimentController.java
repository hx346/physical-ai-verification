package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.job.JobQueueService;
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
 * 实验引擎端点：创建实验（默认 Bin Picking 1000-run 模板）→ 队列 → worker 执行 → 轮询摄取证据。
 */
@RestController
@RequestMapping("/api/experiments")
public class ExperimentController {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(ExperimentController.class);
    private static final String JOB_TYPE_EXPERIMENT = "experiment";
    private static final String DEFAULT_EXPERIMENT_ID = "exp-bin-picking-1000";
    private static final String SIM_EXPERIMENT_ID = "exp-bin-picking-sim";
    private static final int DEFAULT_N = 1000;
    private static final int DEFAULT_SIM_N = 50;
    private static final int EXPERIMENT_SEED = 20260914;

    private final IrRepository irRepository;
    private final JobQueueService jobQueueService;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public ExperimentController(IrRepository irRepository, JobQueueService jobQueueService,
                                JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.irRepository = irRepository;
        this.jobQueueService = jobQueueService;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public record CreateExperimentRequest(
            String projectId,
            String systemConfigId,
            Integer n,
            String method,
            String backend
    ) {
    }

    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody CreateExperimentRequest request) {
        JsonNode system = irRepository.findSystem(request.systemConfigId());
        JsonNode environment = irRepository.findEnvironment(request.projectId());

        List<String> assetIds = new ArrayList<>();
        system.path("components").forEach(c -> assetIds.add(c.path("assetId").asText()));
        List<JsonNode> assets = irRepository.findAssets(assetIds);

        boolean simulator = "simulator".equalsIgnoreCase(request.backend());
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("projectId", request.projectId());
        ObjectNode experiment = payload.putObject("experiment");
        experiment.put("schemaVersion", "0.1.0");
        experiment.put("id", simulator ? SIM_EXPERIMENT_ID : DEFAULT_EXPERIMENT_ID);
        buildParameters(experiment);
        ObjectNode sampling = experiment.putObject("sampling");
        sampling.put("method", request.method() == null ? "lhs" : request.method());
        // 仿真后端默认 50：单次 ~60s wall，50 次 ≈ 1h（DoD 下限）；解析后端默认 1000
        sampling.put("n", request.n() == null ? (simulator ? DEFAULT_SIM_N : DEFAULT_N)
                : request.n());
        sampling.put("seed", EXPERIMENT_SEED);
        sampling.put("batch_size", 50);
        ObjectNode aggregation = experiment.putObject("aggregation");
        aggregation.put("metric", "picking_success_rate");
        aggregation.put("statistic", "success_rate");
        if (simulator) {
            // W4：LHS 采样 → N 次 headless gz；simulation 模板由引擎逐 run 注入
            // 采样参数（object_size/friction/定位噪声）后执行
            experiment.put("backend", "simulator");
            experiment.set("simulation", buildSimulationTemplate());
        }

        payload.set("system", system);
        if (environment != null) {
            payload.set("environment", environment);
        }
        payload.set("assets", objectMapper.valueToTree(assets));

        // 短键：exp:项目前8:系统前8:时间戳（evidence.run_id 有长度限制）
        String jobKey = "exp:" + shortKey(request.projectId()) + ":" + shortKey(request.systemConfigId())
                + ":" + Long.toHexString(System.currentTimeMillis());
        // 仿真实验必须在 sim-worker 执行（requires=gz 能力路由，普通 worker 无 gz）
        jobQueueService.enqueue(jobKey, JOB_TYPE_EXPERIMENT, payload.toString(), MDC.get("traceId"),
                simulator ? "gz" : null, (short) 60);
        return Result.ok(Map.of("jobKey", jobKey));
    }

    /** 仿真实验的单次运行模板：单件箱内抓取（定位噪声→抓取成败的机制最干净）。 */
    private ObjectNode buildSimulationTemplate() {
        ObjectNode sim = objectMapper.createObjectNode();
        sim.put("schemaVersion", "0.1.0");
        sim.put("scene", "bin_picking");
        ObjectNode env = sim.putObject("environment");
        env.put("environment_ref", "env-bin-picking-demo");
        env.put("seed", 42);
        ObjectNode overrides = env.putObject("overrides");
        overrides.put("n_parts", 1);
        ObjectNode script = sim.putObject("script");
        script.put("type", "scripted_pick");
        ObjectNode params = script.putObject("params");
        params.put("approach_speed_mm_s", 200);
        params.put("grasp_force_n", 60);
        ArrayNode metrics = sim.putArray("metrics_to_collect");
        metrics.add("pick_success").add("cycle_time_s")
                .add("collision_count").add("position_error_mm");
        sim.put("timeout_s", 120);
        return sim;
    }

    private static String shortKey(String key) {
        String cleaned = key.replaceAll("[^0-9A-Za-z-]", "");
        return cleaned.length() <= 8 ? cleaned : cleaned.substring(0, 8);
    }

    @GetMapping("/{jobKey}")
    public Result<Map<String, Object>> status(@PathVariable String jobKey) throws Exception {
        var job = jobQueueService.getByKey(jobKey);
        Map<String, Object> out = new HashMap<>();
        out.put("jobKey", job.jobKey());
        out.put("status", job.status());
        out.put("lastError", job.lastError());
        // V0.5 W1.4：批量仿真实验的批次进度（worker 每 run 完成写 payload.progress）
        try {
            String payloadJson = jdbcTemplate.queryForObject(
                    "SELECT payload::text FROM job_queue WHERE job_key=?", String.class, jobKey);
            JsonNode progress = objectMapper.readTree(payloadJson == null ? "{}" : payloadJson)
                    .path("progress");
            if (progress.isObject()) {
                out.put("progress", objectMapper.convertValue(progress, Map.class));
            }
        } catch (Exception e) {
            log.debug("progress unavailable, jobKey={}: {}", jobKey, e.getMessage());
        }

        if ("SUCCEEDED".equals(job.status())) {
            Map<String, Object> ingested = ingestIfNeeded(jobKey);
            out.put("result", ingested.get("result"));
            out.put("evidenceId", ingested.get("evidenceId"));
        }
        return Result.ok(out);
    }

    @GetMapping("/projects/{projectId}")
    public Result<List<Map<String, Object>>> listByProject(@PathVariable String projectId) {
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT id, created_at::text, ir FROM evidence "
                        + "WHERE type='experiment' AND ir->>'projectId'=? ORDER BY created_at DESC LIMIT 10",
                (rs, i) -> {
                    Map<String, Object> row = new HashMap<>();
                    row.put("evidenceId", rs.getString(1));
                    row.put("createdAt", rs.getString(2));
                    try {
                        row.put("ir", objectMapper.readValue(rs.getString(3), Map.class));
                    } catch (Exception e) {
                        row.put("ir", Map.of());
                    }
                    return row;
                }, projectId);
        return Result.ok(rows);
    }

    /** worker 完成后首次查询时摄取：结果 → evidence(type=experiment)。幂等（payload.ingested 标记）。 */
    private Map<String, Object> ingestIfNeeded(String jobKey) throws Exception {
        String payloadJson = jdbcTemplate.queryForObject(
                "SELECT payload::text FROM job_queue WHERE job_key=?", String.class, jobKey);
        JsonNode payload = objectMapper.readTree(payloadJson);
        JsonNode result = payload.path("result");
        Map<String, Object> out = new HashMap<>();
        out.put("result", objectMapper.convertValue(result, Map.class));
        // 轮询会多次触发：首次摄取后 evidenceId 存入 payload，后续读取返回
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

        ObjectNode evidenceIr = objectMapper.createObjectNode();
        evidenceIr.put("schemaVersion", "0.1.0");
        evidenceIr.put("id", evidenceId);
        evidenceIr.put("type", "experiment");
        evidenceIr.putArray("requirementRefs").add("R001").add("R003");
        evidenceIr.put("runRef", jobKey);
        evidenceIr.put("kernelVersion", "0.1.0");
        if (result.hasNonNull("backend")) {
            evidenceIr.put("backend", result.path("backend").asText());
        }
        evidenceIr.set("result", result.path("aggregates"));
        evidenceIr.set("sensitivityRanking", result.path("sensitivity"));
        evidenceIr.set("assumptions", result.path("assumptions"));
        evidenceIr.put("traceId", MDC.get("traceId") == null ? "" : MDC.get("traceId"));
        evidenceIr.put("projectId", projectId);
        evidenceIr.put("createdAt", java.time.OffsetDateTime.now().toString());

        jdbcTemplate.update(
                "INSERT INTO evidence (id, type, run_id, requirement_key, ir) VALUES (?, 'experiment', ?, 'R001', ?::jsonb)",
                evidenceId, jobKey, evidenceIr.toString());
        jdbcTemplate.update(
                "UPDATE job_queue SET payload = payload || ?::jsonb WHERE job_key=?",
                "{\"ingestedEvidenceId\":\"" + evidenceId + "\"}", jobKey);
        out.put("evidenceId", evidenceId);
        return out;
    }

    private void buildParameters(ObjectNode experiment) {
        // depth_noise 上限 15mm：W4 容差探测实测（σ=0 成功 / σ=20 单实例 4σ 偏移
        // 下刀被顶卡死）——上限取翻转点下方，保证批内成败混合（敏感性信号存在）
        String[][] params = {
                {"illumination_lux", "uniform", "100", "50000", "lux"},
                {"occlusion_percent", "uniform", "0", "70", "%"},
                {"depth_noise_mm", "uniform", "0", "15", "mm"},
                {"object_size_mm", "uniform", "20", "80", "mm"},
                {"network_latency_ms", "uniform", "5", "200", "ms"},
                {"friction_coeff", "uniform", "0.1", "0.9", ""},
        };
        ArrayNode array = experiment.putArray("parameters");
        for (String[] p : params) {
            ObjectNode node = array.addObject();
            node.put("name", p[0]);
            node.put("distribution", p[1]);
            node.putArray("range").add(Double.parseDouble(p[2])).add(Double.parseDouble(p[3]));
            node.put("unit", p[4]);
        }
    }
}
