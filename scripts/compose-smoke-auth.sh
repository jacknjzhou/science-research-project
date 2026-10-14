#!/usr/bin/env bash
# bcrypt 上线后的全栈鉴权冒烟：真实种子账号 → /auth/me 能力 → 管理员列用户 → 越权 403。
# 前提：docker compose up -d --build（backend 为 Go 镜像，已跑 000001+000002 迁移种子）。
# 覆盖地址用 SMOKE_BASE；本机无 Docker 时仅 CI/Docker 主机执行。
set -euo pipefail
BASE="${SMOKE_BASE:-http://127.0.0.1:8787}"
PY="${PYTHON:-python3}"

login() { # $1=user $2=pass -> echo token
  curl -fsS -X POST "$BASE/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" \
    | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])'
}

echo "[1/5] healthz"
curl -fsS "$BASE/healthz" | grep -q '"ok":true'

echo "[2/5] 真实 bcrypt 登录(admin/Admin@123456)"
ADMIN_TOKEN=$(login admin 'Admin@123456')
[ -n "$ADMIN_TOKEN" ] || { echo "admin 未取得 token"; exit 1; }

echo "[3/5] /auth/me：角色含 R-ADMIN、caps 非空"
curl -fsS "$BASE/api/v1/auth/me" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
assert d["code"]==0, d
me=d["data"]
assert "R-ADMIN" in me["roles"], me["roles"]
assert len(me["caps"])>0, "caps 不应为空"
print("caps:", me["caps"][:3], "...")'

echo "[4/5] 管理员列用户：命中种子 admin（证明走真 handler 非 passthrough）"
curl -fsS "$BASE/api/v1/admin/users?page=1&size=50" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
assert d["code"]==0, d
names=[u["username"] for u in d["data"]["list"]]
assert "admin" in names, names
assert all("password_hash" not in u for u in d["data"]["list"]), "泄漏口令"
print("users:", names)'

echo "[5/5] 越权：R-STAFF 访问 admin 列表应 HTTP 403"
STAFF_TOKEN=$(login staff 'Staff@123456')
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/admin/users" -H "Authorization: Bearer $STAFF_TOKEN")
[ "$code" = "403" ] || { echo "期望 403，实得 $code"; exit 1; }

echo "compose auth smoke OK"
