# Cloud hosting design — moving OpenFinance to an always-on Tailscale host

> **Partially superseded by `2026-07-29-oracle-hosting-design.md`.** The host is now Oracle
> Always Free rather than a Hetzner CX22 — that shape is EU-only and could not have been
> ordered in a US region as §3 recommends. §3, §4.1, §5, §7, §9 and §10 below are replaced
> there. Everything else — §0 topology, §1 Model A vs B, §2 the code facts, §4.2-4.3 port
> binding, §6 CORS, §8 the phone — remains current and is not duplicated in the newer spec.

**Date:** 2026-07-26
**Status:** Design spec. No application code, Dockerfile, or compose file was changed by
this document.
**Decision:** **Model A — a private, Tailscale-only cloud VM.** Chosen. §1 records why
in brief; everything from §2 on is the implementation.

---

## 0. The problem, and the misconception worth clearing up first

Today the whole stack runs in Docker Desktop on a Windows 11 PC. When that PC is off:

- the phone can't reach the app, and
- the background scheduler (`backend/app/core/scheduler.py`) never ticks, so
  **daily balance snapshots are permanently lost for every day the machine was asleep.**
  Snapshots are the only source of the net-worth-over-time chart, and the model comment
  is blunt about it: *"a day not captured is gone for good"*
  (`backend/app/models/snapshot.py:13-14`). This is the part you cannot backfill.

The question that prompted this decision was *"for Tailscale my PC needs to be on,
right?"* — which conflates **Tailscale the network** with **your PC the host**.

They are separate things. Tailscale is a private network your devices join. It does not
care which device runs the app. Right now your PC happens to be both a tailnet member
*and* the machine running Postgres, so turning the PC off takes the app down. The fix is
to move the app onto a machine that never turns off, and let that machine join the same
tailnet.

**After this change, your PC is just another device on the tailnet — same status as your
iPhone.** You can turn it off, reinstall Windows, or throw it in a lake, and the app
keeps running and keeps syncing.

### Topology

**Before**

```
   iPhone ──────── tailnet ──────── Windows PC
  (client)                     (client AND host:
                                Docker Desktop, Postgres,
                                API, scheduler)
                                        │
                                        └── off at night = app down,
                                            snapshots lost
```

**After**

```
                        ┌──── iPhone            (client)
   Cloud VM ── tailnet ─┼──── Windows PC        (client — may be off)
  (host: Docker,        └──── laptop, etc.      (client)
   Postgres, API,
   scheduler — always on)
        │
        └── public internet: nothing listening. Firewall default-deny.
```

The VM has a public IP because every cloud VM does. Nothing is bound to it. The only way
in is the tailnet.

### The tradeoff you are accepting, stated plainly

**Any device that needs access must have Tailscale installed and be signed into your
Tailscale account. There is no public URL. You cannot open this on a friend's laptop, a
work machine you can't install software on, or a hotel kiosk.**

That is the whole cost. In exchange you keep an app with no login at all, which is the
next section.

---

## 1. Why Model A over Model B (public + real auth)

| | **Model A — Tailscale-only** (chosen) | **Model B — public + login** |
|---|---|---|
| Reachability | Devices on your tailnet | Any browser, anywhere |
| Auth | None (`LOCAL_MODE=true`) — network *is* the boundary | Email + password, argon2id, server-side sessions |
| Code changes | ~1 line + config | ~12 files (auth fixes, prod frontend build, proxy headers, TLS) |
| Cost | ~$8-11/mo | ~$14-16/mo + domain |
| TLS / domain | Not needed (WireGuard already encrypts) | Required |
| Failure mode if misconfigured | Firewall gap exposes an **unauthenticated** finance API | Password is the only thing between the internet and your bank data; no 2FA in the codebase |
| Ops burden | Patch a VM | Patch a VM + cert monitoring + auth hardening + session hygiene |

Model B is a real option and the login screen for it already exists and works
(`frontend/src/auth/AuthPage.tsx`, `backend/app/api/auth.py`). It was rejected for now
because the asymmetry is severe: the downside of Model A is *"I have to have Tailscale
on"*; the downside of a Model B mistake is your complete financial history. Model B also
requires fixing four real gaps first — `/auth/logout` doesn't revoke the session row,
`/auth/register` is open to anyone who finds the URL, `backend/app/schemas/auth.py` has
no server-side password minimum, and slowapi's `get_remote_address` sees only the
proxy's IP behind a reverse proxy, turning the 5/min register limit into a global one.

Revisit Model B when a second human needs access — a partner or housemate — because
that's the point where handing out tailnet invites becomes more friction than a
password.

