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
 * 首次下载时归档快照到对象存储（key: /reports/run-{id}/report.md）；
 * 归档失败仅告警不阻断下载（报告是核心交付物，存储是附加）。
 */
@Service
public class ReportService {

    private static final Logger log = LoggerFactory.getLogger(ReportService.class);
    private static final String ARCHIVE_MEDIA_TYPE = "text/markdown";

    private final VerificationRunService runService;
    private final org.springframework.jdbc.core.JdbcTemplate jdbcTemplate;
    private final ObjectStore objectStore;

    public ReportService(VerificationRunService runService,
                         org.springframework.jdbc.core.JdbcTemplate jdbcTemplate,
                         ObjectStore objectStore) {
        this.runService = runService;
        this.jdbcTemplate = jdbcTemplate;
        this.objectStore = objectStore;
    }

    /** 渲染并归档首次快照（幂等：已存在则跳过）。 */
    public String renderAndArchive(String runId, String systemName) {
        String markdown = render(runId, systemName);
        String key = "/reports/run-" + runId + "/report.md";
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
        return md.toString();
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
