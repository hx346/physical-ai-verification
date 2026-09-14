"""Simulation Adapter SPI（ADR-0003）：上层只产出/消费 Simulation IR 与指标，
禁止任何上层代码直接调用 gz/Isaac API。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SimResult:
    """适配器统一产出：原始指标 + 日志工件 key（对象存储）+ 声明。"""

    metrics: dict[str, float] = field(default_factory=dict)
    log_excerpt: str = ""
    artifacts: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class SimulationAdapter(Protocol):

    name: str

    def build_scene(self, sim_ir: dict) -> str:
        """Simulation IR → 仿真器场景文件内容（如 SDF world）。"""
        ...

    def run(self, sim_ir: dict, scene_content: str, timeout_s: float) -> SimResult:
        """执行一次仿真并抽取指标。超时/失败抛异常（由 worker 记失败）。"""
        ...
