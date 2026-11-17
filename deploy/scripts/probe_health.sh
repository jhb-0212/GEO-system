#!/usr/bin/env bash
# 生产定时探活：/health、/health/db、公开 FAQ 接口三处。
#
# 用法（由 cron / systemd timer / Windows 计划任务调用）：
#   GEO_BASE_URL=https://geo.example.com GEO_PROBE_PROJECT_CODE=gz-base ./probe_health.sh
#
# 任一检查失败即非 0 退出；配置了 GEO_ALERT_WEBHOOK 时额外推送一条告警
# （兼容飞书/钉钉群机器人的 text 消息格式，与业务任务告警可复用同一机器人）。
set -uo pipefail

BASE="${GEO_BASE_URL:-http://127.0.0.1:8080}"
PROJECT="${GEO_PROBE_PROJECT_CODE:-gz-base}"
WEBHOOK="${GEO_ALERT_WEBHOOK:-}"
TIMEOUT="${GEO_PROBE_TIMEOUT:-10}"
BODY_FILE="${TMPDIR:-/tmp}/geo-probe-health.json"

fail() {
  local msg="$1"
  echo "[probe] FAIL: $msg" >&2
  if [ -n "$WEBHOOK" ]; then
    curl -sS -m "$TIMEOUT" -H 'Content-Type: application/json' \
      -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[GEO 探活失败] ${msg}\"}}" \
      "$WEBHOOK" >/dev/null 2>&1 || true
  fi
  exit 1
}

code=$(curl -sS -m "$TIMEOUT" -o "$BODY_FILE" -w '%{http_code}' "$BASE/health") \
  || fail "无法连接 ${BASE}/health"
[ "$code" = "200" ] || fail "/health 返回 ${code}"
grep -q '"status":"ok"' "$BODY_FILE" || fail "/health 响应体不是 ok"

code=$(curl -sS -m "$TIMEOUT" -o /dev/null -w '%{http_code}' "$BASE/health/db") \
  || fail "无法连接 ${BASE}/health/db"
[ "$code" = "200" ] || fail "/health/db 返回 ${code}"

code=$(curl -sS -m "$TIMEOUT" -o /dev/null -w '%{http_code}' \
  "$BASE/api/v1/public/projects/${PROJECT}/faqs") \
  || fail "公开 FAQ 接口请求失败"
[ "$code" = "200" ] || fail "公开 FAQ 接口返回 ${code}"

echo "[probe] OK ${BASE}"
