# ADR-0002：V0.1 持久化与队列只用 PostgreSQL（对象存储另见 ADR-0005）

- 状态：Accepted（2026-09-14；2026-09-14 更新：对象存储由 MinIO 改为 Seafile，见 [ADR-0005](./ADR-0005-storage-seafile.md)）
- 背景：系统含关系数据（项目/需求/资产）、半结构化 IR（JSON）、证据图（requirement↔evidence 多对多）、长任务队列、大对象（URDF/CAD/日志/数据集）。

## 备选方案

| 方案 | 结论 |
|---|---|
| PostgreSQL + Neo4j（Evidence Graph 用图库） | 图查询 V0.1 用不上；多一个数据库的运维/事务一致性成本不值 |
| Kafka / RocketMQ 做任务队列 | V0.1 吞吐（单机、百级任务/天）远不需要；消息系统运维成本高 |
| Redis 队列 / Temporal 工作流 | Temporal 在实验编排复杂化后（V0.5+）再评估；Redis 队列丢可靠性 |
| **PostgreSQL（JSONB + 关系表 + SKIP LOCKED 队列）+ 对象存储（现 Seafile，见 ADR-0005）** | **采纳** |

## 决策

- IR 文档存 JSONB 列；Evidence Graph 用关系表（`evidence.requirement_id / run_id / parent_evidence_id`）表达，查询走索引。
- 长任务队列表 `job_queue` + `FOR UPDATE SKIP LOCKED`（见 architecture.md §6），幂等靠 `job_key` 唯一索引。
- 大对象全部对象存储（Seafile，目录规划：`assets` / `sim-logs` / `datasets` / `reports`，见 ADR-0005）。
- 时序遥测 V0.1 用 PG 分区表；**升级触发条件**：单 run 样本量 > 1e6 或查询 P95 > 2s 时引入 TimescaleDB/ClickHouse。

## 后果

- 正面：单数据库运维、事务一致、compose 一键起；升级路径明确。
- 负面：队列无专业 MQ 特性（死信/顺序/重放需自建，V0.1 用状态机+人工处理兜底）；JSONB 查询性能需索引纪律（GIN）。
- 明确不做：第一天上 Neo4j / Kafka / K8s（产品方案 §32/§35/§36 同口径）。