**Also, briefly: Expo does not solve this.** Expo builds a React Native *client*. A
client is not a server. Whatever Expo produces still has to call a FastAPI process that
talks to Postgres — exactly the thing currently stuck on your desktop. It would cost a
full rewrite of `frontend/src/pages/*` from DOM to native primitives plus a $99/yr Apple
Developer account, and change availability by zero. The existing frontend is already a
mobile-ready SPA with iOS standalone meta tags (§8).

---

## 2. What the existing code forces this design to do

Five facts, all verified in the source, that the runbook below is shaped around.

### 2.1 `LOCAL_MODE=true` means no authentication whatsoever

`backend/app/api/deps.py:32-41`:

```python
def current_user(session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    if settings.local_mode:
        return _local_user(db)
    ...
```

`current_user` backs `require_household`, and `require_household` is the dependency on
every financial route — accounts, transactions, imports, connections, insights. When
`local_mode` is on, that branch returns the single local household **before the cookie is
ever looked at**.

> **The implication, in one sentence: with `LOCAL_MODE=true`, any device that can open a
> TCP connection to the API — meaning any device on your tailnet — has full,
> unauthenticated read and write access to every account, every transaction, and the
> ability to link or delete bank connections.**

Blast radius: if any single tailnet device is compromised — a stolen unlocked iPhone, a
laptop with malware, a device you added for something unrelated and forgot about — that
device has complete access to your financial history and can delete it. There is no
second factor and no audit log. Tailscale ACLs can narrow this (restrict which devices
may reach the VM's ports) and are worth setting up if you ever add a device you don't
fully trust; for a two-device tailnet they're optional.

`backend/app/main.py:16-19` enforces the coupling: `LOCAL_MODE=true` refuses to boot
unless `ENVIRONMENT=development`. Keep both as they are today.

### 2.2 The `APP_SECRET_KEY` guard does not fire in this configuration

`backend/app/main.py:11-14`:

```python
if settings.app_secret_key == DEFAULT_SECRET_KEY and settings.environment != "development":
    raise RuntimeError("APP_SECRET_KEY is still the published default — set a real one")
```

Because §2.1 pins `ENVIRONMENT=development`, **this guard is inert on the new host.** A
fresh `git clone` on the VM has no `backend/.env` (it's `.gitignore`d), so
`app_secret_key` silently falls back to `DEFAULT_SECRET_KEY` — the constant published in
this repo — and the app boots happily. See §5; this is the single most likely silent
failure in the whole migration.

### 2.3 CORS will reject a bare MagicDNS short name

`backend/app/main.py:29-38`, active only in development:

```python
LOOPBACK_ORIGIN_RE = (
    r"^http://("
    r"localhost|127\.0\.0\.1"
    ...
    r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
    r"|[a-z0-9-]+\.[a-z0-9-]+\.ts\.net"
    r")(:\d+)?$"
)
```

Matches: `http://100.x.y.z:5173` and `http://openfinance.tailXXXX.ts.net:5173`.
**Does not match:** `http://openfinance:5173` — the bare MagicDNS short name, which is
the most natural thing to type. The regex requires at least two dot-separated labels
before `.ts.net`.

The page loads either way (it's just static files), but the first `fetch` to
`http://openfinance:8000/auth/me` is cross-origin (different port = different origin),
gets no `Access-Control-Allow-Origin` header back, and the browser blocks it. You'd see
a permanently "Loading…" app with CORS errors in the console and no server-side error at
all. §6 fixes this with one env var.

Note the regex is also anchored to `^http://`, so an **HTTPS** tailnet origin does not
match it either — see §4.4 on Tailscale Serve.

### 2.4 The scheduler lives inside the API process

`backend/app/core/scheduler.py` is an `asyncio` loop started from FastAPI's `lifespan`.
It is not a separate worker and not a cron job. **Anything that keeps the API process
alive gives you background sync for free** — which is why a plain always-on VM is the
right shape and why scale-to-zero platforms would be wrong.

### 2.5 Redis is used for exactly one thing

`backend/app/api/deps.py:15` — slowapi's rate-limit storage. Nothing else in `backend/`
imports redis. With `LOCAL_MODE=true` the rate-limited routes (`/auth/register`,
`/auth/login`) are unreachable in practice. slowapi accepts `memory://`, so the `redis`
service can be deleted outright for this install. Optional, saves ~30 MB.

---

## 3. Provider and cost

**Recommendation: Hetzner Cloud CX22 (2 vCPU / 4 GB RAM / 40 GB NVMe), Ashburn VA or
Hillsboro OR.**

The requirements are: always-on process, persistent local disk for Postgres, cheap,
Tailscale installs cleanly (it does — one-line install script, official Ubuntu/Debian
repo, works on every provider here). That is the definition of "a small VM." Paying a
PaaS premium for managed Postgres and managed TLS on a box nobody but you can reach
would be spending money to solve problems you don't have.

**4 GB, not 1-2 GB.** Model A keeps the existing `frontend/Dockerfile`, which runs the
Vite dev server with filesystem polling (`vite.config.ts:13`). That's ~200-400 MB RSS
plus steady CPU. Postgres 17 on top of it will thrash a 1 GB box.

**A US region, not Germany.** ~15 ms vs ~120 ms per request. On a tap-heavy SPA you feel
the difference.

### Honest pricing

| Option | Spec | Price | Confidence |
|---|---|---|---|
| **Hetzner CX22** (recommended) | 2 vCPU / 4 GB / 40 GB | **~$6-7/mo** + ~$0.65/mo IPv4 + ~20% for backups ≈ **$8-11/mo** | **Low on the exact figure.** See below. |
| DigitalOcean Droplet | 1 vCPU / 2 GB / 50 GB | **$12/mo** + $2.40/mo backups = **$14.40/mo** | High — stable, public, USD |
| Tailscale | 2 devices, 1 user | **$0** | High |

**Where I am unsure:** Hetzner raised prices twice in 2026 — CPX effective 1 Apr 2026,
and a broader increase effective 15 Jun 2026 of roughly 1.3-1.4× on CX/CAX lines. The
pre-increase CX22 was about €4.35/mo; the increase implies roughly €5.50-6.00/mo, but
**CX22 specifically was not in any changelog I could find, every third-party pricing page
disagreed with the others, and Hetzner's own pricing page renders its numbers via
JavaScript and returned nothing to a fetch.** There may also be a US-region surcharge I
could not confirm. **Check console.hetzner.com before committing.** If the number has
drifted badly, the DigitalOcean droplet at a known $12/mo is a perfectly good answer and
requires no further thought.

**Tailscale tier: the free Personal plan is sufficient and will stay sufficient.** After
the April 2026 pricing overhaul it covers up to 6 users with **unlimited user-owned
devices** (previously 3 users / 100 devices). You need 1 user and 3 devices. No paid
tier, ever, for this use case.

---

## 4. Binding and firewall — the section to not skim

This is the single most likely way to silently get this wrong. A cloud VM has a public
IP. `docker compose up` with the current `ports:` entries publishes on `0.0.0.0`, which
means **the public IP**, which means an unauthenticated finance API on the open internet.
Internet-wide scanners find fresh IPs within minutes.

Two independent layers. Either alone would do; use both, because the failure is
catastrophic and the cost is ten minutes.

### 4.1 Layer 1 — provider firewall, default-deny

Hetzner Cloud Firewalls and DigitalOcean Cloud Firewalls are both free and both sit
*outside* the VM, which matters because **Docker's port publishing writes iptables DNAT
rules that bypass `ufw` entirely.** A host firewall configured with `ufw` will not save
you here. The provider firewall will.

Inbound rules — exactly one:

| Proto | Port | Source | Why |
|---|---|---|---|
| UDP | 41641 | `0.0.0.0/0`, `::/0` | Tailscale direct connections. Without it Tailscale still works via DERP relay, just slower. |

**No TCP 22.** No 8000, no 5173, no 5433, no 6379. Outbound: allow everything (needed for
the SimpleFIN API, `apt`, Docker Hub, and Tailscale's coordination server on 443).

**Ordering matters or you will lock yourself out.** Do it in this order:

1. Create the VM with your SSH public key. SSH in over the public IP.
2. Install Tailscale and bring it up with SSH enabled:
   ```
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --ssh --hostname=openfinance
   ```
3. **Verify tailnet SSH works from your PC before proceeding:** `ssh <user>@openfinance`
   must succeed with the public-IP session closed.
4. *Then* apply the default-deny firewall.
5. *Then* deploy the compose stack.

Never bring up a `LOCAL_MODE=true` stack before step 4 is done.

6. **In the Tailscale admin console, disable key expiry for the `openfinance` node.**
   Machine keys expire after ~180 days by default. With a default-deny firewall and no
   public SSH, an expired key means your only way back in is the provider's web rescue
   console. Set it now, not later.

### 4.2 Layer 2 — bind the published ports to the tailnet address

Docker's `ports:` accepts a host IP prefix. Bind to the VM's Tailscale address so the
listener never exists on the public interface at all.

Get the address: `tailscale ip -4` → something like `100.101.102.103` (stable; it only
changes if you `tailscale up --reset` or delete and re-add the node).

Then in `docker-compose.yml`:

```yaml
  api:
    ports: ["${TS_IP}:8000:8000"]     # was ["8000:8000"]
  web:
    ports: ["${TS_IP}:5173:5173"]     # was ["5173:5173"]
  postgres:
    # delete the `ports:` line entirely — nothing outside the compose network needs 5433
  redis:
    # delete the `ports:` line entirely
```

`${TS_IP}` is interpolated by Docker Compose from a **`.env` file sitting next to
`docker-compose.yml` at the repo root** — a different file from `backend/.env`, which is
the application's env. Create the root one with a single line:

```
TS_IP=100.101.102.103
```

Both are covered by the existing `.gitignore` (the `.env` pattern matches at any depth),
so neither gets committed. Keeping the IP in a variable means `docker-compose.yml` stays
portable back to the desktop, where you'd set `TS_IP=127.0.0.1`.

Uvicorn's own `--host 0.0.0.0` in the compose `command` stays as-is: that is the bind
*inside* the container's network namespace and is correct. The host-side bind address in
`ports:` is the thing that matters.

### 4.3 Proving the ports are actually closed

Do all four. The first two prove the negative from outside; the last two explain why.

**1. From your iPhone, on cellular, with the Tailscale VPN toggle OFF**, open Safari to:
- `http://<public-ip>:5173` → must hang and time out, not load the app
- `http://<public-ip>:8000/health` → must hang and time out, not return `{"status":"ok"}`

If either returns anything, stop and fix the firewall before going further.

**2. From any machine not on your tailnet** (or an online port checker such as
`canyouseeme.org`), confirm every one of these is closed: `22`, `5173`, `8000`, `5433`,
`6379`. Or:

```
nmap -Pn -p 22,5173,5433,6379,8000 <public-ip>
```

Every line must read `filtered` (dropped by the firewall) or `closed`. Any `open` is a
failure.

**3. On the VM, confirm the listeners are bound to the tailnet address, not `0.0.0.0`:**

```
ss -tlnp | grep -E '5173|8000'
```

Expected: `100.101.102.103:5173` and `100.101.102.103:8000`. If you see `0.0.0.0:*` the
`${TS_IP}` interpolation didn't take — check that the root `.env` exists and that you ran
`docker compose up -d` from the repo root.

**4. On the VM, confirm Docker's NAT rules are scoped to that IP:**

```
sudo iptables -t nat -L DOCKER -n | grep -E '5173|8000'
```

The `dpt:` rules should carry a destination of `100.101.102.103`, not a bare `0.0.0.0/0`.

**Re-run check 1 after any `docker compose` edit.** It's thirty seconds and it's the only
test that proves the thing you actually care about.

### 4.4 Tailscale Serve and Funnel — relevance

- **Funnel: never enable it. It is precisely the thing this design exists to avoid.**
  Funnel publishes a tailnet service to the *public internet* over HTTPS. Pointing it at
  a `LOCAL_MODE=true` app would put an unauthenticated finance API on a public URL — the
  worst possible outcome, reachable by one wrong command. If you ever want a public URL,
  that is Model B and it starts with turning `LOCAL_MODE` off.

- **Serve: available, but skip it.** `tailscale serve` gives HTTPS on a real `*.ts.net`
  certificate, tailnet-only. It's safe, but it buys nothing here — WireGuard already
  encrypts every byte between your phone and the VM — and it actively breaks two things:
  the CORS regex is anchored to `^http://` so an HTTPS tailnet origin fails it (§2.3),
  and `client.ts` would infer `https://openfinance.tailXXXX.ts.net:8000`, a port Serve
  isn't listening on (§6). Plain HTTP over the tailnet is the right call.

---

## 5. `APP_SECRET_KEY` — rotate it, and what that costs

### 5.1 Why rotation is mandatory even with no public exposure

`backend/app/core/encryption.py:8`:

```python
_KEK = hashlib.sha256(settings.app_secret_key.encode()).digest()  # 32-byte KEK
```

That KEK wraps the DEK that seals `provider_connections.encrypted_credentials` — your
SimpleFIN durable access URL, which is read access to your real bank balances and
transactions.

Until now that database has sat on a disk in your house. **After this migration it sits
on a cloud provider's hardware, on storage you do not own, in snapshots you do not
control, with a hypervisor operator who could in principle read it.** If the key is the
published default `dev-only-insecure-change-me-32-bytes!!`, that ciphertext is plaintext
to anyone who reads the file. And per §2.2 the startup guard will not warn you, because
`LOCAL_MODE` pins `ENVIRONMENT=development`.

Generate one:

```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

It lives in **`backend/.env` on the VM**, `chmod 600`, owned by your user — never in git
(`.gitignore` already covers it), never in `docker-compose.yml`, never pasted into a
chat window. That is the entire secret-management story and it is the right amount for
one file on one box; a secrets manager here would be theatre.

Also put a copy in your password manager. If you lose it, §5.2 explains what that costs.

### 5.2 What happens to already-encrypted tokens — definitive answer

**They become permanently undecryptable. Existing ciphertext does not survive a key
change, and there is no re-key utility anywhere in this repo.**

The mechanism, from `backend/app/core/encryption.py:27-31`:

```python
def decrypt(blob: bytes, aad: bytes = b"") -> bytes:
    wlen = int.from_bytes(blob[:2], "big")
    wrapped, body = blob[2 : 2 + wlen], blob[2 + wlen :]
    dek = _open(_KEK, wrapped)      # AESGCM(_KEK).decrypt(...)
    return _open(dek, body, aad)
```

`_KEK` is derived from `app_secret_key` at module import. Change the key and
`AESGCM(_KEK).decrypt` on the wrapped DEK raises `cryptography.exceptions.InvalidTag`.
There is no key versioning, no second key slot, no fallback. The AAD
(`backend/app/providers/base.py:45-48`) additionally binds the ciphertext to
`household_id:provider`, so the blob is also unusable if moved between households —
`pg_dump`/`pg_restore` preserves UUIDs, so that part is fine.

**In plain terms: after rotating, `Sync now` fails and the connection is dead, unless you
do one of the two things below.**

### 5.3 Two ways to survive the rotation

**Option A — re-encrypt the credential in place (recommended).** No re-link, no new
SimpleFIN token, no duplicate rows. You already hold the plaintext under the old key, so
just decrypt with the old and encrypt with the new. These are operational commands using
existing functions — no code changes.

On the **old desktop stack**, still running the old key, print the credential:

```
docker compose exec -T api python -c "
from app.core.db import SessionLocal
from app.models.connection import ProviderConnection
from app.providers.base import get_credentials
import json
db = SessionLocal()
for c in db.query(ProviderConnection).all():
    print(c.id, json.dumps(get_credentials(c)))
"
```

Save that output somewhere transient and private — it is a live bank credential; delete
it when you're done, and don't leave it in your shell history
(`HISTCONTROL=ignorespace` and a leading space, or `history -d`).

On the **VM**, after the restore in §7 and with the **new** key in `backend/.env`:

```
docker compose exec -T api python -c "
from app.core.db import SessionLocal
from app.models.connection import ProviderConnection
from app.providers.base import set_credentials
import json, sys, uuid
CONN_ID, CREDS = sys.argv[1], json.loads(sys.argv[2])
db = SessionLocal()
c = db.get(ProviderConnection, uuid.UUID(CONN_ID))
set_credentials(c, CREDS)
db.commit()
print('re-encrypted', c.id)
" '<conn-id>' '<the json from above>'
```

Then hit **Sync now** in the UI. If it returns without error, the rotation is complete.

**Option B — delete and re-link.** The fallback if Option A goes wrong. Be aware it is
messier than it looks, for three reasons found in the code:

1. **`DELETE /connections/{id}` will 500.** `accounts.connection_id` is a foreign key
   created with no `ondelete`
   (`backend/migrations/versions/199492b35732_categories_accounts.py:46`), and
   `backend/app/services/connections.py:69` just calls `db.delete(conn)`. Postgres
   raises a foreign-key violation for any account still pointing at it. The docstring
   says *"Imported rows stay put"*, but nothing nulls the column. You must do it by hand
   first:
   ```sql
   UPDATE accounts SET connection_id = NULL WHERE connection_id = '<old-conn-id>';
   DELETE FROM provider_connections WHERE id = '<old-conn-id>';
   ```
2. **Re-linking duplicates every account and re-imports a year of transactions.**
   `backend/app/services/sync.py` matches existing accounts with
   `Account.connection_id == conn.id`. A new connection has a new UUID, so the match set
   starts empty, every account is created fresh, and — because the dedupe sets are keyed
   off those new (empty) accounts — 365 days of transactions land on the duplicates. Your
   net worth doubles. Fix by re-pointing the old accounts at the new connection and
   deleting the fresh duplicates, in SQL, before or immediately after the first sync.
3. **Never delete an account to clean this up.** `balance_snapshots.account_id` is
   `ondelete="CASCADE"` (`backend/app/models/snapshot.py:23`). Deleting an account
   silently destroys its entire balance history — the one thing in this database that
   cannot be re-fetched from anywhere.

Option A avoids all three. Use Option A.

---

## 6. `frontend/src/api/client.ts` — does the port-8000 inference still work?

```ts
const inferred =
  typeof window === "undefined"
    ? "http://localhost:8000"
    : `${window.location.protocol}//${window.location.hostname}:8000`;

export const API_BASE = import.meta.env.VITE_API_URL || inferred;
```

**The URL construction works. The CORS response does not.**

Open `http://openfinance:5173` and `window.location.hostname` is `openfinance`, protocol
`http:`, so `API_BASE` becomes `http://openfinance:8000`. MagicDNS resolves `openfinance`
to the VM's `100.x.y.z` on every tailnet device, and §4.2 binds port 8000 to exactly that
address. The request reaches the API.

Then it gets blocked by the browser, for the reason in §2.3: the origin
`http://openfinance:5173` matches neither `CORS_ORIGINS` nor `LOOPBACK_ORIGIN_RE`, so no
`Access-Control-Allow-Origin` comes back, and `apiFetch`'s `credentials: "include"`
request fails. Symptom: the app sits on "Loading…" forever with CORS errors in the
console and **nothing in the server log**, because from the API's point of view it
answered fine.

**Fix — one line in `backend/.env` on the VM. No code change:**

```
CORS_ORIGINS=http://localhost:5173,http://openfinance:5173,http://100.101.102.103:5173
```

Substitute your real MagicDNS name and tailnet IP. `docker-compose.yml` does not override
`CORS_ORIGINS` in its `environment:` block, so the value from `backend/.env` applies.

Belt and braces: the **full** MagicDNS FQDN
(`http://openfinance.tailXXXX.ts.net:5173`) and the raw tailnet IP
(`http://100.101.102.103:5173`) both already match `LOOPBACK_ORIGIN_RE` and work with no
config at all. Using the FQDN in your home-screen bookmark means one fewer thing to get
wrong. Set `CORS_ORIGINS` anyway so the short name works too.

`client.ts` itself needs **no change** under Model A.

---

## 7. Migration runbook

Assumes §4 is complete: VM up, Tailscale joined and SSH-verified, firewall default-deny,
key expiry disabled.

### Step 1 — capture the baseline on the desktop

```
docker compose exec -T postgres psql -U openfinance -d openfinance -c "
SELECT 'households' t, count(*) FROM households
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'categories', count(*) FROM categories
UNION ALL SELECT 'provider_connections', count(*) FROM provider_connections
UNION ALL SELECT 'accounts', count(*) FROM accounts
UNION ALL SELECT 'transactions', count(*) FROM transactions
UNION ALL SELECT 'balance_snapshots', count(*) FROM balance_snapshots
UNION ALL SELECT 'sessions', count(*) FROM sessions
ORDER BY 1;
SELECT sum(balance) AS account_balance_total FROM accounts;
SELECT sum(amount) AS txn_amount_total FROM transactions;
"
```

Save that output. It is your correctness check.

Also export the SimpleFIN credential now, per §5.3 Option A.

### Step 2 — dump

```
docker compose exec -T postgres pg_dump -U openfinance -Fc openfinance > openfinance.dump
```

Custom format (`-Fc`), not plain SQL — it restores selectively and compresses. Do **not**
try to copy the `pgdata` volume directory: Postgres data directories are not portable
across platforms and you want a portable file anyway.

### Step 3 — ship it over the tailnet

```
scp openfinance.dump <user>@openfinance:~/
```

No public SSH needed; this rides the tailnet. (If you enabled `tailscale up --ssh`, this
works with no key management at all.)

### Step 4 — bring the VM stack up empty first

```
git clone <your repo> /srv/openfinance && cd /srv/openfinance
printf 'TS_IP=%s\n' "$(tailscale ip -4)" > .env          # root .env, for compose interpolation
cp backend/.env.example backend/.env && chmod 600 backend/.env
```

Edit `backend/.env`:

```
APP_SECRET_KEY=<the new generated key from §5.1>
ENVIRONMENT=development
LOCAL_MODE=true
CORS_ORIGINS=http://localhost:5173,http://openfinance:5173,http://100.101.102.103:5173
SYNC_INTERVAL_HOURS=6
ANTHROPIC_API_KEY=<yours, or leave blank>
```

Apply the `ports:` edits from §4.2 to `docker-compose.yml`, then:

```
docker compose up -d
```

This runs `alembic upgrade head` and creates an empty schema. **Now re-run the §4.3
verification.** Do not proceed until the public IP is provably dead.

### Step 5 — restore

```
docker compose exec -T postgres pg_restore -U openfinance -d openfinance \
  --clean --if-exists --no-owner --no-privileges < ~/openfinance.dump
```

`--clean --if-exists` drops the empty tables Alembic just made before recreating them.
Some notices about non-existent objects are expected and harmless. Then re-stamp Alembic
so future migrations line up:

```
docker compose exec -T api alembic upgrade head
```

(A no-op if the dump already carried the current `alembic_version` row, which it will.)

### Step 6 — verify

Re-run the **exact** query from Step 1 against the VM. Every count must match, and both
sums must match to the cent — the sums catch numeric-type mangling that row counts miss.

```
docker compose exec -T postgres psql -U openfinance -d openfinance -c "<same query>"
```

Any mismatch: stop, don't decommission the desktop, investigate.

### Step 7 — re-encrypt the bank credential

Run §5.3 Option A's second command. Then open the app and hit **Sync now**. Success here
is the real end-to-end proof.

### Step 8 — reach it from the phone

Open `http://openfinance:5173` (or the FQDN) in Safari with Tailscale on. Share → Add to
Home Screen. See §8.

### Step 9 — shut down the desktop stack

```
docker compose down
```

on the Windows PC. **Do not leave it running.** Two schedulers syncing the same SimpleFIN
connection will burn your API quota and race on the daily snapshot's
`uq_snapshot_day` unique constraint. Deduplication is on provider transaction IDs so you
won't get doubled rows, but there is no reason to find out. If you want to keep the
desktop stack around for development, set `SYNC_INTERVAL_HOURS=0` in its `backend/.env`.

Keep `openfinance.dump` somewhere safe for a couple of weeks. Delete the exported
credential JSON from §5.3 once sync works.

---

## 8. The phone

`frontend/index.html` — verified, lines 7-15:

```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
<meta name="theme-color" content="#0b0b0c" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
<meta name="apple-mobile-web-app-title" content="OpenFinance" />
```

**Add-to-home-screen is enough.** Share → Add to Home Screen gives a full-screen,
chrome-less app titled "OpenFinance" with a dark status bar that clears the notch. No App
Store, no Expo, no build step.

Two honest caveats, neither blocking:

- **No `manifest.json` and no `apple-touch-icon`.** `frontend/public/` holds only
  `favicon.svg` and `icons.svg`, and iOS does not use SVG favicons for home-screen icons
   — you'll get an auto-generated screenshot thumbnail instead of a logo. Fix is a
  180×180 PNG at `frontend/public/apple-touch-icon.png` plus one `<link>` line in
  `index.html`. `apple-mobile-web-app-capable` is also formally deprecated in favour of a
  manifest's `display: "standalone"`, though iOS still honours it.
- **No service worker**, so no offline mode and no caching. Out of signal — or with
  Tailscale off — you get a blank shell rather than stale data. Acceptable for an app you
  check on wifi or LTE, worth knowing before calling it a PWA.

---

## 9. Files that change

| File | Change | Required? |
|---|---|---|
| `backend/.env` *(on the VM; `.gitignore`d, never committed)* | New generated `APP_SECRET_KEY` (§5.1). `CORS_ORIGINS` including the MagicDNS short name (§6). `LOCAL_MODE=true`, `ENVIRONMENT=development` unchanged. | **Yes** |
| `.env` at repo root *(new; `.gitignore`d)* | One line, `TS_IP=100.x.y.z`, for compose interpolation | **Yes** |
| `docker-compose.yml` | `api.ports` → `["${TS_IP}:8000:8000"]`; `web.ports` → `["${TS_IP}:5173:5173"]`; delete `ports:` from `postgres` and `redis` entirely (§4.2) | **Yes** |
| `backend/app/main.py:11` | Drop `and settings.environment != "development"` so the `APP_SECRET_KEY` guard is unconditional. One line. Turns §2.2's silent failure into a refusal to boot. | Strongly recommended |
| `docker-compose.yml` | Delete the `redis` service; set `REDIS_URL=memory://` (§2.5) | Optional |
| `README.md` | Lines 89-107 ("Reaching it from your phone") describe the desktop topology and are now wrong | Housekeeping |
| `frontend/index.html` + `frontend/public/apple-touch-icon.png` | Home-screen icon (§8) | Cosmetic |

**Explicitly unchanged:** `frontend/src/api/client.ts`, all of `backend/app/api/auth.py`
and `backend/app/services/auth.py`, `backend/Dockerfile`, `frontend/Dockerfile`, every
page component. That minimal blast radius is the main argument for this model.

---

## 10. Backups

Your entire financial history — including balance snapshots that cannot be re-fetched
from any bank — will live on a VM you could delete by accident with one misclick.

### Layer 1 — provider automated backups

A checkbox at ~20% of instance cost (~$1.50-2.50/mo). Whole-disk, 7 daily rotations,
zero maintenance. Enable it. Caveat: a disk snapshot of a *running* Postgres is
crash-consistent, which normally recovers fine, but "normally" is carrying weight in
that sentence. Hence layer 2.

### Layer 2 — nightly logical dump, offsite

Four lines of crontab, and it's the one that actually restores cleanly:

```cron
0 4 * * * cd /srv/openfinance && docker compose exec -T postgres \
  pg_dump -U openfinance -Fc openfinance > /var/backups/of-$(date +\%F).dump 2>>/var/log/of-backup.log
15 4 * * * find /var/backups -name 'of-*.dump' -mtime +14 -delete
30 4 * * * rclone sync /var/backups b2:your-bucket/openfinance
```

Offsite via `rclone` to Backblaze B2 — this database is a few megabytes, so the cost
rounds to zero and it survives the provider losing your account. Backups on the same box
as the database protect against `DROP TABLE` and nothing else.

### The restore test — do it once, now, then every six months

An untested backup is not a backup. This restores into a throwaway database on the same
box and touches nothing real:

```
docker compose exec -T postgres createdb -U openfinance restoretest
docker compose exec -T postgres pg_restore -U openfinance -d restoretest --no-owner \
  < /var/backups/of-$(date +%F).dump
docker compose exec -T postgres psql -U openfinance -d restoretest -c "
SELECT 'accounts' t, count(*) FROM accounts
UNION ALL SELECT 'transactions', count(*) FROM transactions
UNION ALL SELECT 'balance_snapshots', count(*) FROM balance_snapshots
ORDER BY 1;"
docker compose exec -T postgres dropdb -U openfinance restoretest
```

The counts must match the live database. Put a calendar reminder on it. Also confirm
`rclone lsl b2:your-bucket/openfinance | tail` shows a file from last night — a cron job
that silently stopped working six months ago is the classic way to discover you have no
backups on the day you need one.

---

## 11. Known sharp edges

Ranked by how likely they are to actually bite.

1. **Firewall applied after `docker compose up`, or `${TS_IP}` silently unset.** Either
   one publishes an unauthenticated finance API on a public IP. §4.3's check 1 is the
   only thing that proves otherwise. Run it.
2. **The bare MagicDNS name fails CORS** with no server-side error and a permanently
   "Loading…" app (§2.3, §6). Set `CORS_ORIGINS`, or use the full `*.ts.net` FQDN.
3. **`APP_SECRET_KEY` missing on the new host** falls back to the published default and
   the startup guard stays quiet, because `LOCAL_MODE` pins `ENVIRONMENT=development`
   (§2.2). The one-line `main.py` change in §9 removes this class of mistake permanently.
4. **Rotating the key without §5.3 Option A** kills the SimpleFIN connection, and the
   obvious repair (delete + re-link) hits an FK violation, then duplicates every account,
   then tempts you into an account deletion that cascades away your balance snapshots
   (§5.2, §5.3).
5. **Both schedulers running.** Stop the desktop stack (§7 step 9).
6. **Tailscale key expiry after ~180 days**, with no public SSH to recover through.
   Disable expiry on the VM node in the admin console during setup (§4.1 step 6).
7. **Guests can't be shown the app** without a tailnet invite. This is the accepted
   tradeoff, restated here so it isn't a surprise six months from now.
8. **Every tailnet device has full unauthenticated access** (§2.1). If you ever add a
   device you don't fully trust, add a Tailscale ACL restricting who can reach ports
   5173/8000 on `openfinance`, or move to Model B.

---

## Appendix: sources for the pricing claims

Checked 2026-07-26. Where I say I'm unsure, I'm unsure.

- [Hetzner Cloud](https://www.hetzner.com/cloud/) — the pricing page renders figures via
  JavaScript and returned no numbers to a fetch. The CX22 at ~€4.35/mo is a
  *pre-increase* third-party figure.
- [Northflank: Hetzner 2026 price increases](https://northflank.com/blog/hetzner-cloud-server-price-increases)
  — confirms an increase effective 15 Jun 2026, roughly 1.3-1.4× on CX/CAX (CX32
  €6.49 → €8.49; CAX11 €4.49 → €5.99). **CX22 is not listed**, which is why §3 gives a
  range rather than a figure.
- [DigitalOcean droplet pricing](https://www.digitalocean.com/pricing/droplets) — Basic
  droplets from $4/mo; the 2 GB tier at $12/mo.
- [Tailscale pricing](https://tailscale.com/pricing) and
  [the April 2026 pricing update](https://tailscale.com/blog/pricing-v4) — Personal plan
  free: up to 6 users, unlimited user-owned devices.
- Model B comparison figures (§1), for completeness:
  [Render](https://render.com/pricing) Starter web service $7/mo + Postgres Basic ~$6/mo;
  [Railway](https://docs.railway.com/pricing/plans) Hobby $5/mo including $5 usage credit,
  usage-based above; [Fly.io Managed Postgres](https://fly.io/docs/mpg/) Basic $38/mo plus
  $0.28/provisioned GB.
