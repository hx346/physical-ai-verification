package com.roboverify.platform.job;

import com.roboverify.platform.common.api.Result;
import jakarta.validation.constraints.NotBlank;
import org.slf4j.MDC;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/jobs")
public class JobController {

    private final JobQueueService jobQueueService;

    public JobController(JobQueueService jobQueueService) {
        this.jobQueueService = jobQueueService;
    }

    public record EnqueueRequest(
            @NotBlank(message = "jobKey 不能为空") String jobKey,
            @NotBlank(message = "type 不能为空") String type,
            String payloadJson
    ) {
    }

    @PostMapping
    public Result<Boolean> enqueue(@jakarta.validation.Valid @RequestBody EnqueueRequest request) {
        String payload = request.payloadJson() == null ? "{}" : request.payloadJson();
        boolean created = jobQueueService.enqueue(request.jobKey(), request.type(), payload, MDC.get("traceId"));
        return Result.ok(created);
    }

    @GetMapping("/{jobKey}")
    public Result<JobRecord> get(@PathVariable String jobKey) {
        return Result.ok(jobQueueService.getByKey(jobKey));
    }
}
