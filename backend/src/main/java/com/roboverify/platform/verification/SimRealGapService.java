package com.roboverify.platform.verification;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Sim2Real Gap 的 sim 侧聚合派生（V0.8 W2）。
 * 单一实现：报告 Gap 章节与 GET /api/realtest/sessions/{id}/gap 共用，
 * 禁止两处各写一份映射（双实现漂移 = 静默错误）。
 *
 * <p>键归一（关键坑）：runtime gap 端点（main.py）期望<b>解析式引擎</b>聚合键
 * （success_rate_mean / accuracy_p95_mean_mm / cycle_time_s_mean / perception_error_mm_mean），
 * 而<b>仿真后端</b>聚合（sim_backend.py）产出 pick_success_rate / position_error_mm_P95 / …，
 * 单次仿真 run 指标（sequence.py）又是 pick_success / position_error_mm / …——
 * 三族命名在此归一；未覆盖的键如实不派生（不编造 sim 值）。</p>
 */
@Service
public class SimRealGapService {

    private static final Map<String, String> EXPERIMENT_KEY_ALIASES = Map.of(
            "success_rate_mean", "success_rate_mean",
            "pick_success_rate", "success_rate_mean",
            "accuracy_p95_mean_mm", "accuracy_p95_mean_mm",
            "position_error_mm_P95", "accuracy_p95_mean_mm",
            "cycle_time_s_mean", "cycle_time_s_mean",
            "perception_error_mm_mean", "perception_error_mm_mean");

    private static final Map<String, String> SIM_METRIC_ALIASES = Map.of(
            "pick_success", "success_rate_mean",
            "position_error_mm", "accuracy_p95_mean_mm",
            "cycle_time_s", "cycle_time_s_mean",
            "perception_error_mm", "perception_error_mm_mean");

    private final JdbcTemplate jdbcTemplate;
    private final RuntimeClient runtimeClient;

    public SimRealGapService(JdbcTemplate jdbcTemplate, RuntimeClient runtimeClient) {
        this.jdbcTemplate = jdbcTemplate;
        this.runtimeClient = runtimeClient;
    }

    /**
     * 派生项目 sim 侧聚合。优先级：最新 experiment 证据（含 backend=analytic|simulator，
     * 标签如实区分）→ 最新单次 simulation 证据。无可用来源返回 null（gap 上层如实标注）。
     */
    public Map<String, Object> deriveSimSummary(String projectId) {
        if (projectId == null || projectId.isBlank()) {
            return null;
        }
        List<Map<String, Object>> rows = jdbcTemplate.query(
                "SELECT ir FROM evidence WHERE type='experiment' AND ir->>'projectId'=? "
                        + "ORDER BY created_at DESC LIMIT 1",
                (rs, i) -> readMap(rs.getString("ir")), projectId);
        if (!rows.isEmpty()) {
            Map<String, Object> ir = rows.get(0);
            Object result = ir.get("result");
            if (result instanceof Map<?, ?> res) {
                Map<String, Double> summary = mapKeys(res, EXPERIMENT_KEY_ALIASES);
                if (!summary.isEmpty()) {
                    return Map.of("simSummary", summary,
                            "simSource", "experiment:" + orUnknown(ir.get("backend")));
                }
            }
        }
        rows = jdbcTemplate.query(
                "SELECT ir FROM evidence WHERE type='simulation' AND ir->>'projectId'=? "
                        + "ORDER BY created_at DESC LIMIT 1",
                (rs, i) -> readMap(rs.getString("ir")), projectId);
        if (!rows.isEmpty()) {
            Object metrics = ((Map<?, ?>) rows.get(0)).get("metrics");
            if (metrics instanceof Map<?, ?> m) {
                Map<String, Double> summary = mapKeys(m, SIM_METRIC_ALIASES);
                if (!summary.isEmpty()) {
                    return Map.of("simSummary", summary, "simSource", "simulation-run");
                }
            }
        }
        return null;
    }

    /**
     * 会话 Gap：sim 侧从项目证据派生后调 runtime（real 侧聚合在 runtime 完成）。
     * 无 sim 来源不调 runtime，返回 note（诚实边界：sim 侧无对照 ≠ gap 为 0）。
     */
    public Map<String, Object> gapForSession(String sessionId, String projectId) {
        Map<String, Object> derived = deriveSimSummary(projectId);
        Map<String, Object> out = new HashMap<>();
        out.put("sessionId", sessionId);
        if (derived == null) {
            out.put("simSource", null);
            out.put("gap", null);
            out.put("note", "项目暂无实验/仿真聚合——sim 侧无对照");
            return out;
        }
        @SuppressWarnings("unchecked")
        Map<String, Double> simSummary = (Map<String, Double>) derived.get("simSummary");
        out.put("simSource", derived.get("simSource"));
        out.putAll(runtimeClient.realtestGap(sessionId, simSummary));
        return out;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Double> mapKeys(Map<?, ?> from, Map<String, String> aliases) {
        Map<String, Double> out = new HashMap<>();
        for (Map.Entry<?, ?> e : from.entrySet()) {
            String target = aliases.get(String.valueOf(e.getKey()));
            if (target != null && e.getValue() instanceof Number n
                    && !out.containsKey(target)) {  // 首个命中优先，不覆盖
                out.put(target, n.doubleValue());
            }
        }
        return out;
    }

    private static Map<String, Object> readMap(String json) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }

    private static String orUnknown(Object v) {
        return v == null ? "unknown" : String.valueOf(v);
    }
}
