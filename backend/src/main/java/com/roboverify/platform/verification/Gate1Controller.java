package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
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
 * Gate 1 执行框架（V0.9，方案 §52：历史项目 Problem Recall ≥70%，否则 STOP）。
 * 流程：录入历史案例（只含当时设计资料，隐藏最终结果）→ 平台跑验证矩阵 →
 * 评审人把每个已知问题与平台判定做语义匹配记录（框架不自动匹配——不编造）→
 * recall 报表。素材未到位时空态可跑（recall=null，status=PENDING）。
 */
@RestController
@RequestMapping("/api/gate1")
public class Gate1Controller {

    private static final double RECALL_THRESHOLD = 0.70;

    private final JdbcTemplate jdbcTemplate;

    public Gate1Controller(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public record CreateCaseRequest(String label, String projectId, List<Map<String, Object>> knownIssues) {
    }

    public record FindingRequest(String knownIssue, String platformVerdict, Boolean matched, String note) {
    }

    /** 录入历史案例。knownIssues=[{issue, severity?, metric?, note?}]，录入后语义不可变。 */
    @PostMapping("/cases")
    public Result<Map<String, Object>> createCase(@RequestBody CreateCaseRequest request) {
        if (request.label() == null || request.label().isBlank()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "label 不能为空");
        }
        if (request.knownIssues() == null || request.knownIssues().isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "knownIssues 不能为空（Gate 1 需要已知问题清单——隐藏结果的对照基准）");
        }
        for (Map<String, Object> issue : request.knownIssues()) {
            if (issue.get("issue") == null || String.valueOf(issue.get("issue")).isBlank()) {
                throw new BizException(ErrorCode.BAD_REQUEST, "knownIssues[].issue 不能为空");
            }
        }
        String id = jdbcTemplate.queryForObject(
                "INSERT INTO gate1_case (label, project_id, known_issues) "
                        + "VALUES (?, ?::uuid, ?::jsonb) RETURNING id::text",
                String.class, request.label().trim(),
                request.projectId() == null || request.projectId().isBlank() ? null : request.projectId().trim(),
                toJson(request.knownIssues()));
        return Result.ok(Map.of("caseId", id));
    }

    /** 案例列表（含已知问题数/已评匹配数）。 */
    @GetMapping("/cases")
    public Result<List<Map<String, Object>>> cases() {
        return Result.ok(jdbcTemplate.query(
                "SELECT c.id::text, c.label, c.project_id::text, c.known_issues, c.created_at::text, "
                        + "COUNT(f.id) AS n_findings, "
                        + "COUNT(f.id) FILTER (WHERE f.matched) AS n_matched "
                        + "FROM gate1_case c LEFT JOIN gate1_finding f ON f.case_id = c.id "
                        + "GROUP BY c.id ORDER BY c.created_at DESC LIMIT 100",
                (rs, i) -> {
                    Map<String, Object> row = new HashMap<>();
                    row.put("id", rs.getString(1));
                    row.put("label", rs.getString(2));
                    row.put("projectId", rs.getString(3));
                    row.put("knownIssues", readJson(rs.getString(4)));
                    row.put("createdAt", rs.getString(5));
                    row.put("nFindings", rs.getLong(6));
                    row.put("nMatched", rs.getLong(7));
                    return row;
                }));
    }

    /** 记录/更新判定匹配（幂等：同案例同问题 upsert）。 */
    @PostMapping("/cases/{id}/findings")
    public Result<Map<String, Object>> upsertFinding(@PathVariable long id,
                                                     @RequestBody FindingRequest request) {
        if (request.knownIssue() == null || request.knownIssue().isBlank()
                || request.platformVerdict() == null || request.platformVerdict().isBlank()
                || request.matched() == null) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "knownIssue / platformVerdict / matched 均不能为空");
        }
        Integer exists = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM gate1_case WHERE id = ?", Integer.class, id);
        if (exists == null || exists == 0) {
            throw new BizException(ErrorCode.BAD_REQUEST, "案例不存在：id=" + id);
        }
        jdbcTemplate.update(
                "INSERT INTO gate1_finding (case_id, known_issue, platform_verdict, matched, note) "
                        + "VALUES (?, ?, ?, ?, ?) "
                        + "ON CONFLICT (case_id, known_issue) DO UPDATE SET "
                        + "platform_verdict = EXCLUDED.platform_verdict, "
                        + "matched = EXCLUDED.matched, note = EXCLUDED.note",
                id, request.knownIssue().trim(), request.platformVerdict().trim(),
                request.matched(), request.note());
        return Result.ok(Map.of("caseId", String.valueOf(id), "knownIssue", request.knownIssue().trim()));
    }

    /**
     * recall 报表。召回率 = matched / 已评已知问题数（未评问题不计入分母——
     * 素材/评审未齐时 status=PENDING，不出 STOP 结论）。
     * Gate 1 完整判定（方案 §52：10 案例 recall ≥70%）在案例数与评审齐备后由本报表给出。
     */
    @GetMapping("/recall")
    public Result<Map<String, Object>> recall() {
        Map<String, Object> out = new HashMap<>();
        long cases = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM gate1_case", Long.class);
        long known = cases == 0 ? 0 : jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM gate1_finding", Long.class);
        long matched = known == 0 ? 0 : jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM gate1_finding WHERE matched", Long.class);
        out.put("cases", cases);
        out.put("evaluatedIssues", known);
        out.put("matched", matched);
        out.put("missed", known - matched);
        Double recall = known == 0 ? null : (double) matched / known;
        out.put("recall", recall);
        out.put("threshold", RECALL_THRESHOLD);
        String status;
        if (known == 0) {
            status = "PENDING";  // 素材未到位——空态可跑，不伪造结论
        } else {
            status = recall >= RECALL_THRESHOLD ? "PASS" : "FAIL";
        }
        out.put("status", status);
        out.put("note", known == 0
                ? "尚无已评问题（Gate 1 素材/评审未齐）——PENDING，不做 STOP 结论"
                : "recall = matched / evaluatedIssues；Gate 1 完整判定需案例与评审齐备（方案 §52）");
        return Result.ok(out);
    }

    private static String toJson(Object o) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
        } catch (Exception e) {
            throw new BizException(ErrorCode.BAD_REQUEST, "knownIssues 不是合法 JSON 结构");
        }
    }

    private static Map<String, Object> readJson(String json) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
        } catch (Exception e) {
            return null;
        }
    }
}
