package com.roboverify.platform.storage;

import java.io.InputStream;

/**
 * 对象存储 SPI（ADR-0005）：屏蔽 Seafile(WebDAV) / 本地文件系统差异。
 * M0 仅 LocalFsObjectStore 实现；Seafile 适配器（WebDAV）在 M2 随仿真日志/证据文件落地。
 * key 规范：/{bucket}/{domain}/{id}/{filename}，例如 /sim-logs/run-xxx/run.log
 */
public interface ObjectStore {

    void put(String key, InputStream content, long length, String mediaType);

    InputStream get(String key);

    boolean exists(String key);

    void delete(String key);
}
