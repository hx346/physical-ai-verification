#!/usr/bin/env bash
# V0.8 W1 真机遥测管道演练（合成源——只验证管道，不产生真实 Gap 结论）：
#   ros:humble 容器内 smoke_talker → collect_telemetry（直连推送，幂等键）
#   → 平台会话/遥测行数/指标聚合断言 → 幂等重推断言 → Gap 四指标断言。
# 绿 = 采集→导入→Gap 管道就绪；真机接入只剩话题名/格式映射（README §接入）。
# 前置：docker compose up -d postgres backend runtime（默认 http://localhost:18090）、
#       本地已有 ros:humble-ros-base 镜像（Docker Desktop）。
# 用法：bash deploy/ros2/e2e_rehearsal.sh [BASE_URL]
set -uo pipefail
export PYTHONUTF8=1

BASE="${1:-http://localhost:18090}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(cd "$HERE/../../runtime" && pwd)/.venv/Scripts/python"
[ -x "$PY" ] || PY="$(cd "$HERE/../../runtime" && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python"

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mREHEARSAL_FAIL: %s\033[0m\n' "$*"; exit 1; }
jq_get() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

ROS_IMAGE="ros:humble-ros-base"
docker image inspect "$ROS_IMAGE" >/dev/null 2>&1 || fail "缺镜像 $ROS_IMAGE（先 docker pull）"

log "0. 登录 + 演练项目"
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"roboverify123"}' | jq_get "d['data']['token']")
[ -n "$TOKEN" ] || fail "登录失败"
AUTH="Authorization: $TOKEN"

PROJECT=$(curl -s "$BASE/api/projects" -H "$AUTH" \
  | jq_get "next((p['id'] for p in d['data'] if p.get('name')=='ros2-rehearsal'), '')")
if [ -z "$PROJECT" ]; then
  # 注意：git bash 内联 JSON 带中文会坏（GBK），描述一律 ASCII（demo 同款坑）
  PROJECT=$(curl -s -X POST "$BASE/api/projects" -H "$AUTH" -H 'Content-Type: application/json' \
    -d '{"name":"ros2-rehearsal","description":"V0.8 W1 pipeline rehearsal (synthetic source)"}' \
    | jq_get "d['data']['id']")
fi
[ -n "$PROJECT" ] || fail "演练项目获取/创建失败"
echo "projectId=$PROJECT"

log "1. humble 容器内采集 + 直连推送"
EXTKEY="rv-rehearsal-$(date -u +%Y%m%dT%H%M%SZ)"
# 容器内访问宿主 backend：localhost → host.docker.internal（Docker Desktop）
CBASE="${BASE//localhost/host.docker.internal}"
CBASE="${CBASE//127.0.0.1/host.docker.internal}"
RW="$(cygpath -w "$HERE" 2>/dev/null || echo "$HERE")"  # MSYS 路径转 Windows 形式
MSYS_NO_PATHCONV=1 docker run --rm \
  -e RV_API="$CBASE" -e RV_TOKEN="$TOKEN" -e RV_PROJECT="$PROJECT" -e RV_EXTKEY="$EXTKEY" \
  -v "$RW:/ros:ro" \
  "$ROS_IMAGE" bash /ros/rehearse_inside.sh || fail "容器内演练失败（见上）"

log "2. 平台侧断言（会话/行数/指标聚合）"
SESSIONS=$(curl -s "$BASE/api/realtest/sessions?projectId=$PROJECT" -H "$AUTH")
SESS=$(echo "$SESSIONS" | jq_get "next((s['id'] for s in d['data'] if s.get('externalKey')=='$EXTKEY'), '')")
[ -n "$SESS" ] || fail "会话未找到 externalKey=$EXTKEY"
ROWS=$(echo "$SESSIONS" | jq_get "next((s['nRows'] for s in d['data'] if s['id']=='$SESS'), 0)")
[ "$ROWS" = "16" ] || fail "遥测行数 $ROWS != 16"
curl -s "$BASE/api/realtest/sessions/$SESS/summary" -H "$AUTH" | "$PY" -c "
import sys, json
m = json.load(sys.stdin)['data']['metrics']
assert {'picking_success_rate','cycle_time_s','position_error_mm',
        'perception_error_mm','latency_ms'} <= set(m), m
assert m['latency_ms']['samples'] == 2 and m['picking_success_rate']['samples'] == 4, m
print('   指标聚合 OK:', {k: v['samples'] for k, v in sorted(m.items())})
" || fail "summary 断言失败"
echo "sessionId=$SESS rows=$ROWS"

log "3. 幂等重推断言（同 external-key 不重复导入）"
TMPJSON="$(mktemp -d)/payload.json"
printf '{"projectId":"%s","note":"rehearsal dup","externalKey":"%s","csv":"ts,metric,value\\n2026-09-17T00:00:00Z,cycle_time_s,9.9"}' \
  "$PROJECT" "$EXTKEY" > "$TMPJSON"
DUP=$(curl -s -X POST "$BASE/api/realtest/sessions" -H "$AUTH" -H 'Content-Type: application/json' \
  --data-binary "@$TMPJSON" | jq_get "d['data']['duplicate']")
[ "$DUP" = "True" ] || fail "幂等重推未命中（duplicate=$DUP）"
ROWS2=$(curl -s "$BASE/api/realtest/sessions?projectId=$PROJECT" -H "$AUTH" \
  | jq_get "next((s['nRows'] for s in d['data'] if s['id']=='$SESS'), 0)")
[ "$ROWS2" = "16" ] || fail "重推后行数变化 $ROWS2 != 16"
echo "   duplicate=True，rows 仍 16 ✓"

log "4. Gap 断言（sim 四指标映射 + latency 无 sim 对应的诚实边界）"
printf '{"sessionId":"%s","simSummary":{"success_rate_mean":0.75,"accuracy_p95_mean_mm":3.0,"cycle_time_s_mean":6.5,"perception_error_mm_mean":1.0}}' \
  "$SESS" > "$TMPJSON"
curl -s -X POST "$BASE/api/realtest/gap" -H "$AUTH" -H 'Content-Type: application/json' \
  --data-binary "@$TMPJSON" | "$PY" -c "
import sys, json
gap = json.load(sys.stdin)['data']['gap']
assert {'picking_success_rate','position_error_mm','cycle_time_s',
        'perception_error_mm'} <= set(gap), gap
# 四个有 sim 对应的指标必须有 verdict；无对应的（latency_ms）如实标 no_sim_counterpart
assert all('verdict' in v for k, v in gap.items() if k != 'latency_ms'), gap
assert gap['latency_ms']['status'] == 'no_sim_counterpart', gap['latency_ms']
for k in sorted(gap):
    v = gap[k]
    if 'gap_percent' in v:
        print(f\"   {k}: gap={v['gap_percent']:+.1f}% {v['verdict']}\")
    else:
        print(f\"   {k}: {v['status']}\")
" || fail "gap 断言失败"

printf '\n\033[1;32mREHEARSAL_OK\033[0m  管道就绪：真机接入 = 换话题名 + task_result 字段对齐（deploy/ros2/README.md）\n'
