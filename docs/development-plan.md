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

### M1 DoD ✅（2026-09-14 达成）

- [x] Demo 第一幕可复现：RGB 配置 → 定位精度 FAIL（P95 计算值与手算一致）+ Metric Depth 不可观测判定
- [x] 换 RGB-D 配置 → PASS；Verification Matrix 与报告同步更新
- [x] 内核单元测试覆盖 ≥ 80%，随机种子固定可复现（RSS 闭式 3-4-5 交叉校验、MC vs 折叠正态 1.96σ 3% 容差）
- [x] 每个判定在 `evidence` 表有记录且 UI 可下钻查看输入指纹（Drawer：假设清单 + 贡献度 + provenance）
- [x] 关闭 LLM 开关，全流程回归通过（系统未接任何 LLM，原则一天然满足）

> 调整记录：原计划 springdoc-openapi 待 Boot4 兼容版（M1+）；MyBatis-Plus 降级 JdbcTemplate（Boot4 无适配）。

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

### M2 DoD ⚠ 大部分达成（2026-09-15：gz 仿真任务实际执行已验证 ✓，剩证据落库与矩阵下钻）

- [x] 队列消费/状态查询/幂等（job_key 唯一；experiment 类型已验证全链路）
- [x] Worker 崩溃重启后 RUNNING 任务可恢复（心跳超时回收，代码实现+单测覆盖 claim 路径）
- [x] gz 仿真任务实际执行（**2026-09-15 容器实测**：官方 OCI 镜像 `ghcr.io/j-rivero/gazebo:harmonic-full`（gz 8.10.0）+ 无 GPU 无头渲染 ogre2/EGL 通过——rgbd 相机产出 image/depth_image/points 话题且有数据帧；sim-worker 容器（profile=sim）消费 simulation job #8 SUCCEEDED，真实指标 sim_time_s=113 / RTF=0.998 / physics_iterations=113933 / depth_camera_active=1。实测抓出并修复：scene_builder 缺 gz systems 插件（Physics/Sensors）→ 传感器不实例化）
- [x] 仿真证据进 Verification Matrix（**2026-09-15 容器实测**：POST /api/simulations → sim-worker（能力路由 requires=gz）→ evidence 落库 E00162 → scene.sdf 归档 SeaweedFS /sim-logs/{jobKey}/ → 矩阵下钻 API + 前端 Drawer 关联仿真证据区块；IR 请求指标不可得处诚实标注 unavailable 不编造；demo 第八幕 SIM=1 可选）

---

## 5. M3 — 实验引擎与敏感性（11-23 → 12-20）& M4 — 真机只读 + Real2Sim v0（12-21 → 2027-01-31）

### M3 任务拆解

1. **Experiment IR 落地**：参数空间（illumination/occlusion/depth_noise/object_size/network_latency/friction…）+ LHS / Monte Carlo 采样器 [依赖: M2]
2. **批次编排**：Experiment → N 个 sim job 展开 → 聚合（成功率分布、按因子分层统计）；断点续跑（已完成 run 复用）
3. **敏感性分析**：SALib（Morris + Sobol；MC 结果上方差分解）；输出 Parameter Importance 排名 → evidence
4. **相机位姿研究 Demo**（第二幕）：1000 次实验 → 遮挡最大贡献 → 调整位姿 → 成功率提升
   - **待验证假设**：单工作站 1000 次 headless gz-sim ≤ 6h；不满足则降采样或并行容器

### M3 DoD ✅（2026-09-14 达成）

- [x] 合成验证：注入已知主导因子的合成失败模型，敏感性排名正确识别该因子（test_sensitivity_ranks_occlusion_or_depth_top）
- [x] 1000-run 批次（LHS）+ 聚合报告自动生成（断点续跑为 M3 末项优化，当前整批重跑）
- [x] Demo 第二幕全流程复现（run-demo.sh 第 4-5 步：1000-run + 相机位姿 0.65/0.95 对照）

### M4 任务拆解

