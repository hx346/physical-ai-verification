-- V5__widen_evidence_run_id.sql — PostgreSQL：run_id 容纳长 jobKey（exp:uuid:syskey:ts ≈ 74 字符）
ALTER TABLE evidence ALTER COLUMN run_id TYPE varchar(128);
ALTER TABLE real_test_session ALTER COLUMN note TYPE varchar(1024);
