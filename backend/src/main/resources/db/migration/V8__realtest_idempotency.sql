-- V8__realtest_idempotency.sql — PostgreSQL：真机会话导入幂等（V0.8 W1）
-- 采集器直连推送的重试场景：POST 超时但实际成功 → 重推同 external_key 不产生
-- 重复会话（全局工程准则：写操作必须幂等）。
-- 部分唯一索引（WHERE external_key IS NOT NULL）：手工导入（无 key）不受约束，
-- 可多次导入互不冲突。
ALTER TABLE real_test_session ADD COLUMN IF NOT EXISTS external_key varchar(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rts_external_key
    ON real_test_session (external_key) WHERE external_key IS NOT NULL;