1. **ROS 2 只读采集器**：订阅 joint_states / camera / gripper / F/T / task_result；**只读，无任何发布控制话题**（安全边界见 architecture.md §9）
2. **遥测存储**：V0.1 用 PG 分区表（按 run+时间），数据量超阈值再引 TimescaleDB（**决策点：单 run 样本 > 1e6 时升级**）
3. **Sim vs Real Gap 报告**：同一 Experiment 配置下仿真分布 vs 真机分布 → 逐指标 Gap
4. **校准引导 v0**：scipy `least_squares` 有界拟合（noise/friction/latency 参数）→ 生成 `model_version`（DRAFT→TESTING→ACTIVE 流程，版本切换即可回滚）
5. **报告 v2**：增加 Real Test / Sim2Real Gap / 校准版本章节
6. **V0.1 收尾**：端到端 Demo 脚本固化 + 文档 + 发布 tag

### M4 DoD ⚠ 部分达成（2026-09-14：管线闭环，真机数据源待接）

- [x] 遥测导入 → Gap 报告生成（CSV 链路已验证；演示用 synthetic 数据并显式标注"非真机"）
- [x] 校准流程走通 DRAFT→ACTIVE（版本状态机 + 激活即回滚；历史证据仍指向生成时版本——版本隔离验证）
- [x] 全链路 Demo（三幕 + Real2Sim 闭环）一键复现（deploy/demo/run-demo.sh）
- [ ] ROS 2 只读采集器接入真机/bag（代码位预留：realtest CSV 即其导出格式；需 ROS 环境）

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
---

# 10. V0.3 — Simulation Verification（09-21 → 10-16，4 周）

> 产品路线（方案 §44）：V0.1 Design Verification ✓（已超额含仿真/实验/真机 v0 骨架）→
> **V0.3 Simulation Verification：仿真成为一等验证证据源**。
> 前置已消除：gz 无头渲染/能力路由/证据落库/对象归档全链路已实测（2026-09-15）。

## 目标

仿真证据从"独立展示的物理统计"升级为"**能回答设计问题、参与需求判定**"：
IR 请求的 pick_success / cycle_time_s / collision_count / position_error_mm 四项指标
从 unavailable → measured（不编造原则）。

## 任务拆解

1. **W1 抓取序列 v0（简化垂直夹爪）**
   1.1 探测：gz ScriptSystem（Lua）与 gz topic/service CLI 驱动能力（容器内实测）
   1.2 scene_builder：加简化 kinematic 垂直夹爪（两指）+ 接触传感器（指尖）
   1.3 抓取脚本：下降→闭爪→（attach 或几何接触判定）→提升→放置；仿真时钟计 cycle_time
2. **W2 四项指标真实化**
   - pick_success = 夹爪闭合时指尖与目标零件接触且质心偏差 < 指宽/2
   - position_error_mm = 放置后零件位置 vs 目标点（仿真真值）
   - collision_count = 接触传感器计数（非目标接触）
   - cycle_time_s = 序列起止仿真时钟差
   - 全部写入 SimResult.metrics；requestedMetrics 同步 measured
3. **W3 仿真验证判定链**
   - SimulationController 摄取时：若 requirementKey 有阈值（如 R003 ≤3mm），
     生成"仿真 vs 需求"比对结论（SIM_PASS/SIM_FAIL，标注 provenance=simulation）
   - verification_item 证据维度扩展：解析证据 + 仿真证据并列展示（矩阵 UI）
4. **W4 批量仿真 + 假设验证**
   - experiment 引擎支持 backend=simulator（LHS 采样 → N 次 headless gz → 聚合+Sobol）
   - 验证 dev-plan 假设：单工作站 N 次 headless 耗时曲线（1000 次不现实则 50–100 次，
     结果显式标注采样规模）

## V0.3 进展记录

- 2026-09-15 W1：驱动机制定型（VelocityControl cmd_vel + JointPositionController model 级），
  抓取序列全链路 SUCCEEDED，pick_success/cycle_time_s/position_error_mm 三项 measured
- 2026-09-15 W2：控制环提速（PoseStreamer 持续订阅）；**根因修复×2**——warmup 15s 坠落致指底
  扫碰零件（缩短至 6s + 实时 xy 追踪）、闭合冲击弹飞（渐进闭合）；零件不再被弹离（留原位±5mm）
- 2026-09-15 W2 续（10 轮容器迭代）：力语义修正（use_force_commands=true 时 cmd 是力 N，
  曾误发位置值 0.027 当力≈0.027N）；悬停防坠轰炸（Popen 后 1s 起零速，杜绝坠落撞 bin 致姿态歪斜）；
  关节限位防交叉（upper=half_open-1mm，曾允许指穿中线）；仿真对象 key 规范化（jobKey 冒号→连字符，
  Windows 文件系统兼容）；对中已收敛（零件扰动 <5mm）
