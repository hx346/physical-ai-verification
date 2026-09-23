package com.roboverify.platform.verification;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Reality DB 手工/批量录入校验纯逻辑（2026-09-23）：
 * 单条与批量共用，批量额外强制 external_key（幂等键——批量重放不重录的根基）。
 */
class RealityControllerValidationTest {

    private static RealityController.ManualRequest entry(String task, String metric,
            Double p95, Integer samples, String provenance, String externalKey) {
        return new RealityController.ManualRequest("D455", Map.of("distance_mm", 700),
                task, metric, null, null, p95, samples, provenance, null,
                "unit test", externalKey);
    }

    @Test
    void validEntryPasses() {
        assertNull(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", 8.4, 118000, "literature", null), false));
    }

    @Test
    void blankTaskRejected() {
        assertTrue(RealityController.validateManual(
                entry("", "position_error_mm", 8.4, 100, "literature", null), false).contains("task"));
    }

    @Test
    void nonPositiveSamplesRejected() {
        assertTrue(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", 8.4, 0, "literature", null), false).contains("samples"));
    }

    @Test
    void unknownProvenanceRejected() {
        assertTrue(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", 8.4, 100, "guessed", null), false).contains("provenance"));
    }

    @Test
    void calibratedManualEntryRejected() {
        assertTrue(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", 8.4, 100, "calibrated", null), false)
                .contains("calibrated"));
    }

    @Test
    void allNullStatsRejected() {
        assertTrue(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", null, 100, "literature", null), false)
                .contains("p95"));
    }

    @Test
    void batchRequiresExternalKey() {
        assertTrue(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", 8.4, 100, "literature", "  "), true)
                .contains("externalKey"));
        assertNull(RealityController.validateManual(
                entry("bin_picking", "position_error_mm", 8.4, 100, "literature",
                        "datasheet-d455-2m-upper"), true));
    }
}
