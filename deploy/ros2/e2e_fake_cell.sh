#!/usr/bin/env bash
# fake_cell 合成单元端到端演练（真机接入前的演示/回归数据源验证）：
#   ros:humble 容器内 fake_cell（同 seed 确定性序列）→ collect_telemetry 直连推送
#   → 平台会话/行数=runs*5/五指标聚合/pick_rate 与宿主同 seed 期望精确一致。
# 与 e2e_rehearsal.sh 的分工：rehearsal 验管道边界（布尔/缺字段/非法 JSON/幂等重推/Gap
# 映射）；本脚本验合成数据源的规模与确定性——演示数据一键生成，可入每周收尾回归。
# 诚实边界：合成会话的 Gap 数字不构成真机对照结论（README §状态与边界）。
# 前置：本地栈 up（postgres backend runtime）、ros:humble-ros-base 镜像。
# 用法：bash deploy/ros2/e2e_fake_cell.sh [BASE_URL] [RUNS] [SEED]
set -uo pipefail
export PYTHONUTF8=1

BASE="${1:-http://localhost:18090}"
RUNS="${2:-12}"
SEED="${3:-7}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(cd "$HERE/../../runtime" && pwd)/.venv/Scripts/python"
[ -x "$PY" ] || PY="$(cd "$HERE/../../runtime" && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python"

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mFAKE_CELL_FAIL: %s\033[0m\n' "$*"; exit 1; }
jq_get() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

ROS_IMAGE="ros:humble-ros-base"
docker image inspect "$ROS_IMAGE" >/dev/null 2>&1 || fail "缺镜像 $ROS_IMAGE（先 docker pull）"

log "0. 登录 + 演练项目 + 宿主侧期望值（同 seed 算 pick_rate）"
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"roboverify123"}' | jq_get "d['data']['token']")
[ -n "$TOKEN" ] || fail "登录失败"
AUTH="Authorization: $TOKEN"

PROJECT=$(curl -s "$BASE/api/projects" -H "$AUTH" \
  | jq_get "next((p['id'] for p in d['data'] if p.get('name')=='fake-cell-demo'), '')")
if [ -z "$PROJECT" ]; then
  PROJECT=$(curl -s -X POST "$BASE/api/projects" -H "$AUTH" -H 'Content-Type: application/json' \
    -d '{"name":"fake-cell-demo","description":"Synthetic cell demo sessions (fake_cell.py, not real robot)"}' \
    | jq_get "d['data']['id']")
fi
[ -n "$PROJECT" ] || fail "演练项目获取/创建失败"

RW="$(cygpath -w "$HERE" 2>/dev/null || echo "$HERE")"  # Windows python import 路径
EXPECT_RATE=$("$PY" - "$RW" "$RUNS" "$SEED" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from fake_cell import build_sequence
seq = build_sequence(int(sys.argv[2]), 0.85, seed=int(sys.argv[3]))
print(sum(m["pick_success"] for m in seq) / len(seq))
EOF
) || fail "期望值计算失败"
echo "projectId=$PROJECT runs=$RUNS seed=$SEED expect_pick_rate=$EXPECT_RATE"

log "1. humble 容器内合成单元 + 直连推送"
EXTKEY="fake-cell-$(date -u +%Y%m%dT%H%M%SZ)"
CBASE="${BASE//localhost/host.docker.internal}"
CBASE="${CBASE//127.0.0.1/host.docker.internal}"
MSYS_NO_PATHCONV=1 docker run --rm \
  -e RV_API="$CBASE" -e RV_TOKEN="$TOKEN" -e RV_PROJECT="$PROJECT" -e RV_EXTKEY="$EXTKEY" \
  -e RV_RUNS="$RUNS" -e RV_SEED="$SEED" \
  -v "$RW:/ros:ro" \
  "$ROS_IMAGE" bash /ros/rehearse_fake_inside.sh || fail "容器内演练失败（见上）"

log "2. 平台侧断言（会话/行数/五指标/pick_rate 确定性）"
SESSIONS=$(curl -s "$BASE/api/realtest/sessions?projectId=$PROJECT" -H "$AUTH")
SESS=$(echo "$SESSIONS" | jq_get "next((s['id'] for s in d['data'] if s.get('externalKey')=='$EXTKEY'), '')")
[ -n "$SESS" ] || fail "会话未找到 externalKey=$EXTKEY"
ROWS=$(echo "$SESSIONS" | jq_get "next((s['nRows'] for s in d['data'] if s['id']=='$SESS'), 0)")
[ "$ROWS" = "$((RUNS * 5))" ] || fail "遥测行数 $ROWS != $((RUNS * 5))"
echo "sessionId=$SESS rows=$ROWS ✓"

# 临时文件走相对路径（bash 与 Windows python 的 /tmp 视图不同，demo 同款坑）
SUMJSON=".fake-summary-$$.json"
curl -s "$BASE/api/realtest/sessions/$SESS/summary" -H "$AUTH" -o "$SUMJSON"
"$PY" - "$SUMJSON" "$EXPECT_RATE" <<'EOF'
import sys, json
expect = float(sys.argv[2])
m = json.load(open(sys.argv[1], encoding='utf-8'))['data']['metrics']
assert {'picking_success_rate','cycle_time_s','position_error_mm',
        'perception_error_mm','latency_ms'} <= set(m), sorted(m)
for k, v in sorted(m.items()):
    assert v['samples'] > 0, (k, v)  # 五指标全有样本（fake_cell 五字段全出）
rate = m['picking_success_rate']['mean']
assert abs(rate - expect) < 1e-9, (rate, expect)  # 同 seed 端到端确定性
print('   pick_rate=%.4f == expect %.4f OK; metrics=%s' % (rate, expect, sorted(m)))
EOF
RC=$?
rm -f "$SUMJSON"
[ "$RC" -eq 0 ] || fail "summary 断言失败"

printf '\n\033[1;32mFAKE_CELL_OK\033[0m  演示会话就绪（externalKey=%s）——合成数据，非真机结论\n' "$EXTKEY"
