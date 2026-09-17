package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import com.roboverify.platform.job.JobQueueService;
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

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 多参数校准编排（V1.0 §14 Track A'）：真机会话观测 + 参数网格 → DAG 批次仿真
 * → fit_multi_param（MLE + 不可辨识检测）→ model_version DRAFT（版本切换即回滚）。
 *
 * 链路：POST 入队 calibration job（requires=orchestrator，runtime worker 展开
 * 网格点 × repeats 个 simulation 子 job 多 sim-worker 并行）→ GET 轮询，
 * SUCCEEDED 首次查询时摄取写 model_version（幂等，payload 标记模式同 simulation）。
 *
 * 观测 se 诚实边界：成功率正态近似 sqrt(p(1-p)/n)；P95 标准误无闭式，用正态
 * 近似 2.11·σ/√n（φ(1.645)=0.1031 反推）——假设在 params.assumptions 显式标注；
 * 样本 < MIN_SAMPLES 的指标不派生（不编造观测不确定性）。
 */
@RestController
@RequestMapping("/api/calibrations")
public class CalibrationController {

    private static final Logger log = LoggerFactory.getLogger(CalibrationController.class);

    private static final String JOB_TYPE = "calibration";
    /** public：RealTestController activate 回写（Track D）共用，单一事实来源。 */
    public static final String MODEL_TYPE_SIM_PARAMS = "sim_param_calibration";
    private static final int NPARAMS_V1 = 2;
    private static final int MIN_SAMPLES_PER_METRIC = 5;
    private static final double SE_FLOOR = 1e-9;
    // P95 标准误正态近似系数：se(q95) ≈ 2.11·σ/√n（φ(1.645)=0.1031）
    private static final double P95_SE_FACTOR = 2.11;
    private static final String P95_SE_ASSUMPTION =
            "position_error_mm_P95 标准误为正态近似 2.11*sigma/sqrt(n)（无闭式），"
                    + "成功率标准误为 sqrt(p(1-p)/n)；样本数 < " + MIN_SAMPLES_PER_METRIC + " 的指标不派生";

