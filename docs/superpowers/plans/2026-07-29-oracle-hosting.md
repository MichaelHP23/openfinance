# Oracle Always Free Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move OpenFinance off the desktop onto an always-on Oracle Always Free ARM instance reachable only over Tailscale, with a static frontend build and backups that have been restore-tested.

**Architecture:** Phase A is repo work — every change is made and tested on the desktop before any cloud account exists. Phase B is a manual runbook the human executes on the instance; agents cannot provision cloud infrastructure, click through the OCI console, or authenticate Tailscale. Phase A must be complete and committed before Phase B step 4.

**Tech Stack:** Docker Compose, FastAPI, Postgres 17, nginx, Vite/React, Tailscale, Oracle Cloud Infrastructure (Ampere A1, arm64).

**Spec:** `docs/superpowers/specs/2026-07-29-oracle-hosting-design.md`, which supersedes parts of `2026-07-26-cloud-hosting-design.md`. Read both.

## Global Constraints

- Target host is **arm64** (Ampere A1). Every image must resolve an arm64 manifest. Do not add a dependency that ships x86-only wheels.
- The instance is **1 OCPU / 6 GB**, deliberately half the free allowance. Do not "use up" the free tier — §2.1 of the spec explains that memory *utilisation* is what prevents reclamation.
- **Redis stays.** The older spec's advice to delete it is inverted here (spec §2.3).
- `LOCAL_MODE=true` and `ENVIRONMENT=development` stay exactly as they are. There is no authentication; the tailnet is the entire security boundary.
- The frontend is served on **port 5173**, not 80, so every CORS conclusion in the 26 July spec carries over unchanged.
- Never commit `.env` or `backend/.env`. Both are gitignored; `.env.example` files are the committed form.
- Backend tests run with `backend/.venv/Scripts/python.exe -m pytest` on this Windows desktop and require Docker running (testcontainers).

---

## Phase A — Repo changes (agent-executable)

### Task 1: Fail-closed port binding

Today `docker-compose.yml` publishes on `0.0.0.0`. On a box with a public IP that is an unauthenticated finance API on the open internet, and the spec calls it the single most likely way to silently get this wrong. The fix is not just to bind to the tailnet address but to make an unset address **refuse to start** rather than fall back to publishing everywhere.

**Files:**
- Modify: `docker-compose.yml`
- Create: `.env.example` (repo root)
- Create: `.env` (repo root, gitignored, local only)

**Interfaces:**
- Consumes: nothing.
- Produces: `TS_IP` environment variable contract, consumed by `docker-compose.yml` only. Compose fails with a named error when it is unset.

- [ ] **Step 1: Write the failing check**

Create `.env.example` at the repo root:

```
# Address the stack publishes on. On the Oracle instance this MUST be the Tailscale
# address (100.x.y.z) — see docs/superpowers/specs/2026-07-29-oracle-hosting-design.md §4.
# On a desktop, 127.0.0.1 for loopback-only, or your tailnet address to reach it from a phone.
TS_IP=127.0.0.1
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `docker compose config -q`
Expected: FAIL — `TS_IP` is not yet referenced, so this currently passes and publishes on `0.0.0.0`. Confirm the current bad state instead:

Run: `docker compose config --format json | python -c "import json,sys; print(json.load(sys.stdin)['services']['api']['ports'])"`
Expected: shows no `host_ip`, or `0.0.0.0` — the state this task removes.

- [ ] **Step 3: Make the change**

In `docker-compose.yml`, apply all four edits:

```yaml
  postgres:
    # Loopback only. The spec says delete this, which is right for the instance but breaks
    # running the API on a host against the compose database (backend/.env.example points
    # DATABASE_URL at localhost). 127.0.0.1 is never reachable from the public IP, so it
    # meets the same goal on the VM while keeping the dev loop.
    ports: ["127.0.0.1:5433:5432"]
    command: postgres -c shared_buffers=768MB
```

```yaml
  redis:
    ports: ["127.0.0.1:6379:6379"]
```

```yaml
  api:
    ports: ["${TS_IP:?TS_IP must be set — see .env.example}:8000:8000"]
