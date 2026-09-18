# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- **V1.0 Real2Sim + Calibrated Asset（2026-09-17/18，五任务全落地 DoD 8/8，tag v1.0.0——商业产品线成型）**：
  - **校准引擎 v1**（`calibration/multi_param.py`）：σ_scale 一维 → 两参数 MLE（网格响应面双线性插值+高斯似然，无 scipy）；profile 95% CI + 不可辨识检测（响应面平坦/耦合如实标 identifiable=false，UNKNOWN 合法不硬给点估计）；**前向仿真与估计器解耦**（引擎吃参数网格点的仿真聚合）；测试驱动修 3 个实现 bug（MLE 权重归一化=信息量稀释 1.4 倍、profile 阈值应比较 -2ΔlnL 差 2 倍、logLik Hessian 负定时条件数须取绝对值）
  - **校准编排**（`POST /api/calibrations`）：网格×repeats 展开 simulation 子 job（DAG 复用，`cal:…:pt{p}:run{r}` 幂等+断点续跑）→ 逐点聚合 → fit → model_version DRAFT 摄取幂等；realObs se 推导（成功率 sqrt(p(1-p)/n)、P95 正态近似 2.11σ/√n）**假设显式入 params.assumptions**、样本<5 不派生；E2E 实测 8 run 561s identifiable=true
  - **Reality DB v1**（V12 `reality_observation`）：设备×环境×任务×指标分布（方案 §23 数据护城河最小落库）；provenance CHECK（literature/measured/calibrated）；会话聚合自动派生（external_key 部分唯一幂等）+ 手工录入（calibrated 级拒绝手工，只能回写产生）+ V9 failure 关联查询 JOIN
  - **Verification Rule 版本化**（V13 双 key，seed 与原硬编码逐键一致）：SimRealGapService 与 SimulationController 两处映射收敛 `VerificationRuleService` 单源（直查表+回退内置防断链）；版本激活切换 = 规则回滚机制
  - **provenance 回写**：校准 model_version ACTIVE 时来源会话派生观测批量升 calibrated 并标注版本
  - **Gate 2 框架**（V14 `gate2_review`）：专家审核录入 + acceptance 报表（accept/total 保守口径，partial 计分母）；空态 PENDING 不出结论
  - 附带：`fake_cell.py` 合成抓取单元 + `e2e_fake_cell.sh` 一键演练（真机接入前演示/回归数据源，同 seed 端到端确定性）；87 已同步（3 镜像，V12-14 迁移+seed 生成）
