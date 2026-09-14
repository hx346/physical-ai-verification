"""gz-sim 适配器（ADR-0003 首个实现）。

⚠ 集成状态：**代码完成，gz 运行时集成待验证**——需要 gz-sim 容器镜像
（deploy/sim/gz.Dockerfile）与无头渲染（EGL）环境；在 M2 集成窗口由 Robotics
工程师验证。在验证前，simulation 类型任务在本适配器处显式失败（不编造结果）。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..base import SimResult
from .scene_builder import build_world_sdf

GZ_SIM_ENV_FLAG = "ROBOVERIFY_GZ_AVAILABLE"


class GzSimAdapter:

    name = "gz"

    def build_scene(self, sim_ir: dict) -> str:
        return build_world_sdf(sim_ir)

    def run(self, sim_ir: dict, scene_content: str, timeout_s: float) -> SimResult:
        if shutil.which("gz") is None:
            # 不编造仿真结果：无 gz 运行时时显式失败，由 worker 记 FAILED 并留痕
            raise RuntimeError(
                "gz-sim 可执行文件不可用：请在 gz 容器（deploy/sim/gz.Dockerfile，"
                "compose profile=sim）内运行 worker，或等待 M2 集成验证"
            )
        with tempfile.TemporaryDirectory(prefix="rv-sim-") as tmp:
            world = Path(tmp) / "world.sdf"
            world.write_text(scene_content, encoding="utf-8")
            cmd = [
                "gz", "sim", "-s", "--headless-rendering", "-r",
                "--iterations", str(int(timeout_s * 1000)),
                str(world),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            if proc.returncode != 0:
                raise RuntimeError(f"gz sim exited {proc.returncode}: {proc.stderr[-800:]}")
            return SimResult(
                metrics=self.extract_metrics(proc.stdout),
                log_excerpt=proc.stdout[-4000:],
                notes=["gz-sim headless run（集成验证：M2 窗口）"],
            )

    @staticmethod
    def extract_metrics(raw_log: str) -> dict[str, float]:
        """从 gz 输出解析指标。具体话题/插件格式在 M2 集成时按 gz 实际输出补全。"""
        metrics: dict[str, float] = {}
        for line in raw_log.splitlines():
            if "metric:" in line:
                key, _, value = line.partition("metric:")[1].strip().partition("=")
                try:
                    metrics[key.strip()] = float(value)
                except ValueError:
                    continue
        return metrics