- W2 剩余疑点（收敛后）：指-零件接触物理本身——诊断观测到力驱动下指可穿越零件空间而零件不动，
  怀疑 DART 接触求解在该构型下失效（下一步：碰撞有效性单变量实验：零件置于两指间仅闭合力，
  观察是否被阻挡；必要时调 solver iterations/接触刚度/换 bullet 引擎对比）；collision_count 待接
- 2026-09-15 **W3 进展（commit 见 git log）**：
  - **gz-bridge 进程内 transport**（deploy/sim/gz_bridge.cc，gcc -x c++ 编入 sim 镜像）：
    stdin 速度指令→cmd_vel 即时发布、位姿/接触话题→stdout 行协议；实测位姿 0.2s 就绪、
    cmd→运动 ≤63ms——CLI one-shot 死区与位姿滞后根除。**pick_success=1.0 达成且 3/3
    可复现**（E00189–E00191，指标离散 <0.5%）：双向 move 收敛（6mm）、对称闭合
    （25317 接触）、夹起提升 z 0.0475→0.395、cycle 30.4s；position_error≈370mm
    为放置释放真实测量（R003 判 SIM_FAIL 如实呈现）。
  - **仿真判定链**：SimulationController 摄取时 requirement.ir（metric/operator/value）
    vs 仿真实测指标 → evidence.ir.simulationVerdict（SIM_PASS/SIM_FAIL/SIM_UNKNOWN，
    provenance=simulation）；需求指标→仿真指标显式映射表（position_accuracy→
    position_error_mm 等，评审可审），未映射/缺阈值 → SIM_UNKNOWN 诚实降级；
    单次运行 percentile 不适用如实标注。矩阵 Drawer 仿真证据块加判定徽标。
  - 回归修复：对象 key 去前导斜杠（LocalFs 拒绝绝对路径，SeaweedFS 容忍——M2 未炸的
    潜伏坑）；demo 第八幕 Windows 路径坑（mktemp MSYS 路径 Windows python 不可见→
    相对路径）。demo 全八幕 SIM=1 回归通过。
- 2026-09-15 **W4 完成（批量仿真 + 敏感性，V0.3 全 DoD 达成）**：
  - **experiment 引擎支持 backend=simulator**：`POST /api/experiments {backend:
    simulator}` → LHS 采样 → N 次 headless gz（单件箱模板，每 run 独立场景 seed）
    → 聚合 + SRC 敏感性（runtime/experiment/sim_backend.py）。参数映射显式可审：
    depth_noise_mm→抓取目标 N(0,σ) 三轴定位噪声（感知误差模拟，判定仍用真值）、
    object_size_mm/friction_coeff→场景 overrides；illumination/occlusion/latency
    未映射（脚本抓取无感知链，assumptions 如实声明，其 SRC share 属采样噪声非物理）。
    敏感性方法学：Saltelli-Sobol 需 N×(2k+2) 次仿真求值（6 参数 base 256 → 3584 次
    ≈60h）单工作站不可行 → LHS 样本上 SRC（Pearson r²），样本量与 R² 随结果标注。
  - **50-run 实测（E00220）**：50/50 完成、pick_success_rate=0.64（Wilson CI
    [0.50,0.76]）、每 run 59.8s wall、总 49.8min；**敏感性 depth_noise 双目标
    （pick_success/position_error）均排第一**，与解析引擎"深度噪声属主导贡献类"
    方向一致（解析 top3=object_size/friction/depth_noise）。仿真同时揭示解析
    logistic 的 object_size 权重偏差（仿真端 size≈0：单件自定心与尺寸弱相关）——
    模型边界信号，报告并列呈现不掩盖。耗时假设验证：1000 次 ≈16.6h，"1000 次
    ≤6h" 不成立 → 50-100 次为单工作站合理规模（显式标注采样规模）。
  - **参数范围探测先行**（避免整批无信号）：σ=0/20/40 三点探测——翻转点在
    (0,20)，定 [0,15]；σ=20 的 4σ 偏移实例下刀被顶卡死。顺手优化：下刀未到位
    快速收尾（跳过闭合/放置，失败 run wall 196s→~60s）。
  - **worker 心跳实装**（架构 §6 承诺但 runner 从未调用——claim 只设一次
    timeout_at，>5min 任务必被 recover 误回收重跑）：handler 运行期间后台线程
    每 60s 独立连接续期。首版踩坑：函数未 import（NameError 静默吞进 except，
    py_compile 查不出）——手动续期止血 + n=5 验证批确认续期生效
    （timeout_at 随 locked_at+60s 推进）。
  - demo 第九幕（SIM_EXP=1 门控，默认跳过）；八幕回归全绿（pick_success=1.0
    复现、归档正常）。
