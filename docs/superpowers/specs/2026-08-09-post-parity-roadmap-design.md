# Post-Parity Roadmap — P6, P7, P8 Design

**Date:** 2026-08-09
**Status:** Approved for planning
**Scope:** What comes after the origin-parity program (`docs/superpowers/specs/2026-07-30-origin-parity-design.md`, P1–P5, shipped and merged to `main` as of this writing). That spec explicitly caps itself at P1–P5; it does not define a P6. This document does, drawing on the three M0 milestones the origin-parity program left untouched (`docs/superpowers/plans/2026-07-24-m0-foundation.md` §roadmap): M10 auth hardening, M11 plugin system, M12 mobile/PWA. Their old M-numbers are kept as parenthetical references; execution order is P6/P7/P8.

---

## 0. Ordering, and why

Three independent milestones, none blocking another. Sequenced by risk-adjusted value, not by old M-number:

1. **P6 — Auth hardening (M10).** The origin-parity program just added an encrypted document vault, tax exports, and a broader AI tool surface — the blast radius of a session hijack or a missing CSRF check is materially larger now than when M0 shipped `SameSite=Lax` as a stopgap. Security work compounds in value the longer it's deferred and shrinks in cost the sooner it lands, before more surface area is built on top of the current session model. Goes first.
2. **P7 — Mobile/PWA (M12).** Directly builds on the `NAV`/`MoreMenu` responsive work P2 already did. Highest user-facing return for the effort of the three — installable, works offline for reads, no new architecture. Goes second so it ships while the mobile nav work is still fresh context.
3. **P8 — Plugin system (M11).** The biggest architectural bet of the three, and the one whose need is least established: this is a self-hosted, one-household app with no marketplace, no third-party developers, and no current feature that's blocked on lacking an extension point. Building a sandboxed plugin boundary speculatively is the exact shape of thing this codebase's own stated constraints (`PLAN-CONSTRAINTS.md`: "no abstraction with one implementation") warn against. It goes last, and **§5.3 below is a scope check to run before writing its implementation plan, not a green light**.

Each phase gets its own implementation plan, written via `superpowers:writing-plans` immediately before that phase starts — mirroring how P1–P5 worked. This document specs what each phase is, at the depth the original program's spec used per phase; it is not a task-by-task plan.

---

## 1. What already exists (verified against the tree, 2026-08-09)

| Capability | Where |
|---|---|
| Auth — email+password, argon2id hashing, server-side sessions (30-day TTL, sha256-hashed token in a cookie) | `backend/app/services/auth.py`, `app/models/session.py`, `app/core/security.py` |
| `Role` enum with `owner`/`member`/`viewer` already defined on `User`, but **no code path checks it and no invite/join flow exists** — `auth.register` always creates a brand-new household with the registrant as `owner`, so `member`/`viewer` can never be assigned today | `backend/app/models/user.py:11-14`, `backend/app/services/auth.py:24-38` |
| `LOCAL_MODE` — single-household desktop mode, zero authentication, gated to `ENVIRONMENT=development` | `backend/app/main.py:33-40`, `app/api/deps.py:_local_user` |
| CSRF mitigation — `SameSite=Lax` cookie only, no double-submit token anywhere in `app/` | grep of `app/` for `csrf`/`CSRF`/`SameSite` — zero hits beyond cookie config |
| Rate limiting — `slowapi` `Limiter`, keyed by remote address, backed by Redis | `backend/app/api/deps.py:14` |
| Responsive nav — four fixed tabs + `MoreMenu` overflow, documented ceiling at 72px/tab on a 360px phone | `frontend/src/ui/Shell.tsx`, `PLAN-CONSTRAINTS.md` §Navigation |
| PWA — nothing. No `manifest.json`, no service worker, no `vite-plugin-pwa` in `package.json`, no install prompt handling | `frontend/index.html`, `frontend/vite.config.ts`, `frontend/package.json` |
| Extension points — none. No plugin loader, no hook registry, no dynamic import boundary anywhere in `backend/app` or `frontend/src` | whole-tree grep for `plugin`/`extension` — zero hits outside `node_modules` |

---

## 2. P6 — Auth hardening (M10)

