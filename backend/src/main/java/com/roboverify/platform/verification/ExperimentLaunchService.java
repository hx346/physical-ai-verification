package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.roboverify.platform.job.JobQueueService;
import org.slf4j.MDC;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * 实验投递（单批次与对照臂共用）：构建 Experiment payload + 入队。
 * seed 固定——同 n/方法的多次投递得到相同采样矩阵与噪声实例（配对对照的根据）。
 */
@Service
public class ExperimentLaunchService {

    public static final String DEFAULT_EXPERIMENT_ID = "exp-bin-picking-1000";
    public static final String SIM_EXPERIMENT_ID = "exp-bin-picking-sim";
    public static final int DEFAULT_N = 1000;
    public static final int DEFAULT_SIM_N = 50;
    public static final int EXPERIMENT_SEED = 20260914;

    private final IrRepository irRepository;
    private final JobQueueService jobQueueService;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public ExperimentLaunchService(IrRepository irRepository, JobQueueService jobQueueService,
                                   JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.irRepository = irRepository;
        this.jobQueueService = jobQueueService;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    /** 投递一次实验（backend=simulator 时父任务 requires=orchestrator，子 job 由 DAG 展开）。 */
    public String launch(String projectId, String systemConfigId, Integer n, String method,
                         String backend) {
        JsonNode system = irRepository.findSystem(systemConfigId);
        JsonNode environment = irRepository.findEnvironment(projectId);

        List<String> assetIds = new ArrayList<>();
        system.path("components").forEach(c -> assetIds.add(c.path("assetId").asText()));
        List<JsonNode> assets = irRepository.findAssets(assetIds);

        boolean simulator = "simulator".equalsIgnoreCase(backend);
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("projectId", projectId);
        ObjectNode experiment = payload.putObject("experiment");
        experiment.put("schemaVersion", "0.1.0");
        experiment.put("id", simulator ? SIM_EXPERIMENT_ID : DEFAULT_EXPERIMENT_ID);
        buildParameters(experiment);
        ObjectNode sampling = experiment.putObject("sampling");
        sampling.put("method", method == null ? "lhs" : method);
        // 仿真后端默认 50：单次 ~60s wall，50 次 ≈ 1h（DoD 下限）；解析后端默认 1000
        sampling.put("n", n == null ? (simulator ? DEFAULT_SIM_N : DEFAULT_N) : n);
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
        String jobKey = "exp:" + shortKey(projectId) + ":" + shortKey(systemConfigId)
                + ":" + Long.toHexString(System.currentTimeMillis());
        // V0.5 W1 DAG：仿真实验父任务只做编排（采样→展开子 job→收割聚合），在普通
        // worker（orchestrator）执行；单次仿真由子 job requires=gz 路由到 sim-worker。
        // 若父任务仍要求 gz：单 sim-worker 会占住唯一 gz 槽等子任务，自我饿死。
        jobQueueService.enqueue(jobKey, "experiment", payload.toString(), MDC.get("traceId"),
                simulator ? "orchestrator" : null, (short) 60);
        return jobKey;
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

    static String shortKey(String key) {
        String cleaned = key.replaceAll("[^0-9A-Za-z-]", "");
        return cleaned.length() <= 8 ? cleaned : cleaned.substring(0, 8);
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
