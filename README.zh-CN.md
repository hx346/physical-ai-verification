# RoboVerify — 物理智能验证平台（Physical AI Verification Platform）

> **AI 负责设计，RoboVerify 负责证明。**

**English: [README.md](./README.md)**

RoboVerify 是面向机器人与物理智能系统的**工程验证运行时（Engineering Verification Runtime）**。
它不是仿真平台，不是数字孪生平台，也不是 AI 设计助手。

它不回答*"这个机器人工作站该怎么设计？"*——它回答：

- **这个设计是否真的满足需求？** 为什么满足 / 为什么不满足？
- 哪些参数是真正的瓶颈（由敏感性分析排序，而不是由大模型打分）？
- 哪些传感器或执行器实际上没有必要？
- 满足要求的最低成本方案是哪个（帕累托前沿）？
- 仿真和真实世界会差多少（Sim2Real Gap）？
- 有什么**证据**证明该方案可以进入下一阶段？

每一个结论都可追溯：

```
需求 → 约束 → 测试用例 → 仿真 → 实验 → 真机测试 → 证据 → 决策
```

## 核心原则

1. **LLM 可替换。** 任何模型（GPT / Gemini / Claude / Qwen / DeepSeek / 本地模型）都只是 *Reasoning Provider*。不接任何 LLM，系统核心功能必须完整可用。
2. **AI 提出假设，系统证明假设。** PASS/FAIL 判定来自公式、求解器、蒙特卡洛、仿真和真机测试——永远不来自 Prompt。
3. **"推荐"类能力默认未来免费。** 任务拆解、部件推荐、测试计划生成视为商品化能力，不作为护城河。
4. **Reality > 验证 > 实验 > 仿真 > 优化 > 知识 > AI 推理。** 研发投入按此优先级排序。
5. **任何验证必须可追溯**到需求、配置、方法、版本与证据。

## 核心概念

| 概念 | 作用 |
|---|---|
| **Engineering IR** | 语言中立的中間表示：Task / Requirement / System / State / Environment / Experiment / Evidence IR（JSON Schema，权威定义在 [`schemas/`](./schemas/)，随仓库版本化） |
| **Asset Registry** | 工程资产模型（机器人、相机、夹爪），误差参数带显式**来源分级**：`datasheet`（手册）/ `literature`（文献）/ `measured`（实测）/ `calibrated`（校准） |
| **Verification Kernel** | 约束求解器、不确定性引擎（RSS 合成 + 蒙特卡洛 → P50/P90/P95 + 置信区间）、端到端时延预算、可观测性分析、可达性/碰撞 |
| **Experiment Engine** | 在实验空间（光照、遮挡、深度噪声……）上做 LHS / 蒙特卡洛采样 + 敏感性分析（SALib） |
| **Simulation SPI** | 仿真器无关的适配器接口；先接 gz-sim，V0.5 计划接 Isaac Sim |
| **Evidence Graph** | 每条需求的判定结果都由关联的仿真/实验/真机证据记录支撑 |
| **Verification Matrix** | 核心界面：需求 × 指标 × 现值 × 要求 × 判定 × 证据 |

示例——整个产品挂在上面的一张表：

| 需求 | 指标 | 现值 | 要求 | 结果 | 证据 |
|---|---|---:|---:|---|---|
| R01 | 定位精度（P95） | 4.8 mm | < 3 mm | **FAIL** | E102 |
| R02 | 可达范围 | 1.1 m | > 1.0 m | PASS | E103 |
| R03 | 节拍（P95） | 5.4 s | < 6 s | PASS | E104 |
| R04 | 抓取成功率 | 94 % | > 98 % | **FAIL** | E105 |

## 架构

```
              ┌──────────────────┐
              │      Web UI      │  Vue 3 —— Verification Matrix 是核心页面
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐   Java 25 · Spring Boot 4（模块化单体）
              │     Platform     │   项目 · 需求 · 资产 · 证据
              │  （API + IR +    │   报告 · 审计 · 任务编排
              │      持久化）     │
              └───┬──────────┬───┘
   REST/OpenAPI   │          │  任务队列（PostgreSQL SKIP LOCKED）
                   ▼          ▼
        ┌──────────────┐  ┌─────────────────────┐
        │    Runtime   │  │       Workers       │  Python 3.12
        │ （同步内核）   │  │ 仿真 · 实验 · 校准    │
        └──────┬───────┘  └──────────┬──────────┘
               │                     ▼
               │           ┌───────────────────┐
               │           │ gz-sim · ROS 2    │  Linux Docker（Simulation Adapter SPI）
               │           │（后续：Isaac Sim）  │
               │           └─────────┬─────────┘
               ▼                     ▼
        ┌────────────────────────────────────┐
        │  PostgreSQL (JSONB)  ·  MinIO      │  IR · 证据 · URDF/CAD · 日志 · 报告
        └────────────────────────────────────┘
```

