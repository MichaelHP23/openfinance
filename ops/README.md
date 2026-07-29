# Ops scripts

- `backup.sh` — nightly `pg_dump`, gzipped, to `$BACKUP_DIR` (default
  `/var/backups/openfinance`). Fails loudly on a suspiciously small dump. Keeps 30 days.
- `restore-test.sh` — restores the newest dump into a throwaway database, asserts it has
  transactions, drops it. **Run after the first dump and every six months.**

Cron on the instance:

    0 4 * * * /home/ubuntu/openfinance/ops/backup.sh >> /var/log/of-backup.log 2>&1

The offsite copy to OCI Object Storage is step 8 of the runbook in
`docs/superpowers/specs/2026-07-29-oracle-hosting-design.md` §6. A dump that only exists on
the instance does not protect against losing the instance, which is a documented Oracle
free-tier failure mode.
