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
- [ ] ROS 2 只读采集器接入真机/bag（v0 骨架：deploy/ros2/collect_telemetry.py，零发布器 +
      CSV 与 /api/realtest/sessions 逐字节兼容；**2026-09-16 真实 ROS 2 humble 容器联调通过**
      （8/8 消息收齐、边界语义正确、SIGINT 二次 shutdown RCLError 已修、DDS 发现期首条
      丢失边界已标注，冒烟 harness smoke_talker.py 入库）；真机话题名/消息格式联调仍待）

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
- 2026-09-15 **收尾三项（commits 1f4ffc7 / 801b8ce）**：
  - **放置释放优化**（0.1s 轨迹诊断三段根因）：①释放高度零件底悬空 ~35mm+
    -15N 瞬时张开→落体弹跳；②指-零件 60N 挤压接触储能——任何开力（含零力
    撤压，泄压实验证伪）松指瞬间 DART 弹射 2.4m/s（0.1s 位移 236mm，零件已
    触地仍被弹飞）；③保持力降档（60→15N 减储能）两难被否决——弹飞仅部分
    缓解且降档扰动致零件脱夹（pick_success 回归）。终版：低释放（零件底
    ~2mm 触地干涉）+泄压 1.2s+渐进张开，4 seeds 实测 pick 4/4、稳定释放场景
    position_error 5.9-36mm（原全场景 ≥370mm）；重零件弹射残余如实保留
    （DART 力控+突释数值特性），根治（位置控制夹持/SDF 软接触参数）归 V0.4。
  - **ROS 2 只读采集器 v0**（deploy/ros2/）：零发布器（grep 审计 0）、
    task_result JSON→KNOWN_METRICS CSV（与导入端点逐字节兼容）、行缓冲
    kill-safe、--self-test 纯函数自验通过；诚实标注未在真 ROS 运行，待联调。
  - **87 同步**：本地侧就绪（5 自建镜像 build+导出 E:\rv-deploy-87\
    roboverify-images-w4.tar.gz，1.1GB）；执行时 87 离线（ping 100% 丢包、
    ssh 超时×3），远端步骤待服务器恢复后执行（scp→load→up，禁 pull/build）。

---

# 11. V0.5 — Experiment Platform（产品路线 §44 下一站）

> 注：产品方案版本号从 V0.3 直跳 V0.5（无 V0.4）——此前 W1-W4 为 V0.3 的**周编号**。
> V0.3 W4 已交付 experiment backend=simulator v0（单 job 串行 50-run + SRC 敏感性）；
> V0.5 把实验做成平台一等公民：并行编排、断点续跑、配置对照、感知闭环抓取。
> 基准：2026-09-15 起，4 周节奏（单人主力）。

## 目标

实验（Experiment）从"一次 API 调用"升级为可运维、可对照、可扩展的证据生产线：
1. **吞吐**：N 次仿真从单 worker 串行（50 次≈50min）到并行 worker 池（≈50/N 分钟）
2. **韧性**：批次断点续跑（中断/失败 run 复用已完成结果，不重烧 1h）
3. **对照**：同参数空间多系统配置 A/B 对照平台化（demo 第二幕手工流程产品化）
4. **保真**：抓取从"真值+注入噪声"升级为"深度相机感知定位"（Real2Sim 核心预备）

## 任务拆解

1. **W1 批次编排生产化（DAG 化）** [风险: 中——幂等/聚合一致性]
   1.1 experiment job 展开为 N 个 simulation 子 job（job_key=exp:{batch}:run:{i} 幂等）
       + 1 个聚合 job（收割子结果 → 聚合 + SRC → evidence；心跳机制已有）
   1.2 并行 sim-worker：compose `--scale sim-worker=N`（SKIP LOCKED 天然支持多 worker
       抢占；单容器一 gz 实例，CPU 核数定 N）
   1.3 断点续跑：聚合 job 发现已完成子 job（幂等 job_key 已存在即 SUCCEEDED）直接复用
   1.4 批次进度可见：子 job 完成 → 父 job payload.progress={done,total} → status API 透出
2. **W2 实验对照与报告** [风险: 低]
   2.1 对照实验 API：POST /api/experiments/comparisons（同 experiment、多 systemConfigId）
   2.2 对照报告章节：逐指标并列（含解析/仿真/实验三证据维度 + Wilson CI）
   2.3 前端实验批次页（列表/进度/结果下钻）
