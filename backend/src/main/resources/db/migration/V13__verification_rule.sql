-- V13__verification_rule.sql — PostgreSQL：Verification Rule 版本化（V1.0 §14 Track C）。
-- 显式映射/规则从硬编码收敛为版本化数据（评审可审、可切换、可回滚）。
-- 现两处硬编码语义不同，各自成 key：
--   sim-metric-aliases              仿真聚合键 → 解析式聚合键（SimRealGapService 三族归一）
--   requirement-sim-metric-aliases  需求指标名 → 仿真单 run 指标名（SimulationController 判定链）
-- seed v1 = 各自现行硬编码值逐键一致（行为回归保证：切换前后判定/gap 输出不变）。
-- 同一 rule_key 仅一行 active（部分唯一索引）；版本切换 = 事务内先撤旧再启新。
CREATE TABLE verification_rule (
    id         bigserial PRIMARY KEY,
    rule_key   varchar(128) NOT NULL,
    version    int NOT NULL CHECK (version > 0),
    payload    jsonb NOT NULL,
    active     boolean NOT NULL DEFAULT false,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rule_key, version)
);

CREATE UNIQUE INDEX uq_verification_rule_active
    ON verification_rule (rule_key) WHERE active;

-- seed（与 SimRealGapService/SimulationController 现行 Map.of 逐键一致）
INSERT INTO verification_rule (rule_key, version, payload, active, note) VALUES
('sim-metric-aliases', 1, '{
  "pick_success": "success_rate_mean",
  "position_error_mm": "accuracy_p95_mean_mm",
  "cycle_time_s": "cycle_time_s_mean",
  "perception_error_mm": "perception_error_mm_mean"
}'::jsonb, true, 'seeded from SimRealGapService hardcoded map (V0.8 W2)'),
('requirement-sim-metric-aliases', 1, '{
  "position_accuracy": "position_error_mm",
  "picking_success_rate": "pick_success"
}'::jsonb, true, 'seeded from SimulationController hardcoded map (V0.3 W3)');
