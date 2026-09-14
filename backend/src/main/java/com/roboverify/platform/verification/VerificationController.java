package com.roboverify.platform.verification;

import com.roboverify.platform.common.api.Result;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 验证编排端点：POST /runs 触发一次验证（需求集×系统配置），结果含证据引用。
 */
@RestController
@RequestMapping("/api/verification")
public class VerificationController {

    private final VerificationRunService runService;
    private final ReportService reportService;

    public VerificationController(VerificationRunService runService, ReportService reportService) {
        this.runService = runService;
        this.reportService = reportService;
    }

    public record RunRequest(
            @NotBlank(message = "projectId 不能为空") String projectId,
            @NotBlank(message = "systemConfigId 不能为空") String systemConfigId
    ) {
    }

    @PostMapping("/runs")
    public Result<Map<String, Object>> run(@jakarta.validation.Valid @RequestBody RunRequest request) {
        return Result.ok(runService.run(request.projectId(), request.systemConfigId()));
    }

    @GetMapping("/projects/{projectId}/runs")
    public Result<List<Map<String, Object>>> runs(@PathVariable String projectId) {
        return Result.ok(runService.findRuns(projectId));
    }

    @GetMapping("/runs/{runId}/items")
    public Result<List<Map<String, Object>>> items(@PathVariable String runId) {
        return Result.ok(runService.findItems(runId));
    }

    @GetMapping(value = "/runs/{runId}/report", produces = MediaType.TEXT_MARKDOWN_VALUE)
    public String report(@PathVariable String runId) {
        return reportService.renderAndArchive(runId, null);
    }
}