3. **W3 感知定位抓取 v0** [风险: 高——rgbd 数据链与标定]
   3.1 深度图 → 零件定位（点云质心/深度聚类，标定外参），替代注入噪声
   3.2 感知误差成为真实量（相机噪声模型 → 定位误差 → pick_success），
       depth_noise 敏感性从"映射假设"变"实测链路"
   3.3 与真值对照的感知误差指标入 evidence（定位误差分布）
4. **W4 技术债与收尾** [风险: 低]
   4.1 放置弹飞根治：位置控制夹持（use_force_commands=false 双模式）或 SDF 软接触参数
       （V0.3 终局保留项：稳定场景 5.9-36mm，重零件仍弹飞 ~370mm）
   4.2 全链路回归 + 87 同步 + dev-plan 收口

## V0.5 DoD

- [x] 并行编排：3+ sim-worker 下 50-run 批次 wall ≤ 20min（单机 50min 基线）
  **（2026-09-16 达成：4 sim-worker 50-run wall 922.8s=15.4min，E00255；3 worker 实测
  20.4min 差 24s 未达——16C/22T 开发机上 4 worker 无 RTF 退化，单 run wall 均值 72s）**
- [x] 断点续跑：批次中断后重启，已完成 run 不重跑（验证：复用计数 = 已完成数）
  **（2026-09-16 达成：父任务容器中断→recover 重入队→重跑 reusedRuns=6/6 零重跑，
  纯收割 wall 0.1s，E00253；sim-worker 中断场景子 job 亦复用，未完成 run 重跑）**
- [x] 对照实验：同一实验两组相机配置对照，报告并列呈现（demo 第二幕平台化）
  **（2026-09-16 达成：POST /api/experiments/comparisons 2 臂 API 实测 E00256 + demo 5.5
  三臂 E00279 + 报告 System Configuration Comparison 章节 + 前端批次/对照双 Tab 页）**
- [x] 感知抓取：深度定位误差实测入 evidence；depth_noise 敏感性来自真实感知链
  **（2026-09-16 达成：感知模块独立（perception/depth_localize.py 顶视反投影+工作空间窗
  质心）+ gz_bridge D 命令单帧深度落盘 + 序列感知路径（控制目标不读真值，standby 避遮挡，
  真值仅判定）。实测 E00280 n=6：σ=0 感知误差 1.065mm、感知闭环 pick_success=1.0、
  perception_error_mm mean/P95 入 evidence aggregates；诚实结论：真实链下 depth_noise
  杠杆臂仅 ~5-13%（顶视+质心平均+抓取容差），敏感性 share 让位 friction/object_size
  ——解析 1:1 映射的高估被暴露（W4 注入 0.60 vs W3 真实链 0.83））**
- [x] 回归：demo 全幕 + 单次仿真 + 批量实验不回归；87 同步完成
  **（2026-09-16 达成：demo 全幕 CMP=1 绿（R003=2.878mm 基准一致）；单次仿真感知闭环
  pick=1；批次 n=6 ×3 轮全通；87 同步 runtime+sim-worker 镜像）**

## 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| DAG 聚合一致性（子 job 部分失败） | 中 | 聚合按 completed/failed 如实分组（W4 已有此语义），不掩盖 |
| 感知定位精度不足（无标定真机外参） | 高 | 仿真内外参自洽（相机位姿来自场景 SDF 真值）；真机标定归 V0.8 |
| 多 worker 资源争抢（CPU/内存） | 中 | N 按 CPU 核数上限约束；RTF 退化如实记录入 wall 曲线 |
| 感知链与脚本序列耦合过深 | 中 | 定位模块独立（输入深度图 → 输出位姿假设），序列只消费接口 |

## V0.5 进展记录

- 2026-09-16 **W4 放置弹飞根治完成（V0.5 DoD 5/5，收口）**：六策略探针矩阵（力级 25/60N、
  泄压 1.2/3.0s、干涉 2/8mm、分步/单步/闭环下降、position 双模式、准静态卸载）逐步证伪
  定位三重真因：①地面 plane 在 z=-0.01 非 0——释放永远悬空 10mm 开指，穿透回弹空中击飞
  （两 seed 同落 0.8405 的确定性指纹破案；V0.3"DART 突释"归因不完整）；②位置移动硬停
  25g > μg 中途滑脱；③力 60→0 一跳泄压瞬间释放储能（小轻件 508mm）。修复：placeSurfaceZ
  场景真值 + _descend_until 低速闭环两段触地 + 全张后居中回退 + 准静态卸载渐降。
  实测：拾起成功的 5/6 run 放置 7.9-40mm（全重量级；重件 360→38.8mm）；μ=0.18 滑腻件
  运输滑脱为真实物理失败（确定复现保留）。position 双模式保留（DART 默认增益不足夹持
  重件，如实记录）。V0.5 五项 DoD 全部达成（2026-09-16，2 天完成 4 周计划——单人主力
  + AI 协作的实测节奏）。

