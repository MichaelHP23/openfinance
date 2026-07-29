#!/bin/sh
# Restores the newest dump into a throwaway database and checks it has data.
# A backup that has never been restored is a hypothesis. Run after the first dump,
# then every six months.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/openfinance}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRATCH="restore_test_$(date +%s)"

NEWEST="$(ls -1t "$BACKUP_DIR"/of-*.dump.gz 2>/dev/null | head -1)"
if [ -z "$NEWEST" ]; then
  echo "no dumps found in $BACKUP_DIR" >&2
  exit 1
fi
echo "restoring $NEWEST into $SCRATCH"

cd "$REPO_DIR"
docker compose exec -T postgres createdb -U openfinance "$SCRATCH"

# shellcheck disable=SC2002
gunzip -c "$NEWEST" | docker compose exec -T postgres pg_restore -U openfinance -d "$SCRATCH"

COUNT="$(docker compose exec -T postgres psql -U openfinance -d "$SCRATCH" -tAc \
  'select count(*) from transactions')"
echo "restored transactions: $COUNT"

docker compose exec -T postgres dropdb -U openfinance "$SCRATCH"

if [ "$COUNT" -lt 1 ]; then
  echo "RESTORE TEST FAILED: no transactions in the restored database" >&2
  exit 1
fi
echo "restore test ok"
