#!/usr/bin/env bash
# Seafile 对象存储链路 E2E 验证（ADR-0005）。
# 前置：seafileltd/seafile-mc:11.0-latest 已 docker pull 成功
#       （2026-09-14 首次验证时本机网络对 blob CDN 限速/403 未拉成，网络恢复后重试：
#         docker pull seafileltd/seafile-mc:11.0-latest && bash deploy/demo/verify-seafile.sh）
# 步骤：1 启动 Seafile 栈 → 2 建 roboverify 资料库 → 3 启用 SeafDAV → 4 WebDAV 协议断言 → 5 切换说明
# 用法：bash deploy/demo/verify-seafile.sh
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/../.."   # 仓库根

COMPOSE="docker compose -f deploy/docker-compose.yml"
WEB=http://localhost:18080
DAV=http://localhost:18082/seafdav
DAV_USER=admin@roboverify.local
DAV_PASS=roboverify123

PY="$(cd runtime && pwd)/.venv/Scripts/python"
[ -x "$PY" ] || PY="$(cd runtime && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python"
jq_get() { "$PY" -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
expect() { # expect <名称> <期望值> <实际值>
  if [ "$2" = "$3" ]; then echo "  ok   $1 = $3"; else echo "  FAIL $1 期望=$2 实际=$3"; exit 1; fi
}

log "1/5 启动 Seafile 栈（seafile-db + seafile-memcached + seafile）"
$COMPOSE up -d seafile-db seafile-memcached seafile
# 首次初始化需 1-3 分钟，轮询 web 端口（任意 HTTP 响应即算就绪）
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$WEB/" || true)
  [ "$code" != "000" ] && [ -n "$code" ] && break
  sleep 5
done
[ "${code:-000}" != "000" ] || { echo "seafile web 5 分钟未就绪，查看: docker logs roboverify-seafile"; exit 1; }
echo "seafile web ok (http_code=$code)"

log "2/5 创建 roboverify 资料库（幂等）"
API_TOKEN=$(curl -s -X POST "$WEB/api2/auth-token/" -d "username=$DAV_USER&password=$DAV_PASS" | jq_get "d['token']")
[ "$API_TOKEN" != "None" ] && [ -n "$API_TOKEN" ] || { echo "获取 seafile api token 失败"; exit 1; }
REPOS=$(curl -s -H "Authorization: Token $API_TOKEN" "$WEB/api2/repos/")
LIB_ID=$(echo "$REPOS" | jq_get "next((r['id'] for r in d if r['name']=='roboverify'), 'None')" || true)
if [ "$LIB_ID" = "None" ] || [ -z "$LIB_ID" ]; then
  LIB_ID=$(curl -s -X POST -H "Authorization: Token $API_TOKEN" \
    -d "name=roboverify&desc=RoboVerify object storage (ADR-0005)" "$WEB/api2/repos/" | jq_get "d['repo_id']")
  echo "已创建 roboverify 库: $LIB_ID"
else
  echo "roboverify 库已存在: $LIB_ID"
fi

log "3/5 启用 SeafDAV（写 seafdav.conf 并重启 seafile）"
docker exec roboverify-seafile bash -c \
  'printf "[WEBDAV]\nenabled = true\nport = 8080\nfastcgi = false\nshare_name = /seafdav\n" > /seafile/conf/seafdav.conf'
$COMPOSE restart seafile
for i in $(seq 1 36); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -u "$DAV_USER:$DAV_PASS" -X PROPFIND -H 'Depth: 1' "$DAV/" || true)
  [ "$code" = "207" ] && break
  sleep 5
done
expect "SeafDAV PROPFIND" "207" "${code:-000}"

log "4/5 WebDAV 协议断言（MKCOL/PUT/GET/HEAD/DELETE，模拟 ObjectStore 语义）"
OBJFILE=$(mktemp)
echo "roboverify e2e $(date -Iseconds)" > "$OBJFILE"
# put 前递归建父目录（对应 SeafileWebDavObjectStore.mkdirs）
c1=$(curl -s -o /dev/null -w '%{http_code}' -u "$DAV_USER:$DAV_PASS" -X MKCOL "$DAV/roboverify/e2e/")
[ "$c1" = "201" ] || [ "$c1" = "405" ] || { echo "  FAIL MKCOL=$c1"; exit 1; }
echo "  ok   MKCOL 父目录 (201/405)"
c2=$(curl -s -o /dev/null -w '%{http_code}' -u "$DAV_USER:$DAV_PASS" -T "$OBJFILE" "$DAV/roboverify/e2e/obj.txt")
expect "PUT" "201" "$c2"
GET_BODY=$(curl -s -u "$DAV_USER:$DAV_PASS" "$DAV/roboverify/e2e/obj.txt")
diff -q <(cat "$OBJFILE") <(printf '%s\n' "$GET_BODY") > /dev/null && echo "  ok   GET 内容一致" || { echo "  FAIL GET 内容不一致: $GET_BODY"; exit 1; }
c3=$(curl -s -o /dev/null -w '%{http_code}' -u "$DAV_USER:$DAV_PASS" -I "$DAV/roboverify/e2e/obj.txt")
expect "HEAD(exists)" "200" "$c3"
c4=$(curl -s -o /dev/null -w '%{http_code}' -u "$DAV_USER:$DAV_PASS" -X DELETE "$DAV/roboverify/e2e/obj.txt")
expect "DELETE" "204" "$c4"
c5=$(curl -s -o /dev/null -w '%{http_code}' -u "$DAV_USER:$DAV_PASS" -I "$DAV/roboverify/e2e/obj.txt")
expect "HEAD(deleted)" "404" "$c5"
rm -f "$OBJFILE"

log "5/5 backend 切换 Seafile 存储（可选，验证后切回）"
cat <<'EOF'
容器网络内后端访问 SeafDAV 地址为 http://seafile:8080/seafdav。切换方式：
  1) 在 deploy/.env（或环境变量）写入：
       ROBOVERIFY_STORAGE_TYPE=seafile-webdav
       ROBOVERIFY_SEAFILE_URL=http://seafile:8080/seafdav
       ROBOVERIFY_SEAFILE_USER=admin@roboverify.local
       ROBOVERIFY_SEAFILE_PASSWORD=roboverify123
  2) docker compose -f deploy/docker-compose.yml up -d --force-recreate --no-deps backend
  3) 触发一次产生证据的操作（如运行验证或下载报告），然后到 http://localhost:18080
     的 roboverify 库中确认 /roboverify/... 路径对象出现
  4) 验证完切回：删除 .env 中上述行后再次 --force-recreate backend
EOF
echo "Seafile WebDAV 链路验证完成 ✓"