- 2026-09-16 **W3 感知定位抓取 v0 完成**：深度图 → 反投影质心 → 控制目标（替代真值+
  注入噪声）；噪声两层模型（帧偏置 N(0,σ) 主导——ToF/结构光单帧估计特性，逐像素 iid
  σ/10 被质心 √N 平均）；真值仅用于判定（pick_success/position_error/perception_error）。
  **容器实测三连坑**（工作空间窗两次修正）：①顶视透视下箱壁内立面投影泄入窗内（32k 壁面
  点 vs 零件 ~300 点，质心拉偏 180mm）→ XY 内缩板厚+40mm（零件生成保证离壁 ≥75mm）；
  ②箱底板顶面 z=0.03 恰在 z_min 边界（6k 底面点泄入）→ z_min=0.036（最小零件顶面 0.042，
  6mm 保护带）；③提升段引用旧 live 变量 NameError（感知分支重构遗漏，py_compile 查不出
  运行期 NameError）。感知仿真：σ=0 误差 1.065mm（坐标约定对真值校验通过）、感知驱动
  下降-夹持-放置全闭环 pick=1.0、cycle 47-49s（standby+look 开销 ~15s）。
  噪声生效性：帧偏置实测抽值（σ=10.4→bias+14.1mm 等）与感知误差传播一致。

- 2026-09-16 **W2 对照实验平台化完成**：ExperimentLaunchService 抽取共享投递（同 seed 配对
  采样）；ComparisonController（创建/查询/列表，全臂完成自动摄取 evidence type=comparison）；
  Flyway V7（experiment_comparison 表 + evidence CHECK 扩展 comparison）；报告对照章节
  （指标并列 + 差值 + 假设）；批次列表 API；前端实验页双 Tab 重构；demo 5.5 幕（CMP=1）。
  实测：2 臂解析对照（RGB-D 全面更优，rate 0.0743 vs 0.0057、accP95 18.97 vs 25.14mm）；
  demo 三臂对照。诚实边界：仿真臂模板不随 systemConfig 变化（感知链 W3），对照差异≈0 属
  映射边界——已入假设清单。前端页 vue-tsc/vite 构建通过（既有 VerificationMatrixView
  simulationVerdict 类型告警为 W3 遗留，非本次引入）。

- 2026-09-16 **W1 批次编排 DAG 化完成（W1.1-W1.4 全落地）**：
  - **两级 DAG**：experiment 父任务（`requires=orchestrator`，普通 worker）LHS 采样 → 展开
    N 个 simulation 子 job（幂等键 `{parent}:run:{i}`，`requires=gz`）→ 父任务轮询收割 →
    aggregate_runs 聚合 + SRC。**关键设计：父任务必须与 sim-worker 能力隔离**——单
    sim-worker 场景下若父任务被 gz worker 认领，会占住唯一 gz 槽等子任务自我饿死；
    引入 `orchestrator` 能力反向路由（worker 容器 ROBOVERIFY_WORKER_CAPABILITIES=orchestrator）。
  - **可复现性**：noise_instance(seed, i) 按 gauss 调用次数跳过（uniform 消耗与 σ 无关），
    DAG 与串行参考实现逐位一致（单测覆盖）；采样只在父任务做一次，子 job 载荷携带
    已实例化参数与噪声。
  - **断点续跑实测**：父任务容器中断（心跳 TTL 过期 recover 重入队）→ 重跑 → 已完成
    子 job ON CONFLICT 复用零重跑（`aggregates.reusedRuns=6`，纯收割 wall 0.1s，E00253）。
  - **并行实测**：3 sim-worker × n=6 批次 wall 141.9s（单 run ~68s，串行基线 ~410s，
    加速比 ~2.9×）；sim-worker 去 container_name 后 `--scale` 生效；worker_id 默认容器
    hostname（scale 实例 locked_by/日志可区分）。
  - **兜底语义**：批次时限 `simulation.batch_deadline_s` 可配（默认 max(30min,
    1.2×n×单次超时)），超时收割部分结果并标 `deadlineExceeded`，不掩盖；子 job FAILED
    计入 failed run（单 run 失败不毁整批，W4 语义保留）。
