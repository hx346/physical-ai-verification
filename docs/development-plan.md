# RoboVerify 开发计划（V0.1）

> 基准日期：2026-09-14 · 总周期：20 周（至 2027-01-31）· 状态：P0 产品验证期
> 上游输入：私有产品方案（`plan/`，不入库）+ [architecture.md](./architecture.md) + [ADR 0001–0004](./adr/)
> 里程碑日期为单人主力开发 + 关键节点外援的假设下的目标，偏差超过 1 周即触发计划复盘。

## 0. 总目标与验收总纲

**V0.1 唯一目标**：跑通一条完整证据链的 Bin Picking 验证 Demo——

```
输入：Robot A + RGB Camera + Gripper B + 需求(成功率≥98%、节拍≤6s、定位≤3mm)
  → 解析式内核判定 FAIL（Metric Depth 不可观测，P95=7.1mm）
  → 换 RGB-D Camera C → PASS（P95=2.4mm）
  → 1000 次实验 → 敏感性：遮挡为最大失败贡献项
  → 调整相机位姿 → 98.5% PASS
  → 输出 Verification Report（含全程证据链）
```

**总 DoD（Definition of Done）**：

- [ ] 上述 Demo 脚本可从干净环境一键复现（compose up + seed + run）
- [ ] 每个判定都有 evidence 记录（输入指纹 + 内核版本 + traceId）
- [ ] 拔掉 LLM 配置，全部核心流程仍可运行
- [ ] Gate 1（历史项目回放）完成且 Problem Recall ≥ 70%，否则 STOP（见 §6）

## 1. 里程碑总览

| 里程碑 | 周期 | 主题 | 核心产出 |
|---|---|---|---|
| M0 | 09-14 → 09-27（2 周） | 仓库与 IR 基础 | 脚手架、CI、7 个 IR Schema、DB V1、种子资产 |
| M1 | 09-28 → 10-25（4 周） | 解析式验证内核 | 约束/不确定性/时延/可观测性 + Verification Matrix + 报告 v1 |
| M2 | 10-26 → 11-22（4 周） | 仿真接入 | PG 队列 + Worker + gz-sim 适配器 v1 |
| M3 | 11-23 → 12-20（4 周） | 实验引擎 | Experiment IR + LHS/MC + 敏感性分析 |
| M4 | 12-21 → 2027-01-31（6 周，含假期缓冲） | 真机只读 + Real2Sim v0 | ROS 2 只读采集、Gap 报告、校准引导 |
| G（并行） | 全程 | 产品验证门禁 | Gate 1–4 素材与执行（见 §6） |

---

## 2. M0 — 仓库与 IR 基础（09-14 → 09-27）

【目标】双运行时骨架可构建、可测试、可部署；IR 契约冻结 v0.1。
【范围】不含：业务页面、内核算法、仿真。

### 任务拆解

1. **Backend 脚手架**（Spring Boot 4 模块化单体，包结构按域：`project/requirement/asset/systemconfig/verification/evidence/job/audit`）[影响面: backend/] [风险: 低]
   1.1 工程 + 统一 `Result<T>` + 全局异常 + 结构化 JSON 日志 + traceId MDC
   1.2 Flyway V1 DDL（architecture.md §7 全部核心表）+ 回退脚本
   1.3 Sa-Token 三角色登录（admin/engineer/viewer）+ audit_log 切面
2. **Runtime 脚手架**（FastAPI + pytest + structlog + pydantic v2；worker loop 空转版）[影响面: runtime/] [风险: 低]
3. **Frontend 脚手架**（Vite + Vue3 + TS + AntD Vue + Pinia + 路由骨架）[影响面: frontend/]
4. **IR Schema**（7 个：requirement/task/system/state/environment/experiment/evidence；draft 2020-12 + 示例 YAML + 双语言校验用例）[影响面: schemas/，是全系统契约] [风险: 高——变更代价大，需评审后冻结]
   - 每个误差参数带 `provenance` 枚举（ADR-0004）
