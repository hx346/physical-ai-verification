package com.roboverify.platform.storage;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 存储配置。type=local 用于开发与测试；type=seafile-webdav 在 M2 启用。
 */
@ConfigurationProperties(prefix = "roboverify.storage")
public class StorageProperties {

    private String type = "local";
    private Local local = new Local();
    private Seafile seafile = new Seafile();

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public Local getLocal() { return local; }
    public void setLocal(Local local) { this.local = local; }
    public Seafile getSeafile() { return seafile; }
    public void setSeafile(Seafile seafile) { this.seafile = seafile; }

    public static class Local {
        private String baseDir = "./data/objects";

        public String getBaseDir() { return baseDir; }
        public void setBaseDir(String baseDir) { this.baseDir = baseDir; }
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
