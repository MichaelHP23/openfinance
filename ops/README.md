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

## Desktop launcher (Windows)

`launcher/build.cmd` compiles `launcher/OpenFinance.exe` with the C# compiler that ships
with Windows. Double-click the exe (or a shortcut to it) to open the app in its own
window.

It is a launcher, not a standalone program: Docker Desktop and this repository must be on
the machine. If the API already answers on `localhost:8000` it only opens the window.
Otherwise it runs `docker compose up -d` in the nearest folder above the exe that holds
`docker-compose.yml`, waits up to 90 seconds for `/health`, then opens
`http://localhost:5173` in an Edge app window (default browser if Edge is missing).

If your stack was started from a different folder — a git worktree, say — pass that
folder as the argument (a shortcut's Target can carry it):

    OpenFinance.exe "C:\path\to\folder-with-docker-compose"

Compose names its project after the folder, so starting from the wrong one brings up a
second, empty database instead of yours.
