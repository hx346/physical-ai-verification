"""真机遥测聚合与 Sim2Real Gap（M4）。

只读链路：数据来自 ROS 2 只读采集的 CSV 导出或平台导入；
Gap = (sim - real) / real，按指标输出（原则四：Reality 优先）。
"""

from __future__ import annotations

import numpy as np
import psycopg

from ..config import settings

KNOWN_METRICS = ("picking_success_rate", "position_error_mm", "cycle_time_s")


def summarize_telemetry(session_id: str) -> dict[str, dict]:
    """按指标聚合真机遥测：n / mean / P50 / P95。"""
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "SELECT metric, value FROM telemetry WHERE session_id = %s::uuid",
            (session_id,),
        ).fetchall()
    by_metric: dict[str, list[float]] = {}
    for metric, value in rows:
        by_metric.setdefault(metric, []).append(float(value))
    out: dict[str, dict] = {}
    for metric, values in by_metric.items():
        arr = np.asarray(values)
        out[metric] = {
            "samples": int(arr.size),
            "mean": float(arr.mean()),
            "P50": float(np.percentile(arr, 50)),
            "P95": float(np.percentile(arr, 95)),
        }
    return out


def gap_report(real_summary: dict, sim_summary: dict) -> dict:
    """逐指标 Gap：sim_summary 来自实验引擎聚合（或解析式内核）。"""
    gaps: dict[str, dict] = {}
    for metric, real in real_summary.items():
        sim = sim_summary.get(metric)
        if sim is None:
            gaps[metric] = {"status": "no_sim_counterpart"}
            continue
        real_mean = real["mean"]
        gap = (sim - real_mean) / real_mean if real_mean else float("nan")
        gaps[metric] = {
            "real": real,
            "sim": sim,
            "gap_ratio": round(float(gap), 4),
            "gap_percent": round(float(gap) * 100, 2),
            "verdict": "within_20pct" if abs(gap) <= 0.20 else "exceeds_20pct",
        }
    return gaps