完整设计：[`docs/architecture.md`](./docs/architecture.md) · 决策记录：[`docs/adr/`](./docs/adr/)

## 技术栈

| 层 | 选型 |
|---|---|
| 平台 API | Java 25 (LTS) · Spring Boot 4.x · MyBatis-Plus · Flyway · Sa-Token · springdoc-openapi |
| 工程运行时 | Python 3.12+ · FastAPI · NumPy / SciPy / Pandas · Pydantic v2 |
| 运动学 / 碰撞 | Pinocchio · python-fcl / trimesh |
| 敏感性 / 实验设计 | SALib ·（后续：pymoo · Optuna） |
| 仿真 | gz-sim + ROS 2，Linux Docker，走适配器 SPI（V0.5 接 Isaac Sim） |
| 数据 | PostgreSQL 17+（关系 + JSONB）· MinIO（URDF / CAD / 数据集 / 日志 / 报告） |
| 队列 | PostgreSQL `FOR UPDATE SKIP LOCKED`（规模上来才引入 Temporal） |
| 前端 | Vue 3 · TypeScript · Vite · Ant Design Vue · ECharts |
| LLM | 供应商无关适配器，可选——核心流程不依赖任何 LLM |
| 部署 | Docker Compose（Linux）；Windows 开发仿真部分走 WSL2 |
| CI | GitHub Actions |

## 仓库结构

```
.
├── README.md / README.zh-CN.md   中英双语文档
├── docs/
│   ├── architecture.md           系统设计、契约、边界
│   ├── development-plan.md       M0–M4 里程碑、DoD、风险、门禁
│   └── adr/                      架构决策记录（ADR）
├── schemas/                      Engineering IR JSON Schema（唯一权威定义）
├── backend/                      Java 平台服务（Spring Boot 4 模块化单体）
├── runtime/                      Python 工程运行时（内核 + Worker）
├── frontend/                     Vue 3 Web UI
└── deploy/                       docker-compose、环境模板、部署文档
```

## 快速开始（基础设施）

应用服务随 M0 里程碑落地，数据层现在即可运行：

```bash
git clone git@github.com:hx346/physical-ai-verification.git
cd physical-ai-verification/deploy
docker compose up -d

# PostgreSQL    -> localhost:15432（roboverify / roboverify，库：roboverify）
# MinIO 控制台  -> http://localhost:19001（roboverify / roboverify）
```

## 路线图

| 版本 | 主题 | 内容 |
|---|---|---|
| **V0.1**（M0–M4，目标 2027-01） | 设计验证 | 解析式内核 → gz-sim 适配 → 实验引擎 → ROS 2 只读接入 · 场景：**视觉引导料箱抓取** |
| V0.3 | 仿真验证 | 更丰富的仿真证据、多指标覆盖 |
| V0.5 | 实验平台 | Isaac Sim、合成数据、DOE |
| V0.8 | 真机集成 | 遥测、Real2Sim Gap 报告 |
| V1.0 | Real2Sim | 校准的传感器/机器人模型——第一个商业产品 |
| V2.0 | 设计优化 | 配置空间上的帕累托前沿 |
| V3.0 | 智能体工程 | AI 生成方案，RoboVerify 证明，闭环迭代 |

里程碑明细与验收标准：[`docs/development-plan.md`](./docs/development-plan.md)

## 当前状态

**P0 —— 产品验证期。** 第一个季度只有一个目标：证明"自动工程验证"本身具有真实价值。一个场景、一个仿真器、一套 IR、一个验证内核、一个实验引擎、一套证据链、一次真实项目验证。Go/No-Go 门禁见[开发计划 §6](./docs/development-plan.md)。

## 许可证

待定。
