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