5. **种子资产**：3 机器人 / 3 相机 / 2 夹爪，参数全部标 provenance（datasheet 起步）[依赖: 4] [风险: 中——数据质量决定 M1 可信度]
6. **CI**（GitHub Actions：backend build+test、runtime lint+test、frontend build、schema 校验任务）[影响面: .github/]
7. **OpenAPI 契约 v0**：platform↔runtime 内核端点定义（health、verify、jobs）[依赖: 4]

### M0 DoD

- [ ] `docker compose -f deploy/docker-compose.yml up -d` 后 backend `/actuator/health`=UP、runtime `/health`=UP、Flyway 迁移成功
- [ ] 7 个 Schema 双语言（jsonschema / openapi 校验器）对示例文档校验通过，CI 绿
- [ ] 种子资产导入脚本幂等（重复执行无副作用）
- [ ] 一次带 traceId 的请求贯穿 backend→runtime 日志可检索

---

## 3. M1 — 解析式验证内核（09-28 → 10-25）

【目标】**不接仿真也能发现问题**——纯解析式验证闭环 + 核心界面。
【范围】不含：仿真、实验批次、真机。

### 任务拆解

1. **Constraint Solver v1**（runtime/kernel/constraint）：9 类指标（accuracy/reach/cycle/success/collision/payload/latency/FOV/workspace）规则比较 → PASS/FAIL/UNKNOWN + 缺失输入清单 [依赖: M0.4] [影响面: 内核端点]
2. **Uncertainty Engine v1**：RSS 合成 + Monte Carlo（N 可配，默认 1e4）→ P50/P90/P95 + bootstrap CI；**provenance 水位标注**（输入含 datasheet 级参数时结果显式降级说明）[风险: 高——产品核心]
   2.1 单元测试：已知闭式解的误差链验证（如三段独立高斯 RSS）
   2.2 回归基准：固定随机种子快照测试
3. **Timing Analysis**：端到端时延预算表（各环节参数来自资产模型）vs 需求判定
4. **Observability Analysis**：State IR 需求 × 传感器能力矩阵 → directly/partially/not observable
5. **Verification 编排**（backend）：一次 run = 需求集 × 系统配置 → 调内核 → 落 `verification_item` + `evidence`（输入指纹=IR 哈希、kernel_version）
6. **Verification Matrix UI v1**（hero 页：行=需求，列=现值/要求/判定/证据链接，判定色块）+ 需求/系统配置/资产基础 CRUD 页 [影响面: frontend/]
7. **Report v1**：Markdown + PDF 导出（系统概览/需求/配置/矩阵/风险/证据索引）
8. **LLM Adapter v0**（可选开关）：NL→Requirement IR 草稿，仅此一个用途；输出强制过 Schema 校验 + 人工确认
9. **Gate 1 回放工具**：历史项目 YAML 导入 → 复用同一验证管线 → 导出发现清单（供 §6 Gate 1 使用）[依赖: 1–4]

### M1 DoD

- [ ] Demo 第一幕可复现：RGB 配置 → 定位精度 FAIL（P95 计算值与手算一致）+ Metric Depth 不可观测判定
- [ ] 换 RGB-D 配置 → PASS；Verification Matrix 与报告同步更新
- [ ] 内核单元测试覆盖 ≥ 80%，随机种子固定可复现
- [ ] 每个判定在 `evidence` 表有记录且 UI 可下钻查看输入指纹
- [ ] 关闭 LLM 开关，全流程回归通过

---

## 4. M2 — 仿真接入（10-26 → 11-22）

【目标】Simulation IR → gz-sim 批量运行 → 仿真证据进入矩阵。
【范围】仅 gz-sim（Linux Docker）；不含 Isaac、不含实验设计（采样策略属 M3）。

### 任务拆解

