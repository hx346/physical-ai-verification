# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 仓库骨架：双语 README（`README.md` / `README.zh-CN.md`）
- 系统架构文档 `docs/architecture.md`
- 开发计划 `docs/development-plan.md`（M0–M4 里程碑 + 产品验证门禁）
- 架构决策记录 ADR-0001 ~ ADR-0005
- 开发基础设施 `deploy/docker-compose.yml`（PostgreSQL 17 + Seafile 栈）
- M0 脚手架：9 个 Engineering IR JSON Schema + 示例（21 实例校验通过）、
  backend（Spring Boot 4.1 / Java 25，Flyway V1+V2，Sa-Token，JSON 日志，traceId 贯通）、
  runtime（FastAPI，schema 校验，SKIP LOCKED worker 骨架）、frontend（Vue 3 + AntD，验证矩阵页）

### Changed

- 对象存储：MinIO → Seafile（WebDAV，经 ObjectStore SPI 抽象，ADR-0005）
- 部署形态：应用全部容器化（backend/runtime/frontend 进 compose，不在开发机本地跑进程）
- M0 数据访问降级 JdbcTemplate（MyBatis-Plus 无 Boot4 starter，M1 回归）

### Verified

- IR 契约：21 个示例实例全部通过 Schema 校验
- backend：`mvn verify` 7 tests 通过；容器化前后 E2E（登录/鉴权/内核透传/traceId 贯通/inputFingerprint）验证
- runtime：pytest 5 passed；`/ready` 连 PG 正常
- frontend：`npm run build` 通过

## [M1–M4] — 2026-09-14

### Added

- **M1 解析式验证内核**：constraint（reach/payload/FOV）、uncertainty（RSS + 蒙特卡洛
  P50/P90/P95 + bootstrap CI + 贡献度）、timing（端到端时延预算）、observability（状态需求
  vs 传感器）、success（logistic 概率模型，版本化系数 models_v01）；UNKNOWN 为合法结论
- **M1 编排与证据**：verification_run/item/evidence 落库（输入指纹+内核版本+traceId+假设清单）、
  IR 导入端点（过 Schema 校验）、Demo 种子（seed-demo）、报告 v1/v2（Markdown 含实验证据节）
- **M3 实验引擎**：LHS/MC/网格采样（numpy 实现）、逐样本向量化求值、聚合分位数、
  一阶 Sobol 敏感性（SALib）、worker 异步执行 + 幂等证据摄取
- **M2 仿真链路（代码完成，gz 集成待验证）**：Simulation Adapter SPI、Simulation IR→SDF 场景
  生成、gz 适配器（无 gz 运行时显式失败不编造）、compose profile=sim（gz.Dockerfile）
- **M4 真机链路（只读）**：CSV 遥测导入（real_test_session/telemetry 表）、Sim2Real Gap
  报告、depth_sigma_scale 校准拟合、model_version DRAFT→TESTING→ACTIVE 状态机（版本切换即回滚）
- 前端：验证矩阵接真实数据（运行验证/证据 Drawer/报告下载）、实验页（聚合+敏感性条形）、
  项目页演示数据导入
- 全链路 Demo 脚本 `deploy/demo/run-demo.sh`（三幕叙事 + 位姿对照 + Real2Sim 闭环）

### Verified

- runtime：18 tests + ruff clean（RSS 闭式 3-4-5、MC vs 折叠正态 1.96σ 3% 容差、
  RGB FAIL/RGB-D PASS 语义、LHS 分层、Sobol 排名、位姿改进效应、校准插值）
- backend：`mvn verify` BUILD SUCCESS（含 M1–M4 全部控制器）
- 容器化全栈 E2E：见 Demo 脚本执行结果

### Pending（如实标注）

- gz-sim 容器镜像与无头渲染集成（M2 窗口，需 Robotics 工程师验证）
- Seafile 镜像首次拉取验证 + WebDAV 适配器（M2）
- 真机 ROS 2 只读采集器（M4 代码位预留，需真机/ROS 环境）
- GitHub Actions 首跑结果确认
