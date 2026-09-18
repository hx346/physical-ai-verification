package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import com.fasterxml.jackson.databind.ObjectMapper;
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

import java.util.HashMap;
import java.util.List;
import java.util.Map;

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
            args.add("[\"" + tag.trim().replace("\"", "") + "\"]");
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
