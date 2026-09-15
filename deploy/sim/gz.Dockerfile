# gz-sim 仿真 worker（compose profile=sim；ADR-0003）
# 基础镜像已验证（2026-09-14）：Gazebo 官方 OCI 镜像发布在 ghcr.io/j-rivero/gazebo（OSRA 官方支持，
# 覆盖 jetty/ionic/harmonic/fortress × core/full，每周重建；ghcr.io/gazebosim/gz-sim 不存在）。
# full = 完整 gz 套件（含 gz sim 可执行文件）；core 仅到 sdformat，不含 gz sim。
# ⚠ 待验证：无头渲染（EGL/ogre2 headless）在 M2 集成窗口确认，不通过则按官方 TROUBLESHOOTING 调整。
FROM ghcr.io/j-rivero/gazebo:harmonic-full

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip g++ pkg-config \
    && rm -rf /var/lib/apt/lists/*

# gz-bridge（V0.3 W3）：进程内 gz-transport 桥——stdin 速度指令→cmd_vel，
# 位姿/接触话题→stdout 行协议。消灭 CLI one-shot 发布死区与文本渲染滞后
# （W2 终局定性，见 deploy/sim/gz_bridge.cc 头注释）
COPY deploy/sim/gz_bridge.cc /tmp/gz_bridge.cc
RUN gcc -x c++ -O2 -std=c++17 /tmp/gz_bridge.cc -o /usr/local/bin/gz-bridge \
    -lstdc++ $(pkg-config --cflags --libs gz-transport13) && rm /tmp/gz_bridge.cc

WORKDIR /app
ENV ROBOVERIFY_SCHEMA_DIR=/app/schemas \
    ROBOVERIFY_DATABASE_URL=postgresql://roboverify:roboverify@postgres:5432/roboverify \
    PYTHONUNBUFFERED=1

COPY runtime/pyproject.toml runtime/README.md ./
COPY runtime/src ./src
RUN pip3 install --no-cache-dir .
COPY schemas /app/schemas

# 仿真 worker：同一任务消费循环，gz 可执行文件在本镜像内可用
CMD ["python3", "-m", "roboverify_runtime.worker.runner"]
