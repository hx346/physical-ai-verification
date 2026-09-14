-- 仿真任务需路由到具备 gz 能力的 worker（sim-worker，compose profile=sim）。
-- claim 侧按 worker 能力过滤：requires 为空的任务任何 worker 可领。
ALTER TABLE job_queue ADD COLUMN requires varchar(32);

-- 存量 simulation 任务补标
UPDATE job_queue SET requires = 'gz' WHERE type = 'simulation';
