package com.roboverify.platform.verification;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.io.InputStream;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** 报告归档行为：首次快照 / 幂等跳过 / 存储故障降级不阻断下载。 */
class ReportServiceTest {

    /** 内存 fake：记录 put 次数与内容。 */
    static class RecordingStore implements com.roboverify.platform.storage.ObjectStore {
        final Map<String, byte[]> files = new ConcurrentHashMap<>();
        volatile int putCalls;
        volatile boolean broken;

        @Override
        public void put(String key, InputStream content, long length, String mediaType) {
            if (broken) {
                throw new IllegalStateException("store down");
            }
            putCalls++;
            try {
                files.put(key, content.readAllBytes());
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        }

        @Override
        public InputStream get(String key) {
            byte[] body = files.get(key);
            return body == null ? null : new java.io.ByteArrayInputStream(body);
        }

        @Override
        public boolean exists(String key) {
            return files.containsKey(key);
        }

        @Override
        public void delete(String key) {
            files.remove(key);
        }
    }

    private ReportService service(RecordingStore store, List<Map<String, Object>> items) {
        VerificationRunService runService = mock(VerificationRunService.class);
        when(runService.findItems(anyString())).thenReturn(items);
        // V0.8 W2：SimRealGapService 为第 4 依赖（Gap 章节）；mock 的 JdbcTemplate
        // 查不到会话 → appendGapSection 走"无真机对照"诚实分支，不触 runtime
        return new ReportService(runService, mock(JdbcTemplate.class), store,
                mock(SimRealGapService.class));
    }

    @Test
    void archivesFirstDownloadOnly() {
        RecordingStore store = new RecordingStore();
        ReportService reportService = service(store, List.of());

        String first = reportService.renderAndArchive("run-1", "sys");
        String second = reportService.renderAndArchive("run-1", "sys");

        assertEquals(1, store.putCalls, "第二次下载应跳过归档（快照语义）");
        // key 无前导斜杠（V0.3 W3 修复：LocalFs 拒绝绝对路径）——原测试带斜杠自那时起已烂
        assertEquals(first, new String(store.files.get("reports/run-run-1/report.md"),
                java.nio.charset.StandardCharsets.UTF_8));
        assertTrue(second.contains("run-1"));
    }

    @Test
    void storeFailureDoesNotBlockDownload() {
        RecordingStore store = new RecordingStore();
        store.broken = true;
        ReportService reportService = service(store, List.of());

        String markdown = assertDoesNotThrow(() -> reportService.renderAndArchive("run-2", null));
        assertTrue(markdown.contains("run-2"), "存储故障时报告仍应正常返回");
    }

    @Test
    void mockitoSanity() {
        // 防御：确认 mock 依赖可用（items 为空时 render 走早退分支，不触 DB）
        RecordingStore store = new RecordingStore();
        ReportService reportService = service(store, List.of(Map.of("requirementId", "R1")));
        // 有 item 时 render 需要查 projectId → jdbcTemplate.queryForObject 返回 null 也应容忍
        assertDoesNotThrow(() -> reportService.renderAndArchive("run-3", "s"));
    }
}
