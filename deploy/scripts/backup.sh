#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 蒸馏平台 · 一致性备份
#
# SQLite 的 WAL 模式下，运行期间直接复制 app.db 会得到损坏或不完整的副本。
# 这里使用 VACUUM INTO（SQLite 官方推荐的逻辑备份方式），它在一个读事务里
# 生成一致的快照，不需要停机。
#
# 用法：./deploy/scripts/backup.sh [输出目录]
# 环境：DATA_DIR（默认 /data）、EXPORT_DIR（默认 /exports）
# ---------------------------------------------------------------------------
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data}"
EXPORT_DIR="${EXPORT_DIR:-/exports}"
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET="${1:-/backups}/distill-$STAMP"

mkdir -p "$TARGET"

DB="$DATA_DIR/app.db"
if [ -f "$DB" ]; then
  python - "$DB" "$TARGET/app.db" <<'PY'
import sqlite3, sys, pathlib
src, dst = sys.argv[1], sys.argv[2]
# VACUUM INTO 生成的是已经合并 WAL 的完整数据库，且比文件复制更快更安全。
con = sqlite3.connect(src)
try:
    con.execute("VACUUM INTO ?", (dst,))
finally:
    con.close()
pathlib.Path(dst).exists() or sys.exit("backup failed: no output file")
PY
  echo "database -> $TARGET/app.db"
else
  echo "warning: $DB not found, skipping database" >&2
fi

# 原始资料与导出包是数据库之外的另一半状态，必须一起备份，
# 否则恢复后会出现"有记录无文件"的悬挂引用。
for pair in "sources:$DATA_DIR/sources" "skills:$DATA_DIR/skills" "artifacts:$DATA_DIR/artifacts" "exports:$EXPORT_DIR"; do
  name="${pair%%:*}"; path="${pair#*:}"
  if [ -d "$path" ]; then
    cp -a "$path" "$TARGET/$name"
    echo "$name -> $TARGET/$name"
  fi
done

# 密钥文件单独复制：正文不加密，但权限必须收紧。
if [ -f "$DATA_DIR/.secret.key" ]; then
  cp -a "$DATA_DIR/.secret.key" "$TARGET/.secret.key"
  chmod 600 "$TARGET/.secret.key"
  echo "secret key -> $TARGET/.secret.key (0600)"
fi

cat > "$TARGET/MANIFEST.txt" <<EOF
distill-platform backup
created_at: $(date -Iseconds)
host: $(hostname)
source_data_dir: $DATA_DIR
source_export_dir: $EXPORT_DIR
database: $( [ -f "$TARGET/app.db" ] && echo present || echo absent )
notes:
  - .secret.key 是解密已存 API Key 的唯一凭据，丢失后需重新录入所有 Provider。
  - 恢复顺序：先还原数据目录，再启动 migrate 服务，最后启动 api/worker。
EOF

echo "backup complete: $TARGET"