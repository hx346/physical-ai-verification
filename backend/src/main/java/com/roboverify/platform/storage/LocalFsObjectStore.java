package com.roboverify.platform.storage;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/**
 * 本地文件系统实现（开发/测试）。key 直接映射为 baseDir 下的相对路径，
 * 禁止越界（规范化后必须以 baseDir 开头）。
 */
@Component
@ConditionalOnProperty(name = "roboverify.storage.type", havingValue = "local", matchIfMissing = true)
public class LocalFsObjectStore implements ObjectStore {

    private final Path baseDir;

    public LocalFsObjectStore(StorageProperties properties) {
        this.baseDir = Path.of(properties.getLocal().getBaseDir()).toAbsolutePath().normalize();
    }

    @Override
    public void put(String key, InputStream content, long length, String mediaType) {
        Path target = resolve(key);
        try {
            Files.createDirectories(target.getParent());
            Files.copy(content, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            throw new UncheckedIOException("put failed, key=" + key, e);
        }
    }

    @Override
    public InputStream get(String key) {
        try {
            return Files.newInputStream(resolve(key));
        } catch (IOException e) {
            throw new UncheckedIOException("get failed, key=" + key, e);
        }
    }

    @Override
    public boolean exists(String key) {
        return Files.exists(resolve(key));
    }

    @Override
    public void delete(String key) {
        try {
            Files.deleteIfExists(resolve(key));
        } catch (IOException e) {
            throw new UncheckedIOException("delete failed, key=" + key, e);
        }
    }

    private Path resolve(String key) {
        Path target = baseDir.resolve(key).normalize();
        if (!target.startsWith(baseDir)) {
            throw new IllegalArgumentException("illegal object key: " + key);
        }
        return target;
    }
}