- **V0.9 Evidence & Failure Intelligence（2026-09-17，四轨+串行队列全部完成）**：Failure DB 最小落库（Flyway V9 `failure_record` 四元组+severity/source CHECK+trace JSONB+external_key 部分唯一索引，POST/GET /api/failures 幂等）；V10 存量取证回填 6 条（W4 三重真因×3 / W2"接触失效"证伪 / W3 解析映射高估 / μ=0.18 滑脱基线，平台级归属 project_id NULL）；报告 v3 新增 Failure Records + Release Decision Summary 章节（PASS/FAIL/UNKNOWN 计数与显式结论规则，放行决策永远由评审人做）；场景参数化 v2（simulation schema 0.2.0 新增 environment.scenario，缺省值=历史硬编码逐位一致；scenario.json 随 run 归档 sim-logs/{jobKey}/，复现语义=参数逐位一致；校准夹爪几何不参数化但 fixed_gripper 全量回显）；Gate 1 执行框架（Flyway V11 gate1_case/gate1_finding，录入→判定→recall 报表；语义匹配由评审人记录不自动匹配；空态 PENDING 不出 STOP 结论）。Track D 回归双证：SDF 位级 A/B 五场景逐位一致 + n=6 物理批次 pick 5/6 与 W4 基线一致
- **V0.8 W2 真机数据可见化（2026-09-17）**：前端真机测试页 /realtest（会话列表→详情 Drawer summary 聚合→Gap 对照表 verdict 三色 tag；no_sim_counterpart 如实渲染"无仿真对照"；模型版本 Tab 生命周期徽标+激活确认）；SimRealGapService 单源 Gap 派生（报告与前端同源防双实现漂移；三族指标键归一：解析式聚合键/仿真后端聚合键/单 run 指标键，不归一则假性 no_sim_counterpart）；GET /api/realtest/sessions/{id}/gap；报告 v2.1 Sim2Real Gap 章节（无真机/无 sim/runtime 挂三分支显式标注，不省略章节）
- **V0.8 W1 真机遥测直连管道（2026-09-17）**：ROS2 只读采集器 v1（deploy/ros2/collect_telemetry.py——指标扩容 perception_error_mm/latency_ms 与仿真聚合同名对齐；--api-endpoint/--api-token/--project-id 采集结束自动 POST 导入，本地 CSV 仍为事实源，推送失败退出码 3 幂等可重试）；Flyway V8（real_test_session.external_key 部分唯一索引）+ 导入幂等（ON CONFLICT DO NOTHING→duplicate=true）+ 坏行跳过计数；GET /api/realtest/sessions 列表 + /{id}/summary 指标聚合（percentile_cont 与 runtime summarize 同形）；E2E 演练 deploy/ros2/e2e_rehearsal.sh（humble 合成源 REHEARSAL_OK；合成源只验管道不产生真实 Gap 结论，如实标注）
- **V0.5 W4 放置弹飞根治（2026-09-16，DoD 5/5 收口）**：三重真因（地面 plane z=-0.01 非 0——释放悬空 10mm 开指被穿透回弹击飞；位置移动硬停 25g>μg 中途滑脱；力 60→0 一跳泄压瞬间释放储能）× 探针矩阵逐步证伪定位。修复：placeSurfaceZ 场景真值 + 低速闭环两段触地（vz=-0.04/-0.02 按零件实测 z）+ 居中回退 + 准静态卸载（60→0 渐降）。实测：拾起成功 5/6 run 放置 7.9-40mm（全重量级，重件 360→38.8mm）；position 双模式保留（伺服增益不足如实记录）；μ=0.18 滑腻件滑脱为真实物理失败保留。part_mass_kg override、释放段轨迹采样日志
- **V0.5 W3 感知定位抓取 v0（2026-09-16）**：独立感知模块（深度图→顶视反投影→工作空间窗质心，噪声两层诚实模型：帧偏置主导+逐像素 iid 次要）；gz_bridge D 命令单帧深度落盘；序列感知路径（控制目标不读真值、standby 避遮挡、perception_error_mm 入指标/evidence 聚合）；实验 depth_noise → 感知链真实噪声（per-run 可复现）。实测：σ=0 感知误差 1.065mm、感知闭环 pick=1.0（E00280 n=6）；诚实结论——真实链下 depth_noise 杠杆臂 ~5-13%（顶视+质心平均），远低于解析 1:1 映射假设（注入 0.60 vs 真实链 0.83）；工作空间窗两处容器实测修正（壁面透视泄入/底板顶面边界）
- **V0.5 W2 对照实验平台化（2026-09-16）**：`POST /api/experiments/comparisons`（同参数同 seed × 2-5 臂配对采样，差异归因系统配置）→ 全臂完成自动摄取 evidence（type=comparison，Flyway V7：experiment_comparison 表 + evidence 类型扩展）；对照载荷逐指标并列（解析/仿真口径统一）+ 相对基准差值与更优判定 + 假设清单（仿真臂模板不随系统配置变化如实标注）；报告 v2 新增 System Configuration Comparison 章节；GET /api/experiments/batches 批次列表（含进行中进度）；前端实验页重构为批次/对照双 Tab（发起/列表/进度/下钻）；demo 5.5 幕 CMP=1 门控（三臂对照 E00279）
- **V0.5 W1 批次编排 DAG 化（2026-09-16）**：experiment backend=simulator 展开为两级 DAG——
  父任务（requires=orchestrator，普通 worker）LHS 采样 → N 个 simulation 子 job
  （幂等键 `{parent}:run:{i}`，requires=gz）多 sim-worker SKIP LOCKED 并行认领 → 父任务
  轮询收割 → aggregate_runs 聚合 + SRC；断点续跑（父任务中断重跑时已完成子 job ON CONFLICT
  复用，aggregates.reusedRuns 如实计数）；批次兜底时限（simulation.batch_deadline_s 可配，
  默认 max(30min, 1.2×n×单次超时)，超时收割部分结果标 deadlineExceeded 不掩盖）；
  worker_id 默认取容器 hostname（scale 实例日志/locked_by 可区分）；compose sim-worker 去
  container_name 支持 `--scale sim-worker=N`。容器实测：3 sim-worker 6-run 批次 wall
  141.9s（串行基线 ~410s）；父任务中断恢复 reusedRuns=6 零重跑
