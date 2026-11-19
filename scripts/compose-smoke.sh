#!/usr/bin/env bash
# 全栈冒烟：healthz → 登录取 JWT → 带令牌访问 P 列表 → 命中一条 passthrough 契约路由。
# 前提：docker compose up -d --build 已就绪。可用 SMOKE_BASE 覆盖后端地址。
set -euo pipefail
BASE="${SMOKE_BASE:-http://127.0.0.1:8787}"
PY="${PYTHON:-python3}"

echo "[1/4] healthz"
curl -fsS "$BASE/healthz" | grep -q '"ok":true'

echo "[2/4] login"
: "${ARK_SMOKE_USER:?请先 export ARK_SMOKE_USER=...（自己播种的账号）}"
: "${ARK_SMOKE_PASSWORD:?请先 export ARK_SMOKE_PASSWORD=...（ARK_SEED_PASSWORD 同值）}"
TOKEN=$(curl -fsS -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ARK_SMOKE_USER\",\"password\":\"$ARK_SMOKE_PASSWORD\"}" \
  | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
[ -n "$TOKEN" ] || { echo "未取得 token"; exit 1; }

echo "[3/4] list applications（受保护，需令牌）"
curl -fsS "$BASE/api/v1/apply/applications?page=1&size=10" \
  -H "Authorization: Bearer $TOKEN" | grep -q '"code":0'

echo "[4/4] passthrough 兜底（契约已定义、M0 未实现的只读路由）"
# F 模块预算列表 GET /budgets 在契约中存在(servers.url=/api/v1)但 M0 未手工实现
# → 应命中 Go passthrough，返回统一包络 code:0
curl -fsS "$BASE/api/v1/budgets?page=1&size=5" \
  -H "Authorization: Bearer $TOKEN" | grep -q '"code":0'

echo "compose smoke OK"
