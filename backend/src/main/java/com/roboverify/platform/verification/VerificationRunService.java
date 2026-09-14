package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 验证编排：需求集 × 系统配置 → 调内核 → verification_run / verification_item / evidence 落库。
 * 每个判定必须产生证据（输入指纹 + 内核版本 + traceId + 假设清单），原则五。
 */
@Service
public class VerificationRunService {

    private static final Logger log = LoggerFactory.getLogger(VerificationRunService.class);

    private static final String STATUS_COMPLETED = "COMPLETED";
    private static final String STATUS_FAILED = "FAILED";
    private static final String EVIDENCE_TYPE_FORMULA = "formula";

    private final IrRepository irRepository;
    private final RuntimeClient runtimeClient;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public VerificationRunService(IrRepository irRepository, RuntimeClient runtimeClient,
                                  JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.irRepository = irRepository;
        this.runtimeClient = runtimeClient;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> run(String projectId, String systemConfigId) {
        String traceId = MDC.get("traceId");
        List<JsonNode> requirements = irRepository.findRequirements(projectId);
        if (requirements.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "项目无需求，先导入需求集");
        }
        IrRepository.SystemRow systemRow = irRepository.findSystemRow(systemConfigId);
        JsonNode system = systemRow.ir();
        JsonNode environment = irRepository.findEnvironment(projectId);

        List<String> assetIds = new ArrayList<>();
        system.path("components").forEach(c -> assetIds.add(c.path("assetId").asText()));
        List<JsonNode> assets = irRepository.findAssets(assetIds);

        // —— 调内核 ——
        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("requestId", "run-" + System.nanoTime());
        payload.put("traceId", traceId == null ? "" : traceId);
        payload.set("requirements", objectMapper.valueToTree(requirements));
        payload.set("system", system);
        if (environment != null) {
            payload.set("environment", environment);
        }
        payload.set("assets", objectMapper.valueToTree(assets));

        String runId = jdbcTemplate.queryForObject(
                "INSERT INTO verification_run (project_id, system_config_id, status, trace_id, started_at) "
                        + "VALUES (?::uuid, ?::uuid, 'RUNNING', ?, now()) RETURNING id::text",
                String.class, projectId, systemRow.rowId(), traceId);

        Map<String, Object> result;
        try {
            result = runtimeClient.verify(jsonToMap(payload));
        } catch (BizException e) {
            jdbcTemplate.update("UPDATE verification_run SET status=?, finished_at=now() WHERE id=?::uuid",
                    STATUS_FAILED, runId);
            throw e;
        }

        String kernelVersion = String.valueOf(result.getOrDefault("kernelVersion", ""));
        String fingerprint = extractFingerprint(result.get("warnings"));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) result.getOrDefault("items", List.of());
        List<Map<String, Object>> persisted = new ArrayList<>();
        for (Map<String, Object> item : items) {
            String evidenceId = persistEvidenceAndItem(runId, item, fingerprint, kernelVersion, traceId);
            Map<String, Object> row = new java.util.HashMap<>(item);
            row.put("evidenceId", evidenceId);
            persisted.add(row);
        }

        jdbcTemplate.update(
                "UPDATE verification_run SET status=?, kernel_version=?, finished_at=now() WHERE id=?::uuid",
                STATUS_COMPLETED, kernelVersion, runId);
        log.info("verification run completed, runId={}, items={}, traceId={}", runId, persisted.size(), traceId);

