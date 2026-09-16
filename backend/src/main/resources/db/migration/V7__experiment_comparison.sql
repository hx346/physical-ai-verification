-- V0.5 W2 对照实验：一次对照 = 同实验参数（同 seed/n/方法）× 多系统配置臂。
-- 同 seed 配对采样：run i 在各臂的参数实例与噪声实例相同，差异归因系统配置。
CREATE TABLE experiment_comparison (
    id              bigserial PRIMARY KEY,
    comparison_key  varchar(128) NOT NULL UNIQUE,
    project_id      uuid NOT NULL,
    label           varchar(128),
    backend         varchar(16) NOT NULL DEFAULT 'analytic',
    arms            jsonb NOT NULL,   -- [{systemConfigId, jobKey, index}]（创建后不可变）
    evidence_id     varchar(32),      -- 全臂完成后摄取的对照证据（幂等标记）
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_exp_cmp_project ON experiment_comparison (project_id);

-- 对照结论也是证据：evidence 类型扩展 comparison（Evidence Store 可追溯）
ALTER TABLE evidence DROP CONSTRAINT IF EXISTS evidence_type_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_type_check
    CHECK (type IN ('formula', 'simulation', 'experiment', 'real_test', 'assumption', 'comparison'));
