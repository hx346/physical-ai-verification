#!/usr/bin/env bash
# RoboVerify V0.1 全链路 Demo（产品方案 §42 三幕叙事，全部真实计算）
# 前置：docker compose up -d postgres backend runtime worker frontend
# 用法：bash deploy/demo/run-demo.sh [BASE_URL]   # 默认 http://localhost:18090
# 注意：git bash 内联中文会破坏 JSON，所有 body 一律经临时文件 --data-binary 传参。
set -euo pipefail

# Windows GBK 控制台兼容：强制 python UTF-8 输出
export PYTHONUTF8=1

BASE="${1:-http://localhost:18090}"
TMPJSON="$(mktemp -d)/payload.json"

PY="$(cd "$(dirname "$0")/../../runtime" && pwd)/.venv/Scripts/python"
[ -x "$PY" ] || PY="$(cd "$(dirname "$0")/../../runtime" && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python"

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

post() { # post <path> <json-string> [trace-id]
  printf '%s' "$2" > "$TMPJSON"
  local args=(-s -X POST "$BASE$1" -H "$AUTH" -H 'Content-Type: application/json' --data-binary "@$TMPJSON")
  [ "${3:-}" != "" ] && args+=(-H "X-Trace-Id: $3")
  curl "${args[@]}"
}

jq_get() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

log "0. 登录"
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"roboverify123"}' | jq_get "d['data']['token']")
AUTH="Authorization: $TOKEN"
echo "token ok"

log "1. 创建项目并导入演示数据"
PROJECT=$(post "/api/projects" '{"name":"发动机零件自动抓取-Demo","description":"V0.1 demo"}' | jq_get "d['data']['id']")
post "/api/projects/$PROJECT/seed-demo" '{}' | jq_get "d['data']"
echo "projectId=$PROJECT"

SYSTEMS=$(curl -s "$BASE/api/projects/$PROJECT/systems" -H "$AUTH")
SYS_RGB=$(echo "$SYSTEMS" | jq_get "[s for s in d['data'] if s['id']=='sys-rgb-binpicking'][0]['id']")
SYS_RGBD=$(echo "$SYSTEMS" | jq_get "[s for s in d['data'] if s['id']=='sys-rgbd-binpicking'][0]['id']")
echo "sysRGB=$SYS_RGB sysRGBD=$SYS_RGBD"

