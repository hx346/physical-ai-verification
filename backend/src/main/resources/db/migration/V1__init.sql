-- V1__init.sql — PostgreSQL 17（方言：PostgreSQL）
-- 核心表见 docs/architecture.md §7；所有写路径必须带 trace_id 并落 audit_log

CREATE TABLE auth_user (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username      varchar(64)  NOT NULL UNIQUE,
    password_hash varchar(256) NOT NULL,
    role          varchar(16)  NOT NULL CHECK (role IN ('admin', 'engineer', 'viewer')),
    display_name  varchar(128),
    created_at    timestamptz  NOT NULL DEFAULT now(),
    updated_at    timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE auth_token (
    token      varchar(64) PRIMARY KEY,
    user_id    uuid        NOT NULL REFERENCES auth_user (id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_auth_token_user ON auth_token (user_id);

CREATE TABLE project (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        varchar(128) NOT NULL,
    description varchar(1024),
    status      varchar(16)  NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_by  varchar(64),
    created_at  timestamptz  NOT NULL DEFAULT now(),
    updated_at  timestamptz  NOT NULL DEFAULT now()
);

-- IR 全文存 JSONB（schemaVersion 在 IR 内），键列冗余出来走索引
CREATE TABLE requirement (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid        NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    req_key    varchar(64) NOT NULL,
    ir         jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, req_key)
);
CREATE INDEX idx_requirement_project ON requirement (project_id);

CREATE TABLE system_config (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid         NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    name       varchar(128) NOT NULL,
    ir         jsonb        NOT NULL,
    created_at timestamptz  NOT NULL DEFAULT now(),
    updated_at timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX idx_system_config_project ON system_config (project_id);

CREATE TABLE environment (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid        NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    env_key    varchar(64) NOT NULL,
    ir         jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, env_key)
);

CREATE TABLE task_def (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid        NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    task_key   varchar(64) NOT NULL,
    ir         jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, task_key)
);

-- Asset Registry：ir 内 params[].provenance 由导入侧 JSON Schema 强校验（ADR-0004）
CREATE TABLE asset (
    id         varchar(64) PRIMARY KEY,
    category   varchar(32)  NOT NULL CHECK (category IN ('robot', 'camera', 'gripper', 'force_sensor', 'controller', 'compute')),
    vendor     varchar(128),
    model      varchar(128),
    cost_cny   numeric(12, 2),
    ir         jsonb        NOT NULL,
    created_at timestamptz  NOT NULL DEFAULT now(),
    updated_at timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE state_spec (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid        NOT NULL REFERENCES project (id) ON DELETE CASCADE,
    task_key   varchar(64) NOT NULL,
    ir         jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE verification_run (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid        NOT NULL REFERENCES project (id),
    system_config_id uuid        REFERENCES system_config (id),
    status           varchar(16) NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    kernel_version   varchar(32),
    trace_id         varchar(64),
    started_at       timestamptz,
    finished_at      timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_vrun_project ON verification_run (project_id, created_at DESC);

CREATE TABLE verification_item (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         uuid        NOT NULL REFERENCES verification_run (id) ON DELETE CASCADE,
    requirement_key varchar(64) NOT NULL,
    metric         varchar(64) NOT NULL,
    status         varchar(16) NOT NULL CHECK (status IN ('PASS', 'FAIL', 'UNKNOWN')),
    observed       numeric,
    unit           varchar(16),
    percentile     varchar(8),
    detail         varchar(2048),
    evidence_id    varchar(32),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_vitem_run ON verification_item (run_id);

-- Evidence Graph 用关系表表达（ADR-0002）
CREATE TABLE evidence (
    id                 varchar(32) PRIMARY KEY,
    type               varchar(16) NOT NULL CHECK (type IN ('formula', 'simulation', 'experiment', 'real_test', 'assumption')),
    run_id             varchar(64),
    requirement_key    varchar(64),
    parent_evidence_id varchar(32),
    ir                 jsonb       NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_evidence_req ON evidence (requirement_key);
CREATE INDEX idx_evidence_parent ON evidence (parent_evidence_id);

-- 任务队列：SKIP LOCKED 认领，幂等靠 job_key 唯一索引（docs/architecture.md §6）
CREATE TABLE job_queue (
    id           bigserial PRIMARY KEY,
    job_key      varchar(128) NOT NULL UNIQUE,
    type         varchar(32)  NOT NULL,
    payload      jsonb        NOT NULL,
    status       varchar(16)  NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED')),
    priority     smallint     NOT NULL DEFAULT 100,
    attempts     smallint     NOT NULL DEFAULT 0,
    max_attempts smallint     NOT NULL DEFAULT 3,
    timeout_at   timestamptz,
    locked_by    varchar(128),
    locked_at    timestamptz,
    last_error   varchar(2048),
    trace_id     varchar(64),
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX idx_job_queue_claim ON job_queue (priority, id) WHERE status = 'QUEUED';

-- 误差模型版本：DRAFT→TESTING→ACTIVE→DEPRECATED，版本切换即回滚（ADR-0004）
CREATE TABLE model_version (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type   varchar(32) NOT NULL,
    target_asset varchar(64) NOT NULL,
    version      varchar(32) NOT NULL,
    lifecycle    varchar(16) NOT NULL DEFAULT 'DRAFT' CHECK (lifecycle IN ('DRAFT', 'TESTING', 'ACTIVE', 'DEPRECATED')),
    params       jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    activated_at timestamptz,
    UNIQUE (target_asset, model_type, version)
);

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    user_id     varchar(64),
    action      varchar(64) NOT NULL,
    target_type varchar(32) NOT NULL,
    target_id   varchar(64),
    before      jsonb,
    after       jsonb,
    trace_id    varchar(64),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_target ON audit_log (target_type, target_id, created_at DESC);
