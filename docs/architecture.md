# RoboVerify 系统架构

> 权威设计文档。方案层面的产品论证见私有 `plan/` 目录（不入库）；本文描述**落地架构**。
> 关键决策的背景与备选方案见 [`adr/`](./adr/)。

## 1. 定位与总原则

RoboVerify 是 **Engineering Verification Runtime**：输入 Requirement IR + System IR + Asset Registry，输出带证据链的验证结论（Verification Matrix + Verification Report）。

贯穿全部设计的五条原则（与产品方案一致）：

1. **LLM 可替换**：无 LLM 时系统功能完整；LLM 只做 NL→IR 草稿、信息补全、方案生成、结果解释，**不参与 PASS/FAIL 判定**。
2. **AI 提出假设，系统证明假设**：结论来自公式 / 求解器 / 蒙特卡洛 / 仿真 / 实验 / 真机。
3. **Reality > Verification > Experiment > Simulation > Optimization > Knowledge > AI 推理**。
4. **一切可追溯**：每个判定绑定 traceId、输入指纹（配置+参数哈希）、内核版本、证据记录。
5. **不过度工程**：V0.1 单机 compose、PostgreSQL 一把梭；扩展点预留（SPI / 版本化契约），不预实现。

## 2. 容器视图

```
              ┌──────────────────┐
              │      Web UI      │  Vue 3 · Vite · Ant Design Vue · ECharts
              └────────┬─────────┘
                       │ REST/JSON
              ┌────────▼─────────┐
              │     Platform     │  Java 25 · Spring Boot 4 模块化单体
              │  (backend/)      │
              └───┬──────────┬───┘
     同步内核调用   │          │ 异步长任务（PG SKIP LOCKED 队列）
     REST/OpenAPI │          │
                   ▼          ▼
        ┌──────────────┐  ┌─────────────────────┐
        │    Runtime   │  │  Worker 进程池       │  Python 3.12 · FastAPI / worker loop
        │ （FastAPI，   │  │ sim / experiment /  │
        │  纯计算无状态）│  │ calibration         │
        └──────────────┘  └──────────┬──────────┘
                                     │ Adapter SPI
                          ┌──────────▼──────────┐
                          │ gz-sim + ROS 2 容器  │  Linux Docker only
                          │ （V0.5: Isaac Sim）  │
                          └──────────┬──────────┘
                                     │ 证据回写
        ┌────────────────────────────▼───────┐
        │ PostgreSQL 17 (JSONB)  ·  MinIO    │
        └────────────────────────────────────┘
                          ▲
              ┌───────────┴───────────┐
              │ ROS 2 只读采集（M4）    │  真机遥测 → 证据库（禁止控制命令）
              └───────────────────────┘
```

### 职责边界

| 组件 | 职责 | 明确不做 |
|---|---|---|
| **Platform (Java)** | 项目/需求/资产/系统配置的 CRUD 与校验；IR 持久化；验证编排（调用内核、聚合结果）；证据与报告管理；任务队列投递；审计日志；鉴权 | 任何科学计算（数值、采样、运动学全部下沉 Runtime） |
| **Runtime (Python)** | 同步内核：约束求解、误差合成、时延预算、可观测性判定；Worker：仿真任务、实验批次、敏感性计算、校准 | 不直接持有业务数据；通过 Platform API 读写；无 UI |
| **Simulation Adapter** | Simulation IR → gz-sim / Isaac 场景；运行；产出原始结果与指标 | 不含验证逻辑（判定只在内核） |
| **Frontend** | Verification Matrix（核心页）、需求/配置/证据/报告页面 | V0.1 不做 3D 编辑器 |

## 3. 契约面（三个）

契约是双运行时协作的关键，全部版本化、评审后变更：

1. **Platform ↔ Runtime REST 契约**：OpenAPI 3.1，`schemas/openapi/`。内核端点无状态、可重放（幂等由 `requestId` 保证）。
2. **Engineering IR JSON Schema**：`schemas/ir/*.schema.json`，JSON Schema draft 2020-12，语言中立；Java 侧与 Python 侧都以此校验，禁止各自手写模型漂移。IR 版本规则：`schemaVersion` 字段 + 语义化版本；破坏性变更升主版本并双版本共存一个过渡期。
3. **任务队列协议**：PostgreSQL 表 `job_queue`（见 §6），Worker 用 `SELECT ... FOR UPDATE SKIP LOCKED` 认领；状态机 `QUEUED → RUNNING → SUCCEEDED / FAILED / TIMEOUT / CANCELLED`。

## 4. Engineering IR 体系

| IR | 内容 | 备注 |
|---|---|---|
| Requirement IR | metric / operator / value / unit / percentile / confidence / priority | 可执行需求，如 `picking_success_rate >= 0.98 @ P95, conf 0.95` |
| Task IR | Target / Environment / Precondition / SuccessCriteria / FailureCriteria / Constraint | V0.1 仅 `PickObject` |
| System IR | Robot / Sensor / Actuator / Controller / Compute / Network / Software 引用 + 安装参数（如相机位姿） | 组成系统实例，引用 Asset Registry |
| State IR | 任务所需状态（ObjectPose、ContactForce…）+ Accuracy / UpdateRate / Latency / Confidence / Coverage | 可观测性分析的基础 |
| Environment IR | 料箱尺寸、零件特征、光照范围、遮挡等 | 实验空间的边界来源 |
| Experiment IR | 参数空间 + 采样策略（LHS/MC）+ 批次大小 + 聚合方式 | M3 落地 |
| Simulation IR | robot(urdf) / sensor(pose,type) / environment(scene) / experiment 注入 | Adapter SPI 的输入 |
| Evidence IR | 证据类型（formula/simulation/experiment/real_test）+ 输入指纹 + 结果 + 关联需求 | 全部判定的落脚点 |