- **V0.5 W1.4 批次进度可见**：sim 引擎 progress_cb → job payload.progress={done,total} →
  status API 透出（DAG 路径下由父任务轮询时更新）

- **仿真证据落库 + 矩阵下钻（M2 DoD 完结，2026-09-15）**：`SimulationController`（POST /api/simulations
  派发、GET 轮询摄取幂等、按项目/需求查询）；摄取时 scene.sdf/run.log 归档对象存储
  （/sim-logs/{jobKey}/…，evidence.artifacts 引用）；前端矩阵 Drawer 关联仿真证据区块；demo 第八幕（SIM=1 可选）
- **job 队列能力路由**：job_queue.requires 列（Flyway V6）+ worker ROBOVERIFY_WORKER_CAPABILITIES
  （sim-worker=gz），requires 非空的任务只被具备能力的 worker 认领
- **gz-sim 集成实测打通（2026-09-15）**：官方 OCI 镜像 `ghcr.io/j-rivero/gazebo:harmonic-full`（gz 8.10.0）
  无 GPU 无头渲染（ogre2/EGL）通过——rgbd 相机产出 image/depth_image/points 话题且有数据帧；
  simulation job 容器实测 SUCCEEDED（sim_time 113s / RTF 0.998 / 113933 iterations，指标全真实自洽）
- **报告下载归档对象存储（首个 ObjectStore 业务调用点）**：/reports/run-{id}/report.md 首次快照幂等、
  故障降级不阻断下载；数据面 E2E 实测 Java→SigV4→SeaweedFS 3634B 逐字节一致
- **`SeaweedS3ObjectStore`（SeaweedFS 主实现，type=seaweed-s3）**：自研 S3Signer SigV4（零 AWS SDK 依赖，
  AWS 官方测试向量黄金验证），桶懒创建/DELETE 幂等/非法 key 拒绝；SeaweedFS 单容器部署
  （weed server -s3）+ verify-seaweedfs.sh 一键 E2E + .env.example
- gz adapter 真实指标采集（stats 话题采样 + 话题探测 + SDF 模型计数）；simulation handler
  requestedMetrics 可得性诚实标注（unavailable 不编造）

### Changed

- **对象存储最终确认：MinIO → SeaweedFS（S3 协议）**（"seafs" 命名歧义由用户二次确认消解，
  ADR-0005 重写改名；Seafile/WebDAV 适配器保留为备选，compose 栈移除）
- scene_builder 修复：gz world 补 systems 插件（Physics/Sensors 等）——缺失时传感器静默不实例化（实测抓出）
- runtime 兼容 py3.10（gz 镜像 Ubuntu 22.04）：timezone.utc 替 datetime.UTC，requires-python/ruff 放宽
- evidence IR `artifacts[].store` 枚举 +seaweedfs；gz OCI 镜像路径修正（原 gazebosim/gz-sim 不存在）
- springdoc 3.1.1 试装后回退：Boot 4.1 + starter-webmvc 下自动配置未装配，pom 注释保留待上游

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
