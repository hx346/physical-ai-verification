# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

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
