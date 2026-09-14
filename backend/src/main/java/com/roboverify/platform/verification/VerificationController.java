package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.Result;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import org.slf4j.MDC;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * M0：内核透传端点——验证 backend→runtime 全链路（traceId 贯通为 M0 DoD）。
 * M1 将升级为 verification_run 编排（落 run/item/evidence 表）。
 */
@RestController
@RequestMapping("/api/verification")
public class VerificationController {

    private final RuntimeClient runtimeClient;

    public VerificationController(RuntimeClient runtimeClient) {
        this.runtimeClient = runtimeClient;
    }

    public record VerifyPassThroughRequest(
            @NotEmpty(message = "requirements 不能为空") List<Map<String, Object>> requirements,
            @NotNull(message = "system 不能为空") Map<String, Object> system,
            Map<String, Object> environment
    ) {
    }

    @PostMapping("/verify")
    public Result<Map<String, Object>> verify(@jakarta.validation.Valid @RequestBody VerifyPassThroughRequest request) {
        Map<String, Object> payload = new java.util.HashMap<>();
        payload.put("requestId", "req-" + System.nanoTime());
        payload.put("traceId", MDC.get("traceId"));
        payload.put("requirements", request.requirements());
        payload.put("system", request.system());
        if (request.environment() != null) {
            payload.put("environment", request.environment());
        }
        return Result.ok(runtimeClient.verify(payload));
    }
}
