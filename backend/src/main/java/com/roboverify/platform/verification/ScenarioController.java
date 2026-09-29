package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
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
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Scenario Registry（V1.0 场景库填充，V2.0 Optimization 前置资产）：归档的
 * scenario echo 可查可复用（同 scenario+同 seed → SDF 逐位一致）。
 *
 * 双入口：simulation 摄取自动注册（SimulationController 读 result.scenario，
 * label=auto-sim-{jobKey}）+ 手工注册（参数变体命名）。标签检索支持场景库规模统计。
 */
@RestController
@RequestMapping("/api/scenarios")
public class ScenarioController {

    private static final Logger log = LoggerFactory.getLogger(ScenarioController.class);
    /** variant 规范化专用（注入的 mapper 服务于 API 边界，静态规范化独立持有） */
    private static final ObjectMapper CANONICAL = new ObjectMapper();

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public ScenarioController(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public record RegisterRequest(String label, String scene, Map<String, Object> scenario,
                                  List<String> tags, String note) {
    }

    /** 场景库列表（scene/tag 过滤 + 规模统计）。 */
    @GetMapping
    public Result<Map<String, Object>> list(
            @RequestParam(required = false) String scene,
            @RequestParam(required = false) String tag,
            @RequestParam(required = false, defaultValue = "100") int limit) {
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        java.util.List<Object> args = new java.util.ArrayList<>();
        if (scene != null && !scene.isBlank()) {
            where.append(" AND scene=?");
            args.add(scene.trim());
        }
        if (tag != null && !tag.isBlank()) {
            // jsonb 的 ? 操作符与 JDBC 占位符冲突（PG JDBC 需 ?? 转义）——改数组包含
            where.append(" AND tags @> ?::jsonb");
            args.add(tagFilterJson(tag));
        }
        args.add(Math.min(Math.max(limit, 1), 200));
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT id::text, label, scene, tags::text AS tagsJson, source_job_key, note, "
                        + "created_at::text AS createdAt FROM scenario_instance"
                        + where + " ORDER BY created_at DESC LIMIT ?",
                (rs, i) -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("id", rs.getString("id"));
                    m.put("label", rs.getString("label"));
                    m.put("scene", rs.getString("scene"));
                    m.put("tags", readList(rs.getString("tagsJson")));
                    m.put("sourceJobKey", rs.getString("source_job_key"));
                    m.put("note", rs.getString("note"));
                    m.put("createdAt", rs.getString("createdAt"));
                    return m;
                }, args.toArray());
        Map<String, Object> out = new HashMap<>();
        out.put("total", rows.size());
        out.put("items", rows);
        return Result.ok(out);
    }

    /** 场景详情（含完整 scenario echo——复现=同 scenario + 同 seed 重发 simulation）。 */
    @GetMapping("/{id}")
    public Result<Map<String, Object>> detail(@PathVariable String id) {
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT id::text, label, scene, scenario::text AS scenarioJson, "
                        + "tags::text AS tagsJson, source_job_key, note, "
                        + "created_at::text AS createdAt FROM scenario_instance WHERE id=?::bigint",
                (rs, i) -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("id", rs.getString("id"));
                    m.put("label", rs.getString("label"));
                    m.put("scene", rs.getString("scene"));
                    m.put("scenario", readMap(rs.getString("scenarioJson")));
                    m.put("tags", readList(rs.getString("tagsJson")));
                    m.put("sourceJobKey", rs.getString("source_job_key"));
                    m.put("note", rs.getString("note"));
                    m.put("createdAt", rs.getString("createdAt"));
                    return m;
                }, Long.parseLong(id));
        if (rows.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "场景实例不存在: " + id);
        }
        return Result.ok(rows.get(0));
    }

    /** 手工注册场景变体（label 全局唯一——幂等键）。 */
    @PostMapping
    public Result<Map<String, Object>> register(@RequestBody RegisterRequest request) {
        if (isBlank(request.label()) || isBlank(request.scene())) {
            throw new BizException(ErrorCode.BAD_REQUEST, "label/scene 不能为空");
        }
        Map<String, Object> scenario = request.scenario();
        if (scenario == null || scenario.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "scenario 不能为空（应传归档的 scenario echo——全量回显含 fixed_gripper）");
        }
        Integer dup = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM scenario_instance WHERE label=?",
                Integer.class, request.label().trim());
        if (dup != null && dup > 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "label 已存在: " + request.label());
        }
        String id = jdbcTemplate.queryForObject(
                "INSERT INTO scenario_instance (label, scene, scenario, tags, note) "
                        + "VALUES (?, ?, ?::jsonb, ?::jsonb, ?) RETURNING id::text",
                String.class, request.label().trim(), request.scene().trim(),
                objectMapper.valueToTree(scenario).toString(),
                objectMapper.valueToTree(request.tags() == null ? List.of() : request.tags()).toString(),
                request.note());
        log.info("scenario instance registered, id={}, label={}", id, request.label());
        Map<String, Object> out = new HashMap<>();
        out.put("id", id);
        out.put("label", request.label());
        return Result.ok(out);
    }

    /**
     * 跨 seed 泛化分析（2026-09-23，V1.0 后续：模板族"族立起来"→"矩阵铺开"）。
     * 单 seed（42）只保证族内可比，不支撑泛化结论；多 seed 扩展后按 family×seed
     * 聚合 run 结果：pick_rate Wilson 95% 区间 + 定位误差分布。
     * 数据源=scenario_instance.source_job_key ↔ job_queue.result.metrics
     * （自动注册仅发生于 SUCCEEDED 摄取，FAILED run 无场景实例，如实）；手工注册
     * 无 run 的实例不参与统计，仅计数呈现；job_queue 行已修剪（无 FK）的实例
     * LEFT JOIN 保留——变体计数，run 不冒充失败，计 instancesJobMissing。
     */
    @GetMapping("/analysis")
    public Result<Map<String, Object>> analysis(@RequestParam(required = false) String tag) {
        String tagFilter = "";
        List<Object> args = new ArrayList<>();
        if (tag != null && !tag.isBlank()) {
            tagFilter = " AND si.tags @> ?::jsonb";
            args.add(tagFilterJson(tag));
        }
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT si.tags::text AS tagsJson, si.scenario::text AS scenarioJson, "
                        + "j.job_key AS jobKey, "
                        + "j.payload->'result'->'metrics'->>'pick_success' AS pickSuccess, "
                        + "j.payload->'result'->'metrics'->>'position_error_mm' AS positionErrorMm, "
                        + "j.payload->'result'->'metrics'->>'cycle_time_s' AS cycleTimeS "
                        + "FROM scenario_instance si LEFT JOIN job_queue j ON j.job_key = si.source_job_key "
                        + "WHERE si.source_job_key IS NOT NULL" + tagFilter,
                (rs, i) -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("tagsJson", rs.getString("tagsJson"));
                    m.put("jobKey", rs.getString("jobKey"));
                    m.put("scenarioJson", rs.getString("scenarioJson"));
                    m.put("pickSuccess", rs.getString("pickSuccess"));
                    m.put("positionErrorMm", rs.getString("positionErrorMm"));
                    m.put("cycleTimeS", rs.getString("cycleTimeS"));
                    return m;
                }, args.toArray());

        Map<String, FamilyAcc> families = new TreeMap<>();
        int jobMissing = 0;
        for (Map<String, Object> row : rows) {
            String family = readList((String) row.get("tagsJson")).stream()
                    .filter(t -> t.startsWith("family:")).findFirst().orElse("untagged");
            JsonNode scenario = readTree((String) row.get("scenarioJson"));
            Long seed = scenario.path("seed").isNumber() ? scenario.path("seed").asLong() : null;
            FamilyAcc fa = families.computeIfAbsent(family, k -> new FamilyAcc());
            fa.variants.add(variantKey(scenario));
            if (row.get("jobKey") == null) {
                // job_queue 行已修剪（无 FK）：实例仍在库——变体保留计数，run 统计
                // 不冒充（不按失败计），单独如实计数
                jobMissing++;
                continue;
            }
            RunAcc ra = fa.bySeed.computeIfAbsent(seed, k -> new RunAcc());
            ra.n++;
            Double pick = parseDouble((String) row.get("pickSuccess"));
            if (pick != null && pick > 0) {
                ra.successes++;
            }
            addIfPresent(ra.positionErrors, (String) row.get("positionErrorMm"));
            addIfPresent(ra.cycleTimes, (String) row.get("cycleTimeS"));
        }

        List<Map<String, Object>> familyList = new ArrayList<>();
        for (Map.Entry<String, FamilyAcc> entry : families.entrySet()) {
            FamilyAcc fa = entry.getValue();
            RunAcc overall = new RunAcc();
            fa.bySeed.values().forEach(overall::merge);
            List<Map<String, Object>> bySeed = new ArrayList<>();
            List<Long> seeds = new ArrayList<>(fa.bySeed.keySet());
            seeds.sort((a, b) -> a == null ? 1 : b == null ? -1 : Long.compare(a, b));
            double rateMin = 1.0, rateMax = 0.0;
            for (Long seed : seeds) {
                Map<String, Object> cell = cell(fa.bySeed.get(seed));
                cell.put("seed", seed);
                bySeed.add(cell);
                double rate = (double) cell.get("pickRate");
                rateMin = Math.min(rateMin, rate);
                rateMax = Math.max(rateMax, rate);
            }
            Map<String, Object> out = new HashMap<>();
            out.put("family", entry.getKey());
            out.put("variants", fa.variants.size());
            out.put("seeds", seeds);
            out.put("runs", overall.n);
            out.put("overall", cell(overall));
            out.put("bySeed", bySeed);
            if (!bySeed.isEmpty()) {
                out.put("pickRateSpread", Map.of("min", round4(rateMin), "max", round4(rateMax)));
            }
            familyList.add(out);
        }

        // 无 run 的实例（手工注册参数定义）如实计数——不冒充 run 统计
        List<Object> args2 = new ArrayList<>();
        if (!tagFilter.isEmpty()) {
            args2.add(args.get(0));
        }
        Integer noRun = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM scenario_instance si WHERE si.source_job_key IS NULL" + tagFilter,
                Integer.class, args2.toArray());

        Map<String, Object> out = new HashMap<>();
        out.put("families", familyList);
        out.put("instancesWithoutRun", noRun == null ? 0 : noRun);
        out.put("instancesJobMissing", jobMissing);
        return Result.ok(out);
    }

    /** 同族同 seed 单元格：pick_rate Wilson 区间 + 定位误差/节拍分布（P95 最近秩）。 */
    private Map<String, Object> cell(RunAcc ra) {
        Map<String, Object> m = new HashMap<>();
        m.put("n", ra.n);
        m.put("pickRate", ra.n == 0 ? 0.0 : round4((double) ra.successes / ra.n));
        double[] wilson = wilson(ra.successes, ra.n);
        m.put("wilsonLow", round4(wilson[0]));
        m.put("wilsonHigh", round4(wilson[1]));
        Map<String, Object> pos = new HashMap<>();
        pos.put("n", ra.positionErrors.size());
        if (!ra.positionErrors.isEmpty()) {
            pos.put("mean", round4(ra.positionErrors.stream().mapToDouble(Double::doubleValue).average().orElse(0)));
            pos.put("p95", round4(p95NearestRank(ra.positionErrors)));
        }
        m.put("positionErrorMm", pos);
        Map<String, Object> cyc = new HashMap<>();
        cyc.put("n", ra.cycleTimes.size());
        if (!ra.cycleTimes.isEmpty()) {
            cyc.put("mean", round4(ra.cycleTimes.stream().mapToDouble(Double::doubleValue).average().orElse(0)));
        }
        m.put("cycleTimeS", cyc);
        return m;
    }

    /** variant 身份键：scenario 去 seed 后按 key 递归排序的规范 JSON——同变体不同
     *  来源（auto-sim echo / 手工注册）键序不同、数字类型不同（600 与 600.0）也能
     *  归并，多 seed 重跑不虚增 variants。 */
    static String variantKey(JsonNode scenario) {
        JsonNode copy = scenario.deepCopy();
        if (copy.isObject()) {
            ((ObjectNode) copy).remove("seed");
        }
        return sorted(copy).toString();
    }

    /** 递归按 key 排序（Object 内字段名，Array 保序——数组语义有序；数字类型归一
     *  ——600/600.0/6e2 同值同键，手工 int 与 echo float 不虚增 variants）。 */
    private static JsonNode sorted(JsonNode node) {
        if (node.isNumber()) {
            java.math.BigDecimal d = node.decimalValue().stripTrailingZeros();
            if (d.scale() <= 0) {
                try {
                    return CANONICAL.getNodeFactory().numberNode(d.longValueExact());
                } catch (ArithmeticException e) {
                    // 整数值超 long 精度（如 1e20）——BigDecimal 表示，同值仍同键
                }
            }
            return CANONICAL.getNodeFactory().numberNode(d);
        }
        if (node.isObject()) {
            ObjectNode out = CANONICAL.createObjectNode();
            List<String> names = new ArrayList<>();
            node.fieldNames().forEachRemaining(names::add);
            Collections.sort(names);
            for (String name : names) {
                out.set(name, sorted(node.get(name)));
            }
            return out;
        }
        if (node.isArray()) {
            ArrayNode out = CANONICAL.createArrayNode();
            for (JsonNode item : node) {
                out.add(sorted(item));
            }
            return out;
        }
        return node;
    }

    /** Wilson 95% 置信区间（z=1.96）；n=0 返回 [0,0]——不编造区间。 */
    static double[] wilson(int successes, int n) {
        if (n <= 0) {
            return new double[]{0.0, 0.0};
        }
        double z = 1.96;
        double p = (double) successes / n;
        double z2 = z * z;
        double denom = 1 + z2 / n;
        double center = (p + z2 / (2 * n)) / denom;
        double half = z * Math.sqrt(p * (1 - p) / n + z2 / (4.0 * n * n)) / denom;
        return new double[]{Math.max(0.0, center - half), Math.min(1.0, center + half)};
    }

    private static double p95NearestRank(List<Double> values) {
        List<Double> sortedV = new ArrayList<>(values);
        Collections.sort(sortedV);
        int idx = (int) Math.ceil(0.95 * sortedV.size()) - 1;
        return sortedV.get(Math.max(0, Math.min(idx, sortedV.size() - 1)));
    }

    private static void addIfPresent(List<Double> target, String value) {
        Double v = parseDouble(value);
        if (v != null) {
            target.add(v);
        }
    }

    private static Double parseDouble(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Double.parseDouble(value);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static double round4(double v) {
        return Math.round(v * 1e4) / 1e4;
    }

    /** tags 数组包含过滤参数：objectMapper 序列化做完整转义——手拼 JSON 漏转义
     *  反斜杠会产出非法 jsonb（PG invalid input syntax → 500）。 */
    static String tagFilterJson(String tag) {
        return CANONICAL.valueToTree(List.of(tag.trim())).toString();
    }

    private JsonNode readTree(String json) {
        try {
            return objectMapper.readTree(json == null ? "{}" : json);
        } catch (Exception e) {
            return objectMapper.createObjectNode();
        }
    }

    /** 分析聚合的内存累加器（族内按 seed 分桶，overall 由 merge 汇总）。 */
    static class RunAcc {
        int n;
        int successes;
        final List<Double> positionErrors = new ArrayList<>();
        final List<Double> cycleTimes = new ArrayList<>();

        void merge(RunAcc other) {
            n += other.n;
            successes += other.successes;
            positionErrors.addAll(other.positionErrors);
            cycleTimes.addAll(other.cycleTimes);
        }
    }

    static class FamilyAcc {
        final java.util.Set<String> variants = new java.util.HashSet<>();
        // HashMap 容忍 null key（scenario JSON 缺数字 seed 时 seed=null）——TreeMap
        // computeIfAbsent(null) 直接 NPE，单条坏行曾毒化整个 analysis 端点成 500；
        // 输出排序交给 seeds.sort 的 null 末位比较器
        final Map<Long, RunAcc> bySeed = new HashMap<>();
    }

    private Map<String, Object> readMap(String json) {
        try {
            return objectMapper.readValue(json == null ? "{}" : json, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private List<String> readList(String json) {
        try {
            return objectMapper.readValue(json == null ? "[]" : json, List.class);
        } catch (Exception e) {
            return List.of();
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
