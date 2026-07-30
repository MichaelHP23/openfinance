# Oracle Always Free hosting design — the always-on host, revised

**Status:** supersedes §3, §4.1, §5, §7, §9 and §10 of
`2026-07-26-cloud-hosting-design.md`. Everything else in that document — the topology
argument (§0), Model A vs Model B (§1), the five code facts (§2), port binding (§4.2-4.3),
`client.ts` and CORS (§6), and the phone (§8) — still stands and is not repeated here.
Read that document first; this one only says what changed.

**Decision:** Oracle Cloud Always Free, Ampere A1, **1 OCPU / 6 GB**, US region, joined to
the tailnet. $0/month. Clean start rather than a data migration.

---

## 1. What changed since 26 July, and why

Three things, none of them a change of heart about the topology.

**The provider recommendation was unbuildable.** §3 recommended a Hetzner CX22 in Ashburn
or Hillsboro. The CX line is EU-only — Germany and Finland. US regions offer CPX and CCX
only. That recommendation could not have been ordered as written.

**Hetzner's US pricing could not be pinned down.** The original spec already flagged this:
their pricing page renders figures in JavaScript and returns nothing to a fetch. Re-checked
on 29 July, third-party sources for CPX21 in Ashburn spanned $11.13/mo (January) to
$37.49/mo (current), attributed to a 15 June 2026 US increase that also cut US bandwidth to
1-2 TB. A recommendation resting on a number that moves 3× between sources is not a
recommendation.

**The requirement changed from "cheap" to "free."** That reopened the question rather than
adjusting a figure, because the free tier of every platform was re-examined:

| Option | Verdict |
|---|---|
| **Oracle Always Free** | **Chosen.** Always-on, $0, genuine persistent disk. Caveats in §7. |
| DigitalOcean, 2 GB | $14.40/mo verified. The fallback if Oracle capacity never appears. |
| Render free | **Disqualified.** Free Postgres expires after 30 days, 14-day grace, then deleted, and supports no backups. |
| Koyeb free | Gone. Free Starter tier withdrawn after the Mistral acquisition; entry is now $29/mo. |
| Fly.io free | Gone. New accounts get a 2-hour trial. |
| Neon free Postgres | Genuinely free and permanent (0.5 GB), but solves only the database, and scale-to-zero conflicts with §2.4. |

A note on the scale-to-zero platforms generally: §2.4 of the original spec is the reason
they lose. The scheduler is an `asyncio` loop inside the FastAPI process, so anything that
suspends the process stops daily snapshots — and per `snapshot.py:13`, a day not captured
is gone for good. Free tiers built around sleeping idle apps are structurally wrong for
this workload, whatever their price.

---

## 2. Host and sizing

**Oracle Cloud Infrastructure, Always Free tier. Ampere A1 (arm64), 1 OCPU / 6 GB RAM,
Ubuntu 24.04, US region (Ashburn preferred, Phoenix as the capacity fallback).**

Free-tier allowance as of June 2026 is 2 OCPU / 12 GB total across all A1 instances, cut
from 4/24 on 15 June 2026 with no public announcement. **We deliberately take half of what
is free.**

### 2.1 Why taking less is the safer choice

Oracle reclaims idle Always Free compute. The published rule: reclamation when 95th
percentile CPU utilisation is below 20% over a 7-day window — and for Ampere A1
specifically, **memory utilisation must also be below 10%**. Both conditions must hold.

A personal finance app checked a few times a day will never clear the 20% CPU bar. CPU
cannot save this instance. **Memory is the only lever**, and it is a ratio, so a smaller
instance is a safer instance:

| Shape | Stack working set | Memory utilisation | Reclamation risk |
|---|---|---|---|
| 2 OCPU / 12 GB | ~800 MB | ~7% | **Below the 10% floor** |
| **1 OCPU / 6 GB** | ~800 MB | **~13%** | Above the floor |

Working set estimate: Postgres ~200 MB, API ~200 MB, static frontend ~10 MB, Redis ~10 MB,
Ubuntu ~250 MB.

1 OCPU is also ample. The workload is a handful of requests a day plus a scheduler tick
every six hours.

### 2.2 The calibration knob

The 13% figure is an estimate, and OCI's definition of "memory utilisation" (whether page
cache counts) is not documented precisely enough to bet the server on. Leave an explicit
floor rather than hoping:

```yaml
# docker-compose.yml, postgres service
command: postgres -c shared_buffers=768MB
```

