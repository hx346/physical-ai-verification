-- V4__realtest.sql — PostgreSQL：真机测试会话与遥测（M4，只读采集链路）
CREATE TABLE real_test_session (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid        NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    source     varchar(64) NOT NULL DEFAULT 'rosbag_csv',
    note       varchar(512),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_rts_project ON real_test_session (project_id, created_at DESC);

-- 单 run 样本量 > 1e6 时升级 TimescaleDB（ADR-0002 决策点）
CREATE TABLE telemetry (
    id         bigserial PRIMARY KEY,
    session_id uuid    NOT NULL REFERENCES real_test_session (id) ON DELETE CASCADE,
    ts         timestamptz NOT NULL,
    metric     varchar(64) NOT NULL,
    value      numeric     NOT NULL
);
CREATE INDEX idx_tele_session_metric ON telemetry (session_id, metric, ts);