**Depends on:** nothing. Touches `app/services/auth.py`, `app/api/deps.py`, `app/models/user.py`, `app/models/session.py`, and the frontend's login/session flow. Independent of P7/P8.

**Purpose:** close the gaps M0 explicitly deferred, and turn the `Role` enum from a decoration into an enforced boundary — without inventing auth infrastructure a one-household-per-user app doesn't need (no org-level RBAC, no SSO/SAML).

### 2.1 CSRF — double-submit token

`SameSite=Lax` blocks classic cross-site form CSRF but not same-site subdomain attacks or older browsers. Add the double-submit pattern M0 deferred, as an **ASGI middleware** rather than a per-route `Depends` — a route-level dependency can't cleanly see the HTTP method to skip GETs, and a middleware is one place a new mutating endpoint can't forget to wire up:

- On any response where the `csrf_token` cookie is missing, the middleware issues one — a random token, non-httpOnly (the frontend must read it), `SameSite=Lax`. No separate `GET /auth/csrf` endpoint: the first page load already fires a GET (`/auth/me`), so the cookie exists before any form could submit.
- Every mutating request (`POST`/`PATCH`/`PUT`/`DELETE`) must carry `X-CSRF-Token` matching the cookie (`secrets.compare_digest`), or the middleware returns 403 before the route ever runs.
- Exempt paths: `/auth/register`, `/auth/login`, `/auth/join` (§2.4) — none of them has a session yet to protect, and the double-submit pattern has nothing to compare until one exists.
- `LOCAL_MODE` skips the whole check: no cross-origin risk when there's no session to steal.
- Frontend: `frontend/src/api/client.ts`'s single `apiFetch` reads the cookie and attaches the header for every non-GET call. One choke point — every mutation in the app already routes through it.

### 2.2 Session hardening

- **Rotation on privilege-relevant events.** Re-issue the session token (not just extend `expires_at`) on password change and on login itself, invalidating the old one. `resolve_session` already looks up by hash; rotation is `issue_session` + delete the old row, not new machinery.
- **Session list + revoke.** `GET /auth/sessions` (current sessions for the user, with `created_at`/last-seen-ish metadata already on `UserSession`), `DELETE /auth/sessions/{id}` to revoke one, `DELETE /auth/sessions` to revoke all but the current. This is the "session management UI" M0's roadmap named.
- **Absolute + idle timeout.** `UserSession` gains `last_seen_at`; `resolve_session` refuses a session idle past a shorter window (e.g. 14 days) even inside the 30-day absolute TTL. Both are config, not a magic number buried in the function.

### 2.3 2FA (TOTP)

