"""处理器注册表（独立模块，避免 runner ↔ handlers 循环导入）。"""

from __future__ import annotations

_HANDLERS: dict[str, object] = {}  # M2 "simulation"，M3 "experiment"，M4 "calibration"


def handle(job_type: str):
    """处理器注册装饰器。"""
    def register(fn):
        _HANDLERS[job_type] = fn
        return fn
    return register


def get_handler(job_type: str):
    return _HANDLERS.get(job_type)


def registered_types() -> list[str]:
    return sorted(_HANDLERS)
