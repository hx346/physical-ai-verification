package com.roboverify.platform.auth;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PasswordHasherTest {

    @Test
    void hashThenVerifySucceeds() {
        String stored = PasswordHasher.hash("roboverify123");
        assertNotNull(stored);
        assertTrue(PasswordHasher.verify("roboverify123", stored));
    }

    @Test
    void wrongPasswordRejected() {
        String stored = PasswordHasher.hash("roboverify123");
        assertFalse(PasswordHasher.verify("wrong-password", stored));
    }

    @Test
    void malformedStoredValueRejected() {
        assertFalse(PasswordHasher.verify("x", "not-a-hash"));
        assertFalse(PasswordHasher.verify("x", "md5:abcd:ef00"));
    }

    /** 与 V2__seed.sql 中预置的 admin 口令哈希保持一致（改动迭代参数时此测试会失败提醒同步） */
    @Test
    void seedAdminHashMatchesDefaultPassword() {
        String seedHash = "pbkdf2:726f626f766572696679:29f0820a887c69e7e2c8e944d73e43f905c494c987feaf6d128d3c59ba1ef291";
        assertTrue(PasswordHasher.verify("roboverify123", seedHash));
    }
}
