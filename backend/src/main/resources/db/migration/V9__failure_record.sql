-- V9__failure_record.sql — PostgreSQL：失败取证结构化落库（V0.9，方案 §26/§48.3）
-- 护城河资产：failure → root_cause → correction → outcome 四元组 + 溯源
-- （evidence 关联 / trace JSONB / source 区分 sim|real|manual）。
-- 幂等：external_key 部分唯一索引（同 V8 模式）——回填脚本/采集器重放不重复，
-- 手工录入（无 key）不受约束，可多次录入。
CREATE TABLE failure_record (
    id            bigserial PRIMARY KEY,
    project_id    uuid,
    external_key  varchar(128),
    failure_mode  varchar(64) NOT NULL,
    failure_desc  text,
    root_cause    text,
    correction    text,
    outcome       text,
    severity      varchar(16) NOT NULL DEFAULT 'medium'
                  CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    source        varchar(16) NOT NULL DEFAULT 'manual'
                  CHECK (source IN ('sim', 'real', 'manual')),
    evidence_id   varchar(32),
    trace         jsonb,
    detected_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_failure_external_key
    ON failure_record (external_key) WHERE external_key IS NOT NULL;
CREATE INDEX idx_failure_project ON failure_record (project_id);
CREATE INDEX idx_failure_mode ON failure_record (failure_mode);