That pins a guaranteed ~768 MB resident, putting the instance at roughly 17% of 6 GB on
its own, independent of traffic. If a reclamation warning ever arrives anyway, the lever is
to raise `shared_buffers` or resize down to 4 GB — not to add fake load.

### 2.3 Redis stays

§2.5 of the original spec recommends deleting the Redis service to save ~30 MB, since
slowapi accepts `memory://` and the rate-limited routes are unreachable under
`LOCAL_MODE`. **That recommendation inverts here.** Memory headroom is no longer the
scarce resource; memory *usage* is what keeps the instance alive. Keep Redis. It costs
nothing that matters and contributes to the floor.

### 2.4 arm64

Ampere A1 is arm64. Verified as publishing arm64 images: `python:3.13-slim`,
`postgres:17`, `redis:7`, `nginx:alpine`. `psycopg[binary]` ships aarch64 manylinux
wheels. No Dockerfile needs an architecture change; `docker compose build` on the VM
builds natively.

---

## 3. Frontend: build and serve, not the dev server

`frontend/Dockerfile` currently runs `npm run dev -- --host`, and says so:

```dockerfile
# ponytail: dev server in the container — M0 has no prod hosting story yet.
# Swap for a build + static serve stage when there's somewhere to deploy.
```

There is now somewhere to deploy. Replace it with a two-stage build — `npm run build`,
then `nginx:alpine` serving `dist/`.

This was the sole reason the original §3 demanded 4 GB: the Vite dev server runs
filesystem polling (`vite.config.ts:13`), costing ~200-400 MB RSS and steady CPU forever.
Removing it is what makes a 6 GB instance comfortable.

**Serve on port 5173, not 80.** Keeping the port identical means §2.3, §6 and every CORS
conclusion in the original spec carry over unchanged, and the home-screen bookmark does not
move. `client.ts` infers the API base from `window.location` at runtime, not build time, so
a static build changes nothing about API resolution.

Drop the `volumes:` block from the `web` service in compose — it exists to live-mount source
for the dev server and would shadow the built image.

---

## 4. Firewall — three layers, not two

§4.2 and §4.3 of the original spec (bind published ports to `${TS_IP}`, then prove the
public IP answers nothing) apply unchanged and remain the part not to skim. Two
Oracle-specific differences replace §4.1:

**Layer 1 — OCI security list.** Default-deny ingress in the VCN's security list. Allow
inbound only UDP 41641 (Tailscale direct connections) and, temporarily, TCP 22 from your
current IP during setup — removed once Tailscale SSH works. Egress open.

**Layer 2 — the instance's own iptables.** Oracle's Ubuntu images ship with pre-populated
`iptables` rules, unlike most cloud images. This is the classic OCI trap: the security list
says allow, the instance still drops, and nothing logs why. Persisted rules live in
`/etc/iptables/rules.v4`.

**Layer 3 — Docker port binding**, exactly as the original §4.2: `${TS_IP}:8000:8000`,
`${TS_IP}:5173:5173`, and no `ports:` on postgres or redis at all.

Note that Docker inserts its own iptables rules ahead of the filter chain, which is
precisely why layer 3 exists — binding to the tailnet address means Docker never publishes
on the public interface in the first place, regardless of what layers 1 and 2 believe.

**Disable Tailscale key expiry** on the VM node in the admin console during setup. Keys
expire after ~180 days and there is no public SSH left to recover through.

---

## 5. Migration: clean start

**The dump-and-restore runbook (original §7 steps 2-7) and the entire `APP_SECRET_KEY`
rotation analysis (§5) are dropped.** Both existed to carry live data across. There is no
longer live data worth carrying.

The database currently holds 1 household, 10 accounts, 406 transactions and 1 SimpleFIN
connection — all re-synced from the provider on 29 July after the development database was
destroyed by a migration test that ran against it. It also holds **0 balance snapshots and
0 categories**. The snapshot history that dump-and-restore existed to protect is already
gone and cannot be backfilled.

So: stand the stack up empty and link SimpleFIN on the VM.

This deletes sharp edge #4 outright — rotating the key without the original §5.3 Option A
would kill the SimpleFIN connection, and the obvious repair hits an FK violation, then
duplicates every account, then tempts an account deletion that cascades away snapshots. A
fresh key on a fresh database has none of that. Generate `APP_SECRET_KEY` on the VM, and
treat rotation as something you do only if the key is exposed — at which point the price is
re-linking SimpleFIN, which is now a one-click operation rather than the FK minefield the
original §5.3 was written to navigate.

### Runbook

