# ADR-0001：Java 平台 + Python 工程运行时的双运行时架构

- 状态：Accepted（2026-09-14）
- 背景：RoboVerify 需要（a）企业级平台能力（项目/资产/证据/审计/鉴权/报告）与（b）科学计算能力（误差传播、蒙特卡洛、运动学、仿真适配）。团队主线工程能力为 Java / Spring。

## 备选方案

| 方案 | 结论 |
|---|---|
| A. 纯 Python 单体 | 科学计算生态最优，但平台层（审计、权限、事务、长期企业集成）违背团队主线能力，后期重写成本高 |
| B. 纯 Java | 平台能力强，但 NumPy/SciPy/Pinocchio/SALib/gz 生态在 JVM 上缺失或二流，科学计算强行 Java 化必败 |
| C. Java 微服务集群 + Python 服务 | V0.1 团队 3–4 人，微服务运维与联调成本不可承受（YAGNI） |
| **D. Java 模块化单体（Platform）+ Python 无状态运行时（Runtime/Worker）** | **采纳** |

## 决策

- `backend/`：单个 Spring Boot 4 部署单元，按域分包（project/requirement/asset/verification/evidence/job/audit），**禁止拆微服务**直至有真实规模需求。
- `runtime/`：Python 3.12+，FastAPI（同步内核）+ worker 进程（长任务），纯计算、无状态、不持有业务数据，经 Platform API/队列读写。
- 两侧唯一契约：OpenAPI（REST）+ JSON Schema（IR），定义在 `schemas/`，评审后变更。

## 后果

- 正面：各栈做各栈最擅长的事；Runtime 可独立横向扩容（仿真 worker）；将来 K8s 化只动部署层。
- 负面：双栈联调与 CI 复杂度；需纪律维护契约单一权威（schema 漂移即事故）。
- 缓解：IR Schema 双语言校验用例进 CI；契约变更必须走 PR 评审。
