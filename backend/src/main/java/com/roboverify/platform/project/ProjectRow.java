package com.roboverify.platform.project;

import java.time.OffsetDateTime;

/**
 * project 表行视图。
 * M0 说明：MyBatis-Plus 3.5.7（boot3 starter）在 Boot 4.1 下自动配置未生效，
 * 按预案降级 JdbcTemplate（ADR-0001）；MP 出 Boot4 适配版后在 M1 回归。
 */
public record ProjectRow(
        String id,
        String name,
        String description,
        String status,
        String createdBy,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt
) {
}
