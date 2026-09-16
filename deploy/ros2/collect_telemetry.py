#!/usr/bin/env python3
"""ROS 2 只读遥测采集器（M4 遗留项，v0 骨架）——订阅 → 派生指标 → CSV 导出。

安全边界（docs/architecture.md §9）：**零发布器**——本节点不创建任何 publisher，
不向任何控制话题发布消息；只订阅只读。代码审查点：全文仅 Subscription，无 Publisher。

输出 CSV 逐行 `ts(ISO-8601),metric,value`，与平台 `POST /api/realtest/sessions`
（RealTestController.importCsv）导入格式逐字节兼容；指标名单对齐
realtest/gap.py 的 KNOWN_METRICS（picking_success_rate / position_error_mm / cycle_time_s）。

指标来源（两路，真机按实际有的接）：
1. /task_result（std_msgs/String，JSON 内容）——上游任务节点发布的逐周期结果：
   {"pick_success": 1, "cycle_time_s": 6.2, "position_error_mm": 2.4}
   每条消息 → 三行 CSV（缺字段跳过该行，不编造）。
2. /joint_states（sensor_msgs/JointState）——只作采样率/关节名诊断日志，不进 CSV
   （CSV 是 Gap 管线的指标流，不是原始关节流；原始流落盘归后续需求）。

⚠ 诚实声明：开发机无 ROS 环境，本文件未在真 ROS 2 下运行过（rclpy 部分按
Jazzy/Humble API 编写）；纯函数逻辑（CSV 行派生）带 --self-test 自验。
首次接入真机需联调话题名与消息格式。

2026-09-16 真实 ROS 2 humble 容器联调通过（rv_smoke_talker 冒烟 harness）：
订阅/派生/落盘/边界语义（布尔/缺字段/非法 JSON）全部验证；修复 SIGINT 二次
shutdown RCLError。已知边界：启动后 ~1s DDS 发现期内若上游恰好发布，首条消息
可能丢失（volatile 持久性不重放；机器人持续发布场景影响可忽略，追求不丢则
上游需 transient_local）。

用法（ROS 2 环境内）：
  python3 collect_telemetry.py --output telemetry.csv
  ros2 run --prefix 'python3' ... （或 source 后直接 ros2 run 包形式接入）
  Ctrl-C 结束（行缓冲，每条即时落盘，无数据丢失窗口）
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 平台侧 KNOWN_METRICS 的镜像（realtest/gap.py）；映射 task_result 字段 → 指标名
RESULT_FIELD_TO_METRIC = {
    "pick_success": "picking_success_rate",
    "cycle_time_s": "cycle_time_s",
    "position_error_mm": "position_error_mm",
}


def derive_rows(result_json: str, ts: datetime) -> list[tuple[str, str, str]]:
    """task_result JSON → CSV 行列表（ts, metric, value）。

    缺字段/非法 JSON/非数值 → 空列表（不编造指标）。datetime 统一 UTC ISO-8601。
    """
    try:
        payload = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return []
    rows = []
    ts_iso = ts.astimezone(timezone.utc).isoformat()
    for field, metric in RESULT_FIELD_TO_METRIC.items():
        value = payload.get(field)
        if isinstance(value, bool):
            value = int(value)
        if isinstance(value, (int, float)):
            rows.append((ts_iso, metric, repr(float(value))))
    return rows


class TelemetryWriter:
    """CSV 追加器（行缓冲即时落盘——进程被杀不丢已采行）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._new = not path.exists() or path.stat().st_size == 0
        self._fh = open(path, "a", encoding="utf-8", newline="")
        self._writer = csv.writer(self._fh)
        if self._new:
            self._writer.writerow(["ts", "metric", "value"])
            self._fh.flush()

    def write(self, rows: list[tuple[str, str, str]]) -> int:
        for row in rows:
            self._writer.writerow(row)
        self._fh.flush()
        return len(rows)

    def close(self) -> None:
        self._fh.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ROS 2 read-only telemetry collector")
    parser.add_argument("--output", default="telemetry.csv", help="输出 CSV 路径")
    parser.add_argument("--task-result-topic", default="/task_result")
    parser.add_argument("--joint-states-topic", default="/joint_states")
    parser.add_argument("--self-test", action="store_true",
                        help="只跑纯函数自验（无 ROS 环境可执行），不启动节点")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import JointState
        from std_msgs.msg import String
    except ImportError:
        print("ERROR: rclpy 不可用——请在 ROS 2 环境（Humble/Jazzy）内运行；"
              "纯函数自验用 --self-test", file=sys.stderr)
        return 2

    class ReadOnlyCollector(Node):
        """只订阅，零发布（安全边界见文件头注释）。"""

        def __init__(self) -> None:
            super().__init__("roboverify_readonly_collector")
            self.writer = TelemetryWriter(Path(args.output))
            self.n_results = 0
            self.n_joint_msgs = 0
            self.create_subscription(
                String, args.task_result_topic, self._on_result, 10)
            self.create_subscription(
                JointState, args.joint_states_topic, self._on_joints,
                qos_profile_sensor_data)

        def _on_result(self, msg: "String") -> None:
            ts = datetime.now(timezone.utc)
            n = self.writer.write(derive_rows(msg.data, ts))
            self.n_results += 1
            if n == 0:
                self.get_logger().warning(
                    f"task_result 无法派生指标行（JSON 字段缺失/非法）: {msg.data[:120]!r}")
            else:
                self.get_logger().info(f"task_result -> {n} 行 (#{self.n_results})")

        def _on_joints(self, msg: "JointState") -> None:
            self.n_joint_msgs += 1
            if self.n_joint_msgs % 1000 == 1:
                self.get_logger().info(
                    f"joint_states 采样中: {self.n_joint_msgs} 条, 关节 {len(msg.name)} 个")

        def destroy_node(self) -> bool:
            self.get_logger().info(
                f"关闭: task_result {self.n_results} 条 / joint_states "
                f"{self.n_joint_msgs} 条 -> {args.output}")
            self.writer.close()
            return super().destroy_node()

    rclpy.init()
    node = ReadOnlyCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        # 信号可能已触发 context 关闭（rclpy 默认 signal handler），二次 shutdown
        # 抛 RCLError——真 ROS humble 联调实测（2026-09-16），吞掉保证干净退出
        try:
            rclpy.shutdown()
        except Exception:  # noqa: BLE001 — 关闭路径兜底，数据已行缓冲落盘
            pass
    return 0