```

```yaml
  web:
    ports: ["${TS_IP:?TS_IP must be set — see .env.example}:5173:5173"]
```

Add a comment above the `api` ports line:

```yaml
    # ponytail: ${VAR:?msg} makes compose refuse to start when TS_IP is unset, instead of
    # interpolating empty and publishing on 0.0.0.0. Fail closed — on a host with a public
    # IP the quiet fallback is an unauthenticated finance API on the internet.
```

Create `.env` at the repo root with `TS_IP=127.0.0.1` so the local stack still starts.

- [ ] **Step 4: Verify both directions**

Run: `docker compose config -q`
Expected: PASS (`.env` supplies `TS_IP`).

Run: `TS_IP= docker compose config -q`
Expected: FAIL with `TS_IP must be set — see .env.example`.

Run: `docker compose config --format json | python -c "import json,sys; d=json.load(sys.stdin)['services']; [print(s, [p['host_ip'] for p in d[s].get('ports', [])]) for s in ('api','web','postgres','redis')]"`
Expected: every listed address is `127.0.0.1` — `api` and `web` because `.env` sets `TS_IP=127.0.0.1`, `postgres` and `redis` because they are hardcoded to loopback. No `0.0.0.0` anywhere.

- [ ] **Step 5: Confirm the stack still runs**

Run: `docker compose up -d && curl -s http://localhost:8000/health`
Expected: a healthy JSON response.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "fix: refuse to start rather than publish the API on every interface"
```

---

### Task 2: Static frontend build

`frontend/Dockerfile` runs the Vite dev server and carries a note saying to replace it when there is somewhere to deploy. There is now. This is also what makes a 6 GB instance comfortable — the dev server's filesystem polling costs 200-400 MB RSS and steady CPU forever.

**Files:**
- Modify: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Modify: `docker-compose.yml` (remove the `web` `volumes:` block)

**Interfaces:**
- Consumes: `TS_IP` from Task 1.
- Produces: a `web` service serving static files on port 5173 with SPA history fallback. `frontend/src/api/client.ts` is unchanged and still infers the API base from `window.location` at runtime, so nothing about API resolution moves.

- [ ] **Step 1: Write the failing test**

Create `frontend/nginx.conf`:

```nginx
server {
    listen 5173;
    root /usr/share/nginx/html;
    index index.html;

    # BrowserRouter owns the paths. Without this fallback, opening /accounts directly —
    # or reloading it — returns 404 from nginx instead of the app.
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `docker compose build web && docker compose up -d web && curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/accounts`
Expected: this still runs the dev server (Dockerfile unchanged), so the test is not yet meaningful. Record the current image behaviour, then proceed.

- [ ] **Step 3: Replace the Dockerfile**

Replace the entire contents of `frontend/Dockerfile`:

```dockerfile
# Build stage — produces dist/, then is discarded.
FROM node:24-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Serve stage. nginx on 5173, not 80: keeping the port identical means every CORS
# conclusion in the hosting spec still holds and the home-screen bookmark doesn't move.
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173
```

In `docker-compose.yml`, delete the `web` service's `volumes:` block entirely (both the `./frontend:/app` bind and the `/app/node_modules` anonymous volume). They exist to live-mount source for the dev server and would shadow the built image. Replace the surrounding comment with:

```yaml
    # Static build served by nginx. The frontend dev loop is `npm run dev` in ./frontend,
    # not this container — it serves the built bundle, so edits need a rebuild.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose build web && docker compose up -d web`
Expected: build succeeds.

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173/`
Expected: `200`

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173/accounts`
Expected: `200` — this is the SPA fallback. A `404` means `nginx.conf` was not copied to the right path.

Run: `curl -s http://localhost:5173/ | grep -c "<div id=\"root\">"`
Expected: `1`

- [ ] **Step 5: Confirm the unit tests and typecheck still pass**

Run: `cd frontend && npx vitest run --reporter=dot && npx tsc --noEmit`
Expected: 50 passed, tsc exits 0. (`npm run build` runs `tsc -b`, so a type error would already have failed step 4.)

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf docker-compose.yml
git commit -m "feat: serve a built frontend instead of the dev server"
```

---

### Task 3: Make the secret-key guard unconditional

`backend/app/main.py:20` only fires when `ENVIRONMENT != "development"`. Because `LOCAL_MODE=true` pins `ENVIRONMENT=development`, the guard is **inert in exactly the configuration being deployed**. A fresh `git clone` on the instance has no `backend/.env`, so `app_secret_key` silently falls back to the constant published in this repo — and that key derives the KEK for provider credentials, making anything encrypted under it effectively plaintext.

**Files:**
- Modify: `backend/app/main.py:20`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_secret_key_guard.py`

**Interfaces:**
- Consumes: `DEFAULT_SECRET_KEY` and `settings` from `app.core.config` (existing).
- Produces: an import-time `RuntimeError` from `app.main` whenever `APP_SECRET_KEY` is the published default, in every environment.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_secret_key_guard.py`:

```python
"""The guard this covers protects the key that encrypts provider credentials. It used to
be disabled by the exact configuration we deploy (LOCAL_MODE pins ENVIRONMENT=development),
so a host with no .env would boot happily on the repo's published key."""

import os
import subprocess
import sys

from app.core.config import DEFAULT_SECRET_KEY

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _boot(secret_key: str) -> subprocess.CompletedProcess:
    # A subprocess, because the guard runs at import time and app.main is already imported
    # in this process. An explicit env var also outranks any value in backend/.env.
    env = {**os.environ, "APP_SECRET_KEY": secret_key, "ENVIRONMENT": "development"}
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
    )


