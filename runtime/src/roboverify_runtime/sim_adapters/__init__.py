"""Simulation Adapter 注册表（ADR-0003）。"""

from __future__ import annotations

from .base import SimResult as SimResult
from .base import SimulationAdapter as SimulationAdapter

_ADAPTERS: dict[str, SimulationAdapter] = {}


def register(adapter: SimulationAdapter) -> None:
    _ADAPTERS[adapter.name] = adapter


def get_adapter(name: str) -> SimulationAdapter:
    if name not in _ADAPTERS:
        raise KeyError(f"simulation adapter 未注册: {name}（已注册: {sorted(_ADAPTERS)}）")
    return _ADAPTERS[name]


from .gz.adapter import GzSimAdapter  # noqa: E402  默认注册首个实现

register(GzSimAdapter())
