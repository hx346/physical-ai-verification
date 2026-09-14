package com.roboverify.platform.auth;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.HexFormat;

/**
 * PBKDF2-SHA256 口令哈希（JDK 内置，无外部依赖）。
 * 格式：pbkdf2:&lt;salt_hex&gt;:&lt;hash_hex&gt;；迭代 120000，dkLen 32 字节。
 * 种子 admin 口令由 V2__seed.sql 以相同参数预置。
 */
public final class PasswordHasher {

    private static final String ALGORITHM = "PBKDF2WithHmacSHA256";
    private static final int ITERATIONS = 120_000;
    private static final int KEY_LENGTH_BITS = 256;
    private static final int SALT_BYTES = 16;

    private PasswordHasher() {
    }

    public static String hash(String password) {
        byte[] salt = new byte[SALT_BYTES];
        new SecureRandom().nextBytes(salt);
        byte[] dk = pbkdf2(password, salt);
        return "pbkdf2:" + HexFormat.of().formatHex(salt) + ":" + HexFormat.of().formatHex(dk);
    }

    public static boolean verify(String password, String stored) {
        String[] parts = stored.split(":");
        if (parts.length != 3 || !"pbkdf2".equals(parts[0])) {
            return false;
        }
        byte[] salt = HexFormat.of().parseHex(parts[1]);
        byte[] expected = HexFormat.of().parseHex(parts[2]);
        byte[] actual = pbkdf2(password, salt);
        return MessageDigest.isEqual(expected, actual);
    }

    private static byte[] pbkdf2(String password, byte[] salt) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, KEY_LENGTH_BITS);
            return SecretKeyFactory.getInstance(ALGORITHM).generateSecret(spec).getEncoded();
        } catch (Exception e) {
            throw new IllegalStateException("pbkdf2 failure", e);
        }
    }
}
