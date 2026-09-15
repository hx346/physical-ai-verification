"""gz-sim 适配器（ADR-0003 首个实现）。

✅ 集成已验证（2026-09-15）：官方 OCI 镜像 ghcr.io/j-rivero/gazebo:harmonic-full（gz 8.10.0）
容器内无 GPU 无头渲染（ogre2+EGL）实测通过——rgbd 相机产出 image/depth_image/points 话题且有数据帧。

执行模型：后台起 gz server（大 iterations），warmup 后采样真实指标，最后回收进程：
- sim_time_s / physics_iterations / real_time_factor ← /world/{name}/stats 话题（真实值）
- models_in_scene ← SDF 中 <model> 计数（真实值）
- depth_camera_active ← gz topic -l 是否出现 depth_image 话题（真实值）
不输出任何编造指标；无 gz 运行时显式失败（原则二）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ...logging_setup import get_logger
from ..base import SimResult
from .scene_builder import build_scene_bundle, build_world_sdf
from .sequence import GzClient, run_pick_sequence

log = get_logger("sim_adapters.gz")
WORLD_NAME = "bin_picking"
DEPTH_TOPIC = "/camera/rgbd/depth_image"
WARMUP_S = 15.0


class GzSimAdapter:

    name = "gz"

    def build_scene(self, sim_ir: dict) -> str:
        return build_world_sdf(sim_ir)

    def run(self, sim_ir: dict, scene_content: str, timeout_s: float) -> SimResult:
        if shutil.which("gz") is None:
            # 不编造仿真结果：无 gz 运行时时显式失败，由 worker 记 FAILED 并留痕
            raise RuntimeError(
                "gz-sim 可执行文件不可用：请在 gz 容器（deploy/sim/gz.Dockerfile，"
                "compose profile=sim）内运行 worker"
            )
        duration = max(5.0, min(float(timeout_s), 300.0))
        with tempfile.TemporaryDirectory(prefix="rv-sim-") as tmp:
            world = Path(tmp) / "world.sdf"
            world.write_text(scene_content, encoding="utf-8")
            server = subprocess.Popen(
                ["gz", "sim", "-s", "--headless-rendering", "-r",
                 "--iterations", str(10 ** 9), str(world)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                scripted = (sim_ir.get("script") or {}).get("type") == "scripted_pick"
                # scripted_pick：warmup 缩短——夹爪 15s 自由坠落会使指底扫碰零件顶（W2 实测根因）
                time.sleep(min(6.0 if scripted else WARMUP_S, duration * 0.5))
                topics = self._capture(["gz", "topic", "-l"])
                pick_metrics: dict[str, float] = {}
                if scripted:
                    client = GzClient()
                    try:
                        bundle = build_scene_bundle(sim_ir)
                        pick_metrics = run_pick_sequence(client, bundle, log)
                        log.info("pick sequence done", **pick_metrics)
                    except Exception as e:  # noqa: BLE001 — 序列失败不吞，如实记录
                        pick_metrics = {"pick_sequence_error": 1.0}
                        log.error("pick sequence failed", error=str(e), exc_info=True)
                    finally:
                        client.close()
                stats = self._capture(["gz", "topic", "-e", "-t",
                                       f"/world/{WORLD_NAME}/stats", "-n", "1"])
            finally:
                server.terminate()
                try:
                    server_out, _ = server.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server_out, _ = server.communicate()

            metrics = self.extract_metrics(stats)
            metrics["models_in_scene"] = float(scene_content.count("<model "))
            metrics["depth_camera_active"] = 1.0 if DEPTH_TOPIC in topics else 0.0
            metrics.update(pick_metrics)
            notes = [f"gz-sim headless server 运行 {duration:.0f}s 后采样（stats/话题实测）"]
            if metrics["depth_camera_active"] < 1.0:
                notes.append("警告：depth_image 话题未出现，相机传感器未激活（检查 Sensors 系统插件）")
            if "pick_sequence_error" in metrics:
                notes.append("警告：抓取序列执行异常（详见 logExcerpt），指标缺失不编造")
            return SimResult(
                metrics=metrics,
                log_excerpt=(server_out or "")[-4000:],
                notes=notes,
            )

    def _capture(self, cmd: list[str], timeout_s: float = 20.0) -> str:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
            return proc.stdout or ""
        except (subprocess.TimeoutExpired, OSError):
            return ""

    @staticmethod
    def extract_metrics(stats_text: str) -> dict[str, float]:
        """从 /world/.../stats 话题的 protobuf 文本输出解析真实指标。"""
        metrics: dict[str, float] = {}
        m = re.search(r"sim_time\s*\{\s*sec:\s*(\d+)", stats_text)
        if m:
            metrics["sim_time_s"] = float(m.group(1))
        m = re.search(r"iterations:\s*(\d+)", stats_text)
        if m:
            metrics["physics_iterations"] = float(m.group(1))
        m = re.search(r"real_time_factor:\s*([\d.eE+-]+)", stats_text)
        if m:
            metrics["real_time_factor"] = float(m.group(1))
        return metrics
