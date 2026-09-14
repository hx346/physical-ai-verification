package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.exception.BizException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * IR 持久化（requirement / system_config / environment / asset），JSONB 全文存储，
 * 键列冗余走索引。校验在导入端点完成（调 runtime /api/v1/validate，单一契约权威）。
 */
@Repository
public class IrRepository {

    private static final String REQUIREMENT_COLS = "id, project_id, req_key, ir";
    private static final String SYSTEM_COLS = "id, project_id, name, ir";

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public IrRepository(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public void upsertRequirement(String projectId, JsonNode ir) {
        jdbcTemplate.update(
                "INSERT INTO requirement (project_id, req_key, ir) VALUES (?::uuid, ?, ?::jsonb) "
                        + "ON CONFLICT (project_id, req_key) DO UPDATE SET ir = EXCLUDED.ir, updated_at = now()",
                projectId, ir.path("id").asText(), ir.toString());
    }

    public List<JsonNode> findRequirements(String projectId) {
        return jdbcTemplate.query(
                "SELECT " + REQUIREMENT_COLS + " FROM requirement WHERE project_id = ?::uuid ORDER BY req_key",
                (rs, i) -> readTree(rs.getString("ir")), projectId);
    }

    public String insertSystem(String projectId, String name, JsonNode ir) {
        return jdbcTemplate.queryForObject(
                "INSERT INTO system_config (project_id, name, ir) VALUES (?::uuid, ?, ?::jsonb) "
                        + "RETURNING " + SYSTEM_COLS.replace("id, ", "id::text AS id, "),
                (rs, i) -> rs.getString("id"), projectId, name, ir.toString());
    }

    public List<JsonNode> findSystems(String projectId) {
        return jdbcTemplate.query(
                "SELECT ir FROM system_config WHERE project_id = ?::uuid ORDER BY created_at",
                (rs, i) -> readTree(rs.getString("ir")), projectId);
    }

    public JsonNode findSystem(String systemConfigId) {
        return findSystemRow(systemConfigId).ir();
    }

    /** 支持表 uuid 或 System IR 业务键（如 sys-rgbd-binpicking）两种寻址；返回行 uuid + IR。 */
    public record SystemRow(String rowId, JsonNode ir) {
    }

    public SystemRow findSystemRow(String systemConfigId) {
        // PG 的 OR 不短路，::uuid 遇业务键会类型错误 → 统一 id::text 比较
        var rows = jdbcTemplate.query(
                "SELECT id::text AS row_id, ir FROM system_config WHERE id::text = ? OR ir->>'id' = ? LIMIT 1",
                (rs, i) -> new SystemRow(rs.getString("row_id"), readTree(rs.getString("ir"))),
                systemConfigId, systemConfigId);
        if (rows.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "system_config 不存在: " + systemConfigId);
        }
        return rows.getFirst();
    }

    public void upsertEnvironment(String projectId, JsonNode ir) {
        jdbcTemplate.update(
                "INSERT INTO environment (project_id, env_key, ir) VALUES (?::uuid, ?, ?::jsonb) "
                        + "ON CONFLICT (project_id, env_key) DO UPDATE SET ir = EXCLUDED.ir, updated_at = now()",
                projectId, ir.path("id").asText(), ir.toString());
    }

    public JsonNode findEnvironment(String projectId) {
        var rows = jdbcTemplate.query(
                "SELECT ir FROM environment WHERE project_id = ?::uuid ORDER BY created_at LIMIT 1",
                (rs, i) -> readTree(rs.getString("ir")), projectId);
        return rows.isEmpty() ? null : rows.getFirst();
    }

    public List<JsonNode> findAssets(List<String> assetIds) {
        if (assetIds.isEmpty()) {
            return List.of();
        }
        String placeholders = String.join(",", assetIds.stream().map(id -> "?").toList());
        return jdbcTemplate.query(
                "SELECT ir FROM asset WHERE id IN (" + placeholders + ")",
                (rs, i) -> readTree(rs.getString("ir")), assetIds.toArray());
    }

    public List<JsonNode> findAllAssets() {
        return jdbcTemplate.query("SELECT ir FROM asset ORDER BY id",
                (rs, i) -> readTree(rs.getString("ir")));
    }

    private JsonNode readTree(String json) {
        try {
            return objectMapper.readTree(json);
        } catch (Exception e) {
            throw new BizException(ErrorCode.INTERNAL_ERROR, "IR JSON 解析失败");
        }
    }
}
