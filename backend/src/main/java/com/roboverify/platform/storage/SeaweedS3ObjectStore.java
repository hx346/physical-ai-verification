package com.roboverify.platform.storage;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * SeaweedFS S3 网关适配器（ADR-0005，主实现；兼容任意 S3 端点）。
 * SigV4 签名见 {@link S3Signer}（无 AWS SDK 依赖）。key 规范不变：
 * /{bucket}/{domain}/{id}/{filename} → s3://{配置桶}/{domain}/{id}/{filename}。
 * 桶在首次写入时懒创建（幂等）；S3 DELETE 对不存在对象返回 204，天然幂等。
 */
@Component
@ConditionalOnProperty(name = "roboverify.storage.type", havingValue = "seaweed-s3")
public class SeaweedS3ObjectStore implements ObjectStore {

    private final HttpClient http;
    private final String endpoint;
    private final String accessKey;
    private final String secretKey;
    private final String region;
    private final String bucket;
    private final Clock clock;
    private final Map<String, Boolean> bucketReady = new ConcurrentHashMap<>();

    @org.springframework.beans.factory.annotation.Autowired
    public SeaweedS3ObjectStore(StorageProperties properties) {
        this(properties, Clock.systemUTC());
    }

    SeaweedS3ObjectStore(StorageProperties properties, Clock clock) {
        StorageProperties.S3 cfg = properties.getS3();
        if (isBlank(cfg.getEndpoint()) || isBlank(cfg.getAccessKey()) || isBlank(cfg.getSecretKey())) {
            throw new IllegalStateException("roboverify.storage.s3 缺少 endpoint/accessKey/secretKey");
        }
        this.endpoint = cfg.getEndpoint().replaceAll("/+$", "");
        this.accessKey = cfg.getAccessKey();
        this.secretKey = cfg.getSecretKey();
        this.region = cfg.getRegion();
        this.bucket = cfg.getBucket();
        this.clock = clock;
        this.http = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    @Override
    public void put(String key, InputStream content, long length, String mediaType) {
        String safeKey = checkKey(key);
        ensureBucket();
        byte[] body = readBody(content, length);
        HttpRequest request = buildRequest("PUT", objectPath(safeKey), body, Map.of(
                "Content-Type", mediaType == null || mediaType.isBlank() ? "application/octet-stream" : mediaType));
        int status = sendForStatus(request);
        if (status != 200 && status != 201) {
            throw new IllegalStateException("S3 PUT failed, status=" + status + ", key=" + safeKey);
        }
    }

    @Override
    public InputStream get(String key) {
        String safeKey = checkKey(key);
        HttpRequest request = buildRequest("GET", objectPath(safeKey), null, Map.of());
        HttpResponse<InputStream> response = send(request, safeKey);
        int status = response.statusCode();
        if (status == 404) {
            throw new UncheckedIOException(new FileNotFoundException("object not found: " + safeKey));
        }
        if (status != 200) {
            throw new IllegalStateException("S3 GET failed, status=" + status + ", key=" + safeKey);
        }
        return response.body();
    }

    @Override
    public boolean exists(String key) {
        String safeKey = checkKey(key);
        HttpRequest request = buildRequest("HEAD", objectPath(safeKey), null, Map.of());
        int status = sendForStatus(request);
        if (status == 200) {
            return true;
        }
        if (status == 404) {
            return false;
        }
        throw new IllegalStateException("S3 HEAD failed, status=" + status + ", key=" + safeKey);
    }

    @Override
    public void delete(String key) {
        String safeKey = checkKey(key);
        HttpRequest request = buildRequest("DELETE", objectPath(safeKey), null, Map.of());
        int status = sendForStatus(request);
        // S3 语义：删除不存在的对象也返回 204（幂等）
        if (status != 204 && status != 200 && status != 404) {
            throw new IllegalStateException("S3 DELETE failed, status=" + status + ", key=" + safeKey);
        }
    }

    // ---- 内部工具 ----

    private String objectPath(String key) {
        return S3Signer.encodePath("/" + bucket + (key.startsWith("/") ? key : "/" + key));
    }

    private HttpRequest buildRequest(String method, String encodedPath, byte[] body, Map<String, String> extraHeaders) {
        URI uri = URI.create(endpoint + encodedPath);
        Instant now = Instant.now(clock);
        Map<String, String> signed = S3Signer.sign(uri, method, body, now, accessKey, secretKey, region, extraHeaders);
        HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
                .timeout(Duration.ofSeconds(60));
        signed.forEach(builder::header);
        extraHeaders.forEach(builder::header);
        HttpRequest.BodyPublisher publisher = body == null
                ? HttpRequest.BodyPublishers.noBody()
                : HttpRequest.BodyPublishers.ofByteArray(body);
        builder.method(method, publisher);
        return builder.build();
    }

    /** 桶懒创建：HEAD /{bucket} 不存在则 PUT /{bucket}（409=已存在也视为成功）。 */
    private void ensureBucket() {
        bucketReady.computeIfAbsent(bucket, b -> {
            String bucketPath = "/" + b;
            HttpRequest head = buildRequest("HEAD", bucketPath, null, Map.of());
            int status = sendForStatus(head);
            if (status == 200) {
                return Boolean.TRUE;
            }
            HttpRequest create = buildRequest("PUT", bucketPath, new byte[0], Map.of());
            int createStatus = sendForStatus(create);
            if (createStatus != 200 && createStatus != 201 && createStatus != 409) {
                throw new IllegalStateException("S3 CreateBucket failed, status=" + createStatus + ", bucket=" + b);
            }
            return Boolean.TRUE;
        });
    }

    private static String checkKey(String key) {
        for (String segment : key.split("/")) {
            if ("..".equals(segment)) {
                throw new IllegalArgumentException("illegal object key: " + key);
            }
        }
        return key;
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
            throw new UncheckedIOException("S3 request failed: " + request.uri(), e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("S3 request interrupted", e);
        }
    }

    private HttpResponse<InputStream> send(HttpRequest request, String key) {
        try {
            return http.send(request, HttpResponse.BodyHandlers.ofInputStream());
        } catch (IOException e) {
            throw new UncheckedIOException("S3 request failed, key=" + key, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("S3 request interrupted", e);
        }
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
