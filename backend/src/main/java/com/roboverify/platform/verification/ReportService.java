package com.roboverify.platform.verification;

import com.roboverify.platform.storage.ObjectStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * Verification Report v1（Markdown）：可直接进入设计评审（产品方案 §25）。
 * 内容：系统概览 / 需求矩阵 / 逐项证据详情（贡献度+假设+provenance）/ 免责声明。
 * 首次下载时归档快照到对象存储（key: reports/run-{id}/report.md）；
 * 归档失败仅告警不阻断下载（报告是核心交付物，存储是附加）。
 */
@Service
public class ReportService {

    private static final Logger log = LoggerFactory.getLogger(ReportService.class);
    private static final String ARCHIVE_MEDIA_TYPE = "text/markdown";

    private final VerificationRunService runService;
    private final org.springframework.jdbc.core.JdbcTemplate jdbcTemplate;
    private final ObjectStore objectStore;
    private final SimRealGapService simRealGapService;

    public ReportService(VerificationRunService runService,
                         org.springframework.jdbc.core.JdbcTemplate jdbcTemplate,
                         ObjectStore objectStore, SimRealGapService simRealGapService) {
        this.runService = runService;
        this.jdbcTemplate = jdbcTemplate;
        this.objectStore = objectStore;
        this.simRealGapService = simRealGapService;
    }

    /** 渲染并归档首次快照（幂等：已存在则跳过）。 */
    public String renderAndArchive(String runId, String systemName) {
        String markdown = render(runId, systemName);
        String key = "reports/run-" + runId + "/report.md";  // 无前导斜杠：LocalFs 拒绝绝对路径
        try {
            if (!objectStore.exists(key)) {
                byte[] body = markdown.getBytes(StandardCharsets.UTF_8);
                objectStore.put(key, new ByteArrayInputStream(body), body.length, ARCHIVE_MEDIA_TYPE);
                log.info("report archived, key={}, bytes={}", key, body.length);
            }
        } catch (Exception e) {
            log.warn("report archive skipped (store unavailable?), key={}: {}", key, e.getMessage());
        }
        return markdown;
    }

    public String render(String runId, String systemName) {
        List<Map<String, Object>> items = runService.findItems(runId);
        if (items.isEmpty()) {
            return "# Verification Report\n\n> run " + runId + " 无结果\n";
        }
        String projectId = jdbcTemplate.queryForObject(
                "SELECT project_id::text FROM verification_run WHERE id=?::uuid", String.class, runId);
        StringBuilder md = new StringBuilder();
        md.append("# Verification Report\n\n")
                .append("- Run: `").append(runId).append("`\n")
                .append("- System: **").append(systemName == null ? "-" : systemName).append("**\n")
                .append("- Generated: ").append(java.time.OffsetDateTime.now()).append("\n\n");

        md.append("## Verification Matrix\n\n")
                .append("| Requirement | Metric | Current | Required | Result | Evidence |\n")
                .append("|---|---|---:|---:|---|---|\n");
        for (Map<String, Object> item : items) {
            md.append("| ").append(item.get("requirementId"))
                    .append(" | ").append(item.get("metric"))
                    .append(" | ").append(fmt(item.get("observed"))).append(" ").append(orDash(item.get("unit")))
                    .append(" | ").append(orDash(item.get("percentile")))
                    .append(" | **").append(item.get("status")).append("**")
                    .append(" | ").append(orDash(item.get("evidenceId"))).append(" |\n");
        }

        md.append("\n## Evidence Detail\n");
        for (Map<String, Object> item : items) {
            md.append("\n### ").append(item.get("requirementId")).append(" — ").append(item.get("status")).append("\n\n")
                    .append(orDash(item.get("detail"))).append('\n');
            Object evidence = item.get("evidence");
            if (evidence instanceof Map<?, ?> ev) {
                Object result = ev.get("result");
                if (result instanceof Map<?, ?> res) {
                    Object contributors = res.get("contributors");
                    if (contributors instanceof List<?> list && !list.isEmpty()) {
                        md.append("\n贡献度：");
                        for (Object c : list) {
                            if (c instanceof Map<?, ?> cm) {
                                md.append(String.format("%s %.1f%%", cm.get("name"),
                                        ((Number) cm.get("share")).doubleValue() * 100)).append("；");
                            }
                        }
                        md.append('\n');
                    }
                    Object minProv = res.get("minProvenance");
                    if (minProv != null && !String.valueOf(minProv).isBlank()) {
                        md.append("\n> 最低证据来源水位：**").append(minProv)
                          .append("**（低于 measured 的结论待实测确认，ADR-0004）\n");
                    }
                }
                Object assumptions = ev.get("assumptions");
                if (assumptions instanceof List<?> list && !list.isEmpty()) {
                    md.append("\n假设清单：\n");
                    for (Object a : list) {
                        if (a instanceof Map<?, ?> am) {
                            md.append("- [").append(am.get("provenance")).append("] ")
                              .append(am.get("name")).append("：").append(am.get("note")).append('\n');
                        }
                    }
                }
            }
        }

        md.append("\n---\n\n> 声明：解析式结论基于显式假设模型（未校准），仿真/实验/真机证据在后续版本补充；")
          .append("每个判定可经 evidence id 与 traceId 追溯输入指纹与内核版本。\n");
        appendExperimentSection(md, projectId);
        appendComparisonSection(md, projectId);
        appendGapSection(md, projectId);
        return md.toString();
    }