1. **Provision.** Create the A1 instance (§2). Expect capacity failures; see §7.
2. **Tailscale.** Install, `tailscale up`, name the node `openfinance`, disable key expiry,
   note the `100.x.y.z` address.
3. **Lock down.** Apply all three firewall layers (§4). Run the original §4.3 check from
   off-tailnet and confirm the public IP answers nothing. **Do this before the app runs,
   not after.**
4. **Clone and configure.** `git clone`; write `backend/.env` with a freshly generated
   `APP_SECRET_KEY`, `CORS_ORIGINS` including the MagicDNS short name (original §6),
   `LOCAL_MODE=true`, `ENVIRONMENT=development`; write `.env` at the repo root with
   `TS_IP=100.x.y.z`.
5. **Up.** `docker compose up -d --build`. Alembic runs `upgrade head` on boot against the
   empty database.
6. **Verify.** `/health` over the tailnet; the app loads without a permanent "Loading…"
   (that symptom means CORS — original §2.3).
7. **Link SimpleFIN** through the UI on the VM and let it sync. Confirm accounts and
   transactions land.
8. **Backups on** (§6) — before declaring done, not after.
9. **Stop the desktop stack.** `docker compose down` on the PC. Two schedulers writing
   snapshots to two databases is the failure mode this step prevents.

---

## 6. Backups

**This is the section that has no prior art in this project, and the reason it is
non-negotiable is that it was tested by accident on 29 July and failed.** `pg_dump`
appeared in the 26 July spec as a plan; nothing implemented it; a destructive command hit
the development database and there was nothing to restore from.

**Layer 1 — nightly logical dump to OCI Object Storage.** The Always Free tier includes
20 GB of object storage. A compressed dump of this dataset is well under 10 MB.

```
0 4 * * * docker compose exec -T postgres pg_dump -U openfinance -Fc openfinance \
  | gzip > /var/backups/of-$(date +\%F).dump.gz 2>>/var/log/of-backup.log
```

Upload with the OCI CLI, retain 30 days locally and 90 in the bucket.

**Layer 2 — OCI boot volume backups.** Free tier includes block volume backups. Weekly,
retained a month. Recovers the machine; the logical dump recovers the data.

**The restore test.** Run one restore into a throwaway database once, now, immediately
after the first dump exists — and then every six months. A backup that has never been
restored is a hypothesis. Today demonstrated what an untested one is worth.

---

## 7. Risks specific to this choice

Ranked by likelihood of actually biting.

1. **"Out of host capacity" on A1 at create time.** The single most common Oracle free-tier
   complaint. A1 capacity in popular US regions is frequently exhausted, and the shape is
   listed as available regardless. Mitigation: try both Ashburn and Phoenix, try different
   availability domains, retry on a loop over hours or days. If capacity never materialises,
   fall back to DigitalOcean at $14.40/mo — the design is provider-agnostic apart from §2
   and §4.
2. **Idle reclamation** (§2.1). Mitigated by the 6 GB shape plus the `shared_buffers`
   floor, but the underlying policy is Oracle's to change, and they changed the free
   allowance in June with no announcement.
3. **Account closure.** Oracle free accounts have a documented reputation for abrupt
   termination with limited recourse. This is the argument for §6 layer 1 being genuinely
   offsite — a dump that lives only on the instance is not a backup against this failure.
4. **Free-tier terms changing again.** June 2026 halved the allowance quietly. Assume it
   can happen again; the fallback stays the same.
5. **arm64 surprises** in a future dependency that ships x86-only wheels. Currently none;
   worth remembering as the explanation if a future `pip install` fails strangely.
6. **Both schedulers running** — carried over from the original §11. Runbook step 9.
7. **Every tailnet device has full unauthenticated access** — carried over unchanged from
   §2.1. `LOCAL_MODE` means no auth at all; the tailnet is the entire security boundary.

---

## 8. Files that change

Supersedes the original §9 table.

