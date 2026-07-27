# OpenFinance — "Make it like Rocket Money" — Decomposition & First Sub-Project Design

**Date:** 2026-07-26
**Status:** Draft for review
**Scope:** Decompose the request "make it like Rocket Money and all its premium features and
other premium features of other finance apps as well" into shippable sub-projects, and design
**one** of them in full. Sub-projects 2–6 get their own specs later; they are deliberately
sketched only.

---

## 0. How to read this

The request is roughly twelve products. This document does four things:

1. States what the app already does, with the file that does it, so nothing is rebuilt.
2. Enumerates what the paid tiers of the real apps actually sell.
3. Triages each of those against **what data this app can obtain** — a read-only SimpleFIN
   feed of balances and transactions. Several headline premium features are not software
   problems at all and are recommended for outright deletion from scope.
4. Designs the highest value-per-effort sub-project properly.

Governing constraints, restated because they decide most of the calls below:

- One household. Self-hosted. Postgres + Redis + FastAPI + React, already running.
- Money is `Decimal` in Python and `Numeric(19, 4)` in Postgres. Never float.
- Laziest thing that works. No feature flags, no plugin seams, no abstraction with one
  implementation. Every "we might later want…" is cut and recorded as cut.
- The LLM (`backend/app/providers/llm.py`) exists and is optional. It phrases; it never
  calculates. Detection logic below is deterministic arithmetic and stays that way.

---

## 1. Inventory — what the app does today

Verified by reading every file in `backend/app/{services,api,models,providers,schemas,core}`
and `frontend/src/**`. "Partial" means the mechanism exists but is not reachable by a user.

### Backend — shipped and reachable

| Capability | What it actually does | File |
|---|---|---|
| Households + tenancy | Every financial row carries `household_id`; services filter on it | `backend/app/models/household.py`, every service |
| Email/password auth | argon2id hashing, opaque server-side sessions, `/auth/me` | `backend/app/services/auth.py`, `backend/app/api/auth.py` |
| Local mode | No login at all; one implicit household created on first request | `backend/app/api/deps.py` |
| Rate limiting | slowapi over Redis on register/login | `backend/app/api/deps.py` |
| Accounts CRUD | 9 account types, create/list/update/delete; delete cascades txns + snapshots | `backend/app/services/accounts.py`, `backend/app/api/accounts.py` |
| Asset/liability netting | `LIABILITY_TYPES` = credit_card, loan, liability | `backend/app/services/snapshots.py` |
| Transactions CRUD | create/list/update/delete; filter by account, `since`, `until`, merchant `ilike` search | `backend/app/services/transactions.py`, `backend/app/api/transactions.py` |
| CSV import | `date,amount,merchant` columns; dedup via sha256 of the row as `external_id` | `backend/app/services/csv_import.py`, `backend/app/api/imports.py` |
| SimpleFIN bank feed | Claim setup token → durable access URL, encrypted at rest; fetch accounts + transactions; account-type guessing from the bank's name; demo-token flagging | `backend/app/providers/simplefin.py` |
| Credential encryption | AES-GCM envelope encryption, AAD bound to household + provider | `backend/app/core/encryption.py`, `backend/app/providers/base.py` |
| Sync + dedup | Provider-agnostic; dedups on `external_id` **and** on (account, day, amount, merchant) shape counts, so re-issued ids don't multiply rows. First sync pulls 365 days | `backend/app/services/sync.py` |
| Connections | Link / list / sync (`full=true` re-pulls a year) / forget | `backend/app/services/connections.py`, `backend/app/api/connections.py` |
| Background loop | asyncio timer in the API process: sync every connection every `SYNC_INTERVAL_HOURS` (default 6), then capture snapshots | `backend/app/core/scheduler.py` |
| Daily balance snapshots | One row per account per day, idempotent, re-capture overwrites | `backend/app/services/snapshots.py`, `backend/app/models/snapshot.py` |
| Net worth over time | `net_worth_series(days, types=…)` → assets/debts/net per captured day | `backend/app/services/snapshots.py`, `GET /snapshots/net-worth` |
| Investments summary | Portfolio value, per-account share, dividend/interest income (keyword heuristic over descriptions), YTD contributions, income by month | `backend/app/services/investments.py`, `GET /investments`, `GET /investments/history` |
| Financial digest | Computed facts: net worth, 30-day change, per-month income/spending, top 12 merchants, 8 largest transactions, recurring candidates, investments block | `backend/app/services/digest.py`, `GET /insights/digest` |
| AI assistant | Digest → Claude with a "every figure must come from the JSON" system prompt; hidden entirely without an API key | `backend/app/services/insights.py`, `backend/app/api/insights.py` |

### Frontend — shipped and reachable

| Capability | What it does | File |
|---|---|---|
| App shell | Desktop sidebar + **mobile bottom tab bar** (4 tabs), safe-area padding, `Card`/`PageHead`/`Empty` primitives | `frontend/src/ui/Shell.tsx` |
| API client | Derives host from `window.location`, so LAN/Tailscale work unchanged | `frontend/src/api/client.ts` |
| Overview | Net worth hero, month in/out/net stats, net-worth area chart, 6-month cash-flow bars, top-5 merchants, recent activity, assistant card | `frontend/src/pages/OverviewPage.tsx` |
| Accounts | List with balances, add form, delete with confirm, per-account detail | `frontend/src/pages/AccountsPage.tsx`, `AccountDetailPage.tsx`, `frontend/src/accounts.tsx` |
| Investments | Value, allocation bar, income by month, recent income rows, history chart | `frontend/src/pages/InvestmentsPage.tsx` |
| Transactions | Manual entry form, CSV upload, merchant search box, flat list | `frontend/src/pages/TransactionsPage.tsx`, `frontend/src/transactions.tsx` |
| Connections UI | Connect SimpleFIN, sync now, demo-data warning, forget | `frontend/src/connections.tsx` |
| Charts | Measured-SVG `AreaChart`, `BarChart`, `AllocationBar` with hover readouts | `frontend/src/charts.tsx` |
| Palette | 5 CVD-validated categorical colours + accent + "Other" grey | `frontend/src/palette.ts` |
| Money formatting | `usd`, `usdCompact`, `signed`, net worth, monthly series, top merchants (presentation only — arithmetic stays server-side) | `frontend/src/money.ts` |

