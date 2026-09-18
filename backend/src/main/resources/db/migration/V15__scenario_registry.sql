-- V15__scenario_registry.sql — PostgreSQL：Scenario Registry v0（场景库容器，V1.0 §44
-- "场景库有真实规模"是 V2.0 前置；V0.9 场景参数化 v2 的 scenario.json 归档至此可查可复用）。
-- 复现语义：同 scenario JSON + 同 seed → SDF 逐位一致（gz 物理轨迹非位级确定已如实记录）。
-- 来源：①simulation 摄取时自动注册（result.scenario echo，label=auto-sim-{jobKey}，
-- label UNIQUE 幂等）；②手工注册（参数变体命名入库）。
CREATE TABLE scenario_instance (
    id             bigserial PRIMARY KEY,
    label          varchar(128) NOT NULL UNIQUE,
    scene          varchar(64) NOT NULL,           -- bin_picking 等
    scenario       jsonb NOT NULL,                 -- 归档 scenario echo（全量回显含 fixed_gripper）
    tags           jsonb NOT NULL DEFAULT '[]',    -- 检索标签（clutter/low/multi 等）
    source_job_key varchar(256),                   -- 来源 sim run（可追溯，手工注册可空）
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_scenario_instance_scene ON scenario_instance (scene);
