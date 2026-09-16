package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 实验引擎端点：创建实验（单批次）→ 队列 → worker 执行 → 轮询摄取证据。
 * V0.5 W2：新增批次列表（含进行中进度）；payload 构建与投递抽至 ExperimentLaunchService
 * （对照实验每臂复用同参数同 seed 投递）。
 */
@RestController
@RequestMapping("/api/experiments")
public class ExperimentController {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(ExperimentController.class);

    private final JobQueueService jobQueueService;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final ExperimentLaunchService launchService;

    public ExperimentController(JobQueueService jobQueueService, JdbcTemplate jdbcTemplate,
                                ObjectMapper objectMapper, ExperimentLaunchService launchService) {
        this.jobQueueService = jobQueueService;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.launchService = launchService;
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
        String jobKey = launchService.launch(request.projectId(), request.systemConfigId(),
                request.n(), request.method(), request.backend());
        return Result.ok(Map.of("jobKey", jobKey));
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

    /** V0.5 W2 批次列表（含进行中）：type=experiment 任务 × 项目，进度/证据随查随取。 */
    @GetMapping("/batches")
    public Result<List<Map<String, Object>>> batches(@org.springframework.web.bind.annotation.RequestParam String projectId) {
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT job_key, status, created_at::text, payload::text FROM job_queue "
                        + "WHERE type='experiment' AND payload->>'projectId'=? ORDER BY id DESC LIMIT 50",
                (rs, i) -> {
                    Map<String, Object> row = new HashMap<>();
                    row.put("jobKey", rs.getString(1));
                    row.put("status", rs.getString(2));
                    row.put("createdAt", rs.getString(3));
                    try {
                        JsonNode payload = objectMapper.readTree(rs.getString(4));
                        JsonNode experiment = payload.path("experiment");
                        row.put("backend", experiment.path("backend").asText("analytic"));
                        row.put("n", experiment.path("sampling").path("n").asInt());
                        JsonNode progress = payload.path("progress");
                        if (progress.isObject()) {
                            row.put("progress", objectMapper.convertValue(progress, Map.class));
                        }
                        String evidence = payload.path("ingestedEvidenceId").asText("");
                        if (!evidence.isEmpty()) {
                            row.put("evidenceId", evidence);
                        }
                    } catch (Exception e) {
                        log.debug("batch payload parse failed, row={}", rs.getString(1));
                    }
                    return row;
                }, projectId);
        return Result.ok(rows);
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

        com.fasterxml.jackson.databind.node.ObjectNode evidenceIr = objectMapper.createObjectNode();
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
}