### Partial — mechanism exists, user cannot reach it

| Thing | Reality |
|---|---|
| **Categories** | `categories` table and `transactions.category_id` FK exist (`backend/app/models/category.py`, migration `199492b35732`). There is **no** category service, **no** API router, **no** seeded system taxonomy, and **no** UI. `TxnCreate`/`TxnUpdate` accept a `category_id` you have no way to obtain. Effectively: the app has no categorization. |
| **`merchant_normalized`** | Column exists and is read preferentially by `digest.py` and `investments.py`, but nothing ever writes it except a manual `PATCH /transactions/{id}`. In practice always `NULL`. |
| **Recurring detection** | Exists *only* as an inline block inside `digest.py` (≥3 distinct months, ≤2 distinct amounts, ≥3 charges → `recurring_candidates`). It is never persisted, never shown in the UI, and only ever fed to the LLM. No cadence, no next-expected date, no amount tracking. |
| **Roles** | `Role.owner/member/viewer` exists on `User` but is never checked anywhere. There is no invite flow. Everyone in a household is effectively an owner. |

### Genuinely absent

Budgets. Savings goals. Rules/auto-categorization. Split transactions. Tags. Bulk edit. Any
transaction filter in the UI beyond merchant text. Pagination (`useTransactions()` fetches the
entire history on every page load). Cash-flow forecasting. Alerts or notifications of any kind.
Data export. Reports. Investment holdings or cost basis. Duplicate/refund detection.
Multi-user invites.

---

## 2. The premium feature landscape

What the paid tiers actually sell, per app. One line each on what it does for the user.

### Rocket Money Premium (~$6–12/mo, user-chosen price)

| Feature | What it does |
|---|---|
| Recurring/subscription detection | Finds repeating charges, shows a bill calendar, tells you the monthly total you're committed to |
| **Subscription cancellation** | Rocket Money's staff cancel the subscription for you — emails, letters, phone calls |
| **Bill negotiation** | Rocket Money's staff phone your cable/phone/internet provider and argue the bill down; they keep 35–60% of the first year's savings |
| Unlimited budgets & categories | Free tier caps them; premium removes the cap |
| **Smart Savings** | An FDIC-insured account at a partner bank that auto-transfers money you set aside |
| **Credit score monitoring** | VantageScore from TransUnion, refreshed, with score-change alerts |
| Net worth tracking | Assets minus liabilities over time |
| Spending insights | Category breakdowns, month-over-month changes, "you spent more on X" |
| Balance & spending alerts | Low balance, large purchase, bill due, upcoming charge |
| Custom categories & auto-categorization | Rename/create categories; charges from a merchant land in the right one automatically |
| Transaction search & filters | Find by merchant, amount, date, account, category |
| Data export | CSV of transactions |
| Concierge / premium chat | A human answers your questions |

### Monarch Money (~$100/yr, no free tier)

Flexible budgeting with category groups and **rollover** of unspent amounts · goals (savings,
debt payoff) with progress tracking · investment holdings, allocation and performance vs a
benchmark · net worth history · recurring detection with a bill calendar · a **rules engine**
(if merchant contains X, categorize as Y, rename to Z) · **transaction splits** · **household
collaboration** — invite a partner, shared view, separate logins · custom categories and tags ·
cash-flow reports including Sankey · Zillow home-value integration for property assets · CSV
export · configurable alerts.

### Copilot Money (~$95/yr, Apple-only)

Categorization that **learns from your corrections** · recurring detection · budgets with
rollover · investment tracking with cost basis · net worth · rules · **cash-flow forecast to
end of month** · anomaly surfacing ("this is unusual for this merchant") · receipts and
annotations on transactions · Apple Card / Apple Cash import · CSV export.

### YNAB (~$109/yr)

**Zero-based budgeting** — every dollar assigned to a category before it can be spent ·
envelope categories that carry balances forward month to month · **targets** (save $X by date,
spend $Y monthly) · overspending must be covered from another category, enforced · scheduled
transactions · splits · reports: spending trends, income vs expense, net worth · loan planner ·
multi-user sharing · CSV export.

### Empower Personal Dashboard (free tool, monetized by advisory)

Net worth · **investment fee analyzer** (finds expensive funds in your 401k) · asset-allocation
analysis vs a target · retirement planner with Monte Carlo · cash flow · light budgeting ·
savings planner · **human advisor access** above an asset threshold.

### Quicken Simplifi (~$3–6/mo)

**Spending plan** — projected cash left at end of month after known bills and typical spending ·
savings goals with automatic set-asides · watchlists (cap a category, watch it) · recurring
detection · custom categories and tags · reports · refund tracking · alerts · investment
tracking.

### Mint's successors (Credit Karma, NerdWallet, Monarch)

