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
import java.util.Base64;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * WebDAV 适配器单测：用 JDK 内置 HttpServer 模拟 SeafDAV 语义
 * （MKCOL/PUT/HEAD/PROPFIND/GET/DELETE + Basic 认证），不依赖容器。
 */
class SeafileWebDavObjectStoreTest {

    private HttpServer server;
    private final Map<String, byte[]> files = new ConcurrentHashMap<>();
    private final Set<String> dirs = ConcurrentHashMap.newKeySet();
    private volatile boolean headReturns405 = false;

    private SeafileWebDavObjectStore store;

    @BeforeEach
    void startFakeWebdav() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.setExecutor(Executors.newSingleThreadExecutor());
        String expectedAuth = "Basic " + Base64.getEncoder()
                .encodeToString("admin@roboverify.local:roboverify123".getBytes(StandardCharsets.UTF_8));
        server.createContext("/", exchange -> {
            try (exchange) {
                if (!expectedAuth.equals(exchange.getRequestHeaders().getFirst("Authorization"))) {
                    reply(exchange, 401, null);
                    return;
                }
                String path = exchange.getRequestURI().getPath();
                String method = exchange.getRequestMethod();
                switch (method) {
                    case "MKCOL" -> {
                        dirs.add(path);
                        reply(exchange, 201, null);
                    }
                    case "PUT" -> {
                        files.put(path, exchange.getRequestBody().readAllBytes());
                        reply(exchange, 201, null);
                    }
                    case "HEAD" -> {
                        if (headReturns405) {
                            reply(exchange, 405, null);
                        } else if (files.containsKey(path)) {
                            reply(exchange, 200, null);
                        } else {
                            reply(exchange, 404, null);
                        }
                    }
                    case "PROPFIND" -> {
                        boolean found = files.containsKey(path) || dirs.contains(path);
                        reply(exchange, found ? 207 : 404, null);
                    }
                    case "GET" -> {
                        byte[] body = files.get(path);
                        if (body == null) {
                            reply(exchange, 404, null);
                        } else {
                            reply(exchange, 200, body);
                        }
                    }
                    case "DELETE" -> {
                        if (files.remove(path) != null) {
                            reply(exchange, 204, null);
                        } else {
                            reply(exchange, 404, null);
                        }
                    }
                    default -> reply(exchange, 405, null);
                }
            }
        });
        server.start();

        StorageProperties properties = new StorageProperties();
        properties.setType("seafile-webdav");
        properties.getSeafile().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort() + "/seafdav");
        properties.getSeafile().setUsername("admin@roboverify.local");
        properties.getSeafile().setPassword("roboverify123");
        properties.getSeafile().setBasePath("/roboverify");
        store = new SeafileWebDavObjectStore(properties);
    }

    @AfterEach
    void stopFakeWebdav() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void putThenGetRoundtripAndMkcolParents() {
        byte[] body = "run log line1\nline2".getBytes(StandardCharsets.UTF_8);
        String key = "/sim-logs/run-abc123/run.log";
        store.put(key, new ByteArrayInputStream(body), body.length, "text/plain");

        // 父目录应已通过 MKCOL 创建
        assertTrue(dirs.contains("/seafdav/roboverify/sim-logs"));
        assertTrue(dirs.contains("/seafdav/roboverify/sim-logs/run-abc123"));
        assertTrue(store.exists(key));
        try (InputStream in = store.get(key)) {
            assertArrayEquals(body, in.readAllBytes());
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    @Test
    void existsFalseForMissingKey() {
        assertFalse(store.exists("/sim-logs/run-none/run.log"));
    }

    @Test
    void getMissingThrowsFileNotFoundException() {
        UncheckedIOException ex = assertThrows(UncheckedIOException.class,
                () -> store.get("/missing/object.bin"));
        assertTrue(ex.getCause() instanceof java.io.FileNotFoundException);
    }

    @Test
    void deleteIsIdempotent() {
        String key = "/bucket/dom/id/file.txt";
        byte[] body = "x".getBytes(StandardCharsets.UTF_8);
        store.put(key, new ByteArrayInputStream(body), body.length, "application/octet-stream");
        store.delete(key);
        assertFalse(store.exists(key));
        // 二次删除不抛异常（与 LocalFsObjectStore.deleteIfExists 语义一致）
        store.delete(key);
    }

    @Test
    void headUnsupportedFallsBackToPropfind() {
        byte[] body = "y".getBytes(StandardCharsets.UTF_8);
        String key = "/exp/e1/data.csv";
        store.put(key, new ByteArrayInputStream(body), body.length, "text/csv");
        headReturns405 = true;
        assertTrue(store.exists(key));          // PROPFIND -> 207
        assertFalse(store.exists("/exp/e1/none.csv")); // PROPFIND -> 404
    }

    @Test
    void illegalKeyRejectedWithoutRequest() {
        assertThrows(IllegalArgumentException.class,
                () -> store.put("/a/../b/file.txt", new ByteArrayInputStream(new byte[0]), 0, "text/plain"));
    }

    @Test
    void authFailureSurfacesAsError() {
        StorageProperties wrong = new StorageProperties();
        wrong.getSeafile().setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort() + "/seafdav");
        wrong.getSeafile().setUsername("admin@roboverify.local");
        wrong.getSeafile().setPassword("wrong-password");
        SeafileWebDavObjectStore wrongStore = new SeafileWebDavObjectStore(wrong);
        byte[] body = "z".getBytes(StandardCharsets.UTF_8);
        assertThrows(IllegalStateException.class, () -> wrongStore.put(
                "/a/b/c.txt", new ByteArrayInputStream(body), body.length, "text/plain"));
    }

    private static void reply(HttpExchange exchange, int status, byte[] body) throws IOException {
        if (body == null) {
            exchange.sendResponseHeaders(status, -1);
        } else {
            exchange.getResponseHeaders().set("Content-Type", "application/octet-stream");
            exchange.sendResponseHeaders(status, body.length);
            exchange.getResponseBody().write(body);
        }
    }
}
