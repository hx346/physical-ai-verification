#!/usr/bin/env bash
# 容器内演练（由 e2e_fake_cell.sh 经 docker run 调用，ros:humble-ros-base）：
# collect_telemetry（直连推送）+ fake_cell（合成抓取单元）→ CSV 行数断言。
# 与 rehearse_inside.sh（smoke_talker 冒烟）的区别：fake_cell 发 N 条正常消息
# （五字段全出，无边界消息），断言行数 = N*5——验规模与确定性，边界语义归 rehearsal。
# 退出码即结论：0=采集+推送全成，10=self-test，11=fake_cell，20=行数不符，其他=collector 退出码。
set -uo pipefail
cd /ros

python3 fake_cell.py --self-test >/dev/null || { echo "SELF_TEST_FAIL"; exit 10; }

python3 collect_telemetry.py --output /tmp/telemetry.csv \
  --api-endpoint "$RV_API" --api-token "$RV_TOKEN" --project-id "$RV_PROJECT" \
  --external-key "$RV_EXTKEY" --note "fake-cell rehearsal" &
COL=$!
sleep 2.5  # DDS 订阅匹配（volatile 首条丢失边界，见采集器头注释）
python3 fake_cell.py --runs "$RV_RUNS" --cycle 0.5 --seed "$RV_SEED" \
  || { kill "$COL" 2>/dev/null; exit 11; }
sleep 1
kill -INT "$COL"  # Ctrl-C 等价：行缓冲落盘 → rclpy 关闭 → 自动推送
wait "$COL"; RC=$?
echo "collector_exit=$RC"
[ "$RC" -eq 0 ] || exit "$RC"

# 五字段×N run（成功/失败全出）——fake_cell 不发残缺消息
EXPECT=$((RV_RUNS * 5))
N=$(($(wc -l < /tmp/telemetry.csv) - 1))
echo "csv_rows=$N (expect $EXPECT)"
[ "$N" -eq "$EXPECT" ] || { echo "ROWS_MISMATCH"; exit 20; }
echo "INSIDE_OK"
