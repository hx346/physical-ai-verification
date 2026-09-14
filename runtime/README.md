# runtime — Engineering Runtime（Python）

Python 3.12+ · FastAPI（同步内核）+ worker 进程（长任务）。纯计算、无状态、不持有业务数据。

职责：约束求解、误差合成（RSS + Monte Carlo）、时延预算、可观测性分析、运动学（Pinocchio）、仿真适配（gz-sim）、实验引擎（LHS/MC + SALib）、校准（scipy）。

计划包结构（M0 落地）：

```
runtime/
├── kernel/          # constraint / uncertainty / timing / observability
├── sim_adapters/    # Adapter SPI（ADR-0003），gz 为首个实现
├── experiment/      # 采样策略 + 批次聚合 + 敏感性
├── calibration/     # M4
└── worker/          # job_queue 消费循环（SKIP LOCKED）
```

依赖基线：fastapi · pydantic v2 · numpy · scipy · pandas · structlog ·（M2 起：pinocchio、trimesh/python-fcl、gz-ros 容器内依赖）。

**Windows 注意**：解析式内核（kernel/）可直接在 Windows 开发；仿真相关（sim_adapters/）只在 Linux Docker/WSL2 内运行（ADR-0003）。

运行方式：
- **Docker（正式形态）**：`deploy/docker-compose.yml` 的 `runtime` 服务（镜像内含 IR 契约 `/app/schemas`）。
- 本地开发调试：`python -m venv .venv && ./.venv/Scripts/python -m pip install -e ".[dev]"`，
  然后 `./.venv/Scripts/python -m uvicorn roboverify_runtime.main:app --port 8081`；
  测试 `./.venv/Scripts/python -m pytest`（队列测试需 `ROBOVERIFY_TEST_PG=1` 且 PG 在 15432）。