Net worth · spending by category · **free credit score and report** · bill reminders ·
credit-building and refinance **offers** (this is lead-gen, and is how they're funded).

### Cross-cutting premium features named in the request

Recurring-subscription detection and cancellation · bill negotiation · budgeting (zero-based
and flexible/rolling) · net worth over time · cash-flow forecasting · custom categories and
rules · split transactions · transaction search and bulk edit · savings goals · spending
insights and anomaly alerts · credit score monitoring · alerts and notifications · multi-account
household sharing · data export.

---

## 3. Feasibility triage

The only inputs this app can obtain are: **SimpleFIN account balances**, **SimpleFIN
transactions** (date, amount, payee/description, provider id), **manually entered accounts and
transactions**, **CSV imports**, and its **own daily balance snapshots**. Everything below is
judged against that.

### BUILDABLE — from data already held, or a cheap addition

| Feature | Verdict / notes |
|---|---|
| **Recurring & subscription detection** | Buildable and already half-present. Pure arithmetic over transaction dates and amounts: group by normalized merchant, look at gaps between charges, look at amount stability. See §5. |
| Bill calendar / upcoming charges | Falls out of the above: `last_charged_on + median gap`. |
| Subscription **price-increase** detection | Falls out of the above: latest amount vs the median of prior amounts. This is a genuinely valuable Rocket Money feature and costs nothing extra. |
| "Ghost"/ended subscription detection | Falls out of the above: expected charge is overdue by more than a grace window. |
| Net worth over time | **Already shipped** (`snapshots.py`). Nothing to build. |
| Custom categories | Buildable. Table exists; needs a seeded taxonomy, CRUD, and UI. |
| Merchant normalization | Buildable, deterministic: lowercase, strip store numbers/reference digits/punctuation, drop common suffixes (`LLC`, `INC`, `#1234`, `POS DEBIT`). Column already exists. |
| Auto-categorization rules | Buildable. `if merchant matches X → category Y (+ rename to Z)`, applied on sync and on demand. Deterministic, no ML. |
| Auto-categorization *seed* guesses | Buildable with a keyword table (STARBUCKS→Coffee, SHELL→Gas). **This is the one place the LLM earns its keep**: a one-shot "here are my 300 distinct merchant names, propose a category for each" batch call, results written into rules the user can edit. Deterministic rules do the per-transaction work afterward; the LLM is never in the request path. |
| Budgeting — flexible/rolling | Buildable once categories exist: budget amount per category per month, plus carry-over of the unspent (or overspent) remainder. |
| Budgeting — zero-based (YNAB style) | Buildable but a *different product* with real UX weight (assigning every dollar, covering overspending from other categories, "to be budgeted" balance). Recommend shipping flexible/rolling first and treating zero-based as an optional mode later, or not at all. |
| Split transactions | Buildable: child rows referencing a parent, parent excluded from totals. Cheap schema addition. |
| Tags and notes | Buildable. `notes` already exists; tags are a text array column. |
| Transaction search & filters | Buildable; the API already supports `account_id`/`since`/`until`/`search`. Needs amount range, category filter, and a UI. |
| Bulk edit | Buildable: `PATCH /transactions/bulk` with a list of ids and one patch body. |
| Pagination | Buildable and increasingly necessary — the frontend currently loads all transactions. |
| Cash-flow forecasting | Buildable: known recurring charges in the window + trailing median of discretionary spend, projected against current balances. This is Simplifi's "spending plan" and Copilot's month-end projection. |
| Savings goals | Buildable: target amount, target date, linked account(s); progress from live balances and snapshot history. Cannot *move* money (see DROP). |
| Spending insights | Buildable: category totals, month-over-month deltas, largest movers, spend-vs-typical. |
| Anomaly alerts | Buildable deterministically: charge > k× the merchant's historical median; category spend > k× trailing average; a new never-seen merchant above a threshold. Do not reach for the LLM here — a threshold is explainable and free. |
| Alerts & in-app notification feed | Buildable. The scheduler loop already runs every 6h and is the natural evaluation point. |
| Email notifications | Cheap addition: SMTP settings in `config.py`. Push notifications are not — see NEEDS NEW DATA. |
| Multi-member household sharing | Buildable; mostly *already modelled*. Needs an invite flow and actual enforcement of `Role.viewer`. Low value for one household — recommend deferring. |
| Data export | Trivially buildable. CSV/JSON dump of transactions, accounts, snapshots. |
| Reports (income vs expense, trends, category/merchant analysis) | Buildable; largely re-presentation of digest data. |
| Duplicate-charge and refund detection | Buildable: same merchant, same amount, opposite signs or same day. |
| Sankey cash-flow diagram | Buildable, but it's a chunk of custom SVG for one picture. Low value-per-effort; recommend skipping. |

### NEEDS NEW DATA — name the missing source

| Feature | Missing data source |
|---|---|
| Investment **holdings**, share counts, cost basis | SimpleFIN reports balances only (this is already documented in `investments.py`). Needs **Plaid Investments** or **SnapTrade**. |
| Asset allocation by sector / geography / asset class | Needs holdings *plus* a **security-reference feed** (sector/asset-class mapping) — e.g. a market-data provider. |
| Performance vs benchmark, realized/unrealized gains, risk metrics | Needs holdings + **historical price data** (Yahoo Finance, Alpha Vantage, Tiingo). |
| Investment fee analyzer (Empower) | Needs holdings + a **fund expense-ratio dataset**. |
| Home value tracking (Monarch/Zillow) | Needs a **property valuation API**. Zillow's public API is retired; ATTOM/Estated are paid. **Recommendation: don't. A manual `asset` account already tracks a house, and the user can edit the number when they care.** |
| Vehicle value | Needs **KBB/Black Book**, both paid and licensed. Same recommendation: manual asset account. |
| Multi-currency | Needs an **FX rate feed**. Schema is already multi-currency-ready; no FX logic exists. Out of scope for one US household. |
| Real-time / at-swipe alerts | Needs an aggregator with **webhooks**. SimpleFIN is polled every 6 hours; the honest ceiling is "within 6 hours". Say so in the UI rather than implying instant. |
| Pending transactions | SimpleFIN's feed as consumed does not carry a pending flag. Needs a provider that exposes pending state. |
| Merchant logos / rich merchant enrichment | Needs an **enrichment API** (Plaid Enrich, Ntropy). Not worth it — `accounts.tsx` already renders initials in a tile and that reads fine. |
| Push notifications to a phone | Needs a **push service** (APNs/FCM) and a native app or PWA push registration. Email via SMTP is the cheap substitute. |
| Receipt capture / OCR | Needs **image upload + an OCR service**. |
| Crypto beyond what the bank feed shows | Needs **exchange APIs** (Coinbase, Kraken) or on-chain address indexing. |

### NOT BUILDABLE — drop, do not fake

These depend on a business the user is not running. Building a hollow version is worse than
building nothing, because it implies a service that will never arrive.

| Feature | Why it cannot exist here |
|---|---|
| **Bill negotiation** | This is a **call center**. Rocket Money employs humans who phone Comcast and argue, and takes 35–60% of the savings. There is no API, no protocol, no data source. It is a labour business wearing an app. **Drop entirely.** Do not ship a "negotiation tips" page pretending to be the feature. |
| **Subscription cancellation on your behalf** | Same shape: staff send cancellation emails, letters, and make calls; where that fails they lean on card-network controls the user doesn't have. A read-only SimpleFIN feed has **no write surface of any kind**. **Drop the "we cancel it" promise.** The honest, useful substitute — and the one this spec ships — is: detect the subscription, show its real cost, let the user paste the merchant's cancellation URL and mark it cancelled, then *verify from the transaction feed* that the charges actually stopped. That last part is real value and is genuinely buildable. |
| **Credit score & credit report monitoring** | Requires a contract with a bureau (TransUnion/Equifax/Experian), a demonstrated FCRA permissible purpose, and compliance obligations. There is no self-hosted path and no scraping path that isn't a terms violation. **Drop.** Point the user at AnnualCreditReport.com in a README line if anything. |
| **Identity theft / dark-web monitoring** | A vendor subscription resold. No data source. **Drop.** |
| **Smart Savings / auto-transfer to a high-yield account** | Requires being or partnering with a bank or money transmitter, plus a *write*-capable rail. SimpleFIN is read-only by protocol design. **Drop the transfer.** A savings *goal* that tracks progress against a real balance is buildable and is what ships instead. |
| **Bill pay** | Same: no write rail. **Drop.** |
| **Human concierge / advisor access** | It's a person. **Drop.** |
| **Refinance / insurance / credit-card offers** | Affiliate lead-generation. It is how Credit Karma is funded, and it is an anti-feature in a self-hosted app whose selling point is that nothing phones home. **Drop, permanently.** |
| **Instant at-swipe alerts** | Not a business problem but a physics one given a 6-hour poll. **Drop the word "instant"**; ship "next sync". |

**Net effect on scope:** four of Rocket Money's headline premium selling points (negotiation,
cancellation-as-a-service, credit score, smart savings) are not implementable and should be
struck from the roadmap now rather than lingering as perpetual "later" items.