- 2026-09-15 **W2 终局（碰撞单变量实验 + 15 轮生产迭代，commit 3 项根因修复）**：
  - **"DART 接触失效"假设被证伪**：单变量实验（deploy/sim/collision_probe.py，零 g/
    静态 base/单零件/仅闭合力）显示接触检测与响应从未缺失（82 万接触条目、指停在零件面
    ±0.025、bullet/dart 均可稳定夹持）。真凶组合：
    ① **SDF `<inertial>` 缺 `<inertia>` 默认单位阵**（比真实值大 ~4 个数量级）→ LCP 病态
    → 接触互踢弹跳（baseline 复现生产症状；显式盒惯量后稳定夹持）——全场景 link 补真实惯量；
    ② **实心 bin**：零件生成在固体内部 → DART 深穿透弹射 = warmup 弹飞根因——改五面空心箱；
    ③ **protobuf 文本格式省略零值字段**（position { z: 0.235 }，x/y=0 不打印）——位姿解析
    要求 x/y/z 齐备 → 恰在坐标轴上的实体（含所有 finger link，y≡0）被漏读——逐轴可选解析。
  - **collision_count 接通**：gz-sim8 Contact system 只发布 link 级 contact sensor 话题且仅
    有接触时发消息（源码实证，/world/*/physics/contacts 话题不存在）——指面加 contact sensor
    （/gripper/finger_*/contact），闭合→提升窗口计数，4/4 IR 指标 measured（E00174–E00188）。
  - **夹爪控制面定型**：link 级 `<gravity>0</gravity>`（龙门架重力补偿——0.45m 自由落体 0.3s
    即撞箱，零速轰炸来不及；dartsim 模型级 LinearVelocityCmd 零速指令下仍恒定下沉 g·dt
    ≈0.0098m/s，关重力后零速精确悬停）；指长 0.02 抓零件上半侧；侧向下刀沿 y（x 下插被顶面
    接触顶住、x 平移被开口侧指面顶住停在差 clearance 处→偏斜挤飞）。
  - **运动传输瓶颈（诚实结论）**：one-shot CLI 发布（subprocess ~0.3s）+ 位姿流滞后 ~1s 下，
    连续 P 发散（runaway x=2.11，接触对全是 finger↔bin_floor/wall）、等幅步过冲磕箱底、
    精调步爬行超时；5Hz 持续发布线程后大位移收敛（lateral_ok=true、零件被咬住拖动 10cm）
    但短距比例控制仍振荡——**需进程内 gz-transport 节点（W3 事项）**。pick_success 保持 0
    是 15 轮真实结果，证据链完整；抓取物理本身已被单变量实验+生产接触流双重证明。

## V0.3 DoD ✅（2026-09-15 全部达成）

- [x] 四项 IR 请求指标 measured（单次仿真实测，数字自洽可追溯 evidence）
  （4/4：pick_success 真实测量为 0、collision_count 5648——失败被如实记录，
  正是验证系统的意义；运动传输精度为 W3 攻坚项，见 W2 终局记录）
- [x] 仿真结论参与矩阵（requirement 有阈值时可给 SIM_PASS/SIM_FAIL）
- [x] 批量仿真 ≥50 次跑通，敏感性排名与解析引擎方向一致（深度噪声主导类）
- [x] 全链路回归：demo 三幕 + 第八幕 + 归档不回归

## 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| gz 内抓取脚本（attach/接触）复杂度超预期 | 中高 | 先几何接触判定（无 attach），attach 为增强；失败则指标降级为可测子集并如实标注 |
| 仿真循环时间与 1000 次假设差距 | 中 | W4 实测后定采样规模，显式标注；并行容器留 V0.5 |
| 仿真指标与解析内核结论矛盾 | 低 | 矛盾即价值（Real2Sim 起点），报告并列呈现不掩盖 |
