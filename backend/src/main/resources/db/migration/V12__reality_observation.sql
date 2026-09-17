-- V12__reality_observation.sql — PostgreSQL：Reality DB v1（V1.0 §14 Track B，方案 §23）。
-- 数据护城河的最小落库：设备×环境×任务×指标分布（不是设备规格，是观测误差分布）。
-- 对齐方案 §23 例：D455 @ 700mm/34000lux/反光金属 → P50 3.2mm / P95 8.4mm / 118k 样本。
-- 数据源：①真机会话聚合自动派生（external_key=reality-session-{sessionId}-{metric}
-- 幂等）；②手工录入（文献先验 literature / 实测 measured，external_key 可空不受约束，
-- 同 V8/V9 部分唯一索引模式）；③failure 关联（source_failure_id——"失败+修正"维度，
-- 与 V9 failure_record 四元组衔接）。
-- provenance 分级强校验：literature / measured / calibrated（Track D 校准 ACTIVE 回写位）。
-- 诚实边界：会话本身不含设备/环境元数据（V0.8 设计），派生时的上下文由录入者声明。
CREATE TABLE reality_observation (
    id                 bigserial PRIMARY KEY,
    device_model       varchar(128),                    -- 设备型号（NULL=未记录，如实）
    environment        jsonb NOT NULL DEFAULT '{}',     -- 条件：lux/surface/distance/temp…
    task               varchar(128) NOT NULL,           -- 任务类型（bin_picking…）
    metric             varchar(64) NOT NULL,            -- 指标键（真机 CSV 族）
    mean               double precision,
    p50                double precision,
    p95                double precision,
    samples            int NOT NULL CHECK (samples > 0),
    provenance         varchar(32) NOT NULL
                       CHECK (provenance IN ('literature', 'measured', 'calibrated')),
    source_session_id  uuid,                            -- 派生来源会话（手工录入为 NULL）
    source_failure_id  bigint,                          -- V9 failure_record 关联（可空）
    external_key       varchar(256),                    -- 幂等键（派生必填，手工可空）
    note               text,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- 派生幂等：同会话同指标只落一行（部分唯一——手工录入不受约束，同 V8/V9 模式）
CREATE UNIQUE INDEX uq_reality_obs_external_key
    ON reality_observation (external_key) WHERE external_key IS NOT NULL;
CREATE INDEX idx_reality_obs_query ON reality_observation (device_model, metric, task);