**误差参数 provenance 分级**（Asset Registry 中每个误差参数必填）：

```
datasheet（厂商手册，乐观偏置） < literature（公开评测） < measured（自有实测） < calibrated（Real2Sim 校准后）
```

内核输出必须携带 provenance 最低水位与假设清单；低水位输入在报告中被显式标注为"待实测确认"。（ADR-0004）

## 5. Verification Kernel（Runtime 内部）

| 模块 | 方法 | V0.1 范围 |
|---|---|---|
| constraint | 规则 + 区间比较（reach/payload/FOV/workspace/collision 前置检查） | 9 类需求指标 |
| uncertainty | RSS 误差合成 → 解析分布；Monte Carlo（默认 1e4 次，可配）→ P50/P90/P95 + bootstrap CI | 位置精度、成功率影响因子 |
| timing | 端到端时延预算表（camera→network→inference→planning→controller→actuation） | 各环节延迟参数来自资产模型 |
| observability | State IR 需求 vs 传感器能力矩阵 → directly / partially / not observable | 20~30 种状态 |
| reachability | Pinocchio FK + 工作空间采样；碰撞用 FCL | 解析式，M2 后叠加仿真证据 |

判定输出统一为：`PASS / FAIL / UNKNOWN` + 置信度 + 贡献度分解 + 证据引用。**UNKNOWN 也是合法结论**（输入缺失或 provenance 不足时），禁止编造。

## 6. 任务队列（V0.1）

- 表：`job_queue(id, job_key UNIQUE, type, payload jsonb, status, priority, attempts, max_attempts, timeout_at, locked_by, locked_at, created_at, updated_at, last_error)`。
- 幂等：`job_key` 唯一索引（如 `exp:{expId}:run:{runNo}`），重复投递直接复用。
- 重试：`attempts < max_attempts`（默认 3）重新入队；超限 → `FAILED`（人工处理，V0.1 不做自动死信转发）。
- 超时：`timeout_at` 到期由巡检置 `TIMEOUT` 并释放。
- 回滚：队列数据可弃（证据可由 Experiment IR 重放重建）；先停 Worker 再处理积压。

## 7. 数据模型概览（Flyway 管理，V1 于 M0 落地）

核心表：`project`、`requirement`（JSONB 存 Requirement IR）、`system_config`（System IR）、`asset`（+`asset_param` 带 provenance）、`state_spec`、`verification_run`（一次验证编排）、`verification_item`（矩阵中的一行）、`evidence`（Evidence IR + MinIO 对象引用）、`job_queue`、`audit_log`。

Evidence Graph 用关系表表达（`evidence.requirement_id / run_id / parent_evidence_id`），不引入图数据库（ADR-0002）。所有写操作带 `trace_id` 列 + 审计表。

## 8. 部署拓扑

| 环境 | 形态 | 说明 |
|---|---|---|
| 开发（Windows） | Docker Desktop：PG + MinIO + gz-sim 容器；backend/runtime/frontend 本机进程；仿真调试走 WSL2 | 解析式内核（M1 前）纯 Windows 可跑 |
| 开发（Linux/WSL2） | 同上，全容器 | 推荐 M2 起使用 |
| 生产（V0.1~V0.5） | 单机 Linux + docker compose（全栈） | 一台工作站足够 |
| 生产（V0.8+） | K8s + GPU 调度 + 多租户 | 届时另行设计，不预实现 |

## 9. 安全与安全边界

1. **真机接口只读**：M4 的 ROS 2 adapter 仅订阅话题采集证据；**任何控制命令下发在 V0.1~V0.8 明确禁止**。控制链路需要独立的权限/白名单/互锁/审计设计，属于后续版本。
2. **LLM 输出不可信**：NL→IR 的 LLM 输出只能作为**草稿**，必须过 JSON Schema 校验 + 用户确认后才入库；LLM 不能写 evidence、不能改判定。
3. 鉴权：Sa-Token 轻量登录 + 角色（V0.1 单租户、admin/engineer/viewer 三角色足够）。
4. 审计：需求/配置/资产/证据的创建与变更全部落 `audit_log`（who/when/what/before/after）。
5. 仿真容器资源限额（CPU/mem），防止失控任务拖垮工作站。

## 10. 可观测性

- 全链路 `traceId`：Frontend 生成 → Platform MDC → Runtime/Worker 透传（HTTP header / job payload）→ evidence 记录落库。
- 结构化 JSON 日志（logback JSON / structlog），禁止 System.out / print。
- 指标：M0 起 Micrometer + `/actuator/prometheus`（Platform）、Prometheus client（Runtime）；本地 docker compose 预留 Prometheus/Grafana profile（可选开启）。

## 11. 版本化与回滚策略

| 对象 | 版本化 | 回滚 |
|---|---|---|
| IR Schema | `schemaVersion` + git tag | 双版本共存过渡；旧数据只读保留 |
| 误差模型 / 校准模型 | `DRAFT → TESTING → ACTIVE → DEPRECATED` 生命周期（表 `model_version`） | 版本切换即回滚；历史证据绑定生成时的版本 |
| 验证内核 | 语义化版本，evidence 记录 `kernel_version` | 重放（输入指纹不变 → 结果可复现） |
| DB | Flyway，只加不改（向后兼容迁移） | `flyway repair` + 逐版本回退脚本 |
| 报告 | 报告不可变，重新验证生成新版本 | 旧版本永久保留 |

## 12. 相关文档

- 开发计划（里程碑/DoD/风险）：[development-plan.md](./development-plan.md)
- 决策记录：[adr/](./adr/)
- IR Schema：[../schemas/](../schemas/)（M0 落地首批 7 个）