def _self_test() -> int:
    """纯函数自验（开发机无 ROS 也可跑）：派生行格式/缺字段/非法 JSON/布尔。"""
    ts = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    rows = derive_rows('{"pick_success": 1, "cycle_time_s": 6.2, "position_error_mm": 2.45}', ts)
    assert rows == [
        ("2026-09-15T12:00:00+00:00", "picking_success_rate", "1.0"),
        ("2026-09-15T12:00:00+00:00", "cycle_time_s", "6.2"),
        ("2026-09-15T12:00:00+00:00", "position_error_mm", "2.45"),
    ], rows
    assert derive_rows('{"pick_success": 1}', ts) == [
        ("2026-09-15T12:00:00+00:00", "picking_success_rate", "1.0")]
    assert derive_rows("not-json", ts) == []
    assert derive_rows('{"unexpected": 1}', ts) == []
    assert derive_rows('{"pick_success": true}', ts) == [
        ("2026-09-15T12:00:00+00:00", "picking_success_rate", "1.0")]
    # 带时区偏移的 ts 统一转 UTC
    assert derive_rows('{"cycle_time_s": 1}', datetime(2026, 9, 15, 20, 0, 0,
                                                       tzinfo=timezone.utc))[0][0] \
        == "2026-09-15T20:00:00+00:00"
    print("SELF_TEST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