1. **队列与 Worker 框架**：`job_queue` + SKIP LOCKED 认领 + 心跳 + 超时 + 幂等 job_key + 重试（architecture.md §6）[影响面: backend job 模块 + runtime worker] [风险: 中]
2. **gz-sim 适配器 v1**（runtime/sim_adapters/gz）：Simulation IR → 场景生成（URDF + 料箱 + 零件随机堆叠 + 深度相机插件）；脚本化抓取序列（不做完整规划器）；产出指标（可达点覆盖率/碰撞次数/循环时间/FOV 覆盖）[风险: 高——ROS 2/gz 环境复杂度]
   2.1 Linux Docker 镜像（gz-sim + ROS 2，版本以 M0 调研结论为准，暂定 gz Harmonic + ROS 2 Jazzy，**待验证假设**）
   2.2 Windows 开发路径文档化（WSL2）
3. **仿真证据回写**：sim 结果 → Evidence IR（类型=simulation）→ 关联需求；矩阵中解析式结论与仿真结论并列展示
4. **基础指标仿真化验证**：reach/collision/cycle/FOV 四项从解析式切换为"解析式 + 仿真双证据"
5. **CI 仿真冒烟**：Linux runner 跑 3 个最小场景（headless、限时）

### M2 DoD

- [ ] API 提交 100 个仿真任务 → 队列消费完成 → 状态/进度可查 → 证据入库（幂等：重复提交同 job_key 不产生重复证据）
- [ ] Worker 崩溃重启后 RUNNING 任务可恢复（心跳超时回收）
- [ ] 仿真证据在 Verification Matrix 可下钻至原始日志（MinIO 对象）
- [ ] 3 个冒烟场景 CI 稳定通过（连续 3 天）

---

## 5. M3 — 实验引擎与敏感性（11-23 → 12-20）& M4 — 真机只读 + Real2Sim v0（12-21 → 2027-01-31）

### M3 任务拆解

1. **Experiment IR 落地**：参数空间（illumination/occlusion/depth_noise/object_size/network_latency/friction…）+ LHS / Monte Carlo 采样器 [依赖: M2]
2. **批次编排**：Experiment → N 个 sim job 展开 → 聚合（成功率分布、按因子分层统计）；断点续跑（已完成 run 复用）
3. **敏感性分析**：SALib（Morris + Sobol；MC 结果上方差分解）；输出 Parameter Importance 排名 → evidence
4. **相机位姿研究 Demo**（第二幕）：1000 次实验 → 遮挡最大贡献 → 调整位姿 → 成功率提升
   - **待验证假设**：单工作站 1000 次 headless gz-sim ≤ 6h；不满足则降采样或并行容器

### M3 DoD

- [ ] 合成验证：注入已知主导因子的合成失败模型，敏感性排名正确识别该因子
- [ ] 1000-run 批次可断点续跑；聚合报告自动生成
- [ ] Demo 第二幕全流程复现

### M4 任务拆解

1. **ROS 2 只读采集器**：订阅 joint_states / camera / gripper / F/T / task_result；**只读，无任何发布控制话题**（安全边界见 architecture.md §9）
2. **遥测存储**：V0.1 用 PG 分区表（按 run+时间），数据量超阈值再引 TimescaleDB（**决策点：单 run 样本 > 1e6 时升级**）
3. **Sim vs Real Gap 报告**：同一 Experiment 配置下仿真分布 vs 真机分布 → 逐指标 Gap
4. **校准引导 v0**：scipy `least_squares` 有界拟合（noise/friction/latency 参数）→ 生成 `model_version`（DRAFT→TESTING→ACTIVE 流程，版本切换即可回滚）
5. **报告 v2**：增加 Real Test / Sim2Real Gap / 校准版本章节
6. **V0.1 收尾**：端到端 Demo 脚本固化 + 文档 + 发布 tag

### M4 DoD