def test_default_secret_key_refuses_to_boot_even_in_development():
    result = _boot(DEFAULT_SECRET_KEY)
    assert result.returncode != 0
    assert b"APP_SECRET_KEY" in result.stderr


def test_a_real_secret_key_boots():
    result = _boot("a-real-key-that-is-definitely-not-the-default")
    assert result.returncode == 0, result.stderr.decode()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_secret_key_guard.py -v`
Expected: `test_default_secret_key_refuses_to_boot_even_in_development` FAILS — the process exits 0 because the guard is skipped in development.

- [ ] **Step 3: Make the guard unconditional**

In `backend/app/main.py`, replace line 20 and its comment:

```python
if settings.app_secret_key == DEFAULT_SECRET_KEY:
    # This key derives the KEK for provider credentials. The default is published in
    # the repo, so anything encrypted under it is effectively plaintext. Deliberately
    # unconditional: LOCAL_MODE pins ENVIRONMENT=development, so an environment-gated
    # guard is off in precisely the configuration that gets deployed.
    raise RuntimeError("APP_SECRET_KEY is still the published default — set a real one")
```

- [ ] **Step 4: Give the test suite a key**

The suite imports `app.main` through `TestClient`, so an unconditional guard breaks all of it without this. At the **very top** of `backend/tests/conftest.py`, above every `app.` import:

```python
import os

# Must precede any app import: Settings is instantiated at app.core.config import time,
# and the guard in app.main refuses the published default key in every environment.
os.environ.setdefault("APP_SECRET_KEY", "test-only-key-not-the-published-default")