- 2026-09-15 **W1.4 批次进度可见**：progress_cb → job payload.progress={done,total} →
  status API 透出（DAG 路径下由父任务轮询更新）；V0.5 计划落档（版本号修正 V0.3→V0.5 直跳）。
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

- 2026-09-16 **W1 DoD 前两项达成（4-worker 50-run 实测）**：
  - **吞吐**：4 sim-worker × n=50 wall 922.8s=15.4min（DoD ≤20min ✓，串行基线 50min，
    加速 3.3×；3 worker 实测 20.4min 差 24s——4 worker 无退化，单 run wall 均值 72s）。
    E00255：50/50、rate 0.62 Wilson[0.48,0.74]、depth_noise 敏感性第一。
  - **诚实记录：gz 非位级确定**——同 seed 两次 50-run rate 0.60/0.62（边界 run 翻转；
    采样矩阵与噪声实例逐位一致由单测锁定，差异来自物理求解浮点/调度，与 W3"离散<0.5%"
    观察一致）。
  - 4-worker 批次 run wall max 159.8s（均值 72s）——负载竞争下个别 run RTF 退化，
    批次不受影响（兜底时限语义保护）。

# 12. V0.8 — Real Robot Integration（W2 收尾，09-17 → 09-24）

> W1 已完成（commit 7e47212）：采集器 v1 / 幂等导入 / 会话 API / E2E 演练（REHEARSAL_OK）。
> W2 目标：真机数据在前端与报告**可见**。真机 ROS 主机不可接不阻塞 W2——
> 用 e2e_rehearsal 演练数据 / 手工导入即可开发与验证（真机接入仅剩"换话题名"，README 三步）。

## W2 任务拆解

1. **前端真机测试页**（frontend，Track A）
   - 会话列表：GET /api/realtest/sessions，列（会话/项目/runs/指标数/导入时间/external_key/duplicate 标记）
   - 会话详情 Drawer：summary 聚合（指标/mean/P50/P95/样本数，percentile_cont 同形数据）
   - Gap 视图：sim vs real 指标对照 Tab；**no_sim_counterpart 分支无 verdict 键**——如实渲染"无仿真对照"，禁止编造
   - 模型版本徽标：关联校准 model_version（DRAFT→ACTIVE）状态
2. **报告 Gap 章节**（backend，Track B）
   - report v2 → 新增 Sim2Real Gap 章节：指标对照表（metric/sim 值/real 值/ratio/verdict）
   - 项目无真机会话时章节显式标注"无真机对照"，**不省略章节**（诚实边界）
   - latency_ms gap 如实标 no_sim_counterpart（仿真无对应指标，W1 已定语义）
3. （可选 W3）rosbag 回放导入——时间盒 2 天，超时砍

## W2 DoD

- [ ] 前端真机页：列表→详情→Gap 全链路可操作；空态与 no_sim_counterpart 分支渲染正确
- [ ] 报告含 Gap 章节：有真机会话项目可见对照表；无真机项目显式标注
- [ ] E2E：e2e_rehearsal 导入的会话在前端页与报告中均可见（本地栈验证）
- [ ] 87 同步验证（backend+frontend 两镜像，V8 已在线自动迁移无需新迁移）

## W2 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| springdoc 上游阻塞 OpenAPI 聚合 | 高 | 前端按现有 API client 模式手写，不等上游 |
| 真机仍不可接 | 高 | W2 全部用演练数据开发验证；真机窗口随时插入，仅换话题名 |
| 前端页与实验页双 Tab 模式冲突 | 低 | 复用实验页 Tab/Drawer 组件模式，不共享状态 |

# 13. V0.9 — Evidence & Failure Intelligence（09-17 并行启动 → 10-15 窗口）

> 产品路线 §44 修订版新增版本（2026-09-17 方案审查）。**无外部依赖**，与 V0.8 W2 并行。
> 背景：V0.5 W2/W4 已产生高质量失败取证（六策略探针矩阵/确定性指纹破案/三重真因），
> 目前仅存于进展记录与 commit message——护城河资产白白流失，本版本先抢救存量再建增量机制。

