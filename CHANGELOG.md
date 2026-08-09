# Changelog

## [Unreleased] — Origin parity program

## P5 (reports, tax, and the document vault)

### Added
- `services/reports.py`: spending grouped by category, merchant, or month; income vs.
  expense over a trailing window; a year-in-review summary reusing
  `services/snapshots.py` for its net worth delta.
- `services/tax.py`: a from-scratch FIFO lot-matching replay over the trade log,
  separate from `services/portfolio.py`'s average-cost engine; a dividend/interest
  summary from categorized transactions; a Schedule-D-shaped CSV export that discloses
  wash sales are not handled.
- `documents` table and `services/documents.py`: an encrypted vault reusing the
  AES-GCM envelope already sealing provider credentials. Files are decrypted only in
  memory, only for a download.
- `accounts.beneficiary`, a nullable column.
- `services/estate.py`: a computed estate-readiness checklist — will on file,
  beneficiary on every retirement account, a deed for every property account. No
  storage of its own, and no document generation.
- `GET /export/all.zip`: every table the household owns, one CSV per table, enumerated
  from the model registry so a new table is a test failure until it's routed.
- Frontend: a Reports page with spending, cash-flow, year-in-review, tax, and vault
  tabs.

## P3 (goals and cash-flow forecast) — on its own branch, not yet merged

### Added
- `goals` and `goal_accounts` tables: a savings or debt-payoff target and the
  accounts whose balances count toward it. No contributions ledger — progress is
  always the linked accounts' current balance, sign-flipped for debt payoff.
- `services/forecast.py::project` — a daily balance walk from today's cash accounts,
  applying every active recurring series' cadence and the current month's uncovered
  budget spread evenly, plus any hypothetical passed in.
- `can_i_afford`: runs the forecast twice, with and without a hypothetical outflow,
  and reports whether the balance would go negative and what it does to every active
  goal's projected date.
- `GET/POST /goals`, `PATCH/DELETE /goals/{id}`, `GET /forecast?months=`,
  `POST /forecast/afford`.
- Frontend: a Goals page with progress rings and a projected date per goal; a
  forecast chart on Overview with a negative-balance marker and a "can I
  afford…" input.

P1 (categorization) is complete on the `p1-categorization` branch. Nothing has merged to
`main` yet.

### Added
- The system category taxonomy — 12 groups, 63 leaves — seeded into the `categories` table
  that has existed and gone unused since M0. Ids are uuid5 over the category path, so they
  are identical on every install and the seeder is idempotent.
- `category_rules` table: merchant/amount/account conditions, tried in priority order,
  first match wins.
- Categorization application services: apply rules to newly supplied uncategorized rows,
  backfill history without overwriting hand-set categories by default, and roll up
  uncategorized transactions by normalized merchant.
- New transactions land categorized: CSV import and bank sync each run `apply_to` before
  committing, so an import or a sync is one transaction — rows and their categories land
  together or neither does. Manual single-row entry (`POST /transactions`) is not wired
  to this; only import and sync categorize on the way in.
- Category and rule management: `GET/POST /categories`, `PATCH/DELETE /categories/{id}`
  (system rows 403 on write — the row exists, so not 404); `GET/POST /category-rules`,
  `PATCH/DELETE /category-rules/{id}`, `POST /category-rules/reorder`, and
  `POST /category-rules/preview`, which dry-runs a candidate rule against real history
  without saving it. `POST /categorization/backfill` and
  `GET /categorization/uncategorized` expose the same engine over existing rows.
- Optional LLM category suggestions (`POST /categories/suggest`): the model sees merchant
  names and the taxonomy only — no amounts, dates, accounts, or balances — and writes
  nothing itself; suggestions become rules only for the ones the user ticks. No API key,
  no suggestions — 503, not a silent no-op.
- Frontend: a category picker on every transaction row with an "always categorize this
  way?" prompt, declined by default so no rule is written unasked; a rules list on the
  Transactions page you can reorder and run against history; an uncategorized-merchants
  panel that can call the suggestion endpoint.