import pytest
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_secret_key_guard.py -v`
Expected: 2 passed.

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: 232 passed (230 existing + 2 new).

- [ ] **Step 6: Document the requirement**

Add to `backend/.env.example`:

```
# Required. Boot fails on the published default — it derives the encryption key for
# provider credentials. Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
APP_SECRET_KEY=
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/conftest.py backend/tests/test_secret_key_guard.py backend/.env.example
git commit -m "fix: refuse the published secret key in every environment, not just production"
```

---

### Task 4: Backups, with a restore that has actually been run

On 29 July a migration test ran against the development database and dropped every table. `pg_dump` existed in the 26 July spec as a plan and nowhere in the repo, so there was nothing to restore. This task is that gap.

**Files:**
- Create: `ops/backup.sh`
- Create: `ops/restore-test.sh`
- Create: `ops/README.md`

**Interfaces:**
- Consumes: a running `postgres` compose service.
- Produces: `ops/backup.sh` (writes `of-YYYY-MM-DD.dump.gz` to `$BACKUP_DIR`, default `/var/backups/openfinance`) and `ops/restore-test.sh` (restores the newest dump into a throwaway database and asserts it has rows).

- [ ] **Step 1: Write the backup script**

Create `ops/backup.sh`:

```bash
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
```

- [ ] **Step 2: Write the restore test**

Create `ops/restore-test.sh`:

```bash
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
```

- [ ] **Step 3: Make them executable and run the backup**

Run: `chmod +x ops/backup.sh ops/restore-test.sh`
Run: `BACKUP_DIR=/tmp/of-backup-test ./ops/backup.sh`
Expected: `backup ok: of-<today>.dump.gz (NNNNN bytes)` with a size well over 1000.

- [ ] **Step 4: Run the restore test**

Run: `BACKUP_DIR=/tmp/of-backup-test ./ops/restore-test.sh`
Expected: `restored transactions: 406` (or whatever the current count is), then `restore test ok`.

If this fails, stop. The backup is not real until this passes.

- [ ] **Step 5: Document it**

Create `ops/README.md`:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add ops/
git commit -m "feat: nightly dump and a restore test that has been run"
```

---

### Task 5: Correct the README's topology

`README.md` lines 89-107 describe reaching the app from a phone against the desktop stack. After Phase B that is wrong, and a wrong runbook is worse than none.

**Files:**
- Modify: `README.md:89-107`

**Interfaces:**
- Consumes: the final topology from Phase B.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Read the current section**

Run: `sed -n '85,110p' README.md`

The last line of it currently reads *"Your machine has to be awake with `docker compose up -d` running for any of this to answer."* — that sentence is the thing this whole plan removes.

- [ ] **Step 2: Replace the "Reaching it from your phone" section**

Replace everything from `## Reaching it from your phone` up to (not including) `## AI assistant` with:

```markdown
## Reaching it from your phone

The app runs on an always-on cloud instance that has joined a
[Tailscale](https://tailscale.com/) network. Install Tailscale on your phone, sign it into
the same account, and open `http://openfinance:5173` from anywhere.

**Your PC does not need to be on.** It is just another client on the tailnet, the same as
the phone. The instance holds Postgres, the API and the background scheduler, so syncing
and daily balance snapshots continue whatever your desktop is doing.

Nothing is exposed to the public internet — the instance's public IP has no listening
port, and the only route in is the tailnet. That is what makes it safe for the app to have
**no login at all** in local mode. The flip side: a device without Tailscale cannot reach
it, so there is no showing this to someone on their own laptop.

The client derives the API host from whatever address you loaded the page on, so nothing
is configured per-device. In development the API accepts origins from loopback, RFC1918
LAN ranges and Tailscale (100.64/10, `*.ts.net`); the bare MagicDNS short name
(`http://openfinance:5173`) needs listing in `CORS_ORIGINS`, which the deploy sets.

Full design and the provisioning runbook:
`docs/superpowers/specs/2026-07-29-oracle-hosting-design.md`.

## Local development

The `web` container serves a **built** bundle and does not hot-reload. For the frontend dev
loop, run Vite directly and use compose for the backing services:

```bash
docker compose up -d postgres redis api
cd frontend && npm run dev
```
```

- [ ] **Step 3: Check nothing else in the README still claims the desktop hosts it**

Run: `grep -n "docker compose up" README.md`
Expected: remaining hits are development instructions, not "the app lives here" claims. Fix any that read as the latter.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README describes the hosted topology, not the desktop one"
```

---

### Task 6: Verify the whole stack before touching a cloud account

**Files:** none modified — this is a gate.

- [ ] **Step 1: Full backend suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: 232 passed.

- [ ] **Step 2: Full frontend suite and typecheck**

Run: `cd frontend && npx vitest run --reporter=dot && npx tsc --noEmit`
Expected: 50 passed, tsc exits 0.

- [ ] **Step 3: Clean stack from scratch**

Run: `docker compose down && docker compose up -d --build`
Run: `curl -s http://localhost:8000/health && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173/accounts`
Expected: healthy JSON, then `200`.

- [ ] **Step 4: Confirm nothing but the bound address is published**

