# Shared constraints for the Origin-parity phase plans

Every P2–P5 plan carries this by reference. It is what P1 cost to learn. A plan that
contradicts anything here is wrong, and a brief written from it will send its implementer
into a wall that has already been hit once.

Source of truth for scope: `docs/superpowers/specs/2026-07-30-origin-parity-design.md`.
Format exemplar: `docs/superpowers/plans/2026-07-30-p1-categorization.md`.

## Money

`Decimal` in Python, `NUMERIC(19,4)` in Postgres, **string** in TypeScript. Never `float`,
never `number`, not even for display arithmetic. A summed figure round-tripped through
`float` is a bug even when the test passes.

## Tenancy

Every financial row carries `household_id`. Every service function takes `household_id` and
filters on it. `backend/tests/test_tenancy.py` exists to catch violations and is
**service-level, not HTTP-level** — follow its existing shape.

Any user-supplied foreign key must be validated against the household before it reaches the
database. P1 shipped a real tenancy hole by skipping this in one service: an unknown id
became a 500 with the SQL in the traceback, and another household's id was accepted and
stored. The pattern to copy is `categories._check_parent` /
`categorization._check_category` → a typed exception → 422 at the router.

## The gates

Backend, from `backend/`:
- `.venv/Scripts/python.exe -m pytest -q`
- `.venv/Scripts/python.exe -m ruff check app`
- `.venv/Scripts/python.exe -m mypy app`

Frontend, from `frontend/`:
- `npm test`
- `npm run build` ← **this one, not `npm run typecheck`**
- `npm run lint`

**`npm run typecheck` is `tsc --noEmit`; `npm run build` is `tsc -b`. They check different
things.** P1 was written, reviewed three times, merged and pushed behind a green
`typecheck` while `npm run build` had been failing the whole time — a required field added
to a shared type broke two call sites neither command-but-one could see. Every plan's gate
step says `npm run build`.

**Pre-existing baseline, not yours to fix and not a reason to fail a gate:**
`ruff check app` reports **3**, `mypy app` reports **24**, in `portfolio.py`,
`trade_import.py`, `scheduler.py`, `investments.py`, `prices.py`, `recurring.py`.
The real gate is: **no NEW errors in the files the task touches.**

Also pre-existing and still failing on `main`: `frontend/e2e/mobile.spec.ts`, a non-exact
heading matcher hitting both an `<h1>` and a card `<h2>` on AccountsPage. Not yours.

Backend tests need Docker running — `conftest.py` starts a real `postgres:17` container.

## Test fixtures

`backend/tests/conftest.py` provides **only** `pg_engine` and `db`. There is no `household`
fixture and no `account` fixture. A plan whose test code takes them must define them in the
test file it is writing. P1's briefs assumed fixtures that did not exist, three times.

Tests build the schema with `Base.metadata.create_all`, **never** with Alembic. Any seed
data the app needs must live in an importable function that both the migration and the
tests call — never inline in the migration.

## Frontend module resolution

Vite resolves the bare specifier `./foo` to `foo.ts` before `foo.tsx`. A component file
named `foo.tsx` alongside a hooks file `foo.ts` is **unreachable from every importer but
itself**. Give component files distinct names — the shipped pattern is `categories.ts` for
hooks, `CategoryPicker.tsx` / `CategoryCards.tsx` for components. P1's plan got this wrong
and both frontend tasks had to work around it.

React Testing Library: `findByLabelText` on a `<select>` resolves as soon as the element
exists, which is before an async options fetch has resolved. Firing `change` for an
`<option>` that is not in the DOM yet is a silent no-op in jsdom. Await the *option*, not
the select. Likewise `waitFor` returns on its first truthy check — a regression test that
asserts a condition already true when it starts is a false negative.

## The LLM seam

`ClaudeProvider.complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str`.
Not `complete(prompt)`. The model name is `getattr(llm, "model", llm.name)`; there is no
`model_name` attribute. Services take `provider: LLMProvider | None = None` and default to
`ClaudeProvider()`, the way `insights.generate` already does.

The model never calculates and never writes. It proposes; the user confirms; the app
writes. Anything the model returns is validated against a server-side allowlist before it
is shown — P1 drops any category or merchant the model invented rather than surfacing it
for a user to tick without reading.

Parsing a model reply: catch `RecursionError` alongside `json.JSONDecodeError`. Deeply
nested JSON blows the stack instead of failing to parse, and that path 500ed in P1.

## User-supplied regex and other unbounded work

`compile_pattern` in `categorization.py` rejects nested quantifiers because Python's `re`
has no step budget and `(a+)+b` never returns against a thirty-letter string. Any new
feature accepting a pattern, an expression, or an unbounded scan gets the same treatment.
Bound the work before it reaches a request handler.

## House style

- Service modules are flat functions taking `(db, household_id, ...)`. Routers are thin and
  translate service exceptions into `HTTPException`.
- Comments explain **why**, never what. Match the surrounding density.
- **No new dependencies.** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, pytest +
  testcontainers, React 19, TanStack Query, react-hook-form, Recharts, Vitest, Playwright
  are all already installed and are all you get.
- A deliberate shortcut with a known ceiling gets a `ponytail:` comment naming the ceiling
  and the upgrade path.
- One Alembic revision per phase.
- Commit subjects are lowercase and human, no task numbers.

## Navigation — decided, do not re-litigate

`frontend/src/ui/Shell.tsx` holds a `NAV` array already at its documented ceiling of five
tabs (Overview, Accounts, Investments, Transactions, Recurring), because each is `flex-1`
and 72px is what a 360px phone gives a tab.

P2, P3 and P5 each want a new page, so the bar becomes **four fixed tabs plus a More
overflow**:

```
Overview · Accounts · Activity · More
                                  └─ Investments, Recurring, Budgets, Goals, Reports
```

**P2 builds the More sheet** — a new `ui/MoreMenu.tsx`, `NAV` trimmed to four, and the
displaced destinations moved into a `MORE` array in the same file. P3 and P5 each add one
entry to `MORE` and nothing else. A plan for P3 or P5 that rebuilds the menu is wrong; a
plan for P2 that skips it blocks both.

Keyboard reachable, `aria-expanded` on the trigger, closes on route change and on Escape.
Desktop keeps the full horizontal list — the ceiling is a phone constraint.
