#!/usr/bin/env python3
"""ROS 2 冒烟发布器（采集器联调 harness，非真机组件）——发布合成 /task_result 与
/joint_states 若干条，验证 collect_telemetry.py 在真实 rclpy 环境下的订阅/派生/落盘。

用法（ROS 2 环境内，与采集器并行）：
  python3 smoke_talker.py [--count N]
消息序列刻意覆盖边界：正常 JSON / 布尔 pick_success / 缺字段 / 非法 JSON——
验证 derive_rows 的诚实语义（缺字段跳过、非法忽略、不编造）。
"""

from __future__ import annotations

import argparse
import json

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String


def build_messages(count: int) -> list[str]:
    msgs = []
    for i in range(count):
        kind = i % 4
        if kind == 0:  # 正常：五字段齐（V0.8 W1 含 perception_error_mm/latency_ms）
            msgs.append(json.dumps({"pick_success": 1, "cycle_time_s": 6.2 + i * 0.1,
                                    "position_error_mm": 2.4 + i * 0.05,
                                    "perception_error_mm": 1.1 + 0.02 * i,
                                    "latency_ms": 35.0 + i}))
        elif kind == 1:  # 布尔 pick_success（应转 1/0）
            msgs.append(json.dumps({"pick_success": True, "cycle_time_s": 7.1}))
        elif kind == 2:  # 缺字段（只出 cycle_time 行）
            msgs.append(json.dumps({"cycle_time_s": 5.9}))
        else:  # 非法 JSON（整条丢弃）
            msgs.append("{not-json")
    return msgs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    rclpy.init()
    node = Node("rv_smoke_talker")
    pub_result = node.create_publisher(String, "/task_result", 10)
    pub_joints = node.create_publisher(JointState, "/joint_states", 10)

    # DDS 发现竞态：发布器创建后立即发布，订阅匹配完成前的首条会丢（volatile 持久性
    # 不重放）——humble 容器实测可复现。warmup 等待匹配，保证联调结果确定性。
    import time
    time.sleep(1.5)

    joints = JointState()
    joints.name = ["joint_1", "joint_2"]
    for i, text in enumerate(build_messages(args.count)):
        msg = String()
        msg.data = text
        pub_result.publish(msg)
        joints.position = [0.1 * i, -0.2 * i]
        pub_joints.publish(joints)
        node.get_logger().info(f"published #{i}: {text[:60]}")
        rclpy.spin_once(node, timeout_sec=args.interval)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
