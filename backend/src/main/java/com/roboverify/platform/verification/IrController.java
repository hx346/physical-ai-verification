package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.roboverify.platform.common.api.ErrorCode;
import com.roboverify.platform.common.api.Result;
import com.roboverify.platform.common.exception.BizException;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.InputStream;
import java.util.List;
import java.util.Map;

/**
 * IR 导入/查询 + 资产列表 + Demo 种子。
 * 所有导入必须先过 runtime /api/v1/validate（JSON Schema 单一权威，ADR-0001）。
 */
@RestController
@RequestMapping("/api/projects/{projectId}")
public class IrController {

    private static final com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>> MAP_TYPE =
            new com.fasterxml.jackson.core.type.TypeReference<>() {};


    private final IrRepository irRepository;
    private final RuntimeClient runtimeClient;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public IrController(IrRepository irRepository, RuntimeClient runtimeClient,
                        JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.irRepository = irRepository;
        this.runtimeClient = runtimeClient;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @PostMapping("/requirements")
    public Result<Integer> importRequirements(@PathVariable String projectId,
                                              @RequestBody List<Map<String, Object>> requirements) {
        ensureProject(projectId);
        int count = 0;
        for (Map<String, Object> req : requirements) {
            JsonNode node = objectMapper.convertValue(req, JsonNode.class);
            requireValid("requirement", node);
            irRepository.upsertRequirement(projectId, node);
            count++;
        }
        return Result.ok(count);
    }

    @GetMapping("/requirements")
    public Result<List<Map<String, Object>>> listRequirements(@PathVariable String projectId) {
        // HTTP 层为 Jackson 3，不识别 Jackson 2 JsonNode；出口统一转 Map
        return Result.ok(irRepository.findRequirements(projectId).stream()
                .map(node -> objectMapper.convertValue(node, MAP_TYPE))
                .toList());
    }

    public record ImportSystemRequest(String name, Map<String, Object> ir) {
    }

    @PostMapping("/systems")
    public Result<String> importSystem(@PathVariable String projectId,
                                       @RequestBody ImportSystemRequest request) {
        ensureProject(projectId);
        if (request.ir() == null) {
            throw new BizException(ErrorCode.BAD_REQUEST, "ir 不能为空");
        }
        JsonNode ir = objectMapper.convertValue(request.ir(), JsonNode.class);
        requireValid("system", ir);
        return Result.ok(irRepository.insertSystem(projectId, request.name(), ir));
    }

    @GetMapping("/systems")
    public Result<List<Map<String, Object>>> listSystems(@PathVariable String projectId) {
        return Result.ok(irRepository.findSystems(projectId).stream()
                .map(node -> objectMapper.convertValue(node, MAP_TYPE))
                .toList());
    }

    @PostMapping("/environment")
    public Result<Void> importEnvironment(@PathVariable String projectId, @RequestBody Map<String, Object> body) {
        ensureProject(projectId);
        JsonNode ir = objectMapper.convertValue(body, JsonNode.class);
        requireValid("environment", ir);
        irRepository.upsertEnvironment(projectId, ir);
        return Result.ok();
    }

    /** 导入 Bin Picking Demo 数据（需求集 + 环境 + 两个系统配置），幂等。 */
    @PostMapping("/seed-demo")
    public Result<Map<String, Integer>> seedDemo(@PathVariable String projectId) throws Exception {
        ensureProject(projectId);
        JsonNode demo;
        try (InputStream in = new ClassPathResource("demo/bin-picking.json").getInputStream()) {
            demo = objectMapper.readTree(in);
        }
        for (JsonNode req : demo.path("requirements")) {
            requireValid("requirement", req);
            irRepository.upsertRequirement(projectId, req);
        }
        JsonNode env = demo.path("environment");
        requireValid("environment", env);
        irRepository.upsertEnvironment(projectId, env);
        int systems = 0;
        for (JsonNode sys : demo.path("systems")) {
            requireValid("system", sys);
            irRepository.insertSystem(projectId, sys.path("name").asText(), sys);
            systems++;
        }
        return Result.ok(Map.of("requirements", demo.path("requirements").size(), "systems", systems));
    }

    private void requireValid(String ir, JsonNode instance) {
        Map<String, Object> outcome = runtimeClient.validateIr(ir, objectMapper.convertValue(instance, Map.class));
        if (!Boolean.TRUE.equals(outcome.get("valid"))) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    ir + " IR 校验失败: " + outcome.get("errors"));
        }
    }

    private void ensureProject(String projectId) {
        Integer count = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM project WHERE id=?::uuid", Integer.class, projectId);
        if (count == null || count == 0) {
            throw new BizException(ErrorCode.PROJECT_NOT_FOUND);
        }
    }
}