    private final ExperimentLaunchService experimentLaunchService;
    private final JobQueueService jobQueueService;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public CalibrationController(ExperimentLaunchService experimentLaunchService,
                                 JobQueueService jobQueueService,
                                 JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.experimentLaunchService = experimentLaunchService;
        this.jobQueueService = jobQueueService;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public record CreateRequest(String projectId, String systemConfigId, String sessionId,
                                Map<String, List<Double>> paramGrid, Integer runsPerPoint) {
    }

    /** 发起校准。paramGrid 恰 2 参数、每参数 ≥2 档严格递增（镜像引擎校验早失败）。 */
    @PostMapping
    public Result<Map<String, Object>> create(@RequestBody CreateRequest request) {
        validateParamGrid(request.paramGrid());
        Integer sessions = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM real_test_session WHERE id=?::uuid",
                Integer.class, request.sessionId());
        if (sessions == null || sessions == 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "会话不存在: " + request.sessionId());
        }
        Map<String, Object> realObs = telemetryObs(request.sessionId());
        if (realObs.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "会话遥测不足以派生带标准误的观测（每指标需 ≥" + MIN_SAMPLES_PER_METRIC + " 样本）");
        }

        // 单源复用实验仿真上下文（system/environment/assets + simulation 模板）
        ObjectNode payload = experimentLaunchService.buildSimContext(
                request.projectId(), request.systemConfigId(), true);
        ObjectNode sampling = ((ObjectNode) payload.path("experiment")).putObject("sampling");
        sampling.put("seed", ExperimentLaunchService.EXPERIMENT_SEED);
        payload.set("paramGrid", objectMapper.valueToTree(request.paramGrid()));
        payload.put("runsPerPoint", request.runsPerPoint() == null ? 6 : request.runsPerPoint());
        payload.set("realObs", objectMapper.valueToTree(realObs));
        payload.put("sessionId", request.sessionId());
        payload.put("systemConfigId", request.systemConfigId());
        payload.put("assumptions", P95_SE_ASSUMPTION);

        String jobKey = "cal:" + ExperimentLaunchService.shortKey(request.projectId())
                + ":" + ExperimentLaunchService.shortKey(request.sessionId())
                + ":" + Long.toHexString(System.currentTimeMillis());
        jobQueueService.enqueue(jobKey, JOB_TYPE, payload.toString(), MDC.get("traceId"),
                "orchestrator", (short) 60);
        log.info("calibration enqueued, jobKey={}, grid={}, realObs={}",
                jobKey, request.paramGrid().keySet(), realObs.keySet());

        Map<String, Object> out = new HashMap<>();
        out.put("jobKey", jobKey);
        out.put("paramGrid", request.paramGrid());
        out.put("runsPerPoint", request.runsPerPoint() == null ? 6 : request.runsPerPoint());
        out.put("realObs", realObs);
        out.put("assumption", P95_SE_ASSUMPTION);
        return Result.ok(out);
    }

    /** 状态查询 + 首次 SUCCEEDED 时摄取写 model_version DRAFT（幂等）。 */
    @GetMapping("/{jobKey}")
    public Result<Map<String, Object>> status(@PathVariable String jobKey) throws Exception {
        var job = jobQueueService.getByKey(jobKey);
        if (job == null) {
            throw new BizException(ErrorCode.JOB_NOT_FOUND, "校准任务不存在: " + jobKey);
        }
        Map<String, Object> out = new HashMap<>();
        out.put("jobKey", job.jobKey());
        out.put("status", job.status());
        out.put("lastError", job.lastError());
        try {
            String payloadJson = jdbcTemplate.queryForObject(
                    "SELECT payload::text FROM job_queue WHERE job_key=?", String.class, jobKey);
            JsonNode payload = objectMapper.readTree(payloadJson == null ? "{}" : payloadJson);
            JsonNode progress = payload.path("progress");
            if (progress.isObject()) {
                out.put("progress", objectMapper.convertValue(progress, Map.class));
            }
        } catch (Exception e) {
            log.warn("读取校准任务进度失败 jobKey={}", jobKey, e);
        }
        if ("SUCCEEDED".equals(job.status())) {
            ingestIfNeeded(jobKey, out);
        }
        return Result.ok(out);
    }

    /** worker 完成后首次查询时摄取：fit 结果 → model_version DRAFT。幂等。 */
    private void ingestIfNeeded(String jobKey, Map<String, Object> out) throws Exception {
        String payloadJson = jdbcTemplate.queryForObject(
                "SELECT payload::text FROM job_queue WHERE job_key=?", String.class, jobKey);
        JsonNode payload = objectMapper.readTree(payloadJson == null ? "{}" : payloadJson);
        JsonNode result = payload.path("result");
        String existingModel = result.path("ingestedModelVersionId").asText("");
        if (!existingModel.isEmpty()) {
            out.put("result", objectMapper.convertValue(result, Map.class));
            out.put("modelVersionId", existingModel);
            return;
        }
        if (result.isMissingNode()) {
            return;
        }

        // fit 结果整体入 params（含 params/paramCis/identifiable/surface/aggregates）
        ObjectNode params = (ObjectNode) result;
        params.put("jobKey", jobKey);
        // Track D 回写锚点：activate 时按 sessionId 升级来源会话观测为 calibrated
        String sourceSession = payload.path("sessionId").asText("");
        if (!sourceSession.isEmpty()) {
            params.put("sessionId", sourceSession);
        }
        params.put("assumptions", P95_SE_ASSUMPTION);
        String modelId = jdbcTemplate.queryForObject(
                "INSERT INTO model_version (model_type, target_asset, version, lifecycle, params) "
                        + "VALUES (?, ?, ?, 'DRAFT', ?::jsonb) RETURNING id::text",
                String.class, MODEL_TYPE_SIM_PARAMS,
                payload.path("systemConfigId").asText(""),
                "v" + System.currentTimeMillis(),
                objectMapper.writeValueAsString(params));

        // payload 标记回写（同 simulation 摄取模式），二次查询直接复用
        jdbcTemplate.update(
                "UPDATE job_queue SET payload = jsonb_set(payload, "
                        + "'{result,ingestedModelVersionId}', to_jsonb(?::text)) WHERE job_key=?",
                modelId, jobKey);

        out.put("result", objectMapper.convertValue(result, Map.class));
        out.put("modelVersionId", modelId);
        log.info("calibration ingested, jobKey={}, modelVersionId={}, identifiable={}",
                jobKey, modelId, result.path("identifiable").asBoolean());
    }

    /** 会话遥测 → {仿真聚合键: {mean, se, samples}}（se 推导假设见 P95_SE_ASSUMPTION）。 */
    private Map<String, Object> telemetryObs(String sessionId) {
        List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT metric, count(*)::int AS n, avg(value) AS mean, "
                        + "stddev_pop(value) AS sd, "
                        + "percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95 "
                        + "FROM telemetry WHERE session_id=?::uuid GROUP BY metric",
                sessionId);
        Map<String, Object> obs = new HashMap<>();
        for (Map<String, Object> row : rows) {
            String metric = String.valueOf(row.get("metric"));
            int n = ((Number) row.get("n")).intValue();
            if (n < MIN_SAMPLES_PER_METRIC) {
                continue;  // 样本不足不派生（不编造 se）
            }
            double mean = ((Number) row.get("mean")).doubleValue();
            double sd = row.get("sd") == null ? 0.0 : ((Number) row.get("sd")).doubleValue();
            switch (metric) {
                // CSV 指标名 → 仿真聚合键族（与 SimRealGapService 三族归一同口径）
                case "picking_success_rate" -> obs.put("pick_success_rate",
                        obs("mean", mean, Math.sqrt(mean * (1.0 - mean) / n), n));
                case "position_error_mm" -> obs.put("position_error_mm_P95",
                        obs("mean", ((Number) row.get("p95")).doubleValue(),
                                P95_SE_FACTOR * sd / Math.sqrt(n), n));
                case "perception_error_mm" -> obs.put("perception_error_mm_mean",
                        obs("mean", mean, sd / Math.sqrt(n), n));
                default -> { /* cycle_time_s/latency_ms 不入 v1 校准指标集 */ }
            }
        }
        return obs;
    }

    private static Map<String, Object> obs(String key, double mean, double se, int n) {
        Map<String, Object> m = new HashMap<>();
        m.put(key, round4(mean));
        m.put("se", round4(Math.max(se, SE_FLOOR)));
        m.put("samples", n);
        return m;
    }

    private static void validateParamGrid(Map<String, List<Double>> grid) {
        if (grid == null || grid.size() != NPARAMS_V1) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "paramGrid 须恰 " + NPARAMS_V1 + " 个参数（v1 两参数 MLE，如 depth_noise_mm × friction_coeff）");
        }
        for (Map.Entry<String, List<Double>> e : grid.entrySet()) {
            List<Double> vals = e.getValue();
            if (vals == null || vals.size() < 2) {
                throw new BizException(ErrorCode.BAD_REQUEST, "参数 " + e.getKey() + " 须 ≥2 档");
            }
            for (int i = 1; i < vals.size(); i++) {
                if (vals.get(i) <= vals.get(i - 1)) {
                    throw new BizException(ErrorCode.BAD_REQUEST,
                            "参数 " + e.getKey() + " 档位须严格递增");
                }
            }
        }
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }
}