    /**
     * 报告 v2.1（V0.8 W2）：Sim2Real Gap 章节——sim 侧由 SimRealGapService 从项目最新
     * 实验/仿真证据派生（键归一在服务内），real 侧为项目最新真机会话。
     * 诚实边界：无真机会话/无 sim 聚合/runtime 不可用时章节显式标注，不省略不编造。
     */
    @SuppressWarnings("unchecked")
    private void appendGapSection(StringBuilder md, String projectId) {
        if (projectId == null) {
            return;
        }
        md.append("\n## Sim2Real Gap\n\n");
        List<String> sessions = jdbcTemplate.queryForList(
                "SELECT id::text FROM real_test_session WHERE project_id = ?::uuid "
                        + "ORDER BY created_at DESC LIMIT 1",
                String.class, projectId);
        if (sessions.isEmpty()) {
            md.append("> 本项目暂无真机会话——无真机对照（真机数据接入后重新生成报告可补全）。\n");
            return;
        }
        String sessionId = sessions.get(0);
        Map<String, Object> gapResult;
        try {
            gapResult = simRealGapService.gapForSession(sessionId, projectId);
        } catch (com.roboverify.platform.common.exception.BizException e) {
            md.append("> runtime 不可用，本章节缺失（服务恢复后重新生成报告可补全）。\n");
            return;
        }
        if (gapResult.get("gap") == null) {
            md.append("> ").append(orDash(gapResult.get("note"))).append('\n');
            return;
        }
        md.append("- 真机会话：`").append(sessionId).append("`\n")
          .append("- sim 来源：").append(orDash(gapResult.get("simSource"))).append("\n\n");
        Map<String, Object> gap = (Map<String, Object>) gapResult.get("gap");
        Map<String, Object> real = (Map<String, Object>) gapResult.getOrDefault("real", Map.of());
        md.append("| 指标 | sim | real mean | real P95 | gap % | 结论 |\n")
          .append("|---|---:|---:|---:|---:|---|\n");
        gap.forEach((metric, v) -> {
            Map<String, Object> realStats = real.get(metric) instanceof Map<?, ?> r
                    ? (Map<String, Object>) r : Map.of();
            if (v instanceof Map<?, ?> vm && "no_sim_counterpart".equals(vm.get("status"))) {
                md.append("| ").append(metric)
                  .append(" | - | ").append(fmt(realStats.get("mean")))
                  .append(" | ").append(fmt(realStats.get("P95")))
                  .append(" | - | 无仿真对照 |\n");
            } else if (v instanceof Map<?, ?> vm) {
                md.append("| ").append(metric)
                  .append(" | ").append(fmt(vm.get("sim")))
                  .append(" | ").append(fmt(realStats.get("mean")))
                  .append(" | ").append(fmt(realStats.get("P95")))
                  .append(" | ").append(vm.get("gap_percent") == null ? "-"
                          : String.format("%.1f%%", ((Number) vm.get("gap_percent")).doubleValue()))
                  .append(" | ").append(orDash(vm.get("verdict"))).append(" |\n");
            }
        });
        md.append("\n> verdict 语义：within_20pct = sim 与 real 偏差在 ±20% 内；")
          .append("exceeds_20pct = 超 20%（Real2Sim 校准的起点信号）；")
          .append("无仿真对照 = 该指标 sim 侧无对应（如 latency_ms）。\n");
    }

