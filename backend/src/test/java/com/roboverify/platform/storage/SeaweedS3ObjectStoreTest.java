package com.roboverify.platform.storage;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * SeaweedFS S3 适配器单测：JDK 内置 HttpServer 模拟 S3 网关语义
 * （CreateBucket/PUT/GET/HEAD/DELETE），并校验请求携带 SigV4 结构头与真实 payload 哈希。
 */
class SeaweedS3ObjectStoreTest {

    private HttpServer server;
    private final Map<String, byte[]> objects = new ConcurrentHashMap<>();
    private final Set<String> buckets = ConcurrentHashMap.newKeySet();
    private String lastAmzDate;
    private String lastAuthHeader;
    private String lastContentSha;

    private SeaweedS3ObjectStore store;

    @BeforeEach
    void startFakeS3() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.createContext("/", exchange -> {
            try (exchange) {
                String path = exchange.getRequestURI().getPath();
                String method = exchange.getRequestMethod();
                lastAmzDate = exchange.getRequestHeaders().getFirst("x-amz-date");
                lastAuthHeader = exchange.getRequestHeaders().getFirst("Authorization");
                lastContentSha = exchange.getRequestHeaders().getFirst("x-amz-content-sha256");

                if (path.lastIndexOf('/') == 0) {
                    // 桶级操作：/{bucket}
                    switch (method) {
                        case "HEAD" -> reply(exchange, buckets.contains(path.substring(1)) ? 200 : 404, null);
                        case "PUT" -> {
                            buckets.add(path.substring(1));
                            reply(exchange, 200, null);
                        }
                        default -> reply(exchange, 405, null);
                    }
                    return;
                }
                switch (method) {
                    case "PUT" -> {
                        objects.put(path, exchange.getRequestBody().readAllBytes());
                        reply(exchange, 200, null);
                    }
                    case "GET" -> {
                        byte[] body = objects.get(path);
                        if (body == null) {
                            reply(exchange, 404, "<?xml version=\"1.0\"?><Error><Code>NoSuchKey</Code></Error>"
                                    .getBytes(StandardCharsets.UTF_8));
                        } else {
                            reply(exchange, 200, body);
                        }
                    }
                    case "HEAD" -> reply(exchange, objects.containsKey(path) ? 200 : 404, null);
                    case "DELETE" -> {
                        objects.remove(path);
                        reply(exchange, 204, null); // S3 语义：幂等
                    }
                    default -> reply(exchange, 405, null);
                }
            }
        });
        server.start();

        StorageProperties properties = new StorageProperties();
        properties.setType("seaweed-s3");
        properties.getS3().setEndpoint("http://127.0.0.1:" + server.getAddress().getPort());
        properties.getS3().setAccessKey("roboverify");
        properties.getS3().setSecretKey("roboverify-secret");
        properties.getS3().setRegion("us-east-1");
        properties.getS3().setBucket("roboverify");
        store = new SeaweedS3ObjectStore(properties);
    }

    @AfterEach
    void stopFakeS3() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void putCreatesBucketLazilyThenRoundtrip() throws IOException {
        byte[] body = "sim log line1\nline2".getBytes(StandardCharsets.UTF_8);
        String key = "/sim-logs/run-abc/run.log";
        store.put(key, new ByteArrayInputStream(body), body.length, "text/plain");

        // 桶应已懒创建；对象在桶下
        assertTrue(buckets.contains("roboverify"));
        assertTrue(objects.containsKey("/roboverify/sim-logs/run-abc/run.log"));
        assertTrue(store.exists(key));
        try (InputStream in = store.get(key)) {
            assertArrayEquals(body, in.readAllBytes());
        }
    }

    @Test
    void putSendsValidSigV4Headers() throws Exception {
        byte[] body = "payload".getBytes(StandardCharsets.UTF_8);
        store.put("/a/b/c.bin", new ByteArrayInputStream(body), body.length, "application/octet-stream");
        assertTrue(lastAuthHeader != null && lastAuthHeader.startsWith("AWS4-HMAC-SHA256 Credential=roboverify/"));
        assertTrue(lastAmzDate != null && lastAmzDate.matches("\\d{8}T\\d{6}Z"));
        // payload 哈希独立复核（非循环依赖签名器）
        String expected = hex(MessageDigest.getInstance("SHA-256").digest(body));
        org.junit.jupiter.api.Assertions.assertEquals(expected, lastContentSha);
    }

    @Test
    void existsFalseForMissingKey() {
        assertFalse(store.exists("/none/obj.bin"));
    }

    @Test
    void getMissingThrowsFileNotFoundException() {
        UncheckedIOException ex = assertThrows(UncheckedIOException.class, () -> store.get("/missing/o.bin"));
        assertTrue(ex.getCause() instanceof java.io.FileNotFoundException);
    }

    @Test
    void deleteIsIdempotent() throws IOException {
        String key = "/x/y/z.txt";
        byte[] body = "d".getBytes(StandardCharsets.UTF_8);
        store.put(key, new ByteArrayInputStream(body), body.length, "text/plain");
        store.delete(key);
        assertFalse(store.exists(key));
        store.delete(key); // S3 对不存在对象返回 204，不抛
    }

    @Test
    void illegalKeyRejected() {
        assertThrows(IllegalArgumentException.class,
                () -> store.put("/a/../b.txt", new ByteArrayInputStream(new byte[0]), 0, "text/plain"));
    }

    @Test
    void missingConfigRejected() {
        StorageProperties empty = new StorageProperties();
        assertThrows(IllegalStateException.class, () -> new SeaweedS3ObjectStore(empty));
    }

    private static void reply(HttpExchange exchange, int status, byte[] body) throws IOException {
        if (body == null) {
            exchange.sendResponseHeaders(status, -1);
        } else {
            exchange.getResponseHeaders().set("Content-Type", "application/xml");
            exchange.sendResponseHeaders(status, body.length);
            exchange.getResponseBody().write(body);
        }
    }

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }
}
