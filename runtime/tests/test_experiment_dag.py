"""V0.5 W1 DAG 编排纯函数测试：子任务收割语义、批次兜底时限。

端到端（并行 wall/断点续跑/进度）用容器实测验证（dev-plan V0.5 DoD）。
"""

from __future__ import annotations

from roboverify_runtime.worker.handlers.experiment import _batch_deadline_s, _harvest_runs


def _job(status: str, payload: dict | None = None, last_error: str | None = None) -> dict:
    return {"status": status, "payload": payload or {}, "lastError": last_error}


def test_harvest_mixed_statuses_honest():
    """成功取指标、失败取原因、非终态/缺失计 deadline——不掩盖部分完成。"""
    keys = ["b:run:0", "b:run:1", "b:run:2", "b:run:3"]
    jobs = {
        "b:run:0": _job("SUCCEEDED", {
            "params": {"depth_noise_mm": 5.0}, "graspNoise": [0.001, -0.002, 0.0],
            "result": {"metrics": {"pick_success": 1.0, "sim_time_s": 30.1,
                                   "pick_sequence_error": None},
                       "wall_s": 59.8}}),
        "b:run:1": _job("FAILED", last_error="gz server failed"),
        "b:run:2": _job("RUNNING"),
        # b:run:3 缺失（子任务投递后父任务被回收重跑等情形）
    }
    runs, deadline = _harvest_runs(jobs, keys)
    assert deadline is True
    assert len(runs) == 4
    assert runs[0]["metrics"] == {"pick_success": 1.0, "pick_sequence_error": None}  # sim_time_s 被白名单过滤
    assert runs[0]["wall_s"] == 59.8
    assert runs[0]["graspNoise"] == [0.001, -0.002, 0.0]
    assert runs[1]["error"] == "gz server failed"
    assert runs[2]["error"].startswith("batch deadline exceeded (sub-job RUNNING)")
    assert runs[3]["error"].startswith("batch deadline exceeded (sub-job MISSING)")


def test_harvest_all_terminal_no_deadline():
    keys = ["b:run:0", "b:run:1"]
    jobs = {
        "b:run:0": _job("SUCCEEDED", {"params": {}, "graspNoise": [0, 0, 0],
                                      "result": {"metrics": {"pick_success": 0.0}}}),
        "b:run:1": _job("FAILED", last_error="x"),
    }
    runs, deadline = _harvest_runs(jobs, keys)
    assert deadline is False
    assert runs[0]["metrics"] == {"pick_success": 0.0}
    assert "wall_s" not in runs[0]  # 子任务结果缺 wall 时不编造
    assert "metrics" not in runs[1]


def test_batch_deadline_configurable_with_safe_default():
    # 显式配置优先
    assert _batch_deadline_s({"batch_deadline_s": 60, "timeout_s": 120}, 50) == 60.0
    # 默认：max(1800, 1.2 × n × 单次超时)
    assert _batch_deadline_s({"timeout_s": 120}, 50) == 7200.0
    assert _batch_deadline_s({}, 3) == 1800.0  # 无 timeout_s 时按 120s 缺省