## 任务拆解

1. **Failure DB 最小落库**（backend，Track C）
   - Flyway V9：`failure_record` 表（id/project_id 可空/failure_mode/failure_desc/root_cause/
     correction/outcome/severity/source(sim|real|manual)/evidence_id 可空关联/trace JSONB/
     detected_at/created_at）
   - 幂等：`(source, external_key)` 部分唯一索引 WHERE external_key NOT NULL（手工录入不受约束，同 V8 模式）
   - API：POST /api/failures（@Valid）、GET /api/failures?projectId=、GET /api/failures/{id}
   - 边界入参出参一律 Map（Jackson3/Jackson2 双坑），JdbcTemplate，Controller 不注 DAO
2. **存量取证回填**（Track C 后置，依赖 V9 表）
   - 回填清单：①W4 三重真因（地面 z=-0.01 悬空开指/位置硬停滑脱/力一跳泄压）；②W2"DART 接触失效"证伪
     （82 万接触条目实证，接触从未缺失）；③W3 解析 1:1 映射高估（0.60 vs 真实链 0.83）；④μ=0.18 滑腻件
     运输滑脱（真实物理失败，确定复现保留）；⑤V0.3 W4 空中击飞归因不完整修正
   - 形式：Flyway V10 seed INSERT（可追溯可回滚）优于散装脚本——实施时按此原则
3. **报告 v3**（backend，Track C 后置）
   - Failure 章节：失败模式列表+根因+修复+结局（按 severity 排序）
   - **Release Decision 摘要**章节：需求判定汇总（PASS/FAIL/UNKNOWN 计数）+ 证据完备性 +
     放行建议；**放行决策永远由人做，平台只给证据摘要**
4. **场景模板参数化 v2**（runtime，Track D）
   - scene_builder 单硬编码模板 → 参数化 Scenario 描述（JSON）：箱体几何/零件分布/相机位姿/
     光照/支撑面真值（placeSurfaceZ 等）/override 全集
   - Scenario 实例随 run 归档：sim-logs/ 同目录存 scenario JSON；复现 = 同 scenario JSON + 同 seed
     （**已知 gz 非位级确定**——复现语义为参数逐位一致，非物理轨迹一致，如实标注）
   - Scenario Registry v0：DB 表 or 对象存储+DB 索引，实施时按最小改动定
5. **Gate 1 执行框架**（backend，素材到位即跑；素材未到位只交付框架空态可跑）
   - 历史项目录入 → 批量判定 → recall 报表（Problem Recall ≥70% 判 STOP）

## V0.9 DoD

- [ ] failure_record CRUD+幂等可用（V9 迁移只走 Flyway，禁止手工 ALTER）
- [ ] 存量 W2/W4 取证 5 类全部入库，GET /api/failures 可查
- [ ] 报告 v3：Failure 章节 + Release Decision 摘要在 demo 项目报告可见
- [ ] Scenario JSON 随 sim run 归档且同参数重建场景逐位一致（单测锁定）
- [ ] Gate 1 框架链路通（录入→判定→recall 报表，无数据空态可跑）
- [ ] 87 同步验证（backend/runtime/sim-worker 三镜像）

## V0.9 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| failure 表设计过度（拟人化 Failure Intelligence） | 中 | 只落 failure/root_cause/correction/outcome 四元组+溯源，不做知识图谱 |
| 场景参数化改动破坏 W1-W4 已校准序列 | 高 | 参数化只重构生成路径不改数值；n=6 A/B 回归（放置 7.9-40mm 基线）必须通过 |
| 与 V0.8 W2 并行的 backend 文件冲突 | 中 | Track B 只改报告服务，Track C 全新文件+迁移，唯一交集 V9/V10 迁移编号串行分配 |
| Gate 1 素材持续缺位 | 高 | 框架先行，recall 数字明确标"待素材"，不伪造 |

## 并行轨道安排（2026-09-17 启动）

```text
Track A（frontend）  V0.8 W2 真机测试页        —— 独立
Track B（backend）   V0.8 W2 报告 Gap 章节      —— 独立（只动报告服务）
Track C（backend+DB）V0.9 Failure DB（V9 迁移+API）—— 独立（全新文件）
Track D（runtime）   V0.9 场景参数化 v2         —— 独立（只动 sim_adapters）
后置串行：回填 V10（依赖 C）→ 报告 v3（依赖 C+回填）→ Gate 1 框架
```