- `users` gains `totp_secret` (nullable, envelope-encrypted at rest with the same AES-GCM scheme `app/core/encryption.py` already provides for provider credentials and P5's documents — not a new crypto path) and `totp_enabled`.
- `POST /auth/2fa/enroll` returns a provisioning URI (`pyotp`-shaped, but **no new dependency** — TOTP is HMAC-SHA1 over a 30-second counter, implementable in stdlib `hmac`/`hashlib`/`base64` in under 30 lines; check this against `PLAN-CONSTRAINTS.md`'s "no new dependencies" before reaching for a library).
- `POST /auth/2fa/verify` confirms enrollment with a code; `POST /auth/login` becomes two-step when `totp_enabled` is true — password first, then a short-lived pre-auth token exchanged for a real session on a correct code.
- **Cut: backup/recovery codes.** Real value, but it's a second secret-storage path with its own consumption/regeneration lifecycle — worth its own follow-up once TOTP itself is proven out, not bundled into the same phase.

### 2.4 Household invites, and RBAC that actually means something

**Correction to this spec's first draft:** `Role` (`owner`/`member`/`viewer` — `backend/app/models/user.py:11-14`) exists on every `User` row, but verified against the tree, there is no invite or join flow anywhere. `auth.register` always creates a **new** household and makes the registrant its `owner` (`backend/app/services/auth.py:24-38`). `member` and `viewer` are enum values nothing has ever assigned. RBAC enforcement without a way to reach a second role would be gates a test can exercise only by hand-constructing a `User(role=member)` row — dead code from every real user's perspective. P6 builds the invite flow so the gates it also builds are reachable.

**Invites — a shareable link, not an email.** No SMTP or mail-sending infrastructure exists anywhere in the app, and this is a self-hosted, single-operator product whose own login page already pitches "no third party watching your spending" — adding a mail relay dependency for one feature cuts against that. The owner generates a link and shares it themselves (Slack, text, whatever they'd already use).

```
household_invites
  id, household_id (FK, indexed)
  role         enum: member                 -- see below on why `viewer` isn't offered here
  token_hash   text (sha256, same pattern as UserSession.token_hash)
  created_by   UUID FK users
  expires_at   timestamptz          -- 7 days
  used_at      timestamptz NULL
  created_at
```

- `POST /auth/invites` (owner-only, no body — every invite is `role=member`) → creates a row, returns the **raw** token once (never stored, never retrievable again — same shape as an API key). The frontend renders it as a copyable link: `{origin}/join/{token}`.
- `GET /auth/invites` (owner-only) → pending invites: role, created_at, expires_at, used_at.
- `DELETE /auth/invites/{id}` (owner-only) → revoke an unused invite.
- `POST /auth/join {token, email, password}` → validates the token (exists, unexpired, unused), creates the `User` **in the invite's `household_id`** with role `member` — `auth.register` with the household supplied instead of created — marks `used_at`, issues a session. Exempt from CSRF (§2.1): no session exists yet.

**RBAC.** `member` reads everything in the household and writes the day-to-day (transactions, categories, budgets, goals) — the role this phase makes reachable. Only `owner` can: manage invites, revoke another user's sessions, delete the household, manage provider connections (bank credentials), reach the document vault and tax export (P5), read the audit log (§2.7). One dependency, `require_owner`, same shape as the existing `require_household` — added at each gated route, not a general policy engine. A permissions matrix table is **cut**: two reachable roles and a dozen or so owner-gated endpoints don't justify one.

**`viewer` is cut from this phase, not wired up.** The enum value already exists on `Role` (`backend/app/models/user.py:13`) from before this plan, but making it mean "read, never write" honestly requires a `require_writer` check added to every mutating endpoint across the whole app — accounts, transactions, categories, budgets, goals, connections, documents, everything — which is a cross-cutting change well past "make the invite flow reachable" and was not part of the design this spec's own §0 scoped. `POST /auth/invites` only ever issues `member` invites; `viewer` stays an enum value nothing assigns, same as today, until it's its own scoped phase.

### 2.5 OAuth providers — cut from this phase

Real value, explicitly named in M0's roadmap, and explicitly deferred here: it's a third-party integration (Google/GitHub OAuth app registration, redirect URI management, token exchange) that's a project of its own, and this is a self-hosted app where the operator already controls who has an account. Revisit as its own phase if multi-provider login becomes an actual ask rather than a roadmap leftover.

### 2.6 Passkeys — cut from this phase

Same reasoning as OAuth, doubled: WebAuthn is a genuinely large surface (attestation, credential storage, platform authenticator quirks) for a self-hosted app that just got a working 2FA story in §2.3. Not blocking; not this phase.

### 2.7 Audit log

- `audit_events` table: `id`, `household_id`, `user_id`, `action` (text — `"session.revoked"`, `"invite.accepted"`, `"vault.document_downloaded"`, `"connection.deleted"`, etc.), `metadata` (JSONB, small), `created_at`. Append-only, no update path.
- Write calls added at the small set of sensitive points: login, session revoke, invite created/revoked/accepted, 2FA enrolled, document download/delete, provider connection add/delete. Not every mutation — a log of every `PATCH /transactions/{id}` is noise, not audit trail.
- `GET /audit-log?since=&action=` — owner-only, paginated.

**Tests** — CSRF rejected without token / with mismatched token, CSRF skipped in `LOCAL_MODE` and on `/auth/register`/`/auth/login`/`/auth/join`, session rotation invalidates the old token, idle timeout rejects a stale-but-not-expired session, TOTP enroll→verify→login round trip, wrong TOTP code rejected with rate limiting (reuse the existing `slowapi` limiter, don't build a second one), an expired or already-used invite token is rejected, a joined `member` lands in the inviting household (not a new one) and is blocked from an owner-only route with 403 not 500, audit log entries carry no plaintext secrets.

**Cut, restated:** OAuth, passkeys, backup codes, a general permissions matrix, per-field audit diffing, `viewer` enforcement (§2.4), email delivery of invites.

---

## 3. P7 — Mobile / PWA (M12)

**Depends on:** nothing new — builds on P2's `Shell.tsx`/`MoreMenu` responsive work, already shipped.

**Purpose:** installable on a phone home screen, usable read-only with a flaky or absent connection, and the mobile nav's one known pre-existing bug (`mobile.spec.ts`'s heading strict-mode violation, on `main` since before P1) gets fixed as part of the same pass rather than carried forward a third time.

### 3.1 PWA installability

- `frontend/public/manifest.json` — name, icons (the existing `icons.svg` sprite already has what's needed; export the sized PNGs a manifest requires), `display: "standalone"`, theme color matching the existing Tailwind palette.
- `vite-plugin-pwa` is a **new dependency** — flag it against `PLAN-CONSTRAINTS.md`'s "no new dependencies" rule and check first whether a hand-rolled `service-worker.js` registered from `main.tsx` covers what's actually needed (cache-first for the app shell, network-first for API calls) before reaching for the plugin. Given this app's entire API surface is same-origin JSON, the honest answer is likely a ~40-line hand-written service worker beats a dependency for a one-time need — default to that unless the hand-rolled version turns out to fight the Vite build in a way the plugin solves cleanly.
- Install prompt: capture `beforeinstallprompt`, surface a dismissible banner, not a modal.

### 3.2 Offline read cache

- Service worker caches: the app shell (JS/CSS bundle, already content-hashed by Vite) cache-first; GET API responses (`/accounts`, `/transactions`, `/budgets/*`, `/goals`, `/reports/*`) network-first with a cache fallback, keyed by URL.
- **No offline writes, no background sync, no queue.** A write attempted offline fails visibly with "you're offline" rather than silently queuing — this app moves financial data, and a queued mutation that replays against a since-changed balance is a correctness bug waiting to happen, not a feature. The existing TanStack Query error states (already used everywhere per the P3 final-review fixes) carry this UI for free.
- A small "offline — showing cached data as of {time}" banner, driven by `navigator.onLine` plus a TanStack Query `onError` check for a network failure specifically (vs. a 4xx/5xx, which should still surface as a real error).

### 3.3 Mobile nav — fix the pre-existing bug in the same pass

`frontend/e2e/mobile.spec.ts` fails on `main` today: `getByRole("heading", { name: "Accounts" })` matches both `AccountsPage`'s `<h1>` and its "Your accounts" card `<h2>`. `PLAN-CONSTRAINTS.md` and `TASK.md` have both carried this forward as "not yours" since P1. P7 touches every mobile-facing surface anyway — fix it here: either the test narrows to `{ name: "Accounts", exact: true }` (already how the failure message shows the correct locator) or the card heading gets a more specific accessible name. The test file already documents the exact fix; it was never blocking, just never anyone's stated job.

### 3.4 Responsive polish

- Audit every page at 360px width (the same floor `PLAN-CONSTRAINTS.md`'s nav ceiling assumes) — this is a pass over existing pages, not new pages. Likely findings: table-heavy views (`ReportsCards.tsx`, transaction lists) needing a card layout below a breakpoint, form inputs needing larger tap targets.
- No new component library, no CSS framework beyond the Tailwind already in use.

**Cut:** React Native / a real native app (explicitly deferred in M0's own roadmap note — "React Native later, reusing the same API"), push notifications (needs a service worker *and* a server-side push subscription store — real scope, not a line item here), background sync for offline writes (§3.2).

**Tests** — manifest is valid JSON and installable per Lighthouse's PWA checklist, service worker serves the app shell when the network is mocked offline (Playwright's `context.setOffline(true)`), API cache falls back correctly, `mobile.spec.ts` passes for the first time since before P1, a 360px viewport pass across Overview/Accounts/Transactions/Budgets/Goals/Reports with no horizontal scroll.

---

## 4. P8 — Plugin system (M11)

**Depends on:** nothing technical. Depends on a real answer to §5.3 first.

**What M0's roadmap said:** "Extension boundary decision (subprocess/WASM sandbox), plugin API for importers/reports/providers/dashboards/AI tools/notifications."

### 4.1 Why this is scoped differently from P6/P7

P6 and P7 fix or extend something that demonstrably exists and is used today (a real session model, a real responsive nav). A plugin system is infrastructure for extension points **nothing currently needs** — every importer, report, provider, and AI tool this app has was built as a first-class module in `app/services/`, not as a plugin, and every one of them works. Building a sandboxed extension boundary now is optimizing for a future third-party developer ecosystem that doesn't exist for a self-hosted, single-household app with no marketplace and no announced intent to build one.

### 4.2 If it proceeds anyway — shape of the design

- **Extension points, in priority order if this is scoped down rather than cut:** CSV importers (different banks export different columns — this is the one place a plugin boundary would see real, current pain, since `services/csv_import.py` already special-cases formats) and report definitions (a user-authored report over their own data is low-risk: read-only, sandboxed by the query surface it's given, not by process isolation).
- **Sandbox:** subprocess with a strict stdin/stdout JSON protocol and a wall-clock/memory limit, not WASM — WASM buys safety this threat model (a user running plugins on their own self-hosted instance, against their own data) doesn't obviously need, at real toolchain cost (a WASM runtime is squarely a "new dependency" `PLAN-CONSTRAINTS.md` would flag). A misbehaving plugin should be able to hang or crash itself, never touch the database directly, never see another household's data (moot in a single-household deployment, but the code shouldn't assume that forever) and never make an outbound network call unless the specific plugin kind requires it (a provider plugin necessarily does; a report plugin shouldn't).
- **API surface:** plugins get a narrow, versioned, read-mostly interface — for a CSV importer, raw file bytes in, normalized transaction rows out, no database handle at all. For a report, a typed query function over the household's own data, no raw SQL.
- **Distribution:** local filesystem drop-in (`~/.openfinance/plugins/`), no registry, no auto-update, no signing infrastructure — each of those is its own project once there's evidence anyone but the app's own maintainer writes a plugin.

### 4.3 Cut, pending §5.3

Dashboard plugins, notification plugins, AI-tool plugins (P4's tool registry is explicitly closed — `PLAN-CONSTRAINTS.md`'s "no mutation tools" constraint gets much harder to guarantee once a third party can register one), a plugin marketplace, signed/verified plugins, hot-reload.

---

## 5. Cross-cutting

### 5.1 Migrations

One Alembic revision per phase, same as P1–P5. P6 adds `totp_secret`/`totp_enabled` to `users`, `last_seen_at` to `sessions`, and the new `audit_events` table. P7 adds no schema. P8, if it proceeds, likely needs none either (plugin registration can live on disk, not in Postgres, for a single-operator install).

### 5.2 Nothing new in the dependency tree, by default

Same standing rule as P1–P5. P6's TOTP and P7's service worker are both flagged above as "check stdlib/hand-rolled first" specifically because they're the two places in this roadmap most likely to tempt a new dependency. P8's WASM-vs-subprocess call in §4.2 is the same question at higher stakes.

### 5.3 Before writing P8's implementation plan

Answer in writing, as part of that plan's own opening section (the way this document's §0 answers "why this order"): what specific current pain does a plugin boundary solve that a first-class module in `app/services/` doesn't? If the honest answer is "none yet, but Origin's roadmap had one," that's grounds to defer P8 indefinitely rather than build it — re-read `PLAN-CONSTRAINTS.md`'s house style and `docs/superpowers/specs/2026-07-30-origin-parity-design.md` §4's "even better" claims before starting; nothing there asks for extensibility, and speculative infrastructure is the one thing every phase before this one was deliberately built to avoid.

## 6. Sequencing

| Phase | Old roadmap slot | Depends on | Blocks |
|---|---|---|---|
| P6 Auth hardening | M10 | — | — |
| P7 Mobile / PWA | M12 | — | — |
| P8 Plugin system | M11 | A written answer to §5.3 | — |

Not strictly sequential the way P1–P5 were (no phase's data model depends on another's) — P6 and P7 could run in parallel across two sessions if that's ever useful. They're written and executed in the order above because that's the order of value, not because P7 needs P6.