| File | Change | Required? |
|---|---|---|
| `backend/.env` *(on the VM, `.gitignore`d)* | Generated `APP_SECRET_KEY`; `CORS_ORIGINS` with the MagicDNS short name; `LOCAL_MODE=true`, `ENVIRONMENT=development` | **Yes** |
| `.env` at repo root *(new, `.gitignore`d)* | `TS_IP=100.x.y.z` for compose interpolation | **Yes** |
| `docker-compose.yml` | `api.ports` → `["${TS_IP}:8000:8000"]`; `web.ports` → `["${TS_IP}:5173:5173"]`; remove `ports:` from postgres and redis; remove the `web` `volumes:` block; add `shared_buffers` to postgres | **Yes** |
| `frontend/Dockerfile` | Two-stage build → `nginx:alpine` serving `dist/` on 5173 (§3) | **Yes** |
| `backend/app/main.py:11` | Drop `and settings.environment != "development"` so the `APP_SECRET_KEY` guard is unconditional. Turns the original §2.2 silent failure into a refusal to boot. | Strongly recommended |
| `README.md` | Lines 89-107 describe the desktop topology and are now wrong | Housekeeping |
| `frontend/index.html` + `public/apple-touch-icon.png` | Home-screen icon (original §8) | Cosmetic |

**Explicitly unchanged:** `frontend/src/api/client.ts`, all auth code, `backend/Dockerfile`,
every page component. `frontend/Dockerfile` moves out of the unchanged column — that is the
only addition to the blast radius, and it closes a TODO that was already written down.

---

## 9. What this deliberately does not do

- **No authentication work.** Tailnet-only keeps `LOCAL_MODE` defensible. A public URL
  would require turning the existing (already-written) auth on, and would put bank balances
  behind one password. Rejected in favour of Tailscale, consistent with the original §1.
- **No managed Postgres.** Neon's free tier is real, but splitting the database out adds a
  network hop and a second free-tier dependency to solve a problem this instance does not
  have.
- **No CI/CD.** `git pull && docker compose up -d --build` over Tailscale SSH.
- **No monitoring stack.** The failure mode that matters is "instance reclaimed," and the
  signal for that is Oracle's email plus the app not loading.

### 9.1 Cloudflare, reconsidered and rejected (29 July 2026)

Raised after Phase A shipped: host it through Cloudflare and make it private instead.
Three different things go by that name, and none of them is cheaper than this plan.

- **Workers/Pages + D1** is a rewrite, not a migration. FastAPI, SQLAlchemy and Alembic
  do not run there, and D1 is SQLite — the money invariant is Postgres `NUMERIC(19,4)`
  end to end.
- **Cloudflare Containers** needs the paid Workers plan and sleeps when idle. Scale-to-zero
  is the same defect that eliminated Render and Neon in §1; the scheduler is the whole point.
- **Tunnel + Access** is the only real candidate, and it is a *front door*, not a host — it
  replaces Tailscale, not this instance. It still costs more:
  - Named tunnels require a domain on a zone you control (~$5–11/yr).
    `trycloudflare.com` quick tunnels are ephemeral, randomly named, and cannot carry
    Access policies.
  - Cloudflare terminates TLS, putting a third party in the path over bank data.
    Tailscale is end-to-end WireGuard with nobody in the middle.
  - **The failure modes invert, and that decides it.** A wrong Tailscale ACL makes the app
    unreachable. A wrong Access policy makes an unauthenticated finance API world-readable.
    With `LOCAL_MODE=true` there is no login behind it, so the network *is* the auth —
    prefer the mechanism that fails closed.
  - `frontend/src/api/client.ts:9` pins port 8000 on the page's hostname, so serving on
    443 also needs two hostnames plus `VITE_API_URL`, or an nginx `/api` proxy.

What Tunnel would genuinely buy: browser access with no client install, and the ability to
show the app to someone on their own laptop. §9's first bullet already priced that and
declined it. Revisit only if that requirement changes — not for cost.

---

## Sources

Checked 29 July 2026.

- [Oracle: Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) — reclamation policy: <20% p95 CPU over 7 days, plus <10% memory for A1.
- [InfoQ: Oracle quietly halves free tier A1 limits](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/) — 4 OCPU/24 GB → 2 OCPU/12 GB.
- [TerminalBytes: Oracle free tier changes 2026](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026/) — effective 15 June 2026; 200 GB storage unchanged; enforcement inconsistent.
- [Render: free Postgres expires after 30 days](https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90) — plus 14-day grace, then deletion; no backups on free.
- [Neon free tier](https://neon.com/faqs/managed-postgres-databases-free-tier) — permanent, 0.5 GB, scale-to-zero after 5 min.
- [Koyeb free tier status](https://www.srvrlss.io/provider/koyeb/) — Starter withdrawn post-acquisition; $29/mo entry.
- [DigitalOcean droplet pricing](https://www.digitalocean.com/pricing/droplets) — 2 GB/1 vCPU at $12/mo, backups 20% weekly.
- Hetzner CX availability and US CPX pricing: sources contradicted each other by 3×; treated as unverifiable rather than reported as fact.
