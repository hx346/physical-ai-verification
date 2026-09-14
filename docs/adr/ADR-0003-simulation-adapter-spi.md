# ADR-0003：Simulation Adapter SPI —— 先接 gz-sim，且仿真只跑 Linux Docker

- 状态：Accepted（2026-09-14）
- 背景：平台不能绑定单一仿真器（产品方案 §17）；主力开发机为 Windows；gz-sim/ROS 2 为 Linux 优先生态。

## 备选方案

| 方案 | 结论 |
|---|---|
| A. 先接 Isaac Sim | 高保真与合成数据强，但依赖 NVIDIA 栈（GPU/许可/体量大），V0.1 门槛过高，计划放在 V0.5 |
| B. 先接 MuJoCo | 轻量、物理准确，但视觉传感器仿真（深度相机、光照）弱于 gz-sim，与 Bin Picking 视觉验证目标不匹配 |
| C. 多仿真器同时支持 | 违背"第一版只接一个"的范围纪律，SPI 未验证前并行适配是浪费 |
| **D. Simulation IR + Adapter SPI，V0.1 唯一实现 gz-sim（Linux Docker）** | **采纳** |

## 决策

- 上层只产出/消费 **Simulation IR**（`schemas/ir/simulation.schema.json`），禁止任何上层代码直接调用 gz/Isaac API。
- Adapter 接口（Python Protocol）：`build_scene(sim_ir) -> SceneHandle`、`run(scene, timeout) -> RawResult`、`extract_metrics(raw) -> Metrics`。
- gz-sim + ROS 2 封装在 Linux Docker 镜像内；**Windows 开发一律走 WSL2 或远程 Linux 主机**，不提供原生 Windows 仿真路径。
- 版本假设（M0 调研确认）：gz Harmonic + ROS 2 Jazzy；若 M0 验证推翻，仅改镜像与适配器，不影响上层。

## 后果

- 正面：更换/新增仿真器（Isaac/MuJoCo/CoppeliaSim）只加适配器；上层与证据链零改动。
- 负面：SPI 抽象需要克制——只抽象 V0.1 用到的能力（场景生成/深度相机/脚本化抓取/指标提取），避免为假想需求过度设计。
- 约束：仿真容器必须设 CPU/内存限额；CI 仿真任务仅 Linux runner。
