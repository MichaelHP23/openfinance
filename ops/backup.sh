#!/bin/sh
# Nightly logical dump. Custom format (-Fc) so pg_restore can be selective.
# Install: 0 4 * * * /path/to/repo/ops/backup.sh >> /var/log/of-backup.log 2>&1
set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/openfinance}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%F)"

mkdir -p "$BACKUP_DIR"

cd "$REPO_DIR"
docker compose exec -T postgres pg_dump -U openfinance -Fc openfinance \
  | gzip > "$BACKUP_DIR/of-$STAMP.dump.gz"

# A dump that is a fraction of the expected size is a failed dump that exited 0.
SIZE="$(wc -c < "$BACKUP_DIR/of-$STAMP.dump.gz")"
if [ "$SIZE" -lt 1000 ]; then
  echo "backup FAILED: of-$STAMP.dump.gz is only ${SIZE} bytes" >&2
  exit 1
fi

# ponytail: retention by mtime, not a manifest. 30 days local; the offsite copy in
# object storage keeps 90 and is the one that survives losing the instance.
find "$BACKUP_DIR" -name 'of-*.dump.gz' -mtime +30 -delete

echo "backup ok: of-$STAMP.dump.gz (${SIZE} bytes)"