---

## 4. Decomposition into sub-projects

Six units. Each is one spec, one plan, one branch, one merge. Each is independently useful if
the ones after it are never built.

### SP1 — Recurring & Subscriptions **(S/M)**

**Scope:** Detect repeating charges and income from existing transaction history (cadence +
merchant + amount stability). Persist them as first-class rows. Show a Recurring page: monthly
committed total, next-30-days bill calendar, per-series charge history. Flag price increases.
Flag series that have stopped. Let the user rename, ignore, or mark a series cancelled with the
merchant's own cancellation link. Replace the ad-hoc block in `digest.py` with a read of the
new table.

**Why it's a coherent unit:** it is the single feature Rocket Money is *known* for; it needs no
schema anywhere else; it uses only data already in the database; a partial heuristic already
exists to salvage; and it produces the input that cash-flow forecasting and bill alerts both
need later.

**Depends on:** nothing.

---

### SP2 — Categories, Merchant Normalization & Rules **(M)**

**Scope:** Seed a system category taxonomy (~30 categories, two levels). Category CRUD scoped
to household. Deterministic merchant normalization written into the existing
`merchant_normalized` column on sync and import. A rules table (`match merchant contains/regex
→ set category, optionally rename`), applied on sync and re-appliable to history. A one-shot
optional LLM pass that proposes rules for the user's distinct merchant list, which the user
edits and accepts — the LLM writes rules, never categorizes a transaction at request time.
Category assignment UI on the transaction list.

**Why it's a coherent unit:** categorization is a substrate. Budgets, spending insights, and
category reports are all meaningless without it, and all trivial once it exists.

**Depends on:** nothing hard. Benefits from SP1 shipping first only because SP1 exercises the
merchant-key logic that SP2 then persists.

---

### SP3 — Budgets **(M)**

**Scope:** Monthly budget amount per category, with rollover of the unspent/overspent
remainder. Progress bars, over-budget states, month navigation. "Typical spend" suggestion from
trailing history when setting a budget. Explicitly **flexible/rolling**, not zero-based.

**Why it's a coherent unit:** one table, one service, one page, one clear question ("am I
over?"). Zero-based budgeting is a different product and is cut (see §4 cuts).

**Depends on:** SP2 (categories).

---

### SP4 — Transaction Workbench **(M/L)**

**Scope:** Server-side pagination. Filter panel (date range, amount range, account, category,
uncategorized-only). Multi-select with bulk categorize / bulk tag / bulk delete. Split a
transaction into parts across categories. Tags. Editable notes. Duplicate and refund detection
surfaced inline.

**Why it's a coherent unit:** it is all one page and one data-access path; splitting it further
means touching the same list component three times.

**Depends on:** SP2 for category assignment to mean anything.

---

### SP5 — Cash-Flow Forecast & Savings Goals **(M)**

**Scope:** Project the next 30–60 days: current balances, plus known recurring income, minus
known recurring bills, minus trailing-median discretionary spend, with a low-point date and a
projected month-end figure. Savings goals: target amount and date against a linked account's
real balance, with required-monthly-contribution and on-track/off-track from snapshot history.

**Why it's a coherent unit:** both are forward-looking projections off the same two inputs
(recurring series + snapshots), and share a chart.

**Depends on:** SP1 (recurring series). Better with SP2/SP3 but does not require them.

---

### SP6 — Alerts, Insights & Export **(S)**

**Scope:** An `alerts` table and an evaluation pass hooked into the existing scheduler tick:
large charge vs merchant history, subscription price increase (from SP1), low projected balance
(from SP5), budget exceeded (from SP3), new never-seen merchant over a threshold, sync failure.
In-app notification feed with unread state; optional SMTP email. CSV/JSON export of
transactions, accounts, and snapshots.

**Why it's a coherent unit:** every alert is the same shape — a scheduled deterministic check
that writes a row — and export is small enough that it doesn't deserve its own project.

**Depends on:** SP1 for price-increase alerts, SP3 for budget alerts, SP5 for balance alerts.
Ships last because it harvests the others. Export has no dependency and can be pulled forward
if the user wants it sooner.

---

### Recommended build order

