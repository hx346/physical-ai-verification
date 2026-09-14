package com.roboverify.platform.verification;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.roboverify.platform.common.api.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/assets")
public class AssetController {

    private static final com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>> MAP_TYPE =
            new com.fasterxml.jackson.core.type.TypeReference<>() {};


    private final IrRepository irRepository;
    private final ObjectMapper objectMapper;

    public AssetController(IrRepository irRepository, ObjectMapper objectMapper) {
        this.irRepository = irRepository;
        this.objectMapper = objectMapper;
    }

    @GetMapping
    public Result<List<Map<String, Object>>> list() {
        // HTTP 层为 Jackson 3，不识别 Jackson 2 JsonNode；出口统一转 Map
        return Result.ok(irRepository.findAllAssets().stream()
                .map(node -> objectMapper.convertValue(node, MAP_TYPE))
                .toList());
    }
}