- [ ] 一段真实 ROS 2 bag（或一次真机会话，若届时可用）导入 → Gap 报告生成
- [ ] 校准流程走通一次 DRAFT→TESTING→ACTIVE，历史证据仍指向旧版本（版本隔离验证）
- [ ] 全链路 Demo（三幕）一键复现

---

## 6. 并行轨道 G — 产品验证门禁

技术里程碑之外，P0 的生死判定（不达标 → STOP / 暂停产品化）：

| Gate | 内容 | 时点 | 通过标准 | 责任 |
|---|---|---|---|---|
| G1 | 10 个历史机器人项目回放（只给当时设计资料，隐藏结果） | M1 结束后启动，M3 前完成 | Problem Recall ≥ 70% | 产品/架构负责人 |
| G2 | 3–5 位机器人专家审核平台结论 | M3 期间 | Recommendation Acceptance ≥ 80% | 产品/架构负责人 |
| G3 | 真实工程效率对比 | M4 期间 | 方案验证时间降低 ≥ 30% | 全员 |
| G4 | 市场验证：接触 5–10 家客户 | M4 结束 | ≥ 1 家愿付 5–10 万+ PoC | 产品/架构负责人 |

> G1 素材（历史项目资料）属敏感数据，放 `plan/` 同级私有目录，**不入库**。

## 7. 非功能任务（贯穿各里程碑）

| 项 | 落点 | DoD |
|---|---|---|
| traceId 全链路 | M0 起 | 任一验证 run 可从 UI 下钻到全部日志 |
| 审计 | M0 起 | 需求/配置/资产/证据变更全量审计可查 |
| 回滚 | 每里程碑 | Flyway 回退脚本演练一次；模型版本切换演练（M4） |
| 性能基线 | M1/M3 | 内核单次验证 < 5s（解析式）；1000-run 批次 ≤ 6h（假设，M3 验证） |
| 安全 | M0/M4 | 三角色鉴权生效；ROS 2 adapter 代码审查确认零发布话题 |
| 数据质量 | M0 起 | 种子资产参数缺 provenance 即导入失败（强校验） |

## 8. 风险登记表（Top 6）

| # | 风险 | 等级 | 对策 | 触发信号 |
|---|---|---|---|---|
| R1 | 冷启动可信度：预测值基于 datasheet 误差（乐观偏置），客户质疑 | 高 | provenance 分级 + 报告显式标注"待实测"；优先收集公开传感器评测数据作为 literature 级先验；G1 用历史项目背书 | G1 recall < 70% |
| R2 | 双运行时 + 前端对 3–4 人团队负担过重 | 高 | Java 侧严格单体禁微服务；Runtime 无状态化；IR Schema 唯一契约减少联调 | 里程碑滑点 > 1 周 |
| R3 | gz-sim/ROS 2 环境复杂度（尤其 Windows 开发） | 中 | 仿真只跑 Linux Docker；WSL2 路径 M2 前验证；M1 全程不依赖仿真 | M2 首周环境不可用 |
| R4 | 抓取物理保真度：成功率无法纯解析预测 | 中 | 成功率结论主要来自实验引擎（MC over 场景参数），解析式只给误差/可达/时延；报告标注模型边界 | Demo 结果与直觉明显相悖 |
| R5 | 数据飞轮延迟：Reality DB 在 V0.8 后才积累 | 低（接受） | 近期护城河=证据工作流进入客户评审流程；LLM 层保持薄 | — |
| R6 | 单人带宽（Robotics 工程师未到位） | 高 | M2 前完成招聘/外援；M1 设计为可单人完成 | M1 结束时无人接 M2 |

## 9. 估时与资源假设

- 主力：1 名全栈/架构（Java + Python + 前端）；M2 起需要 1 名 Robotics 工程师（gz/ROS 2/运动学）。
- 本计划按"单人主力 + M2 起增加 1 人"排期；若持续单人，M2–M4 各延 2 周，总量约 26 周。
- 里程碑日期为日历目标，非承诺；每周五对照 DoD 检查点复盘。
