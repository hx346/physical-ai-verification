package com.roboverify.platform;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * 上下文加载测试：需要真实 PostgreSQL（Flyway 迁移）。
 * 本地：docker compose up -d postgres 后设置 ROBOVERIFY_DB=1 再跑。
 * CI：M0 无 DB service，跳过；M1 引入 service 容器后强制执行。
 */
@SpringBootTest
@EnabledIfEnvironmentVariable(named = "ROBOVERIFY_DB", matches = "1")
class PlatformApplicationTests {

    @Test
    void contextLoads() {
    }
}