| # | Sub-project | Size | Depends on | Rationale for position |
|---|---|---|---|---|
| 1 | **Recurring & Subscriptions** | S/M | — | Highest value-per-effort by a distance. The flagship feature, no dependencies, no new data, a partial implementation already exists in `digest.py`, and it feeds SP5 and SP6. |
| 2 | Categories, Normalization & Rules | M | — | Substrate for SP3, SP4, and half of SP6. Nothing above it can be built well until it lands. |
| 3 | Budgets | M | SP2 | The second-most-asked-for feature across every app listed, and cheap once categories exist. |
| 4 | Transaction Workbench | M/L | SP2 | Highest effort, and its value compounds only after categories and budgets give the user a reason to bulk-edit. Also fixes the "loads all transactions" scaling problem. |
| 5 | Cash-Flow Forecast & Goals | M | SP1 | Genuinely differentiating (Simplifi's best feature), but it needs SP1's recurring series to be trustworthy first. |
| 6 | Alerts, Insights & Export | S | SP1/SP3/SP5 | Small, and mostly a harvest of everything above. Building it earlier means building it twice. |

### Cut from the whole programme (recorded so it isn't rediscovered)

- Zero-based/envelope budgeting — a second budgeting product; flexible/rolling covers the need.
- Sankey diagrams — a lot of bespoke SVG for one picture.
- Multi-user invites and role enforcement — one household; the models already exist if it ever matters.
- Multi-currency and FX — no source, no need.
- Plugin architecture, feature flags, provider abstractions with one implementation.
- Everything in the NOT BUILDABLE table.

---

## 5. Detailed design — SP1: Recurring & Subscriptions

Everything below is SP1. SP2–SP6 are not designed here.

### 5.1 What ships

A user opens **Recurring** and sees: how much they are committed to per month, what is charging
them in the next 30 days, and a list of every repeating charge with its cadence, typical
amount, and next expected date. Anything whose price went up is badged. Anything that stopped
charging is badged. They can rename a series, dismiss a false positive permanently, and record
that they cancelled something — after which the app tells them whether the charges actually
stopped.

It does **not** cancel anything, negotiate anything, or claim it can. The UI says so in one
line.

### 5.2 The detection heuristic

Deterministic, no ML, no LLM. Runs over the household's transactions from the last **18
months**.

**Step 1 — merchant key.** For each transaction, take `merchant_normalized or merchant_raw` and
reduce it to a stable key:

```
lowercase
strip a leading card-network/POS prefix ("pos debit ", "ach debit ", "sq *", "tst* ", "pp*")
drop any run of 3+ digits and any "#1234"-style store number
drop trailing legal suffixes (llc, inc, corp, co, ltd)
collapse non-alphanumerics to single spaces, trim
```

Keep this in the recurring service as a module-level `merchant_key(name: str) -> str`. It is
**not** written to the database in SP1 — SP2 owns `merchant_normalized`. Because the key is
computed from `merchant_normalized or merchant_raw`, SP2 improves this for free with no change
here.

**Step 2 — group.** Bucket transactions by `(merchant_key, sign(amount))`. Sign matters:
a paycheck and a refund from the same employer are different series. Collapse same-day
duplicates within a group to one charge (take the larger absolute amount).

**Step 3 — reject the obvious.** Fewer than **3** charges → not a series. Span shorter than
**21 days** → not a series.

**Step 4 — cadence.** Compute the day gaps between consecutive charges. Take the **median**
gap and classify it:

| Cadence | Median gap (days) |
|---|---|
| weekly | 5–9 |
| biweekly | 12–16 |
| monthly | 25–35 |
| quarterly | 80–100 |
| yearly | 350–380 |

A median outside every bucket → reject the group. Then measure tightness: the fraction of
individual gaps that also land in the median's bucket, **or** within a whole-multiple of it
(a missed month shows as ~60 days on a monthly series and must not disqualify it).

```
cadence_score = (gaps in-bucket + 0.5 × gaps at a whole multiple) / total gaps
```

Reject below `0.60`.

**Step 5 — amount stability.**

```
spread = (max(|amount|) - min(|amount|)) / median(|amount|)
amount_score = 1.0 if spread <= 0.05      # fixed price — Netflix
              0.8 if spread <= 0.25       # near-fixed — a gym with a fee
              0.5 if spread <= 1.00       # variable bill — electric, water
              reject otherwise
amount_varies = spread > 0.25
```

Variable bills are real recurring commitments and are kept, flagged, and shown with a range
rather than a single figure.

**Step 6 — confidence**, an integer 0–100, deterministic:

```
count_score  = min(charge_count, 6) / 6
confidence   = round(100 × (0.50×cadence_score + 0.30×amount_score + 0.20×count_score))
```

Persist only `confidence >= 55`. The threshold is a module constant with a comment saying it
was chosen to keep quarterly-with-one-miss in and coincidental same-amount pairs out.

**Step 7 — derived fields.**

- `typical_amount` = median of `|amount|` over all charges (Decimal, never float — use
  `statistics.median` on a sorted list of `Decimal`, which returns a `Decimal` for odd counts
  and the exact mean of two `Decimal`s for even ones).
- `last_amount`, `last_charged_on` = the most recent charge.
- `next_expected_on`: for monthly/quarterly/yearly, the same day-of-month advanced by 1/3/12
  months, clamped to the month's length (a 31st becomes the 30th in April). For
  weekly/biweekly, `last_charged_on + median_gap`.
- `status`:
  - `ended` when `today > next_expected_on + grace`, `grace = max(7, median_gap // 2)` days.
  - `active` otherwise.
  - `ignored` and `cancelled` are user-set and are never overwritten by detection.
- `price_increase_amount`: `last_amount - median(|amount| of all prior charges)`, stored only
  when it is `>= Decimal("1.00")` **and** `>= 10%` of that prior median. Otherwise `NULL`.

**Step 8 — upsert.** Key on `(household_id, merchant_key)`. Derived fields are overwritten
every run; `label`, `status` when user-set, `cancel_url`, and `notes` are sticky. Series that no
longer detect and were never user-touched are deleted; user-touched ones flip to `ended`.

Detection is **idempotent** and cheap enough to run whole (one household, a few thousand rows).
No incremental machinery.

### 5.3 Data model

New file `backend/app/models/recurring.py`:

```python
import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Cadence(str, enum.Enum):
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class SeriesStatus(str, enum.Enum):
    active = "active"
    ended = "ended"          # detection stopped seeing charges
    cancelled = "cancelled"  # the user says they cancelled it
    ignored = "ignored"      # the user says this isn't a subscription


class RecurringSeries(Base, UUIDMixin, TimestampMixin):
    """A repeating charge or deposit, inferred from transaction history.

    Derived columns are recomputed from scratch on every detection run; the user-owned
    ones (label, status, cancel_url, notes) survive it. That split is the whole reason
    the row is keyed on merchant_key rather than on an id detection invents each time.
    """

    __tablename__ = "recurring_series"
    __table_args__ = (
        UniqueConstraint("household_id", "merchant_key", name="uq_recurring_merchant"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    # The account most of the charges land on — informational, not a constraint. A card
    # that gets replaced moves the series without breaking it.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    merchant_key: Mapped[str] = mapped_column(String, index=True)
    label: Mapped[str] = mapped_column(String)  # user-editable; defaults to the raw name

    cadence: Mapped[Cadence] = mapped_column(Enum(Cadence, name="recurring_cadence"))
    status: Mapped[SeriesStatus] = mapped_column(
        Enum(SeriesStatus, name="recurring_status"), default=SeriesStatus.active
    )
    # Positive for money in (a paycheck), negative for money out. Sign is part of the
    # series identity, so the same employer's refund is a different row.
    direction: Mapped[int] = mapped_column(Integer)

    typical_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    last_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4))
    amount_varies: Mapped[bool] = mapped_column(default=False)
    # Set only when the latest charge is >= $1 and >= 10% above the prior median.
    price_increase_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(19, 4), nullable=True
    )

    charge_count: Mapped[int] = mapped_column(Integer)
    first_charged_on: Mapped[date] = mapped_column(Date)
    last_charged_on: Mapped[date] = mapped_column(Date)
    next_expected_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer)  # 0-100

    # Where the user goes to cancel. Pasted by hand — nothing knows this automatically.
    cancel_url: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
```

Register it in `backend/app/models/__init__.py` alongside the others.

**Deliberately absent:**

- **No `recurring_charges` join table and no FK on `transactions`.** The charges of a series are
  found by recomputing `merchant_key` over the household's transactions at read time. At one
  household's volume this is a single indexed query plus a string function — cheaper than
  maintaining a link table that detection would have to reconcile on every run.
- No `category_id` on the series. SP2 owns categories.
- No `provider` / `institution` denormalization.
- No soft-delete, no audit columns, no versioning.

### 5.4 Alembic migration

One revision, `recurring series`, `down_revision` = the current head (`d5f2c1a83b70` at time of
writing — confirm with `alembic heads` before generating).

Notes for whoever writes it:

- Autogenerate then hand-clean, matching `d5f2c1a83b70_balance_snapshots.py` (explicit
  `sa.Column` list, explicit `op.create_index`) rather than the raw autogen style of
  `199492b35732`.
- Two new Postgres enum types are created implicitly by `create_table`: `recurring_cadence` and
  `recurring_status`. The **downgrade must drop them explicitly** after `drop_table`, or a
  re-upgrade fails with "type already exists":

  ```python
  def downgrade() -> None:
      op.drop_table("recurring_series")
      sa.Enum(name="recurring_cadence").drop(op.get_bind())
      sa.Enum(name="recurring_status").drop(op.get_bind())
  ```

- Money columns are `sa.Numeric(19, 4)`, matching every other money column.
- Indexes: `household_id` and `merchant_key`, plus the unique constraint. Nothing composite —
  the table will hold tens of rows.
- No backfill. The first scheduler tick after deploy populates it; the Recurring page shows a
  "scanning…" empty state until then, and a **Rescan** button forces it immediately.

### 5.5 Service

New file `backend/app/services/recurring.py`. Follows the existing service shape: module-level
functions taking `(db, household_id, …)`, no HTTP, `@dataclass` result objects, docstrings that
explain *why* in the house style.

```python
LOOKBACK_DAYS = 548          # 18 months — enough to see a yearly charge twice
MIN_CHARGES = 3
MIN_CONFIDENCE = 55

@dataclass
class DetectionResult:
    detected: int
    updated: int
    ended: int
    removed: int

def merchant_key(name: str) -> str: ...

def detect(db: Session, household_id: uuid.UUID) -> DetectionResult:
    """Rebuild the household's recurring series from transaction history.

    Idempotent and whole-table: cheap enough at one household's volume that incremental
    detection would only add a reconciliation bug.
    """

def list_for(
    db: Session, household_id: uuid.UUID, *, status: SeriesStatus | None = None
) -> list[RecurringSeries]: ...

def get(db, household_id, series_id) -> RecurringSeries | None: ...

def charges(db, household_id, series: RecurringSeries) -> list[Transaction]:
    """Every transaction whose merchant key matches this series, newest first."""

def update(db, household_id, series_id, data: SeriesUpdate) -> RecurringSeries | None:
    """Rename, ignore, or mark cancelled. Detection never overwrites these."""

def monthly_committed(series: list[RecurringSeries]) -> Decimal:
    """Active outgoing series normalized to a per-month figure.

    Decimal throughout: weekly x 52/12, biweekly x 26/12, quarterly / 3, yearly / 12,
    quantized to cents at the end so the total doesn't drift.
    """
```

`monthly_committed` uses `Decimal` multipliers (`Decimal(52) / Decimal(12)`) and a final
`.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`. No floats anywhere in this module.

**Wiring:**

- `backend/app/core/scheduler.py` — `run_once()` calls `recurring.detect(db, household_id)`
  after `snapshots_service.capture(...)`, in its own `try/except` with a `log.warning`, matching
  how snapshot failures are already tolerated. One bad household must not stop the loop.
- `backend/app/services/digest.py` — **delete** the inline recurring-candidate block (the
  `for name, (_total, count) in ranked:` loop) and populate `digest.recurring_candidates` from
  `recurring.list_for(db, household_id, status=SeriesStatus.active)` instead, emitting
  `{merchant, typical_amount, cadence, next_expected_on, confidence}`. The digest's float
  convention (`_f`) is preserved at that boundary — the digest is LLM input, not a money API.
  The existing test `test_digest_flags_a_repeating_charge_as_recurring` must keep passing;
  it may need `recurring.detect()` called first in its setup.

### 5.6 API

New file `backend/app/api/recurring.py`, registered in `main.py` alongside the other routers.
New schemas in `backend/app/schemas/recurring.py`. Money fields are typed `Decimal` in Pydantic,
which serializes to a JSON **string** — matching `AccountOut.balance` and `TxnOut.amount`, and
matching the frontend's existing `balance: string` / `amount: string` types.

```
GET /recurring?status=active
```

```jsonc
[
  {
    "id": "…uuid…",
    "label": "Netflix",
    "merchant_key": "netflix",
    "account_id": "…uuid…",
    "cadence": "monthly",
    "status": "active",
    "direction": -1,
    "typical_amount": "15.4900",
    "last_amount": "17.9900",
    "min_amount": "15.4900",
    "max_amount": "17.9900",
    "amount_varies": false,
    "price_increase_amount": "2.5000",
    "charge_count": 11,
    "first_charged_on": "2025-09-14",
    "last_charged_on": "2026-07-14",
    "next_expected_on": "2026-08-14",
    "confidence": 92,
    "cancel_url": null,
    "notes": null
  }
]
```

`status` accepts `active` (default), `ended`, `cancelled`, `ignored`, or `all`.

```
GET /recurring/summary
```

```jsonc
{
  "monthly_committed": "412.3700",   // active outgoing, normalized to a month
  "monthly_incoming": "5200.0000",   // active incoming, same normalization
  "active_count": 14,
  "upcoming": [                       // next 30 days, soonest first
    { "id": "…", "label": "Netflix", "on": "2026-08-14", "amount": "17.9900" }
  ],
  "price_increases": 2,
  "last_detected_at": "2026-07-26T04:11:03Z"
}
```

```
GET /recurring/{id}
```

Returns the series object plus `"charges": [{ "id", "posted_at", "amount", "account_id" }]`,
newest first.

```
PATCH /recurring/{id}
```

Body: `{ "label"?, "status"?, "cancel_url"?, "notes"? }`. `status` may only be set to
`cancelled` or `ignored` (or back to `active`); `ended` is detection-owned and a request to set
it is a `422`. Returns the updated series. `404` if not in the household.

```
POST /recurring/refresh
```

Runs `detect` synchronously and returns `DetectionResult` as
`{ "detected", "updated", "ended", "removed" }`. Synchronous is fine — the work is a single
query plus in-memory grouping. If it ever isn't, Redis is already there.

**Cut:** no `/recurring/upcoming` endpoint (the summary carries it), no pagination, no bulk
operations, no calendar-feed (iCal) export.

### 5.7 UI

**Routing and shell.** New route `/recurring` in `frontend/src/App.tsx`, wrapped in
`<Protected>` like the others. Add to `NAV` in `frontend/src/ui/Shell.tsx`:

```ts
{ to: "/recurring", label: "Recurring", short: "Bills", end: false, glyph: "↻" }
```

This takes the mobile tab bar from four tabs to **five**. Each is `flex-1`, so on a 360 px
phone that's 72 px per tab — the existing `text-[11px]` labels and `text-base` glyphs fit, and
`short: "Bills"` is chosen to stay on one line. Verify on a 320 px viewport in the Playwright
run; if it crowds, drop the glyph line-height rather than the label.

**Files.** `frontend/src/pages/RecurringPage.tsx` (thin page, composes cards — like
`TransactionsPage.tsx`) and `frontend/src/recurring.tsx` (components + hooks — like
`transactions.tsx` / `accounts.tsx`). Data hooks go in `frontend/src/recurring.tsx` rather than
`data.ts`, since `data.ts` is the shared-across-pages set.

**Page layout (top to bottom, single column on mobile):**

1. `PageHead title="Recurring" sub="Repeating charges found in your history"`.
2. Three `Stat`-style cards in a `grid-cols-2 lg:grid-cols-3`: **Committed / month**,
   **Coming in / month**, **Active series**. Reuses the `Stat` pattern from
   `OverviewPage.tsx` — lift it into `ui/Shell.tsx` as a shared export in this sub-project,
   since a second page now needs it.
3. **Next 30 days** `Card`: rows of `date · label · amount`, soonest first. Empty state via
   `Empty`. This is the bill calendar; it is a list, not a grid — a month grid on a phone is
   twelve pixels per cell and unreadable.
4. **Price went up** `Card`, rendered only when `price_increases > 0`: label, old → new,
   delta in `text-clay`. This is the highest-value thing on the page; it sits above the
   full list.
5. **All recurring** `Card`: the series list, grouped `Money out` then `Money in`.

**Series row.** One row per series, tappable to expand in place (no route, no modal — a modal
on a phone is a step backwards):

```
[label]                         [typical amount]
[cadence · next 14 Aug]         [badges]
```

Badges: `↑ $2.50` for a price increase (`text-clay`), `ended` for a stopped series (`text-muted`),
`~` for `amount_varies` with a tooltip carrying the min–max range, and a small confidence dot
for anything under 75 so a shaky guess reads as a guess.

**Expanded detail** shows, in order: a `BarChart` from `frontend/src/charts.tsx` of the last 12
charge amounts (bars, not an area — charges are discrete events); the charge table reusing
`TxnRows` from `frontend/src/transactions.tsx`; and the actions row.

**Actions row** — rename (inline input), **Not a subscription** (`status: "ignored"`), and
**I cancelled this**, which reveals a field for the merchant's cancellation URL and sets
`status: "cancelled"`. Below it, one line of copy, and this line is the honest core of the
feature:

> This app can't cancel anything for you — it's a read-only view of your bank. Cancel with the
> merchant, then come back: if the charges stop, this series will show as ended.

**Colour.** Single-series marks use `ACCENT` from `frontend/src/palette.ts`. `SERIES` is not
used — nothing on this page is categorical until SP2 brings categories. Negative/warning states
use the existing `text-clay` class, as `OverviewPage.tsx` and `accounts.tsx` already do.

**Overview page addition.** One `Card` after "Where it goes": **Coming up**, the first five
entries of `summary.upcoming` with a link to `/recurring`. Reuses the existing `Card` and
`delay` animation convention.

**Mobile.** No table wider than the viewport: the series list is flex rows with a truncating
label (`min-w-0 flex-1 truncate`, as `accounts.tsx` does), not a `<table>`. The expanded chart
is inside a `w-full` measured container, which `charts.tsx` already handles via its
`ResizeObserver`. Bottom padding is already handled by `Shell`'s `pb-28`.

### 5.8 Testing

**`backend/tests/test_recurring.py`** — uses the existing `db` fixture (real Postgres via
testcontainers, per-test transaction rollback) and the `_household` helper pattern from
`test_snapshots.py`. A local `_charge(db, hid, account, merchant, amount, on)` helper writes
transactions directly. All money assertions compare `Decimal`, never `float`, never `pytest.approx`.

| Test | Asserts |
|---|---|
| `test_monthly_fixed_charge_is_detected` | 6 monthly charges of 15.49 → one series, `cadence == monthly`, `typical_amount == Decimal("15.49")`, `confidence >= 80` |
| `test_two_charges_are_not_a_series` | below `MIN_CHARGES` → nothing detected |
| `test_weekly_biweekly_quarterly_yearly_cadences` | parametrized over gap sizes 7/14/91/365 → correct `Cadence` |
| `test_irregular_gaps_are_rejected` | charges at 3, 40, 12, 90 days → nothing detected |
| `test_wildly_varying_amounts_are_rejected` | same merchant, 5/500/40/900 → nothing detected |
| `test_variable_bill_is_kept_and_flagged` | electric bill 88/104/95/119 monthly → detected, `amount_varies is True`, min/max recorded |
| `test_one_missed_month_still_detects` | monthly with a 60-day gap in the middle → detected, `confidence` lower than the clean case |
| `test_next_expected_clamps_to_month_length` | charges on the 31st → next expected in a 30-day month is the 30th |
| `test_series_that_stopped_is_marked_ended` | last charge 4 months ago on a monthly series → `status == ended` |
| `test_price_increase_is_flagged` | 9.99 ×5 then 12.99 → `price_increase_amount == Decimal("3.00")` |
| `test_small_price_change_is_not_flagged` | 9.99 → 10.19 → `price_increase_amount is None` |
| `test_income_series_is_detected_with_positive_direction` | biweekly paycheck → `direction == 1` |
| `test_refund_does_not_merge_with_charges` | same merchant, opposite signs → two groups, not one |
| `test_merchant_key_collapses_store_numbers` | `SQ *COFFEE #4471` and `SQ *COFFEE #0012` → same key |
| `test_detect_is_idempotent` | run twice → same row count, no duplicates |
| `test_detect_preserves_user_label_and_ignored_status` | rename + ignore, re-run → both survive |
| `test_monthly_committed_normalizes_cadences` | weekly 10 + monthly 30 + yearly 120 → exact `Decimal` total, no float drift |
| `test_series_do_not_leak_across_households` | household B sees nothing (mirrors `test_tenancy.py`) |

**`backend/tests/test_recurring_api.py`** — router-level, mirroring `test_accounts.py`:
list defaults to active, `status=all` widens it, `GET /{id}` includes charges, `PATCH` renames
and ignores, `PATCH` to `status: "ended"` returns 422, unknown id returns 404, another
household's id returns 404 (not 403 — don't confirm existence), `POST /refresh` returns counts.

