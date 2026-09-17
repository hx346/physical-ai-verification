#!/usr/bin/env bash
# 容器内演练（由 e2e_rehearsal.sh 经 docker run 调用，ros:humble-ros-base）：
# collect_telemetry（直连推送）+ smoke_talker（合成源）→ CSV 行数断言。
# 退出码即结论：0=采集+推送全成，10=self-test，11=talker，20=行数不符，其他=collector 退出码。
set -uo pipefail
cd /ros

python3 collect_telemetry.py --self-test >/dev/null || { echo "SELF_TEST_FAIL"; exit 10; }

python3 collect_telemetry.py --output /tmp/telemetry.csv \
  --api-endpoint "$RV_API" --api-token "$RV_TOKEN" --project-id "$RV_PROJECT" \
  --external-key "$RV_EXTKEY" --note "V0.8 W1 rehearsal" &
COL=$!
sleep 2.5  # DDS 订阅匹配（volatile 首条丢失边界，见采集器头注释）
python3 smoke_talker.py --count 8 --interval 0.3 || { kill "$COL" 2>/dev/null; exit 11; }
sleep 1
kill -INT "$COL"  # Ctrl-C 等价：行缓冲落盘 → rclpy 关闭 → 自动推送
wait "$COL"; RC=$?
echo "collector_exit=$RC"
[ "$RC" -eq 0 ] || exit "$RC"

# count=8 → 五字段×2 + 布尔二字段×2 + 缺字段×2 + 非法×2 = 5*2+2*2+1*2 = 16 行
N=$(($(wc -l < /tmp/telemetry.csv) - 1))
echo "csv_rows=$N (expect 16)"
[ "$N" -eq 16 ] || { echo "ROWS_MISMATCH"; exit 20; }
echo "INSIDE_OK"