log "2. 第一幕：RGB 配置 → 预期 FAIL（度量深度不可观测）"
post "/api/verification/runs" "{\"projectId\":\"$PROJECT\",\"systemConfigId\":\"$SYS_RGB\"}" demo-act1 | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
for i in d['items']:
    print(f\"  {i['requirementId']}: {i['status']:7s} observed={i.get('observed')} {i.get('unit') or ''} evidence={i.get('evidenceId')}\")
r003 = [i for i in d['items'] if i['requirementId'] == 'R003'][0]
assert r003['status'] == 'FAIL', 'R003 应为 FAIL'
print('   detail:', r003['detail'][:110])
print('第一幕断言通过：R003 FAIL（度量深度不可观测）✓')
"

log "3. 第二幕：换 RGB-D（0.65m 近距）→ 预期定位精度 PASS"
RUN2=$(post "/api/verification/runs" "{\"projectId\":\"$PROJECT\",\"systemConfigId\":\"$SYS_RGBD\"}" demo-act2)
RUN2_ID=$(echo "$RUN2" | jq_get "d['data']['runId']")
echo "$RUN2" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
for i in d['items']:
    print(f\"  {i['requirementId']}: {i['status']:7s} observed={i.get('observed')} {i.get('unit') or ''} evidence={i.get('evidenceId')}\")
r003 = [i for i in d['items'] if i['requirementId'] == 'R003'][0]
assert r003['status'] == 'PASS', 'R003 应为 PASS'
print('第二幕断言通过：R003 PASS ✓')
"

log "4. 第三幕：1000 次实验（LHS，worker 异步）→ Sobol 敏感性"
JOB=$(post "/api/experiments" "{\"projectId\":\"$PROJECT\",\"systemConfigId\":\"$SYS_RGBD\",\"n\":1000,\"method\":\"lhs\"}" demo-act3 | jq_get "d['data']['jobKey']")
echo "jobKey=$JOB"
for i in $(seq 1 90); do
  STATUS=$(curl -s "$BASE/api/experiments/$JOB" -H "$AUTH" | jq_get "d['data']['status']")
  [ "$STATUS" = "SUCCEEDED" ] && break
  [ "$STATUS" = "FAILED" ] && { echo "experiment FAILED"; exit 1; }
  sleep 2
done
curl -s "$BASE/api/experiments/$JOB" -H "$AUTH" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
agg = d['result']['aggregates']
print(f\"  samples={agg['samples']} success_mean={agg['success_rate_mean']:.4f} \"
      f\"success_P5={agg['success_rate_P5']:.4f} acc_p95_mean={agg['accuracy_p95_mean_mm']:.2f}mm\")
print('  敏感性 Top3:', [(s['name'], round(s['share'],3)) for s in d['result']['sensitivity'][:3]])
print('  证据:', d.get('evidenceId'))
assert agg['samples'] == 1000
print('第三幕断言通过：1000-run + 敏感性排名 ✓')
"

log "5. 相机位姿研究（0.65m vs 0.95m 对照实验）"
SYS_HIGH_IR=$(echo "$SYSTEMS" | "$PY" -c "
import sys, json
systems = json.load(sys.stdin)['data']
ir = [s for s in systems if s['id'] == 'sys-rgbd-binpicking'][0]
for c in ir['components']:
    if c['id'] == 'cam-overhead-1':
        c['mountPose']['z'] = 0.95
ir['id'] = 'sys-rgbd-binpicking-high'
ir['name'] = 'RGB-D 高位对照 0.95m'
print(json.dumps(ir, ensure_ascii=False))
")
SYS_HIGH=$(post "/api/projects/$PROJECT/systems" "{\"name\":\"RGB-D 高位对照 0.95m\",\"ir\":$SYS_HIGH_IR}" | jq_get "d['data']")
JOB_HIGH=$(post "/api/experiments" "{\"projectId\":\"$PROJECT\",\"systemConfigId\":\"$SYS_HIGH\",\"n\":1000,\"method\":\"lhs\"}" | jq_get "d['data']['jobKey']")
for i in $(seq 1 90); do
  S=$(curl -s "$BASE/api/experiments/$JOB_HIGH" -H "$AUTH" | jq_get "d['data']['status']")
  [ "$S" = "SUCCEEDED" ] && break; sleep 2
done
curl -s "$BASE/api/experiments/$JOB_HIGH" -H "$AUTH" | "$PY" -c "
import sys, json
agg = json.load(sys.stdin)['data']['result']['aggregates']
print(f\"  0.95m 对照：success_mean={agg['success_rate_mean']:.4f} acc_p95_mean={agg['accuracy_p95_mean_mm']:.2f}mm\")
print('  （对照第 4 步的 0.65m 数值——相机位姿是可控优化变量）')
"

log "6. 报告（含实验证据节，前 24 行）"
curl -s "$BASE/api/verification/runs/$RUN2_ID/report" -H "$AUTH" | head -24

log "7. Real2Sim 演示（合成遥测，标注 synthetic）：Gap + 校准闭环"
SESSION=$(post "/api/realtest/sessions" '{"projectId":"'"$PROJECT"'","note":"synthetic demo telemetry（非真机）","csv":"ts,metric,value\n2026-09-14T10:00:00Z,picking_success_rate,0.941\n2026-09-14T10:05:00Z,picking_success_rate,0.938\n2026-09-14T10:10:00Z,picking_success_rate,0.945\n2026-09-14T10:15:00Z,picking_success_rate,0.940"}' | jq_get "d['data']['sessionId']")
post "/api/realtest/gap" "{\"sessionId\":\"$SESSION\",\"simSummary\":{\"success_rate_mean\":0.9867,\"accuracy_p95_mean_mm\":2.85}}" | "$PY" -c "
import sys, json
gap = json.load(sys.stdin)['data']['gap']
for m, g in gap.items():
    print(f\"  {m}: gap={g.get('gap_percent')}% verdict={g.get('verdict')}\")
"
CAL=$(post "/api/realtest/calibrate" "{\"systemConfigId\":\"$SYS_RGBD\",\"observedSuccessMean\":0.941}" demo-calib)
echo "$CAL" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
print(f\"  sigmaScale={d['sigmaScale']} predicted={d['predictedSuccess']} residual={d['residual']} \"
      f\"modelVersionId={d['modelVersionId']} lifecycle={d['lifecycle']}\")
"
MODEL_ID=$(echo "$CAL" | jq_get "d['data']['modelVersionId']")
post "/api/realtest/models/$MODEL_ID/activate" '{}' | jq_get "d['code']"
echo "  校准版本已激活（DRAFT→ACTIVE；回滚=再激活旧版本）"

# 第八幕（可选，需 sim-worker）：gz-sim 无头仿真 → 证据归档对象存储 → 矩阵下钻。
# 前置：docker compose -f deploy/docker-compose.yml --profile sim up -d sim-worker
log "8. gz-sim 仿真（可选：SIM=1 且 sim-worker 运行时执行，约 60s）"
if [ "${SIM:-0}" = "1" ]; then
  # 相对路径：Windows python 打不开 MSYS /tmp 映射路径（跨平台坑，2026-09-15）
  SIM_JSON=".simreq-$$.json"
  "$PY" -c "
import json, yaml, pathlib
ir = yaml.safe_load(pathlib.Path('schemas/examples/simulation/bin-picking.yaml').read_text(encoding='utf-8'))
ir['timeout_s'] = 45
json.dump({'projectId': '$PROJECT', 'simulation': ir, 'requirementKey': 'R003'}, open('$SIM_JSON', 'w', encoding='utf-8'))"
  SIM_JOB=$(curl -s -X POST "$BASE/api/simulations" -H "$AUTH" -H 'Content-Type: application/json' \
    --data-binary "@$SIM_JSON" | jq_get "d['data']['jobKey']")
  echo "  jobKey=$SIM_JOB 轮询中…"
  for i in $(seq 1 30); do
    SIM_OUT=$(curl -s "$BASE/api/simulations/$SIM_JOB" -H "$AUTH")
    SIM_STATUS=$(echo "$SIM_OUT" | jq_get "d['data']['status']")
    [ "$SIM_STATUS" = "SUCCEEDED" ] && break
    [ "$SIM_STATUS" = "FAILED" ] && { echo "  仿真任务失败"; break; }
    sleep 5
  done
  echo "$SIM_OUT" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
print('  状态:', d['status'], ' evidenceId:', d.get('evidenceId'))
m = (d.get('result') or {}).get('metrics') or {}
print('  gz 实测指标:', json.dumps(m, ensure_ascii=False))
rm = (d.get('result') or {}).get('requestedMetrics') or {}
print('  IR 请求指标可得性（不可得不编造）:', json.dumps(rm, ensure_ascii=False))
"
  curl -s "$BASE/api/simulations/requirements/R003" -H "$AUTH" | "$PY" -c "
import sys, json
evs = json.load(sys.stdin)['data']
print(f'  矩阵下钻 R003 仿真证据 {len(evs)} 条；artifacts 归档于',
      [a['key'] for e in evs for a in e['ir'].get('artifacts', [])] or '(无)')
"
  rm -f "$SIM_JSON"
else
  echo "  跳过（SIM=1 且启动 sim-worker 后执行：docker compose --profile sim up -d sim-worker）"
fi

# 第九幕（可选，需 sim-worker）：批量仿真实验（W4）——LHS 采样 → N 次 headless gz
# → 聚合 + SRC 敏感性。n=50 约 1h（单次 ~60s wall），n 可用 SIM_EXP_N 覆盖。
log "9. 批量仿真实验（可选：SIM_EXP=1 且 sim-worker 运行时执行，n=50 约 1h）"
if [ "${SIM_EXP:-0}" = "1" ]; then
  N="${SIM_EXP_N:-50}"
  EXP_JOB=$(post "/api/experiments" "{\"projectId\":\"$PROJECT\",\"systemConfigId\":\"$SYS_RGBD\",\"backend\":\"simulator\",\"n\":$N}" | jq_get "d['data']['jobKey']")
  echo "  jobKey=$EXP_JOB（n=$N，每 run ~60s wall，轮询间隔 60s）…"
  for i in $(seq 1 180); do
    EXP_OUT=$(curl -s "$BASE/api/experiments/$EXP_JOB" -H "$AUTH")
    EXP_STATUS=$(echo "$EXP_OUT" | jq_get "d['data']['status']")
    [ "$EXP_STATUS" = "SUCCEEDED" ] && break
    [ "$EXP_STATUS" = "FAILED" ] && { echo "  实验任务失败"; break; }
    sleep 60
  done
  echo "$EXP_OUT" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
print('  状态:', d['status'], ' evidenceId:', d.get('evidenceId'))
a = (d.get('result') or {}).get('aggregates') or {}
print('  聚合:', json.dumps({k: a.get(k) for k in
      ('samples','completed','failed','pick_success_rate',
       'pick_success_rate_ci95_wilson','wall_per_run_s_mean','wall_total_s')}, ensure_ascii=False))
r = d.get('result') or {}
print('  敏感性 top3 (pick_success):', [(s['name'], s['share']) for s in r.get('sensitivity', [])[:3]])
"
else
  echo "  跳过（SIM_EXP=1 且启动 sim-worker 后执行；n 用 SIM_EXP_N 覆盖，默认 50）"
fi

log "Demo 全部完成 ✓（三幕 + 位姿对照 + Real2Sim 闭环 + 可选仿真/批量实验幕）"
rm -f "$TMPJSON"
