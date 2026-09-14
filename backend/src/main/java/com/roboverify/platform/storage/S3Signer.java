package com.roboverify.platform.storage;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Collectors;

/**
 * AWS Signature V4 最小实现（service=s3，无依赖，JDK 自带加密）。
 * 仅覆盖本 SPI 所需的简单请求：无 query、无 multipart、payload 哈希为真实 SHA-256。
 * S3 规则：路径段只做一次 URI 编码（保留 '/' 与非保留字符 A-Za-z0-9-._~）。
 * 签名头固定为 host + x-amz-content-sha256 + x-amz-date + 调用方额外头（小写排序）。
 */
final class S3Signer {

    private static final DateTimeFormatter DATE_FMT =
            DateTimeFormatter.ofPattern("yyyyMMdd").withZone(ZoneOffset.UTC);
    private static final DateTimeFormatter AMZ_DATE_FMT =
            DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC);

    private S3Signer() {
    }

    /**
     * 计算签名并返回需附加到请求的头（Authorization / x-amz-date / x-amz-content-sha256）。
     *
     * @param uri        完整目标 URI（path 必须已用 encodePath 编码一次，此处不再编码避免双编码）
     * @param payload    请求体（null 视为空）
     * @param extraHeaders 额外业务头（如 Content-Type；host 由 uri 推导）
     */
    static Map<String, String> sign(URI uri, String method, byte[] payload, Instant now,
                                    String accessKey, String secretKey, String region,
                                    Map<String, String> extraHeaders) {
        byte[] body = payload == null ? new byte[0] : payload;
        String payloadHash = sha256Hex(body);
        String amzDate = AMZ_DATE_FMT.format(now);
        String date = DATE_FMT.format(now);

        // canonical headers：host + x-amz-* + 额外头，键小写排序
        TreeMap<String, String> headers = new TreeMap<>();
        if (extraHeaders != null) {
            extraHeaders.forEach((k, v) -> headers.put(k.toLowerCase(), v.trim()));
        }
        headers.put("host", hostHeader(uri));
        headers.put("x-amz-content-sha256", payloadHash);
        headers.put("x-amz-date", amzDate);
        String canonicalHeaders = headers.entrySet().stream()
                .map(e -> e.getKey() + ":" + e.getValue() + "\n")
                .collect(Collectors.joining());
        String signedHeaders = String.join(";", headers.keySet());

        String canonicalRequest = method + "\n"
                + (uri.getRawPath().isEmpty() ? "/" : uri.getRawPath()) + "\n"
                + "" + "\n"  // 无 query
                + canonicalHeaders
                + "\n"
                + signedHeaders + "\n"
                + payloadHash;

        String scope = date + "/" + region + "/s3/aws4_request";
        String stringToSign = "AWS4-HMAC-SHA256\n" + amzDate + "\n" + scope + "\n"
                + sha256Hex(canonicalRequest.getBytes(StandardCharsets.UTF_8));

        byte[] kDate = hmacSha256(("AWS4" + secretKey).getBytes(StandardCharsets.UTF_8),
                date.getBytes(StandardCharsets.UTF_8));
        byte[] kRegion = hmacSha256(kDate, region.getBytes(StandardCharsets.UTF_8));
        byte[] kService = hmacSha256(kRegion, "s3".getBytes(StandardCharsets.UTF_8));
        byte[] kSigning = hmacSha256(kService, "aws4_request".getBytes(StandardCharsets.UTF_8));
        String signature = hex(hmacSha256(kSigning, stringToSign.getBytes(StandardCharsets.UTF_8)));

        return Map.of(
                "Authorization", "AWS4-HMAC-SHA256 Credential=" + accessKey + "/" + scope
                        + ",SignedHeaders=" + signedHeaders + ",Signature=" + signature,
                "x-amz-date", amzDate,
                "x-amz-content-sha256", payloadHash);
    }

    /** S3 风格路径编码：分段编码一次，保留 '/' 与非保留字符。 */
    static String encodePath(String rawPath) {
        StringBuilder out = new StringBuilder();
        for (String segment : rawPath.split("/", -1)) {
            if (!segment.isEmpty()) {
                StringBuilder enc = new StringBuilder();
                for (byte b : segment.getBytes(StandardCharsets.UTF_8)) {
                    char c = (char) (b & 0xFF);
                    if (isUnreserved(c)) {
                        enc.append(c);
                    } else {
                        enc.append('%').append(String.format("%02X", b));
                    }
                }
                out.append(enc);
            }
            out.append('/');
        }
        if (rawPath.equals("/") || rawPath.isEmpty()) {
            return "/";
        }
        out.setLength(out.length() - 1); // 去掉末尾多余 '/'
        return out.toString();
    }

    private static boolean isUnreserved(char c) {
        return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')
                || c == '-' || c == '.' || c == '_' || c == '~';
    }

    private static String hostHeader(URI uri) {
        int port = uri.getPort();
        boolean defaultPort = (port == -1)
                || ("http".equals(uri.getScheme()) && port == 80)
                || ("https".equals(uri.getScheme()) && port == 443);
        return defaultPort ? uri.getHost() : uri.getHost() + ":" + port;
    }

    private static String sha256Hex(byte[] data) {
        return hex(digest("SHA-256", data));
    }

    private static byte[] digest(String algorithm, byte[] data) {
        try {
            return MessageDigest.getInstance(algorithm).digest(data);
        } catch (Exception e) {
            throw new IllegalStateException("digest failed: " + algorithm, e);
        }
    }

    private static byte[] hmacSha256(byte[] key, byte[] data) {
        try {
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException("hmac failed", e);
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
