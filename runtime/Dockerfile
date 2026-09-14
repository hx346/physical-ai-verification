# Python 工程运行时（解析式内核 + worker；仿真依赖在 M2 的 gz 镜像中另建）
# build context = 仓库根（compose: context: .., dockerfile: runtime/Dockerfile）
FROM python:3.13-slim

WORKDIR /app

# 清华源加速；IR 契约（schemas/）随镜像分发，唯一权威定义仍在仓库
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PYTHONUNBUFFERED=1 \
    ROBOVERIFY_SCHEMA_DIR=/app/schemas

COPY runtime/pyproject.toml runtime/README.md ./
COPY runtime/src ./src
RUN pip install --no-cache-dir .
COPY schemas /app/schemas

EXPOSE 8081
# 默认起 API；worker 容器复用同一镜像、覆盖 command（M2 起）
CMD ["python", "-m", "uvicorn", "roboverify_runtime.main:app", "--host", "0.0.0.0", "--port", "8081"]
