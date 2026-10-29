#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 蒸馏平台 · 从备份恢复
#
# 用法：./deploy/scripts/restore.sh /backups/distill-20261030-120000
#
# 该脚本会覆盖现有数据，因此要求显式确认。先停止 api/worker 再执行。
# ---------------------------------------------------------------------------
set -euo pipefail

SRC="${1:-}"
DATA_DIR="${DATA_DIR:-/data}"
EXPORT_DIR="${EXPORT_DIR:-/exports}"

if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
  echo "用法：$0 <备份目录>" >&2
  exit 1
fi

if [ "${DISTILL_FORCE:-}" != "yes" ]; then
  echo "即将用 $SRC 覆盖 $DATA_DIR 与 $EXPORT_DIR。"
  echo "请先停止 api 与 worker 服务。"
  read -r -p "确认继续？输入 yes：" reply
  [ "$reply" = "yes" ] || { echo "已取消"; exit 1; }
fi

mkdir -p "$DATA_DIR" "$EXPORT_DIR"

# 恢复前先给当前状态留一个兜底快照，避免恢复错版本后无法回退。
if [ -f "$DATA_DIR/app.db" ]; then
  SAFETY="$DATA_DIR.pre-restore-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$SAFETY"
  cp -a "$DATA_DIR/app.db" "$SAFETY/app.db" || true
  echo "当前数据库已备份到 $SAFETY"
fi

if [ -f "$SRC/app.db" ]; then
  rm -f "$DATA_DIR/app.db" "$DATA_DIR/app.db-wal" "$DATA_DIR/app.db-shm"
  cp -a "$SRC/app.db" "$DATA_DIR/app.db"
  echo "数据库已恢复"
fi

for name in sources skills artifacts; do
  if [ -d "$SRC/$name" ]; then
    rm -rf "${DATA_DIR:?}/$name"
    cp -a "$SRC/$name" "$DATA_DIR/$name"
    echo "$name 已恢复"
  fi
done

if [ -d "$SRC/exports" ]; then
  rm -rf "${EXPORT_DIR:?}/"*
  cp -a "$SRC/exports/." "$EXPORT_DIR/"
  echo "exports 已恢复"
fi

if [ -f "$SRC/.secret.key" ]; then
  cp -a "$SRC/.secret.key" "$DATA_DIR/.secret.key"
  chmod 600 "$DATA_DIR/.secret.key"
  echo "密钥已恢复（若不还原此文件，已保存的 API Key 将无法解密）"
fi

# SQLite 的 WAL/SHM 是旧状态的残留，必须清掉，否则会把旧页合并回来。
rm -f "$DATA_DIR/app.db-wal" "$DATA_DIR/app.db-shm"

echo
echo "恢复完成。下一步："
echo "  alembic upgrade head   # 让 schema 追平当前版本"
echo "  启动 api 与 worker"