        return Map.of("runId", runId, "kernelVersion", kernelVersion, "traceId", traceId == null ? "" : traceId,
                "items", persisted);
    }

    public List<Map<String, Object>> findRuns(String projectId) {
        return jdbcTemplate.query(
                "SELECT id::text, status, kernel_version, trace_id, started_at, finished_at "
                        + "FROM verification_run WHERE project_id=?::uuid ORDER BY created_at DESC LIMIT 20",
                (rs, i) -> Map.of(
                        "runId", rs.getString("id"),
                        "status", rs.getString("status"),
                        "kernelVersion", rs.getString("kernel_version") == null ? "" : rs.getString("kernel_version"),
                        "traceId", rs.getString("trace_id") == null ? "" : rs.getString("trace_id")),
                projectId);
    }

    public List<Map<String, Object>> findItems(String runId) {
        return jdbcTemplate.query(
                "SELECT vi.requirement_key, vi.metric, vi.status, vi.observed, vi.unit, vi.percentile, "
                        + "vi.detail, vi.evidence_id, e.ir AS evidence_ir "
                        + "FROM verification_item vi LEFT JOIN evidence e ON e.id = vi.evidence_id "
                        + "WHERE vi.run_id=?::uuid ORDER BY vi.requirement_key",
                (rs, i) -> {
                    Map<String, Object> row = new java.util.HashMap<>();
                    row.put("requirementId", rs.getString("requirement_key"));
                    row.put("metric", rs.getString("metric"));
                    row.put("status", rs.getString("status"));
                    row.put("observed", rs.getBigDecimal("observed"));
                    row.put("unit", rs.getString("unit"));
                    row.put("percentile", rs.getString("percentile"));
                    row.put("detail", rs.getString("detail"));
                    row.put("evidenceId", rs.getString("evidence_id"));
                    String ir = rs.getString("evidence_ir");
                    if (ir != null) {
                        try {
                            row.put("evidence", objectMapper.readValue(ir, Map.class));
                        } catch (Exception ignored) {
                            // 证据 IR 损坏时保底返回空
                        }
                    }
                    return row;
                }, runId);
    }

    /** 证据 + 矩阵行落库；返回 evidence id。 */
    private String persistEvidenceAndItem(String runId, Map<String, Object> item,
                                          String fingerprint, String kernelVersion, String traceId) {
        String reqId = String.valueOf(item.getOrDefault("requirementId", "?"));
        String evidenceId = jdbcTemplate.queryForObject(
                "SELECT 'E' || lpad(nextval('evidence_seq')::text, 5, '0')", String.class);

        ObjectNode evidenceIr = objectMapper.createObjectNode();
        evidenceIr.put("schemaVersion", "0.1.0");
        evidenceIr.put("id", evidenceId);
        evidenceIr.put("type", EVIDENCE_TYPE_FORMULA);
        ArrayNode reqRefs = evidenceIr.putArray("requirementRefs");
        reqRefs.add(reqId);
        evidenceIr.put("runRef", runId);
        evidenceIr.put("kernelVersion", kernelVersion);
        ObjectNode fp = evidenceIr.putObject("inputFingerprint");
        fp.put("algorithm", "sha256");
        fp.put("value", fingerprint);
        ObjectNode res = evidenceIr.putObject("result");
        res.put("status", String.valueOf(item.getOrDefault("status", "UNKNOWN")));
        Object observed = item.get("observed");
        if (observed instanceof Number n) {
            res.put("observed", n.doubleValue());
        }
        res.put("unit", String.valueOf(item.getOrDefault("unit", "")));
        res.put("percentile", String.valueOf(item.getOrDefault("percentile", "")));
        res.put("detail", String.valueOf(item.getOrDefault("detail", "")));
        Object minProv = item.get("minProvenance");
        if (minProv != null) {
            res.put("minProvenance", String.valueOf(minProv));
        }
        if (item.get("contributors") instanceof List<?> contributors) {
            ArrayNode arr = res.putArray("contributors");
            for (Object c : contributors) {
                if (c instanceof Map<?, ?> cm) {
                    ObjectNode cn = arr.addObject();
                    cn.put("name", String.valueOf(cm.get("name")));
                    cn.put("share", ((Number) cm.get("share")).doubleValue());
                }
            }
        }
        if (item.get("assumptions") instanceof List<?> assumptions) {
            ArrayNode arr = evidenceIr.putArray("assumptions");
            for (Object a : assumptions) {
                if (a instanceof Map<?, ?> am) {
                    ObjectNode an = arr.addObject();
                    an.put("name", String.valueOf(am.get("name")));
                    an.put("provenance", String.valueOf(am.get("provenance")));
                    an.put("note", String.valueOf(am.get("note")));
                }
            }
        }
        evidenceIr.put("traceId", traceId == null ? "" : traceId);
        evidenceIr.put("createdAt", java.time.OffsetDateTime.now().toString());

        jdbcTemplate.update(
                "INSERT INTO evidence (id, type, run_id, requirement_key, ir) VALUES (?, ?, ?, ?, ?::jsonb)",
                evidenceId, EVIDENCE_TYPE_FORMULA, runId, reqId, evidenceIr.toString());

        jdbcTemplate.update(
                "INSERT INTO verification_item (run_id, requirement_key, metric, status, observed, unit, "
                        + "percentile, detail, evidence_id) VALUES (?::uuid, ?, ?, ?, ?, ?, ?, ?, ?)",
                runId, reqId,
                String.valueOf(item.getOrDefault("metric", reqId)),
                String.valueOf(item.getOrDefault("status", "UNKNOWN")),
                item.get("observed") instanceof Number n ? n.doubleValue() : null,
                item.get("unit") == null ? null : String.valueOf(item.get("unit")),
                item.get("percentile") == null ? null : String.valueOf(item.get("percentile")),
                item.get("detail") == null ? null : String.valueOf(item.get("detail")),
                evidenceId);
        return evidenceId;
    }

    private String extractFingerprint(Object warnings) {
        if (warnings instanceof List<?> list) {
            for (Object w : list) {
                String s = String.valueOf(w);
                if (s.startsWith("inputFingerprint=")) {
                    return s.substring("inputFingerprint=".length());
                }
            }
        }
        return "";
    }

    private Map<String, Object> jsonToMap(JsonNode node) {
        try {
            return objectMapper.convertValue(node, Map.class);
        } catch (Exception e) {
            throw new BizException(ErrorCode.INTERNAL_ERROR, "payload 转换失败");
        }
    }
}
