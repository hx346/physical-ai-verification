#!/usr/bin/env python3
"""合成机器人单元 fake_cell（真机接入前的演示/回归数据源——非真机组件）。

与 smoke_talker.py 的分工：smoke_talker 是联调冒烟（刻意覆盖布尔/缺字段/非法 JSON
边界，8 条即停）；fake_cell 模拟一个抓取单元持续执行 N 个 run——每 run 发布一条
正常 task_result（指标从配置分布抽样、pick_success 按概率翻转，失败 run 定位误差
显著放大——与仿真/真机失败语义一致），供采集器收满一个有真实感的会话。

用途：① 前端真机页/报告 Gap 章节的演示数据；② 管道回归（可入每周收尾检查）。
诚实边界（与 e2e_rehearsal 同语义，README §状态与边界）：合成数据只产生
"管道演练"会话，Gap 数字不构成真机对照结论；建议 external-key 带 fake-cell-
前缀便于识别与清理。

简化假设（区别于真实机器人，如实标注）：各 run 独立同分布、失败 run 的
perception/latency 不放大、cycle_time 不区分成败——够演示与回归，不做行为建模。

用法（ROS 2 环境内，与采集器并行；采集器侧建议 --external-key fake-cell-...）：
  python3 fake_cell.py                                  # 20 runs 默认分布
  python3 fake_cell.py --runs 50 --pick-prob 0.7 --seed 42 --cycle 7.0
  python3 fake_cell.py --self-test                      # 纯函数自验（无需 ROS 环境）
"""

from __future__ import annotations

import argparse
import json
import random

# 指标分布常量（演示口径，非任何真实机型标定——禁止当真机数据引用）
CYCLE_MEAN, CYCLE_SIGMA = 7.0, 1.2          # cycle_time_s，s
CYCLE_MIN, CYCLE_MAX = 3.0, 15.0
POS_OK_MEAN, POS_OK_SIGMA = 12.0, 8.0       # 成功 run position_error_mm，mm
POS_OK_MAX = 60.0
POS_FAIL_MEAN, POS_FAIL_SIGMA = 420.0, 150.0  # 失败 run position_error_mm（显著放大）
POS_FAIL_MIN, POS_FAIL_MAX = 100.0, 1200.0
PERC_MEAN, PERC_SIGMA = 1.5, 0.8            # perception_error_mm，mm
PERC_MAX = 8.0
LAT_MEAN, LAT_SIGMA = 35.0, 10.0            # latency_ms，ms
LAT_MIN, LAT_MAX = 5.0, 120.0
DDS_WARMUP_S = 1.5                          # 发布器→订阅匹配等待（volatile 首条丢失边界）


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_run(rng: random.Random, pick_prob: float) -> dict:
    """生成一个 run 的 task_result 载荷（五字段全出——fake_cell 不发残缺消息，
    边界覆盖归 smoke_talker）。"""
    ok = rng.random() < pick_prob
    pos = (rng.gauss(POS_OK_MEAN, POS_OK_SIGMA) if ok else
           rng.gauss(POS_FAIL_MEAN, POS_FAIL_SIGMA))
    pos = _clip(pos, 0.0, POS_OK_MAX) if ok else _clip(pos, POS_FAIL_MIN, POS_FAIL_MAX)
    return {
        "pick_success": 1 if ok else 0,
        "cycle_time_s": round(_clip(rng.gauss(CYCLE_MEAN, CYCLE_SIGMA), CYCLE_MIN, CYCLE_MAX), 3),
        "position_error_mm": round(pos, 3),
        "perception_error_mm": round(_clip(rng.gauss(PERC_MEAN, PERC_SIGMA), 0.0, PERC_MAX), 3),
        "latency_ms": round(_clip(rng.gauss(LAT_MEAN, LAT_SIGMA), LAT_MIN, LAT_MAX), 1),
    }


def build_sequence(runs: int, pick_prob: float, seed: int) -> list[dict]:
    return [build_run(random.Random(seed + i), pick_prob) for i in range(runs)]


def _self_test() -> None:
    seq = build_sequence(200, 0.85, seed=7)
    seq2 = build_sequence(200, 0.85, seed=7)
    assert seq == seq2, "同 seed 序列应逐位一致（确定性）"
    for m in seq:
        assert set(m) == {"pick_success", "cycle_time_s", "position_error_mm",
                          "perception_error_mm", "latency_ms"}, "五字段必须齐"
        assert m["pick_success"] in (0, 1)
        assert 0 < m["cycle_time_s"] <= CYCLE_MAX
        assert m["position_error_mm"] >= 0 and m["perception_error_mm"] >= 0
        assert m["latency_ms"] >= 0
    ok_runs = [m for m in seq if m["pick_success"] == 1]
    fail_runs = [m for m in seq if m["pick_success"] == 0]
    assert ok_runs and fail_runs, "200 run @p=0.85 两分支都应有样本"
    assert max(m["position_error_mm"] for m in ok_runs) <= POS_OK_MAX
    assert min(m["position_error_mm"] for m in fail_runs) >= POS_FAIL_MIN
    rate = len(ok_runs) / len(seq)
    assert abs(rate - 0.85) < 0.10, f"大数定律：率 {rate:.3f} 偏离 0.85 过大"
    print("fake_cell self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--pick-prob", type=float, default=0.85)
    parser.add_argument("--cycle", type=float, default=1.0,
                        help="run 间隔秒（真实节拍约 7s，演示/回归可调小加速）")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--task-result-topic", default="/task_result")
    parser.add_argument("--self-test", action="store_true",
                        help="纯函数自验（无需 ROS 环境）")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if not (0.0 < args.pick_prob < 1.0):
        raise SystemExit("--pick-prob 需在 (0,1) 开区间（两分支都要有样本）")

    seq = build_sequence(args.runs, args.pick_prob, args.seed)

    import time

    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    rclpy.init()
    node = Node("rv_fake_cell")
    pub = node.create_publisher(String, args.task_result_topic, 10)
    time.sleep(DDS_WARMUP_S)  # DDS 订阅匹配（同 smoke_talker 的首条丢失边界）

    for i, m in enumerate(seq):
        msg = String()
        msg.data = json.dumps(m)  # 载荷全 ASCII 数字，无编码坑
        pub.publish(msg)
        node.get_logger().info(f"run #{i + 1}/{args.runs}: {msg.data}")
        rclpy.spin_once(node, timeout_sec=args.cycle)

    rate = sum(m["pick_success"] for m in seq) / len(seq)
    node.get_logger().info(
        f"fake_cell done: runs={args.runs} pick_rate={rate:.3f} seed={args.seed}")
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
