# ROS 2 只读遥测采集器（M4 骨架 → V0.8 W1 直连版）

RoboVerify 真机数据入口：**只读订阅 → 指标派生 → CSV（事实源）→ 直连推送 → Gap/校准**。

## 安全边界（架构 §9）

`collect_telemetry.py` 全文**零 Publisher**——不向任何话题发布消息，不可能干扰
被测机器人。接入客户现场前审查点：`grep -c create_publisher` 应为 0（当前代码无此调用）。

## 数据流（V0.8 W1 起：采集器直连平台）

```
真机 /task_result (std_msgs/String, JSON)
        │  每条消息派生 0-5 行（缺字段跳过，不编造）
        ▼
telemetry.csv   (ts,metric,value —— 行缓冲即时落盘，事实源)
        │  Ctrl-C 结束时自动 POST（--api-endpoint 模式；失败仅退出码 3，数据不丢）
        ▼
平台导入:  POST /api/realtest/sessions {"projectId","csv","note","externalKey"}  ← 幂等键
会话/聚合: GET  /api/realtest/sessions[?projectId=] 、/sessions/{id}/summary
Gap:      POST /api/realtest/gap {"sessionId","simSummary"}
校准:     POST /api/realtest/calibrate → model_version DRAFT→ACTIVE
```

指标名单与 `runtime/src/roboverify_runtime/realtest/gap.py` 对齐：
`picking_success_rate` / `position_error_mm` / `cycle_time_s` /
`perception_error_mm`（与仿真聚合同名，gap 自动对上）/ `latency_ms`
（仿真暂无对应 → gap 如实标 `no_sim_counterpart`）。

`/joint_states` 仅作采样诊断日志（不进 CSV——CSV 是 Gap 指标流，非原始关节流）。

## task_result 消息格式（上游任务节点按此发布）

```json
{"pick_success": 1, "cycle_time_s": 6.2, "position_error_mm": 2.45,
 "perception_error_mm": 1.2, "latency_ms": 35.5}
```

字段全部可选——缺哪个少派生哪行，不编造。

## 真机接入步骤（管道已演练就绪，接入只剩这三步）

1. **话题名**：`--task-result-topic /<实际话题>`（默认 `/task_result`；
   `/joint_states` 同理）。QoS：task_result 用 reliable 队列 10，关节流
   best-effort（传感器语义）。
2. **task_result 字段对齐**：上游任务节点按上表发 JSON（字段名/单位：mm、秒、毫秒）。
3. **直连参数**：`--api-endpoint http://<平台>:18090 --api-token <token>
   --project-id <uuid>`。鉴权头为**裸 token**（无 Bearer 前缀）。

## 用法

```bash
# 纯函数自验（无需 ROS 环境）
python3 collect_telemetry.py --self-test

# ROS 2 环境内（Humble/Jazzy）——离线模式（只落 CSV，人工上传）
python3 collect_telemetry.py --output telemetry.csv \
    --task-result-topic /cell/task_result --joint-states-topic /arm/joint_states

# 直连模式（V0.8 W1）：Ctrl-C 结束 → 行缓冲已落盘 → 自动推送（幂等可重试）
python3 collect_telemetry.py --output telemetry.csv \
    --api-endpoint http://10.0.0.5:18090 --api-token "$TOKEN" --project-id "$PID"
```

## 管道演练（E2E，合成源）

```bash
bash deploy/ros2/e2e_rehearsal.sh   # 前置：本地栈 + ros:humble-ros-base 镜像
```

humble 容器内 smoke_talker（合成源）→ 采集器直连推送 → 平台断言
（16 行/5 指标聚合/幂等重推 duplicate=True/Gap 四指标映射）。
**合成源只验证管道，不产生真实 Gap 结论**（诚实边界）。

## 合成抓取单元（fake_cell，演示/回归数据源）

```bash
# ROS 2 环境内与采集器并行（采集器建议 --external-key fake-cell-... 便于识别清理）
python3 fake_cell.py --runs 20 --pick-prob 0.85 --seed 42 --cycle 7.0

# 一键端到端（前置：本地栈 + ros:humble-ros-base 镜像）：合成单元 → 采集 → 平台会话 → 确定性断言
bash deploy/ros2/e2e_fake_cell.sh
```

与 smoke_talker 分工：smoke_talker 验边界语义（布尔/缺字段/非法 JSON，8 条即停）；
fake_cell 出规模数据（每 run 五字段全出、失败 run 定位误差放大、同 seed 确定性）。
用途=真机接入前的前端真机页/报告 Gap 演示数据与管道回归。**合成会话不构成
真机对照结论**（external-key 带 fake-cell- 前缀，演示数据定期清理）。

## 状态与边界（诚实声明）

- 真实 ROS 2 humble 容器联调通过（订阅/派生/落盘/边界语义/SIGINT 关闭）；
  E2E 直连推送演练绿（2026-09-17）。
- **未在真机器人上运行过**——真机接入需现场联调话题名与消息实际格式
  （接入步骤见上，预期只动参数不改代码）。
- DDS 发现期（启动 ~1s）首条消息可能丢失（volatile 不重放；持续发布场景可忽略）。
- 相机/点云话题未订阅（原始流落盘与时序库归后续版本，方案 §33）。
- F/T（WrenchStamped）订阅位未加——需要时按 `_on_result` 同型扩展一行。

## 回滚

采集器/演练脚本为 `deploy/ros2/` 独立文件，删除即回滚，不影响运行中服务。
平台侧幂等键/列表 API 走 Flyway V8（`external_key` 列 + 部分唯一索引），
回滚 = revert 迁移提交（列可保留无害）。
