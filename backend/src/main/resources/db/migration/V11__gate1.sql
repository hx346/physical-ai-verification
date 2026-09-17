-- V11__gate1.sql — PostgreSQL：Gate 1 执行框架（V0.9，dev-plan §13 任务 5；方案 §52）
-- Gate 1：10 个历史机器人项目——只提供当时设计资料、隐藏最终结果、平台判定，
-- 对照已知问题算 Problem Recall（≥70% 通过，否则 STOP）。
-- 已知问题 ↔ 平台判定的语义匹配是评审人判断（框架不做自动匹配，不编造）；
-- 框架只负责：案例录入 → 判定记录 → recall 报表。素材未到位时空态可跑。
CREATE TABLE gate1_case (
    id           bigserial PRIMARY KEY,
    label        varchar(128) NOT NULL,
    project_id   uuid,
    known_issues jsonb NOT NULL,   -- [{issue, severity, metric?, note?}]（录入后不可变语义）
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gate1_finding (
    id              bigserial PRIMARY KEY,
    case_id         bigint NOT NULL REFERENCES gate1_case(id),
    known_issue     varchar(256) NOT NULL,
    platform_verdict varchar(64) NOT NULL,  -- 平台侧判定摘录（如 FAIL 项/SIM_FAIL/证据缺失）
    matched         boolean NOT NULL,       -- 评审人判断：平台是否提前发现该问题
    note            text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, known_issue)           -- 同案例同问题幂等（upsert 语义）
);
CREATE INDEX idx_gate1_finding_case ON gate1_finding (case_id);
