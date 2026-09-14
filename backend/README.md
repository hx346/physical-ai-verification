# backend — Platform（Java）

Java 25 · Spring Boot 4 · **模块化单体**（禁止微服务拆分，见 [ADR-0001](../docs/adr/ADR-0001-dual-runtime-architecture.md)）。

职责：项目/需求/资产/系统配置 CRUD 与校验、IR 持久化（JSONB）、验证编排、证据与报告管理、任务队列投递、审计、鉴权。**不做任何科学计算**。

计划包结构（M0 落地）：

```
com.roboverify.platform
├── project / requirement / asset / systemconfig   # 域模块
├── verification                                    # 验证编排，调 runtime 内核
├── evidence / report
├── job                                             # job_queue 投递与巡检
├── audit / auth / common
```

技术要点：MyBatis-Plus · Flyway · Sa-Token · springdoc-openapi · logback JSON + traceId MDC。
设计详见 [docs/architecture.md](../docs/architecture.md)。
