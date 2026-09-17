package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Gate 2 执行框架（V1.0 §14，方案 §6/§44）：专家审核平台结论，
 * Recommendation Acceptance ≥ 80%。
 * 同 Gate 1 模式：框架只负责记录与报表，verdict 语义全部来自评审人；
 * 素材未到位空态 PENDING，不出 PASS/FAIL 结论。
 * 口径：acceptance = accept / 全部评审（partial 计入分母不算认可——保守，不粉饰）。
 */
@RestController
@RequestMapping("/api/gate2")
public class Gate2Controller {

    private static final Logger log = LoggerFactory.getLogger(Gate2Controller.class);
    private static final double ACCEPTANCE_THRESHOLD = 0.80;

    private final JdbcTemplate jdbcTemplate;

    public Gate2Controller(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public record ReviewRequest(String reviewer, String subject, String verdict, String note) {
    }

    @PostMapping("/reviews")
    public Result<Map<String, Object>> create(@RequestBody ReviewRequest request) {
        if (isBlank(request.reviewer()) || isBlank(request.subject())) {
            throw new BizException(ErrorCode.BAD_REQUEST, "reviewer/subject 不能为空");
        }
        if (!List.of("accept", "reject", "partial").contains(request.verdict())) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "verdict 须为 accept/reject/partial 之一");
        }
        String id = jdbcTemplate.queryForObject(
                "INSERT INTO gate2_review (reviewer, subject, verdict, note) "
                        + "VALUES (?, ?, ?, ?) RETURNING id::text",
                String.class, request.reviewer().trim(), request.subject().trim(),
                request.verdict(), request.note());
        log.info("gate2 review recorded, id={}, subject={}, verdict={}",
                id, request.subject(), request.verdict());
        Map<String, Object> out = new HashMap<>();
        out.put("id", id);
        return Result.ok(out);
    }

    @GetMapping("/reviews")
    public Result<List<Map<String, Object>>> list(
            @org.springframework.web.bind.annotation.RequestParam(required = false) String subject) {
        String sql = "SELECT id::text, reviewer, subject, verdict, note, "
                + "created_at::text AS createdAt FROM gate2_review";
        if (subject != null && !subject.isBlank()) {
            sql += " WHERE subject=? ORDER BY created_at DESC LIMIT 100";
            return Result.ok(jdbcTemplate.queryForList(sql, subject.trim()));
        }
        return Result.ok(jdbcTemplate.queryForList(sql + " ORDER BY created_at DESC LIMIT 100"));
    }

    /** 认可率报表：acceptance = accept/total（partial 计分母不算认可）；空态 PENDING。 */
    @GetMapping("/acceptance")
    public Result<Map<String, Object>> acceptance() {
        Map<String, Object> counts = jdbcTemplate.queryForMap(
                "SELECT count(*)::int AS total, "
                        + "count(*) FILTER (WHERE verdict='accept')::int AS accepted, "
                        + "count(*) FILTER (WHERE verdict='partial')::int AS partial, "
                        + "count(*) FILTER (WHERE verdict='reject')::int AS rejected "
                        + "FROM gate2_review");
        Map<String, Object> out = new HashMap<>();
        int total = ((Number) counts.get("total")).intValue();
        int accepted = ((Number) counts.get("accepted")).intValue();
        out.put("reviews", total);
        out.put("accepted", accepted);
        out.put("partial", ((Number) counts.get("partial")).intValue());
        out.put("rejected", ((Number) counts.get("rejected")).intValue());
        out.put("threshold", ACCEPTANCE_THRESHOLD);
        out.put("note", "Gate 2：3-5 位机器人专家审核平台结论；acceptance=accept/total"
                + "（partial 计分母不算认可，保守口径）");
        if (total == 0) {
            out.put("acceptance", null);
            out.put("status", "PENDING");  // 素材未到位，不出结论
        } else {
            double acc = (double) accepted / total;
            out.put("acceptance", Math.round(acc * 10000.0) / 10000.0);
            out.put("status", acc >= ACCEPTANCE_THRESHOLD ? "PASS" : "FAIL");
        }
        return Result.ok(out);
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
