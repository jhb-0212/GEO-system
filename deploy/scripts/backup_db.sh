#!/usr/bin/env bash
# 生产数据库备份（Linux 宿主机）：自定义格式 pg_dump，落盘后做一次可读性校验。
#
# 用法：
#   APP_ENV=prod ./deploy/scripts/backup_db.sh
#   ./deploy/scripts/backup_db.sh geo-prod-postgres-1
#   GEO_BACKUP_DIR=/data/backups ./deploy/scripts/backup_db.sh
#
# 环境变量：
#   APP_ENV               prod 时自动解析 geo-prod-postgres-1；dev/local/test/空 用 geo-postgres
#   GEO_PG_CONTAINER      显式指定容器名，优先于 APP_ENV 推断
#   GEO_DB_NAME           默认 geo
#   GEO_DB_USER           默认 geo
#   GEO_BACKUP_DIR        默认 deploy/backups
#   GEO_BACKUP_KEEP       本地保留份数，默认 7
#   BACKUP_ALERT_WEBHOOK  失败时 POST JSON；未配置只写日志并以非零退出
#
# 说明：脚本只读取容器内数据库，不映射 5432；备份文件落在宿主机目录，需另行同步到异地。

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

CONTAINER="${1:-${GEO_PG_CONTAINER:-}}"
DB="${GEO_DB_NAME:-geo}"
DB_USER="${GEO_DB_USER:-geo}"
OUT_DIR="${GEO_BACKUP_DIR:-$REPO_ROOT/deploy/backups}"
KEEP="${GEO_BACKUP_KEEP:-7}"
ALERT_WEBHOOK="${BACKUP_ALERT_WEBHOOK:-}"
KEEP="${KEEP:-7}"

if ! [[ "$KEEP" =~ ^[1-9][0-9]*$ ]]; then
  echo "GEO_BACKUP_KEEP 必须是正整数，当前为：$KEEP" >&2
  exit 2
fi

json_escape() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()), end="")' <<< "$1" | sed 's/^"//; s/"$//'
  else
    printf '%s' "$1" | sed ':a;N;$!ba;s/\\/\\\\/g; s/"/\\"/g; s/\n/\\n/g'
  fi
}

send_alert() {
  local message="$1"
  local host time payload escaped
  host="$(hostname 2>/dev/null || echo unknown)"
  time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ -z "$ALERT_WEBHOOK" ]; then
    echo "告警（未配置 webhook，仅记录）：$message" >&2
    return 0
  fi
  escaped="$(json_escape "$message")"
  payload="$(printf '{"event":"backup_failed","host":"%s","app_env":"%s","container":"%s","database":"%s","message":"%s","time":"%s"}' \
    "$(json_escape "$host")" "$(json_escape "${APP_ENV:-unset}")" "$(json_escape "$CONTAINER")" \
    "$(json_escape "$DB")" "$escaped" "$time")"
  if curl -sS -m 10 -H 'Content-Type: application/json' -d "$payload" "$ALERT_WEBHOOK" >/dev/null; then
    echo "告警已推送：$ALERT_WEBHOOK" >&2
  else
    echo "告警推送失败（不影响退出码）：$ALERT_WEBHOOK" >&2
  fi
}

fail() {
  send_alert "$1"
  echo "[backup] FAIL: $1" >&2
  exit 1
}

TMP_CONTAINER=""
cleanup() {
  if [ -n "$TMP_CONTAINER" ] && [ -n "$CONTAINER" ]; then
    docker exec "$CONTAINER" rm -f "$TMP_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  fail "未找到 docker 命令"
fi

if [ -z "$CONTAINER" ]; then
  case "${APP_ENV:-}" in
    prod|production) CONTAINER="geo-prod-postgres-1" ;;
    ""|dev|local|test) CONTAINER="geo-postgres" ;;
    *) fail "APP_ENV=${APP_ENV} 无法确定数据库容器；请显式传容器名或设置 GEO_PG_CONTAINER" ;;
  esac
fi

running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [ "$running" != "true" ]; then
  names="$(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
  fail "容器 $CONTAINER 不存在或未运行。当前运行中的容器：${names:-无}"
fi

mkdir -p -- "$OUT_DIR" || fail "无法创建备份目录 $OUT_DIR"
if [ ! -w "$OUT_DIR" ]; then
  fail "备份目录不可写：$OUT_DIR"
fi

stamp="$(date +%Y%m%d-%H%M%S)"
target="$OUT_DIR/geo-$stamp.dump"
TMP_CONTAINER="/tmp/geo-backup-$$.dump"

echo "[backup] 数据库 $DB -> $target（容器 $CONTAINER，APP_ENV=${APP_ENV:-unset}）"
if ! docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB" -Fc -f "$TMP_CONTAINER"; then
  fail "pg_dump 失败"
fi

if ! docker cp "$CONTAINER:$TMP_CONTAINER" "$target"; then
  fail "备份文件导出失败"
fi

if [ ! -s "$target" ]; then
  fail "备份文件为空：$target"
fi

if ! docker exec "$CONTAINER" pg_restore --list "$TMP_CONTAINER" >/dev/null; then
  fail "备份文件校验失败（pg_restore --list）"
fi

size="$(du -h "$target" | awk '{print $1}')"
echo "[backup] 完成：$target（$size），已通过 pg_restore --list 校验"

# 保留策略：只清理由本脚本产生的 geo-*.dump，按修改时间保留最近 KEEP 份。
count=0
while IFS= read -r old; do
  count=$((count + 1))
  if [ "$count" -gt "$KEEP" ]; then
    rm -f -- "$old" && echo "[backup] 已清理过期备份 $old"
  fi
done < <(find "$OUT_DIR" -maxdepth 1 -type f -name 'geo-*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -nr | cut -d' ' -f2-)

exit 0
