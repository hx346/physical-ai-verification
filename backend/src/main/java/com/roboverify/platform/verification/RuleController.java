package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
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
 * Verification Rule 管理面（V1.0 §14 Track C）：映射规则版本化——新增版本、
 * 激活切换（= 回滚机制：activate 旧版本即回滚）。seed v1 = 原硬编码值。
 * 验证链路运行时读取走 VerificationRuleService（无 active 行回退内置默认）。
 */
@RestController
@RequestMapping("/api/rules")
public class RuleController {

    private static final Logger log = LoggerFactory.getLogger(RuleController.class);

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public RuleController(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public record NewVersionRequest(Map<String, String> payload, String note) {
    }

    /** 各 rule_key 的当前 active 版本。 */
    @GetMapping
    public Result<List<Map<String, Object>>> active() {
        return Result.ok(jdbcTemplate.query(
                "SELECT id::text, rule_key, version, payload::text AS payload, note, "
                        + "created_at::text AS createdAt FROM verification_rule "
                        + "WHERE active ORDER BY rule_key",
                (rs, i) -> row(rs.getString("id"), rs.getString("rule_key"), rs.getInt("version"),
                        rs.getString("payload"), rs.getString("note"), rs.getString("createdAt"), true)));
    }

    /** 某规则的版本历史（新→旧）。 */
    @GetMapping("/{ruleKey}")
    public Result<List<Map<String, Object>>> history(@PathVariable String ruleKey) {
        return Result.ok(jdbcTemplate.query(
                "SELECT id::text, rule_key, version, payload::text AS payload, active, note, "
                        + "created_at::text AS createdAt FROM verification_rule "
                        + "WHERE rule_key=? ORDER BY version DESC",
                (rs, i) -> row(rs.getString("id"), rs.getString("rule_key"), rs.getInt("version"),
                        rs.getString("payload"), rs.getString("note"), rs.getString("createdAt"),
                        rs.getBoolean("active")),
                ruleKey));
    }

    /** 新增版本（默认非 active——改动先落库可审，激活是显式动作）。 */
    @PostMapping("/{ruleKey}/versions")
    public Result<Map<String, Object>> createVersion(@PathVariable String ruleKey,
                                                     @RequestBody NewVersionRequest request) {
        if (request.payload() == null || request.payload().isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "payload 不能为空");
        }
        Integer next = jdbcTemplate.queryForObject(
                "SELECT coalesce(max(version), 0) + 1 FROM verification_rule WHERE rule_key=?",
                Integer.class, ruleKey);
        String id = jdbcTemplate.queryForObject(
                "INSERT INTO verification_rule (rule_key, version, payload, active, note) "
                        + "VALUES (?, ?, ?::jsonb, false, ?) RETURNING id::text",
                String.class, ruleKey, next, objectMapper.valueToTree(request.payload()).toString(),
                request.note());
        log.info("verification rule version created, key={}, version={}", ruleKey, next);
        Map<String, Object> out = new HashMap<>();
        out.put("id", id);
        out.put("ruleKey", ruleKey);
        out.put("version", next);
        out.put("active", false);
        return Result.ok(out);
    }

    /** 激活指定版本（同 key 旧 active 自动撤销）——规则回滚 = activate 旧版本。 */
    @PostMapping("/{ruleKey}/versions/{version}/activate")
    @Transactional(rollbackFor = Exception.class)
    public Result<Map<String, Object>> activate(@PathVariable String ruleKey, @PathVariable int version) {
        Integer exists = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM verification_rule WHERE rule_key=? AND version=?",
                Integer.class, ruleKey, version);
        if (exists == null || exists == 0) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "版本不存在: " + ruleKey + " v" + version);
        }
        jdbcTemplate.update("UPDATE verification_rule SET active=false WHERE rule_key=? AND active",
                ruleKey);
        jdbcTemplate.update(
                "UPDATE verification_rule SET active=true WHERE rule_key=? AND version=?",
                ruleKey, version);
        log.info("verification rule activated, key={}, version={}", ruleKey, version);
        Map<String, Object> out = new HashMap<>();
        out.put("ruleKey", ruleKey);
        out.put("version", version);
        out.put("active", true);
        return Result.ok(out);
    }

    private Map<String, Object> row(String id, String ruleKey, int version, String payload,
                                    String note, String createdAt, boolean active) {
        Map<String, Object> m = new HashMap<>();
        m.put("id", id);
        m.put("ruleKey", ruleKey);
        m.put("version", version);
        try {
            m.put("payload", objectMapper.readValue(payload, Map.class));
        } catch (Exception e) {
            m.put("payload", payload);
        }
        m.put("active", active);
        m.put("note", note);
        m.put("createdAt", createdAt);
        return m;
    }
}