    /** 报告 v2（V0.5 W2）：项目最新对照实验——逐指标并列 + 相对基准差值 + 假设。 */
    @SuppressWarnings("unchecked")
    private void appendComparisonSection(StringBuilder md, String projectId) {
        if (projectId == null) {
            return;
        }
        var rows = jdbcTemplate.query(
                "SELECT ir FROM evidence WHERE type='comparison' AND ir->>'projectId'=? "
                        + "ORDER BY created_at DESC LIMIT 1",
                (rs, i) -> rs.getString("ir"), projectId);
        if (rows.isEmpty()) {
            return;
        }
        try {
            Map<String, Object> ir = new com.fasterxml.jackson.databind.ObjectMapper()
                    .readValue(rows.getFirst(), Map.class);
            Map<String, Object> comparison = (Map<String, Object>) ir.get("comparison");
            if (comparison == null) {
                return;
            }
            md.append("\n## System Configuration Comparison（V0.5 W2）\n\n");
            md.append("- 对照：`").append(orDash(ir.get("comparisonKey"))).append("`")
              .append("（backend=").append(orDash(ir.get("backend"))).append("）\n\n");
            List<Map<String, Object>> arms = (List<Map<String, Object>>) comparison.get("arms");
            Map<String, String> labels = (Map<String, String>) comparison.get("metricLabels");
            List<String> metricKeys = (List<String>) comparison.get("metricKeys");
            if (arms == null || arms.isEmpty() || metricKeys == null) {
                return;
            }
            // 指标并列表：行=指标，列=各臂（首臂为基准）
            md.append("| 指标 |");
            for (Map<String, Object> arm : arms) {
                md.append(" ").append(arm.get("systemConfigId")).append(" |");
            }
            md.append("\n|---|");
            for (int i = 0; i < arms.size(); i++) {
                md.append("---:|");
            }
            md.append('\n');
            for (String key : metricKeys) {
                md.append("| ").append(labels == null ? key : labels.getOrDefault(key, key)).append(" |");
                for (Map<String, Object> arm : arms) {
                    md.append(' ').append(fmt(arm.get(key))).append(" |");
                }
                md.append('\n');
            }
            md.append("| samples |");
            for (Map<String, Object> arm : arms) {
                md.append(' ').append(fmt(arm.get("samples"))).append(" |");
            }
            md.append('\n');

            List<Map<String, Object>> deltas = (List<Map<String, Object>>) comparison.get("deltas");
            if (deltas != null && !deltas.isEmpty()) {
                md.append("\n差值（相对基准臂）：\n\n| 臂 | vs | 指标 | Δ | 更优 |\n|---|---|---|---:|---|\n");
                for (Map<String, Object> d : deltas) {
                    for (String key : metricKeys) {
                        if (d.containsKey(key)) {
                            md.append("| ").append(d.get("systemConfigId"))
                              .append(" | ").append(d.get("vs"))
                              .append(" | ").append(labels == null ? key : labels.getOrDefault(key, key))
                              .append(" | ").append(fmt(d.get(key)))
                              .append(" | ").append(orDash(d.get(key + "__better"))).append(" |\n");
                        }
                    }
                }
            }

            List<Map<String, String>> assumptions = (List<Map<String, String>>) comparison.get("assumptions");
            if (assumptions != null && !assumptions.isEmpty()) {
                md.append("\n对照假设：\n");
                for (Map<String, String> a : assumptions) {
                    md.append("- [").append(a.get("provenance")).append("] ")
                      .append(a.get("name")).append("：").append(a.get("note")).append('\n');
                }
            }
        } catch (Exception ignored) {
            // 对照证据损坏时报告主体仍可输出
        }
    }

    /** 报告 v2：项目最新实验证据（聚合 + Sobol 敏感性排名）。 */
    @SuppressWarnings("unchecked")
    private void appendExperimentSection(StringBuilder md, String projectId) {
        if (projectId == null) {
            return;
        }
        var rows = jdbcTemplate.query(
                "SELECT ir FROM evidence WHERE type='experiment' AND ir->>'projectId'=? "
                        + "ORDER BY created_at DESC LIMIT 1",
                (rs, i) -> rs.getString("ir"), projectId);
        if (rows.isEmpty()) {
            return;
        }
        try {
            Map<String, Object> ir = new com.fasterxml.jackson.databind.ObjectMapper()
                    .readValue(rows.getFirst(), Map.class);
            md.append("\n## Experiment Evidence\n\n");
            Object result = ir.get("result");
            if (result instanceof Map<?, ?> res) {
                res.forEach((k, v) -> md.append("- ").append(k).append(": ").append(v).append('\n'));
            }
            Object sens = ir.get("sensitivityRanking");
            if (sens instanceof List<?> list && !list.isEmpty()) {
                md.append("\n敏感性排名（一阶 Sobol）：\n\n| # | 参数 | 占比 |\n|---|---|---:|\n");
                int rank = 1;
                for (Object s : list) {
                    if (s instanceof Map<?, ?> sm && ((Number) sm.get("share")).doubleValue() > 0.001) {
                        md.append("| ").append(rank++).append(" | ").append(sm.get("name"))
                          .append(" | ").append(String.format("%.1f%%",
                                  ((Number) sm.get("share")).doubleValue() * 100)).append(" |\n");
                    }
                }
            }
            md.append("\n> 实验为解析模型逐样本求值（LHS/MC），gz 仿真证据在 M2 集成后并入。\n");
        } catch (Exception ignored) {
            // 实验证据损坏时报告主体仍可输出
        }
    }

    private static String fmt(Object v) {
        return v instanceof Number n ? String.format("%.4g", n.doubleValue()) : "-";
    }

    private static String orDash(Object v) {
        return v == null ? "-" : String.valueOf(v);
    }
}
