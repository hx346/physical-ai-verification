package com.roboverify.platform.storage;

import org.junit.jupiter.api.Test;

import java.net.URI;
import java.time.Instant;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * SigV4 正确性验证：AWS 官方文档示例向量
 * （https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html）。
 */
class S3SignerTest {

    private static final String EXPECTED_AUTH =
            "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request,"
                    + "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,"
                    + "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41";

    @Test
    void awsOfficialVector() {
        // 官方 GET Object 示例：GET /test.txt + Range: bytes=0-9
        Map<String, String> signed = S3Signer.sign(
                URI.create("https://examplebucket.s3.amazonaws.com/test.txt"),
                "GET",
                null,
                Instant.parse("2013-05-24T00:00:00Z"),
                "AKIAIOSFODNN7EXAMPLE",
                "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "us-east-1",
                Map.of("Range", "bytes=0-9"));

        assertEquals(EXPECTED_AUTH, signed.get("Authorization"));
        assertEquals("20130524T000000Z", signed.get("x-amz-date"));
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                signed.get("x-amz-content-sha256"));
    }

    @Test
    void encodePathKeepsUnreservedAndEncodesSpecialChars() {
        assertEquals("/bucket/sim-logs/run-1/run.log", S3Signer.encodePath("/bucket/sim-logs/run-1/run.log"));
        assertEquals("/b/a%20b/c.txt", S3Signer.encodePath("/b/a b/c.txt"));
        assertEquals("/b/%E4%B8%AD.txt", S3Signer.encodePath("/b/中.txt"));
        assertEquals("/", S3Signer.encodePath("/"));
    }

    @Test
    void nonStandardPortIncludedInHost() {
        // endpoint http://seaweedfs:8333 → host 头须带端口；默认端口不带
        Map<String, String> signed = S3Signer.sign(
                URI.create("http://seaweedfs:8333/roboverify/a.txt"),
                "PUT", new byte[]{'x'}, Instant.parse("2026-09-14T00:00:00Z"),
                "ak", "sk", "us-east-1", Map.of());
        String auth = signed.get("Authorization");
        org.junit.jupiter.api.Assertions.assertTrue(auth.contains("SignedHeaders=host;x-amz-content-sha256;x-amz-date"));
    }
}
