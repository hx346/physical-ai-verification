# gz-sim 仿真 worker（compose profile=sim；ADR-0003）
# ⚠ 假设待验证：基础镜像 tag 与无头渲染（EGL）在 M2 集成窗口确认；
#   不通过则按 gz 官方镜像调整 tag，上层代码不变。
FROM ghcr.io/gazebosim/gz-sim:harmonic

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV ROBOVERIFY_SCHEMA_DIR=/app/schemas \
    ROBOVERIFY_DATABASE_URL=postgresql://roboverify:roboverify@postgres:5432/roboverify \
    PYTHONUNBUFFERED=1

COPY runtime/pyproject.toml runtime/README.md ./
COPY runtime/src ./src
RUN pip3 install --no-cache-dir --break-system-packages .
COPY schemas /app/schemas

# 仿真 worker：同一任务消费循环，gz 可执行文件在本镜像内可用
CMD ["python3", "-m", "roboverify_runtime.worker.runner"]
