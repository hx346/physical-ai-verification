# ROS 2 只读遥测采集器（M4 · v0 骨架）

RoboVerify 真机数据入口：**只读订阅 → 指标派生 → CSV → 平台导入 → Gap/校准**。

## 安全边界（架构 §9）

`collect_telemetry.py` 全文**零 Publisher**——不向任何话题发布消息，不可能干扰
被测机器人。接入客户现场前审查点：`grep -c create_publisher` 应为 0（当前代码无此调用）。

## 数据流

```
真机 /task_result (std_msgs/String, JSON)
        │  每条消息派生 0-3 行（缺字段跳过，不编造）
        ▼
telemetry.csv   (ts,metric,value —— 与 POST /api/realtest/sessions 兼容)
        ▼
平台导入:  POST /api/realtest/sessions {"projectId", "csv", "note"}
Gap:      POST /api/realtest/gap       {"sessionId", "simSummary"}
校准:     POST /api/realtest/calibrate → model_version DRAFT→ACTIVE
```

指标名单与 `runtime/src/roboverify_runtime/realtest/gap.py` 的 KNOWN_METRICS
对齐：`picking_success_rate` / `position_error_mm` / `cycle_time_s`。

`/joint_states` 仅作采样诊断日志（不进 CSV——CSV 是 Gap 指标流，非原始关节流）。

## task_result 消息格式（上游任务节点按此发布）

```json
{"pick_success": 1, "cycle_time_s": 6.2, "position_error_mm": 2.45}
```

## 用法

```bash
# 纯函数自验（无需 ROS 环境；开发机已跑通）
python3 collect_telemetry.py --self-test

# ROS 2 环境内（Humble/Jazzy）
python3 collect_telemetry.py --output telemetry.csv \
    --task-result-topic /cell/task_result --joint-states-topic /arm/joint_states
# Ctrl-C 结束；行缓冲即时落盘，无数据丢失窗口
```

## 状态与边界（诚实声明）

- **未在真 ROS 2 环境运行过**（开发机无 ROS；rclpy 部分按 Humble/Jazzy API 编写）。
  首次接入真机需联调：话题名、消息实际格式、QoS（传感器数据 best-effort）。
- 相机/点云话题未订阅（数据量大，原始流落盘非本期需求）。
- F/T（WrenchStamped）订阅位未加——需要时按 `_on_result` 同型扩展一行。

## 回滚

纯新增文件，删除 `deploy/ros2/` 即回滚；不影响任何运行中服务。
