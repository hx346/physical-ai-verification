-- V14__gate2.sql — PostgreSQL：Gate 2 执行框架（V1.0 §14，方案 §6/§44）。
-- Gate 2：3-5 位机器人专家审核平台结论，Recommendation Acceptance ≥ 80%。
-- 同 Gate 1 模式（V11）：框架先行，素材（专家评审）未到位空态 PENDING 不出结论；
-- 语义判断全部来自评审人录入，框架不做任何自动评分。
CREATE TABLE gate2_review (
    id         bigserial PRIMARY KEY,
    reviewer   varchar(128) NOT NULL,
    subject    varchar(256) NOT NULL,   -- 审核对象（报告 run / 推荐 / 项目判定标识）
    verdict    varchar(32) NOT NULL CHECK (verdict IN ('accept', 'reject', 'partial')),
    note       text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_gate2_review_subject ON gate2_review (subject);
