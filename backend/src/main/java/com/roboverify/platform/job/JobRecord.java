package com.roboverify.platform.job;

import java.time.OffsetDateTime;

/**
 * job_queue 行视图（只读展示用；状态机见 docs/architecture.md §6）。
 */
public record JobRecord(
        Long id,
        String jobKey,
        String type,
        String status,
        Short priority,
        Short attempts,
        Short maxAttempts,
        OffsetDateTime timeoutAt,
        String lockedBy,
        String lastError,
        String traceId,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt
) {
}