Run: `docker compose ps --format json | python -c "import json,sys; [print(l['Service'], sorted({p.get('URL') for p in l.get('Publishers') or []})) for l in map(json.loads, sys.stdin)]"`
Expected: every published address is `127.0.0.1`. A `0.0.0.0` on any service means this task did not take effect — stop and fix it before Phase B, because on the instance that is a public finance API.

---

## Phase B — Provisioning runbook (human-executed)

Agents cannot do these steps: they need an Oracle account, console clicks, a Tailscale login, and a payment-card identity check. Phase A must be committed and pushed first.

- [ ] **B1. Create the Oracle account.** Free tier signup requires a card for identity verification; it is not charged on Always Free. Choose a US home region — **the home region cannot be changed later**.

- [ ] **B2. Provision the instance.** Ampere A1, Ubuntu 24.04, **1 OCPU / 6 GB** (spec §2.1 — do not take the full 2/12). Expect `Out of host capacity`; it is the most common free-tier complaint. Retry across availability domains and across hours. If capacity never appears, fall back to a DigitalOcean 2 GB droplet at $14.40/mo — only §2 and §4 of the spec are provider-specific.

- [ ] **B3. Install Tailscale.** `curl -fsSL https://tailscale.com/install.sh | sh`, then `sudo tailscale up`. Name the node `openfinance`. **Disable key expiry** for this node in the admin console — keys expire after ~180 days and there is no public SSH left to recover through. Record the `100.x.y.z` address.

- [ ] **B4. Lock it down — before the app runs, not after.** All three layers from spec §4: OCI security list default-deny (inbound UDP 41641 only, plus TCP 22 from your current IP temporarily); the instance's own `iptables` (Oracle's Ubuntu images ship pre-populated rules, and this is the classic trap where the security list says allow and the instance still drops); and Docker binding via `TS_IP`. Then run the §4.3 check **from a machine off the tailnet** and confirm the public IP answers nothing on 8000 and 5173.

- [ ] **B5. Deploy.** `git clone`, then create `backend/.env` with a generated `APP_SECRET_KEY` (Task 3 now makes a missing one a hard boot failure rather than a silent fallback), `CORS_ORIGINS` including the MagicDNS short name, `LOCAL_MODE=true`, `ENVIRONMENT=development`; and `.env` at the repo root with `TS_IP=100.x.y.z`. Then `docker compose up -d --build`. Alembic runs `upgrade head` on boot against the empty database.

- [ ] **B6. Verify.** `/health` over the tailnet, then open `http://openfinance:5173` from the phone. A permanent "Loading…" means CORS, not a server error — spec §2.3 and §6.

- [ ] **B7. Link SimpleFIN** through the UI and let it sync. Confirm accounts and transactions land. Then hit `POST /recurring/refresh` so detection runs against the fresh data.

- [ ] **B8. Backups on, before declaring done.** Install the cron from `ops/README.md`, wait for or force one dump, run `ops/restore-test.sh`, then configure the OCI Object Storage upload (20 GB free) and weekly boot-volume backups.

- [ ] **B9. Stop the desktop stack.** `docker compose down` on the PC. Two schedulers writing snapshots into two databases is the failure this prevents.

---

## Out of scope

Tracked, deliberately not in this plan:

- **Recurring detection does not run after a sync**, though the UI says it does. `backend/app/services/connections.py` never calls `recurring_service.detect`. Small backend fix, unrelated to hosting.
- **Chat tab** — decided during brainstorming (saved multi-turn threads, read-only lookup tools), not yet specced. Comes after the move.
- **Trade import** — the holdings page stays empty until a CSV is imported through `/investments/trades/import`. Waiting on the user's spreadsheet.
- **`apple-touch-icon.png`** — spec §8 lists it as cosmetic. Without it, iOS uses an auto-generated screenshot as the home-screen icon instead of a logo. One 180×180 PNG plus one `<link>` line in `frontend/index.html`, whenever someone cares.
- **`backend/.env.example` says port 5432 for `DATABASE_URL`** while compose publishes 5433. Pre-existing inconsistency, unrelated to hosting, worth a one-line fix sometime.
