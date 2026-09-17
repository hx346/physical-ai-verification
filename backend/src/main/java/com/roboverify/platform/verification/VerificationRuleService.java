package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Verification Rule 单源（V1.0 §14 Track C）：显式映射从双处硬编码收敛为版本化
 * 数据表（V13）。V0.8 W2 三族指标键归一教训：散落的映射副本必然漂移。
 *
 * 两 key 语义不同（勿混用）：
 *  - sim-metric-aliases              仿真聚合键 → 解析式聚合键（gap 归一）
 *  - requirement-sim-metric-aliases  需求指标名 → 仿真单 run 指标名（判定链）
 *
 * 读取直查 DB（调用点均为低频路径：报告/判定/摄取），无缓存即无失效问题。
 * 回退语义：无 active 行或表不可读 → 返回内置默认（=V13 seed 值）并 warn 一次
 * ——迁移前/表损坏场景行为不变，不阻断验证链路。
 */
@Service
public class VerificationRuleService {

    private static final Logger log = LoggerFactory.getLogger(VerificationRuleService.class);

    public static final String KEY_SIM_METRIC_ALIASES = "sim-metric-aliases";
    public static final String KEY_REQUIREMENT_SIM_ALIASES = "requirement-sim-metric-aliases";

    /** 内置默认（=V13 seed 逐键一致）——表缺失/无 active 行时的回退，防链路中断。 */
    private static final Map<String, String> DEFAULT_SIM_METRIC_ALIASES = Map.of(
            "pick_success", "success_rate_mean",
            "position_error_mm", "accuracy_p95_mean_mm",
            "cycle_time_s", "cycle_time_s_mean",
            "perception_error_mm", "perception_error_mm_mean");

    private static final Map<String, String> DEFAULT_REQUIREMENT_SIM_ALIASES = Map.of(
            "position_accuracy", "position_error_mm",
            "picking_success_rate", "pick_success");

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public VerificationRuleService(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    /** 仿真聚合键 → 解析式聚合键（gap 归一）。 */
    public Map<String, String> simMetricAliases() {
        return load(KEY_SIM_METRIC_ALIASES, DEFAULT_SIM_METRIC_ALIASES);
    }

    /** 需求指标名 → 仿真单 run 指标名（判定链）。 */
    public Map<String, String> requirementSimAliases() {
        return load(KEY_REQUIREMENT_SIM_ALIASES, DEFAULT_REQUIREMENT_SIM_ALIASES);
    }

    private Map<String, String> load(String ruleKey, Map<String, String> fallback) {
        try {
            String payload = jdbcTemplate.queryForObject(
                    "SELECT payload::text FROM verification_rule WHERE rule_key=? AND active "
                            + "ORDER BY version DESC LIMIT 1",
                    String.class, ruleKey);
            if (payload == null) {
                return fallback;
            }
            JsonNode node = objectMapper.readTree(payload);
            Map<String, String> out = new LinkedHashMap<>();
            node.fieldNames().forEachRemaining(k ->
                    out.put(k, node.get(k).asText()));
            return out.isEmpty() ? fallback : out;
        } catch (Exception e) {
            log.warn("verification_rule 读取失败，回退内置默认 ruleKey={}", ruleKey, e);
            return fallback;
        }
    }
}
