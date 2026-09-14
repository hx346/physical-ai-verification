package com.roboverify.platform.storage;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 存储配置。type=local 用于开发与测试；type=seaweed-s3 生产推荐（ADR-0005）；
 * type=seafile-webdav 为备选实现（保留）。
 */
@ConfigurationProperties(prefix = "roboverify.storage")
public class StorageProperties {

    private String type = "local";
    private Local local = new Local();
    private S3 s3 = new S3();
    private Seafile seafile = new Seafile();

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public Local getLocal() { return local; }
    public void setLocal(Local local) { this.local = local; }
    public S3 getS3() { return s3; }
    public void setS3(S3 s3) { this.s3 = s3; }
    public Seafile getSeafile() { return seafile; }
    public void setSeafile(Seafile seafile) { this.seafile = seafile; }

    public static class Local {
        private String baseDir = "./data/objects";

        public String getBaseDir() { return baseDir; }
        public void setBaseDir(String baseDir) { this.baseDir = baseDir; }
    }

    /** SeaweedFS S3 网关（或任意 S3 兼容端点）。 */
    public static class S3 {
        private String endpoint;
        private String accessKey;
        private String secretKey;
        private String region = "us-east-1";
        private String bucket = "roboverify";

        public String getEndpoint() { return endpoint; }
        public void setEndpoint(String endpoint) { this.endpoint = endpoint; }
        public String getAccessKey() { return accessKey; }
        public void setAccessKey(String accessKey) { this.accessKey = accessKey; }
        public String getSecretKey() { return secretKey; }
        public void setSecretKey(String secretKey) { this.secretKey = secretKey; }
        public String getRegion() { return region; }
        public void setRegion(String region) { this.region = region; }
        public String getBucket() { return bucket; }
        public void setBucket(String bucket) { this.bucket = bucket; }
    }

    public static class Seafile {
        private String baseUrl;
        private String username;
        private String password;
        private String basePath = "/roboverify";

        public String getBaseUrl() { return baseUrl; }
        public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
        public String getUsername() { return username; }
        public void setUsername(String username) { this.username = username; }
        public String getPassword() { return password; }
        public void setPassword(String password) { this.password = password; }
        public String getBasePath() { return basePath; }
        public void setBasePath(String basePath) { this.basePath = basePath; }
    }
}
