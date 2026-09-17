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

V0.8 W1（2026-09-17）真机遥测直连：
- 指标扩容：task_result JSON 新增 perception_error_mm / latency_ms 字段自动
  派生（有则进 CSV，无则不出——与仿真聚合 perception_error_mm 同名对齐，
  gap 侧自动接上；latency_ms 仿真暂无对应 → gap 标 no_sim_counterpart）。
- --api-endpoint：采集结束（Ctrl-C）自动 POST 平台导入会话。本地 CSV 仍是
  事实源（行缓冲即时落盘），推送失败仅退出码 3，数据不丢。
- 幂等：--external-key（默认 ros-collector-{host}-{启动时刻 UTC}）——推送
  超时重试同 key 重推，平台返回原会话不重复导入。

用法（ROS 2 环境内）：
  python3 collect_telemetry.py --output telemetry.csv \
      --task-result-topic /cell/task_result \
      --api-endpoint http://<平台地址>:18090 --api-token <token> \
      --project-id <uuid>
  Ctrl-C 结束（行缓冲即时落盘 → 自动推送）。
"""

from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

# 平台侧 KNOWN_METRICS 的镜像（realtest/gap.py）；映射 task_result 字段 → 指标名。
# V0.8 W1 扩容：perception_error_mm（与仿真聚合同名）/ latency_ms（计划 §20
# Latency 采集点——上游任务节点上报感知→动作延迟，字段无则不出）。
RESULT_FIELD_TO_METRIC = {
    "pick_success": "picking_success_rate",
    "cycle_time_s": "cycle_time_s",
    "position_error_mm": "position_error_mm",
    "perception_error_mm": "perception_error_mm",
    "latency_ms": "latency_ms",
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


def default_external_key(now: datetime | None = None) -> str:
    """幂等键默认值：采集器一次运行一个会话（host + 启动时刻 UTC）。"""
    t = now or datetime.now(timezone.utc)
    return f"ros-collector-{socket.gethostname()}-{t.strftime('%Y%m%dT%H%M%SZ')}"


def build_import_payload(csv_text: str, project_id: str, note: str,
                         external_key: str) -> dict:
    """CSV 文本 → POST /api/realtest/sessions 请求体（字段名对齐 ImportCsvRequest）。"""
    return {"projectId": project_id, "csv": csv_text, "note": note,
            "externalKey": external_key}


def push_to_platform(endpoint: str, payload: dict, token: str | None = None,
                     timeout_s: float = 30.0) -> tuple[int, dict | None]:
    """零依赖推送（urllib，humble 容器无需 pip）。鉴权头用裸 token
    （Authorization: <token>，平台 Sa-Token 语义——带 Bearer 前缀会被当
    token 内容拒掉）。返回 (HTTP 状态, 响应 JSON)；异常抛给调用方统一兜底。
    """
    from urllib.request import Request, urlopen

    url = endpoint.rstrip("/") + "/api/realtest/sessions"
    req = Request(url, data=json.dumps(payload).encode("utf-8"),
                  headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", token)
    with urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return resp.status, body


def _push_csv(path: Path, args: argparse.Namespace) -> bool:
    """采集结束后推送本地 CSV。失败只影响退出码（3），数据不丢。"""
    if not path.exists() or path.stat().st_size == 0:
        print(f"WARN: 无 CSV 可推送（{path}）", file=sys.stderr)
        return False
    payload = build_import_payload(path.read_text(encoding="utf-8"),
                                  args.project_id, args.note, args.external_key)
    try:
        status, body = push_to_platform(args.api_endpoint, payload, args.api_token)
    except Exception as exc:  # noqa: BLE001 — 推送兜底：网络/平台不可用，数据已落盘
        print(f"PUSH_FAIL: {exc}（CSV 已保留在 {path}，可重推同 external-key 幂等）",
              file=sys.stderr)
        return False
    data = (body or {}).get("data") or {}
    print(f"PUSH_OK: sessionId={data.get('sessionId')} imported={data.get('imported')} "
          f"skipped={data.get('skipped', 0)} duplicate={data.get('duplicate', False)}")
    return status == 200 and data.get("sessionId") is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ROS 2 read-only telemetry collector")
    parser.add_argument("--output", default="telemetry.csv", help="输出 CSV 路径")
    parser.add_argument("--task-result-topic", default="/task_result")
    parser.add_argument("--joint-states-topic", default="/joint_states")
    parser.add_argument("--self-test", action="store_true",
                        help="只跑纯函数自验（无 ROS 环境可执行），不启动节点")
    parser.add_argument("--api-endpoint", default=None,
                        help="平台后端地址（如 http://10.0.0.5:18090）——采集结束自动导入会话")
    parser.add_argument("--api-token", default=None, help="平台登录 token（裸值）")
    parser.add_argument("--project-id", default=None, help="平台项目 ID（api 模式必填）")
    parser.add_argument("--note", default="ros2 collector")
    parser.add_argument("--external-key", default=None,
                        help="导入幂等键（默认 ros-collector-{host}-{启动 UTC}）")
    args = parser.parse_args(argv)

    if args.api_endpoint and not args.project_id:
        parser.error("--api-endpoint 需同时提供 --project-id")

    if args.self_test:
        return _self_test()

    try:
        import rclpy
        from rclpy.executors import ExternalShutdownException
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

    # 幂等键在采集启动时定格（同一运行的重推共享同 key）
    if not args.external_key:
        args.external_key = default_external_key()

    rclpy.init()
    node = ReadOnlyCollector()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        # 两种 SIGINT 到达路径：交互 Ctrl-C（Python 默认 handler → KeyboardInterrupt）
        # 与 kill -INT/脚本场景（rclpy.init 装的 handler 先关 context → spin 抛
        # ExternalShutdownException——humble 容器实测，2026-09-17）。
        pass
    finally:
        node.destroy_node()
        # 信号可能已触发 context 关闭（rclpy 默认 signal handler），二次 shutdown
        # 抛 RCLError——真 ROS humble 联调实测（2026-09-16），吞掉保证干净退出
        try:
            rclpy.shutdown()
        except Exception:  # noqa: BLE001 — 关闭路径兜底，数据已行缓冲落盘
            pass
    # V0.8 W1 直连推送（rclpy 已关，纯 HTTP）：CSV 是事实源，失败仅退出码 3
    if args.api_endpoint:
        return 0 if _push_csv(Path(args.output), args) else 3
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
    # V0.8 W1：新指标映射（有则派生，与仿真聚合同名对齐）
    rows5 = derive_rows('{"pick_success": 1, "cycle_time_s": 6.0, "position_error_mm": 2.0,'
                        ' "perception_error_mm": 1.2, "latency_ms": 35.5}', ts)
    assert [r[1] for r in rows5] == ["picking_success_rate", "cycle_time_s",
                                     "position_error_mm", "perception_error_mm",
                                     "latency_ms"], rows5
    assert rows5[4] == ("2026-09-15T12:00:00+00:00", "latency_ms", "35.5")
    # 幂等键默认值格式 + 推送请求体字段名对齐 ImportCsvRequest
    key = default_external_key(datetime(2026, 9, 17, 8, 30, 5, tzinfo=timezone.utc))
    assert key == f"ros-collector-{socket.gethostname()}-20260917T083005Z", key
    assert build_import_payload("ts,metric,value", "p1", "n", "k") == {
        "projectId": "p1", "csv": "ts,metric,value", "note": "n", "externalKey": "k"}
    print("SELF_TEST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
