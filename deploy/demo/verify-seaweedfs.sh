#!/usr/bin/env bash
# SeaweedFS S3 对象存储链路 E2E 验证（ADR-0005）。
# 前置：chrislusf/seaweedfs 镜像已 docker pull 成功（镜像 ~40MB，较小）。
# 断言客户端：python 标准库独立实现 SigV4（与后端 S3Signer 交叉验证，两份独立实现互通即协议级验证）。
# 用法：bash deploy/demo/verify-seaweedfs.sh
set -euo pipefail
export PYTHONUTF8=1
cd "$(dirname "$0")/../.."   # 仓库根

COMPOSE="docker compose -f deploy/docker-compose.yml"
S3=http://localhost:18333
STATUS=http://localhost:19333
AK=roboverify
SK=roboverify-secret
BUCKET=roboverify

PY="$(cd runtime && pwd)/.venv/Scripts/python"
[ -x "$PY" ] || PY="$(cd runtime && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python"
log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

log "1/3 启动 SeaweedFS（单进程 server：master+volume+filer+S3 网关）"
$COMPOSE up -d seaweedfs
for i in $(seq 1 36); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$STATUS/cluster/status" || true)
  [ "$code" = "200" ] && break
  sleep 5
done
[ "${code:-000}" = "200" ] || { echo "seaweedfs 状态页未就绪: docker logs roboverify-seaweedfs"; exit 1; }
echo "seaweedfs ok (cluster/status=200)"

log "2/3 S3 协议断言（SigV4：CreateBucket/PUT/GET/HEAD/DELETE）"
"$PY" - "$S3" "$AK" "$SK" "$BUCKET" <<'EOF'
import datetime, hashlib, hmac, sys, urllib.request, urllib.error, urllib.parse

endpoint, ak, sk, bucket = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
EMPTY = hashlib.sha256(b"").hexdigest()

def s3(method, path, body=b""):
    # path 需先按 SigV4 规则编码（非保留字符 + '/' 保留），签名与请求用同一编码串
    import urllib.parse as _p
    path = _p.quote(path, safe="/-._~")
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "host": urllib.parse.urlparse(endpoint).netloc,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(headers.items()))
    signed = ";".join(sorted(headers))
    cr = f"{method}\n{path}\n\n{canonical_headers}\n{signed}\n{payload_hash}"
    scope = f"{date}/us-east-1/s3/aws4_request"
    sts = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(cr.encode()).hexdigest()}"
    key = ("AWS4" + sk).encode()
    for part in (date, "us-east-1", "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(key, sts.encode(), hashlib.sha256).hexdigest()
    auth = (f"AWS4-HMAC-SHA256 Credential={ak}/{scope},"
            f"SignedHeaders={signed},Signature={sig}")
    req = urllib.request.Request(endpoint + path, data=body if body else None, method=method)
    req.add_header("Authorization", auth)
    req.add_header("x-amz-date", amz_date)
    req.add_header("x-amz-content-sha256", payload_hash)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def expect(name, want, got):
    if want != got:
        print(f"  FAIL {name} 期望={want} 实际={got}")
        sys.exit(1)
    print(f"  ok   {name} = {got}")

body = f"roboverify e2e {datetime.datetime.now().isoformat()}".encode()
st, _ = s3("PUT", f"/{bucket}")                       # CreateBucket（幂等：200 首建 / 409 已存在）
if st not in (200, 409):
    print(f"  FAIL CreateBucket 期望=200/409 实际={st}")
    sys.exit(1)
print(f"  ok   CreateBucket = {st}")
st, _ = s3("PUT", f"/{bucket}/e2e-test/obj.txt", body)
expect("PUT", 200, st)
st, got = s3("GET", f"/{bucket}/e2e-test/obj.txt")
expect("GET", 200, st)
assert got == body, f"GET 内容不一致: {got!r}"
print("  ok   GET 内容一致")
st, _ = s3("HEAD", f"/{bucket}/e2e-test/obj.txt")
expect("HEAD(exists)", 200, st)
st, _ = s3("DELETE", f"/{bucket}/e2e-test/obj.txt")
expect("DELETE", 204, st)
st, _ = s3("HEAD", f"/{bucket}/e2e-test/obj.txt")
expect("HEAD(deleted)", 404, st)
st, _ = s3("DELETE", f"/{bucket}/e2e-test/obj.txt")
expect("DELETE(幂等)", 204, st)
st, _ = s3("PUT", f"/{bucket}/e2e-test/中文 名.txt", "unicode key".encode())
expect("PUT(unicode key)", 200, st)
st, got = s3("GET", f"/{bucket}/e2e-test/中文 名.txt")
expect("GET(unicode key)", 200, st)
assert got == "unicode key".encode()
print("  ok   unicode key 内容一致")
print("S3 协议断言全部通过 ✓")
EOF

log "3/3 backend 切换 SeaweedFS 存储（可选，验证后切回）"
cat <<'EOF'
backend 容器内访问 SeaweedFS：http://seaweedfs:8333。切换方式：
  1) 在 deploy/.env（或环境变量）写入：
       ROBOVERIFY_STORAGE_TYPE=seaweed-s3
       ROBOVERIFY_S3_ENDPOINT=http://seaweedfs:8333
       ROBOVERIFY_S3_ACCESS_KEY=roboverify
       ROBOVERIFY_S3_SECRET_KEY=roboverify-secret
       ROBOVERIFY_S3_BUCKET=roboverify
  2) docker compose -f deploy/docker-compose.yml up -d --force-recreate --no-deps backend
  3) 触发产生大对象的操作（M2 仿真日志/报告导出）后，用上面 python 断言片段或
     s3浏览器检查 s3://roboverify/... 路径对象出现
  4) 验证完切回：删除 .env 中上述行后再次 --force-recreate backend
EOF
echo "SeaweedFS 链路验证完成 ✓"