**`backend/tests/test_insights.py`** — existing digest test updated to run detection first;
assert the digest's `recurring_candidates` now carries `cadence` and `next_expected_on`.

**Frontend `frontend/src/recurring.test.tsx`** (vitest, following `insights.test.tsx`):
renders a series list from fixture data; groups money-out above money-in; shows the price-increase
badge when `price_increase_amount` is set and not when it's null; shows the `ended` badge;
renders the empty state with no series. `frontend/src/money.test.ts` gains a case if any new
formatter is added (it shouldn't need one).

**E2E `frontend/e2e/smoke.spec.ts`** — one added block: navigate to `/recurring` via the nav,
assert the heading and that the page renders without an error boundary. Plus a mobile-viewport
assertion that all five bottom-tab labels are visible at 360×780.

**Lint/type gates**, unchanged and all must be green: `ruff check app tests`, `mypy app`
(strict), `npm run typecheck`, `npm run lint`.

### 5.9 What SP1 explicitly does not do

- Does not cancel, negotiate, or contact any merchant.
- Does not send notifications — SP6 owns alerting; SP1 only *records* the price increase.
- Does not categorize anything — SP2 owns categories.
- Does not forecast — SP5 consumes these series to do that.
- Does not persist `merchant_normalized` — SP2 owns that column.
- Does not detect internal transfers between the user's own accounts as a special case. They
  will appear as a recurring pair (out of checking, into savings), which is arguably correct;
  if it proves annoying, the user ignores the series in one tap. Revisit only if it does.
- No ML, no embeddings, no LLM in the detection path. The LLM already receives the results
  through the digest, which is the correct division: the app computes, the model phrases.

---

## 6. Definition of done for SP1

- Migration applies and rolls back cleanly (including both enum types).
- `recurring.detect()` runs on every scheduler tick and via `POST /recurring/refresh`.
- All tests in §5.8 pass against real Postgres; ruff, mypy strict, tsc, and oxlint green.
- `/recurring` works on a 360 px phone with five bottom tabs and no horizontal scroll.
- `digest.py` no longer contains its own recurring heuristic.
- `README.md` "Not here yet" list updated; `CHANGELOG.md` entry added.
- The cancellation copy in the UI says plainly that the app cannot cancel anything.
