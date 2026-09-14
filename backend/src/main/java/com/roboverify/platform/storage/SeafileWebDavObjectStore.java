package com.roboverify.platform.storage;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.ByteArrayInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

/**
 * Seafile SeafDAV(WebDAV) 适配器（ADR-0005）。
 * baseUrl 指向 WebDAV 根（如 http://seafile:8080/seafdav，容器内互访），
 * basePath 为其下前缀（资料库名或子目录，如 /roboverify）；key 追加在其后。
 * 语义：put 前递归 MKCOL 父目录；exists 用 HEAD（405 时回退 PROPFIND）；
 * delete 幂等（404 视为成功，与 LocalFsObjectStore.deleteIfExists 对齐）。
 */
@Component
@ConditionalOnProperty(name = "roboverify.storage.type", havingValue = "seafile-webdav")
public class SeafileWebDavObjectStore implements ObjectStore {

    private static final String PROPFIND_BODY =
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
                    + "<D:propfind xmlns:D=\"DAV:\"><D:prop/></D:propfind>";

    private final HttpClient http;
    private final String rootUrl;
    private final String authHeader;

    public SeafileWebDavObjectStore(StorageProperties properties) {
        StorageProperties.Seafile cfg = properties.getSeafile();
        if (isBlank(cfg.getBaseUrl()) || isBlank(cfg.getUsername()) || isBlank(cfg.getPassword())) {
            throw new IllegalStateException("roboverify.storage.seafile 缺少 baseUrl/username/password");
        }
        String base = cfg.getBaseUrl().replaceAll("/+$", "");
        String path = cfg.getBasePath() == null ? "" : cfg.getBasePath().replaceAll("/+$", "");
        if (!path.isEmpty() && !path.startsWith("/")) {
            path = "/" + path;
        }
        this.rootUrl = base + path;
        String token = cfg.getUsername() + ":" + cfg.getPassword();
        this.authHeader = "Basic " + Base64.getEncoder().encodeToString(token.getBytes(StandardCharsets.UTF_8));
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    @Override
    public void put(String key, InputStream content, long length, String mediaType) {
        String safeKey = checkKey(key);
        mkdirs(parentOf(safeKey));
        byte[] body = readBody(content, length);
        HttpRequest request = baseBuilder(url(safeKey))
                .header("Content-Type", mediaType == null || mediaType.isBlank()
                        ? "application/octet-stream" : mediaType)
                .PUT(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();
        int status = sendForStatus(request);
        if (status != 201 && status != 204 && status != 200) {
            throw new IllegalStateException("WebDAV PUT failed, status=" + status + ", key=" + safeKey);
        }
    }

    @Override
    public InputStream get(String key) {
        String safeKey = checkKey(key);
        HttpRequest request = baseBuilder(url(safeKey)).GET().build();
        HttpResponse<InputStream> response = send(request, safeKey);
        int status = response.statusCode();
        if (status == 404) {
            throw new UncheckedIOException(new FileNotFoundException("object not found: " + safeKey));
        }
        if (status != 200) {
            throw new IllegalStateException("WebDAV GET failed, status=" + status + ", key=" + safeKey);
        }
        return response.body();
    }

    @Override
    public boolean exists(String key) {
        String safeKey = checkKey(key);
        HttpRequest head = baseBuilder(url(safeKey))
                .method("HEAD", HttpRequest.BodyPublishers.noBody())
                .build();
        int status = sendForStatus(head);
        if (status == 200 || status == 204) {
            return true;
        }
        if (status == 404) {
            return false;
        }
        // 个别 WebDAV 实现对 HEAD 支持不全（405），回退 PROPFIND Depth:0
        HttpRequest propfind = baseBuilder(url(safeKey))
                .header("Depth", "0")
                .header("Content-Type", "application/xml")
                .method("PROPFIND", HttpRequest.BodyPublishers.ofString(PROPFIND_BODY))
                .build();
        return sendForStatus(propfind) == 207;
    }

    @Override
    public void delete(String key) {
        String safeKey = checkKey(key);
        HttpRequest request = baseBuilder(url(safeKey)).DELETE().build();
        int status = sendForStatus(request);
        // 204/200 删除成功；404 幂等成功；405 表示父路径不存在同样视为不存在
        if (status != 204 && status != 200 && status != 404 && status != 405) {
            throw new IllegalStateException("WebDAV DELETE failed, status=" + status + ", key=" + safeKey);
        }
    }

    // ---- 内部工具 ----

    private HttpRequest.Builder baseBuilder(String url) {
        return HttpRequest.newBuilder(URI.create(url))
                .header("Authorization", authHeader)
                .timeout(Duration.ofSeconds(60));
    }

    private String url(String key) {
        return rootUrl + (key.startsWith("/") ? key : "/" + key);
    }

    private static String checkKey(String key) {
        for (String segment : key.split("/")) {
            if ("..".equals(segment)) {
                throw new IllegalArgumentException("illegal object key: " + key);
            }
        }
        return key;
    }

    private static String parentOf(String key) {
        int idx = key.lastIndexOf('/');
        return idx <= 0 ? "" : key.substring(0, idx);
    }

    /** 递归创建父目录（MKCOL），已存在（405/200/301）不视为错误。 */
    private void mkdirs(String parentPath) {
        if (parentPath.isEmpty()) {
            return;
        }
        List<String> prefixes = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        for (String segment : parentPath.split("/")) {
            if (segment.isEmpty()) {
                continue;
            }
            current.append('/').append(segment);
            prefixes.add(current.toString());
        }
        for (String prefix : prefixes) {
            HttpRequest request = baseBuilder(url(prefix))
                    .method("MKCOL", HttpRequest.BodyPublishers.noBody())
                    .build();
            int status = sendForStatus(request);
            if (status != 201 && status != 405 && status != 200 && status != 301) {
                throw new IllegalStateException("WebDAV MKCOL failed, status=" + status + ", path=" + prefix);
            }
        }
    }

    private static byte[] readBody(InputStream content, long length) {
        try {
            if (length <= 0) {
                return content.readAllBytes();
            }
            return content.readNBytes(Math.toIntExact(length));
        } catch (IOException e) {
            throw new UncheckedIOException("read object body failed", e);
        }
    }

    private int sendForStatus(HttpRequest request) {
        try {
            return http.send(request, HttpResponse.BodyHandlers.discarding()).statusCode();
        } catch (IOException e) {
            throw new UncheckedIOException("WebDAV request failed: " + request.uri(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("WebDAV request interrupted", e);
        }
    }

    private HttpResponse<InputStream> send(HttpRequest request, String key) {
        try {
            return http.send(request, HttpResponse.BodyHandlers.ofInputStream());
        } catch (IOException e) {
            throw new UncheckedIOException("WebDAV request failed, key=" + key, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("WebDAV request interrupted", e);
        }
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
