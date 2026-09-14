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

技术要点（M0 落地）：Flyway · Sa-Token · **JdbcTemplate**（MyBatis-Plus 3.5.7 的 boot3 starter 在 Boot 4.1 下自动配置未生效，按 ADR-0001 预案降级，Boot4 适配版发布后在 M1 回归） · logback JSON（logstash-encoder）+ traceId MDC · 部署为 Docker 容器（见根目录 compose）。
springdoc-openapi 同样待 Boot4 兼容版本，M1 接入。

运行（Docker，正式形态）：`deploy/docker-compose.yml` 的 `backend` 服务。
本地开发调试：`./mvnw spring-boot:run`（默认 8090，8080 常被占用）。
默认账号：admin / roboverify123（V2__seed.sql，生产必须改密）。

设计详见 [docs/architecture.md](../docs/architecture.md)。