### Fixed
- Nothing yet, but recorded: `ruff` and `mypy` do not pass on this repo and have not for a
  while — 129 and 24 errors respectively, in `portfolio.py`, `trade_import.py`,
  `scheduler.py`, and `test_trades.py`. The README claims otherwise. See `TASK.md`.

### Planning
- `TASK.md` — current phase, gates, and the invariants that outrank convenience, so an
  agent picking this up cold knows what is in flight.
- Design spec for the Origin parity program
  (`docs/superpowers/specs/2026-07-30-origin-parity-design.md`): five sequential phases
  covering categorization, budgets, goals and cash-flow forecasting, a tool-calling AI
  advisor, and reports/tax/document-vault. Credit-score monitoring, CFP access, and a
  high-yield cash account are cut by name — they need a bureau contract, a licensed
  human, and a banking partner respectively.
- Implementation plan for P1, categorization
  (`docs/superpowers/plans/2026-07-30-p1-categorization.md`).

P2 (budgets) is complete on the `p2-budgets` branch, building on P1's categories.

### Added — P2
- `budgets` table: one row per household, category, and month, `UNIQUE (household_id,
  category_id, month)` so the date column is the whole period and a write is always an
  upsert.
- `services/budgets.py`: `status` (budgeted, actual, remaining, pace) over every leaf
  category whether budgeted or not; `rollover_carry`, computed fresh from stored amounts
  and actual spend on every read and never written, so toggling rollover off cannot
  corrupt a saved number; `suggest`, a trailing-3-month median rounded to the nearest 5,
  skipping months with no data for a category rather than treating them as zero;
  `copy_from`, an idempotent month-to-month copy.
- `GET/PUT /budgets/{month}`, `POST /budgets/{month}/suggest`,
  `POST /budgets/{month}/copy`. A budget's `category_id` is checked against the
  household before it is written — an unknown or foreign id is 422, never a 500.
  Deleting a category a budget still points at is refused with 409, the same treatment
  P1 already gives a category a rule or transaction still points at.
- Frontend: a Budgets page with a month switcher, per-category rows showing a pace bar
  that ambers when spending is outrunning the calendar, a rollover checkbox per row, and
  Suggest / Copy last month actions.
- Navigation: the mobile tab bar drops from five fixed tabs to three (Overview,
  Accounts, Activity) plus a `ui/MoreMenu.tsx` sheet holding Investments, Recurring, and
  the new Budgets page — keyboard reachable, `aria-expanded` on the trigger, closes on
  route change and on Escape. Desktop's sidebar is unchanged, listing everything.

## [Unreleased] — M0 Foundation

### Added
- Daily balance snapshots + net worth over time chart, recorded by a background loop
  that also syncs connections every `SYNC_INTERVAL_HOURS`.
- Optional AI assistant: a computed digest goes to Claude, which interprets but never
  calculates. Hidden entirely without `ANTHROPIC_API_KEY`; `/insights/digest` exposes
  the facts it was given.
- SimpleFIN Bridge provider: claim a setup token, encrypt the access URL, sync accounts
  and transactions with dedup on provider transaction ids. Connect / Sync now / Forget
  in the UI.
- `APP_SECRET_KEY` startup guard — the published default is refused outside development.
- `LOCAL_MODE` single-user desktop mode — no login, one household, guarded to
  `ENVIRONMENT=development`. Compose enables it by default.
- Designed UI: sidebar shell, overview with net worth / cash flow / top merchants,
  accounts and transactions pages.
- Email/password auth: argon2id hashing, opaque server-side sessions, rate-limited
  register/login, `GET /auth/me`.
- Household tenancy — every financial row scoped to `household_id`, with isolation tests.
- `BankProvider` protocol + `ManualProvider`; provider credentials encrypted at rest
  (AES-GCM envelope encryption, AAD bound to household + provider).
- Accounts and categories; transactions with CRUD, filtering, and CSV import with dedup.
- React frontend: auth pages, accounts, transactions, CSV upload.
- Postgres + Redis + API + web via Docker Compose; Alembic migrations run on API start.
- Tests: pytest + testcontainers, vitest, Playwright smoke; ruff, mypy strict, tsc, oxlint.
