# Investments: trade log, holdings, and performance

Design spec — 2026-07-26. No code in this document is committed; it is a sketch of
intent, sized to be implemented in slices.

## 0. What exists today, and why it has to change

`backend/app/services/investments.py` opens with an honest disclaimer: SimpleFIN gives
balances and transactions, not holdings, so the current feature shows portfolio value,
income guessed from description keywords, and contributions. That is the ceiling of what
a read-only bank feed can support.

The user already keeps the real data by hand, in "The Measure of a Plan" portfolio
tracker spreadsheet. The trade log in that sheet is the missing input. Once the app has
a trade log it can compute everything the sheet computes, and the SimpleFIN feed stops
being the source of truth for investments and becomes a cross-check.

So the shape of this feature is: **one manual input surface (trades), everything else
derived.** That is also the sheet's design, and it is the laziest correct design — there
is exactly one thing to keep accurate.

---

## 1. Data model

### 1.1 The central decision: `Trade` is NOT a `Transaction`

A trade gets its own table. Reasons, in order of weight:

1. **Ownership differs.** `Transaction` rows are provider-owned. `services/sync.py`
   writes them, dedupes on `external_id`, and will happily overwrite or re-create them.
   Trades are user-owned and hand-entered; a sync must never touch them. Mixing two
   write-ownership models in one table is how you lose hand-typed history.
2. **Shape differs badly.** A trade needs `security_id`, `quantity`, `price_per_unit`,
   `fees`, `split_ratio`, `investment_category_id`. Bolting those onto `Transaction`
   means six nullable columns that are null on 99% of rows.
3. **It poisons every existing query.** `insights.py`, `digest.py`, `money.ts`
   `monthTotals`, the transactions page, and category rollups all assume a
   `Transaction` is a cash movement with a merchant. A `BUY VTI -4,000.00` row would
   read as $4,000 of spending in the digest handed to the LLM. A `SELL` would read as
   income. Fixing that means threading an `is_trade` exclusion through every one of
   those call sites — more work than a new table, forever.
4. **The sheet agrees.** The Trade Log is its own tab with its own columns.

The counter-argument — "a trade moves cash, so it belongs in the cash ledger" — is real
but is about *display*, not *storage*. It is solved in Phase 3 by a nullable
`Trade.transaction_id` link that reconciles a logged dividend against the matching
SimpleFIN row. Storage stays separate.

### 1.2 New tables

Six tables. Three of them are Phase 1.

| Table | Phase | Why |
|---|---|---|
| `securities` | 1 | A ticker, its currency, its category. The sheet's ticker list. |
| `trades` | 1 | The Trade Log. The only manual input. |
| `security_prices` | 1 | Daily close per security. Also holds manual overrides. |
| `investment_categories` | 2 | User-defined buckets + target allocation %. |
| `fx_rates` | 2 | Daily base-pair rates, same shape as `security_prices`. |
| `benchmarks` | 4 | Which tickers to index against. See §1.6 — probably drop this. |

Dropped from the sheet entirely:

- **The 5-currency cap.** Arbitrary spreadsheet limitation. `securities.currency` is a
  3-char code; there is no cap.
- **"Total Amount (before trading fees)".** Derived: `quantity * price_per_unit`. Never
  stored. Storing a derivable column invites it to disagree with its inputs.
- **A separate "investment accounts" list.** The app already has `accounts` with
  `AccountType.investment`. `trades.account_id` FKs to it. Do not build a second
  account concept.
- **The spin-off tool.** See §9.

### 1.3 `securities`

```python
# app/models/security.py

class Security(Base, UUIDMixin, TimestampMixin):
    """A tradeable thing, keyed by the symbol the user types.

    Scoped per household rather than global: the same symbol means different
    instruments on different exchanges, and one user's portfolio is not a reference
    database. `symbol` is stored uppercase and is the natural key the CSV import and
    the price fetcher both match on.
    """

    __tablename__ = "securities"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investment_categories.id"), nullable=True
    )
    # Symbol as the price provider knows it, when that differs from what the user
    # types (Yahoo wants "SHOP.TO", the user writes "SHOP"). Null means use `symbol`.
    quote_symbol: Mapped[str | None] = mapped_column(nullable=True)
    # Illiquid holdings — private company shares, a rental property. No provider will
    # ever quote these, so the only price they get is a manual one.
    is_manual_price: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("household_id", "symbol", name="uq_security_symbol"),)
```

### 1.4 `trades`

```python
# app/models/trade.py

class TradeType(str, enum.Enum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    split = "split"


class Trade(Base, UUIDMixin, TimestampMixin):
    """One row of the trade log — the only thing in this feature a human types.

    Everything else (holdings, cost base, realized gains, returns) is derived by
    replaying these in date order, so a wrong row is fixed by editing the row, not by
    unwinding a stored balance.
    """

    __tablename__ = "trades"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), index=True
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id"), index=True
    )
    traded_on: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[TradeType] = mapped_column(Enum(TradeType, name="trade_type"))

    # Buy/sell: units traded, always positive — direction comes from `type`, not sign.
    # Dividend: units the payment was on, or 0 if unknown. Split: unused.
    quantity: Mapped[Decimal] = mapped_column(Numeric(19, 8), default=Decimal(0))
    # Buy/sell: price per unit. Dividend: per-unit payment, or 0 with `amount` set.
    price_per_unit: Mapped[Decimal] = mapped_column(Numeric(19, 8), default=Decimal(0))
    fees: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal(0))
    # New shares per old share. 2 for a 2-for-1, 0.5 for a 1-for-2 reverse split.
    # Only read when type == split.
    split_ratio: Mapped[Decimal | None] = mapped_column(Numeric(19, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(nullable=True)
    # sha256(date|type|symbol|qty|price|account) — lets a CSV re-import be idempotent,
    # exactly as csv_import.py does for transactions.
    external_id: Mapped[str | None] = mapped_column(nullable=True, index=True)
```

Quantity and price use `Numeric(19, 8)`, not `(19, 4)`. Fractional-share brokerages
report to 6+ decimals and a 4-decimal price loses money on a $0.000012 crypto unit.
Money columns (`fees`, and everything computed) stay `Numeric(19, 4)` to match the rest
of the codebase.

**Why no `amount` column.** The sheet has "Total Amount (before trading fees)". It is
`quantity * price_per_unit`. Derive it. The one awkward case is a dividend where the
user knows the total but not the per-unit rate — handle that in the API layer by
accepting `amount` and storing `price_per_unit = amount / quantity`, or
`quantity = 0, price_per_unit = amount` when units are unknown. The service treats a
dividend's cash as `quantity * price_per_unit if quantity else price_per_unit`. This is
slightly ugly and is worth one comment in the model.

**No `investment_category_id` on the trade.** The sheet puts category on the trade row.
That is a spreadsheet workaround for not having a ticker table. Category belongs to the
security; putting it on the trade lets the same ticker be two categories on two rows,
which is a bug, not a feature. Category lives on `securities.category_id`.

### 1.5 `security_prices`

```python
# app/models/security_price.py

class SecurityPrice(Base, UUIDMixin, TimestampMixin):
    """Daily close per security, in the security's own currency.

    Modelled on `balance_snapshots`: one row per (security, day), unique, append-only
    in practice. A manual row always wins over a fetched one for the same day — that
    is the sheet's "Market Value (MANUAL INPUT)" column, generalised.
    """

    __tablename__ = "security_prices"
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("securities.id", ondelete="CASCADE"), index=True
    )
    priced_on: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(19, 8))
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | yahoo | twelvedata

    __table_args__ = (UniqueConstraint("security_id", "priced_on", name="uq_price_day"),)
```

### 1.6 Phase 2+ tables

```python
class InvestmentCategory(Base, UUIDMixin, TimestampMixin):
    """User's own buckets — Domestic equity, Foreign equity, Fixed income.

    Deliberately not the existing `categories` table: those are spend categories with a
    parent tree, and mixing "Groceries" into an asset-allocation dropdown is confusing.
    """

    __tablename__ = "investment_categories"
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id"), index=True
    )
    name: Mapped[str] = mapped_column()
    # Target allocation, 0–100. The sheet's TARGET ASSET ALLOCATION column. Nothing
    # enforces that these sum to 100 — the UI shows the sum and flags a drift.
    target_pct: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal(0))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
```

```python
class FxRate(Base, UUIDMixin, TimestampMixin):
    """Daily rate, always quoted as 1 unit of `base` in `quote`.

    Stored one-directional and inverted on read. Storing both directions means two rows
    that can round differently and disagree.
    """

    __tablename__ = "fx_rates"
    base: Mapped[str] = mapped_column(String(3), index=True)
    quote: Mapped[str] = mapped_column(String(3), index=True)
    rated_on: Mapped[date] = mapped_column(Date, index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(19, 8))

    __table_args__ = (UniqueConstraint("base", "quote", "rated_on", name="uq_fx_day"),)
```

`benchmarks` — **drop the table.** A benchmark is one ticker. Store it as a household
setting (`households.benchmark_symbol`, nullable, default `"^GSPC"`), or, laziest of
all, create a `Security` row flagged `is_benchmark`. One column beats one table.
Decision: add `Security.is_benchmark: bool = False`. The S&P 500 is just a seeded
security with `symbol = "^GSPC"`. Its prices flow through the same `security_prices`
table as everything else, and the benchmark chart is the same query as a holding chart.
This removes an entire subsystem.

### 1.7 Alembic migration plan

Head is `d5f2c1a83b70` (balance snapshots). Follow its style, not the autogenerated
style of `199492b35732` — explicit `sa.Column`, explicit FK constraints,
`op.create_index(op.f(...))`, a real `downgrade`, `Create Date` as a bare date.

One migration per phase, hand-written after `--autogenerate` to strip the
`### commands auto generated ###` noise:

- **Phase 1** — `<rev>_investment_trade_log.py`, revises `d5f2c1a83b70`.
  Creates `securities`, `trades`, `security_prices`, and the `trade_type` enum.
  `downgrade` drops the three tables then
  `sa.Enum(name="trade_type").drop(op.get_bind())` — Postgres does not drop an enum
  with its table, and the `account_type` enum in `199492b35732` already has this bug.
  Do not repeat it.
- **Phase 2** — `<rev>_investment_categories_fx.py`. Creates `investment_categories`,
  `fx_rates`, adds `securities.category_id` FK (nullable, so no backfill needed).
- **Phase 4** — `<rev>_security_benchmark_flag.py`. One boolean column.

Every new module goes into `app/models/__init__.py`, which is what makes autogenerate
see them.

---

## 2. Cost basis engine

Average cost, per **(security, account)** pair. Not per security globally.

The sheet computes average cost per ticker and reports realized gains broken out by
account. Those two are only consistent if the cost base is tracked per account —
otherwise a sale from a taxable account is charged an average that includes shares
bought inside an IRA. Per-account is also what a Canadian ACB and most non-US tax
regimes actually require. Cost slightly higher; correctness much higher. Do it per
account, and sum across accounts for the portfolio-level view.

### 2.1 State

```python
@dataclass
class Position:
    units: Decimal = Decimal(0)       # shares held
    cost_base: Decimal = Decimal(0)   # total cost of those shares, in trade currency
    realized: Decimal = Decimal(0)    # cumulative realized gain
    dividends: Decimal = Decimal(0)   # cumulative cash dividends

    @property
    def avg_cost(self) -> Decimal:
        return self.cost_base / self.units if self.units else Decimal(0)
```

### 2.2 Replay

`positions(db, household_id, as_of=None)` loads every trade for the household ordered by
`(traded_on, created_at)` and folds them into a `dict[(security_id, account_id), Position]`.
`created_at` is the tiebreaker so two same-day trades apply in entry order — this matters
for a same-day buy-then-sell, and for a split entered after the buy it splits.

### 2.3 Per-type rules

**BUY**
```
gross      = quantity * price_per_unit
units     += quantity
cost_base += gross + fees
```
Fees are capitalised into the cost base. This is what every tax authority requires and
what the sheet does — the sheet's "Total Amount (before trading fees)" plus a separate
"Trading Fees" column exists precisely so the two can be added.

**SELL**
```
if quantity > units: reject (422) — you cannot sell what you do not hold
avg           = cost_base / units
basis_sold    = avg * quantity
proceeds      = quantity * price_per_unit - fees
realized     += proceeds - basis_sold
cost_base    -= basis_sold
units        -= quantity
```
Note the asymmetry: fees are **added** to cost on a buy and **subtracted** from proceeds
on a sell. Both reduce the gain. This is correct and is the single most common thing to
get backwards.

A sell that takes `units` to exactly zero must set `cost_base = Decimal(0)` explicitly
rather than relying on the subtraction — `Numeric(19,8)` division leaves crumbs, and a
position showing 0 shares with $0.0000003 of cost base looks broken. Snap to zero when
`units == 0`.

**DIVIDEND**
```
cash        = (quantity * price_per_unit) if quantity else price_per_unit
dividends  += cash
# units and cost_base unchanged
```
A cash dividend does not touch the position. A **reinvested** dividend is two rows in
the log: a `dividend` for the cash, then a `buy` for the units. The sheet works this way
and it is the only representation that keeps both the income total and the cost base
right. Say this explicitly in the UI help text, because it is the #1 thing users get
wrong.

**SPLIT**
```
units      *= split_ratio
# cost_base unchanged — a split creates no gain and consumes no money
```
`split_ratio` is new-per-old: `2` for 2-for-1, `0.5` for a 1-for-2 reverse. Average cost
per unit falls out correctly because `cost_base` is held constant while `units` scales.
A split row is entered once per (security, account) it affects — the replay applies it
only to positions matching both keys, so a holding split across three accounts needs
three rows. That is annoying. Mitigation: the API accepts `account_id = null` on a split
and fans it out to every account holding that security at write time, creating N rows.
Cheap to implement, and the log still shows exactly what happened.

### 2.4 Market value and unrealized gain

```
price       = latest price on or before `as_of` from security_prices
market      = units * price
unrealized  = market - cost_base
unreal_pct  = unrealized / cost_base   (guard cost_base == 0)
```

Everything in the security's own currency; §4 converts to base.

### 2.5 Where it runs, and when to stop computing on read

`app/services/portfolio.py`, called on every request. Compute on read — no cached
positions table.

Sizing: a 20-year log at 4 trades/month is ~1,000 rows. The fold is one pass with
Decimal arithmetic, well under 10ms, plus one indexed query. The holdings page will be
dominated by the price lookup, not the replay.

**The tripwire:** if `trades` ever exceeds ~50,000 rows for one household, or the
holdings endpoint p95 exceeds 300ms, add a `position_snapshots` table keyed on
`(security_id, account_id, as_of_month)` and replay only from the last snapshot. Do not
build that now. Write the tripwire into a comment in `portfolio.py` so the next person
knows the condition rather than guessing.

---

## 3. Market prices

The sheet uses `GOOGLEFINANCE()`. There is no equivalent the app can call. What follows
is researched as of 2026-07-26 and **verified by live request where marked**.

### 3.1 Recommendation

**Two providers behind one interface, plus manual override.**

**Default: Yahoo Finance chart endpoint** — `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`.

- **Verified live 2026-07-26.** Returned `AAPL` OHLC, `^GSPC` (the S&P 500), and
  `CADUSD=X` (an FX pair) with no key, no signup, no `User-Agent` tricks beyond a
  browser-ish UA.
- `?range=5d&interval=1d` for a quote (take the last close, or `meta.regularMarketPrice`);
  `?range=10y&interval=1d` for a full backfill in one call.
- `?events=div` returns the dividend history, which is a nice-to-have for
  cross-checking the dividend rows the user typed.
- **Free-tier limits: none published, because there is no tier.** This is an
  undocumented internal endpoint. It has no terms permitting programmatic use, no SLA,
  and Yahoo has broken it before (the 2017 shutdown, the 2023 crumb/cookie requirement
  that killed a generation of scrapers). **I am telling you plainly: this may stop
  working with no notice.** For a self-hosted single-user app fetching ~20 symbols once
  a day, that is an acceptable risk with a cheap recovery path (switch providers in
  config). For anything user-facing at scale it would not be.
- Rate-limit posture: fetch once per day from the scheduler, one request per symbol,
  `httpx` with a 30s timeout matching `simplefin.py`. Sequential, not concurrent.

**Keyed alternative: Twelve Data** — `https://api.twelvedata.com/time_series`.

- Free tier as reported by Twelve Data's own pricing and support pages: **800 API
  credits/day, 8 requests/minute, 5,000 data points per request**, covering US equities,
  forex, and crypto. **I did not verify these numbers against a live authenticated call
  — I have no key — so treat them as "as advertised in July 2026" and re-check at
  implementation time.** Vendor free tiers change frequently and silently.
- 800/day is enormous for this use case (20 symbols daily = 20 calls). The 8/min limit
  means a first-run backfill of 20 symbols takes ~3 minutes; do it from the scheduler,
  not from a request handler.
- This is the provider to name in the README as the supported path, because it has
  terms that permit what we are doing.

**Rejected:**

- **Stooq** — looked ideal (free CSV, no key, 20+ years). **Verified dead 2026-07-26:**
  both `stooq.com` and `stooq.pl` now return a JavaScript proof-of-work browser
  challenge instead of CSV. Any blog post recommending it is stale. Do not use it.
- **Alpha Vantage** — free tier is reported at **25 requests/day** in 2026, down from
  500. That does not survive a single backfill. Not viable.
- **Finnhub** (60 req/min free) and **Polygon** (1 year of history free) are fine but
  add a signup for no gain over the two above.
- **`yfinance` the Python package** — it is a scraper for the same endpoint, plus a
  large dependency and a pandas requirement this backend does not have. Call the
  endpoint directly with the `httpx` that is already a dependency.

### 3.2 FX rates

**Frankfurter** — `https://api.frankfurter.dev/v1/...`.

- **Verified live 2026-07-26.** `GET /v1/latest?base=USD&symbols=CAD,EUR` returned
  `{"base":"USD","date":"2026-07-24","rates":{"CAD":1.4086,"EUR":0.87897}}`.
  `GET /v1/2026-01-02..2026-01-08?base=USD&symbols=CAD` returned the daily series.
- ECB reference rates, ~30 currencies, history to 1999-01-04. **No key, no published
  rate limit, fair use expected.** Open source, so it can be self-hosted if the public
  instance dies.
- Caveat worth encoding: ECB publishes on **business days only**, once daily at 16:00
  CET. A weekend date returns nothing. The FX lookup must therefore be "most recent rate
  on or before this date", exactly like the price lookup. Same code path.
- If Frankfurter is unreachable, Yahoo's `CADUSD=X` (verified above) is a fallback that
  needs no new provider.

### 3.3 The provider interface

Mirror `app/providers/base.py` + `simplefin.py`. Small protocol, injectable `httpx.Client`
so tests use `MockTransport` and never touch the network — the existing test suite's
pattern.

```python
# app/providers/prices.py

class PriceProvider(Protocol):
    name: str
    def quote(self, symbol: str) -> Decimal | None: ...
    def history(self, symbol: str, since: date) -> list[tuple[date, Decimal]]: ...


class YahooPriceProvider:   # default, no config
class TwelveDataProvider:   # used when TWELVE_DATA_API_KEY is set
```

Config additions to `app/core/config.py`, following the `anthropic_api_key` comment
style ("without a key the feature reports itself unavailable"):

```python
# Market prices. Empty key -> the unofficial Yahoo endpoint, which needs no signup but
# has no terms and can break without notice. Set a Twelve Data key for the supported
# path (free tier: 800 calls/day, 8/min as of 2026-07).
twelve_data_api_key: str = ""
price_refresh_hours: float = 24.0
base_currency: str = "USD"
```

### 3.4 Manual override

Two mechanisms, because the sheet has two needs:

1. **`Security.is_manual_price = True`** — never fetch this symbol at all. Private
   company shares, a private REIT, a valuation the user updates quarterly. The fetcher
   skips it entirely; the UI shows a "set price" field on the holdings row.
2. **`SecurityPrice.source = "manual"` for a specific day** — the user corrects one bad
   close. The resolution rule: for a given `(security, day)`, a `manual` row wins over a
   fetched row. Implemented as `ON CONFLICT DO NOTHING` in the fetcher when a manual row
   exists for that day, which is one `WHERE source != 'manual'` clause in the upsert.

Both are the same table and the same read path. No special-casing downstream.

### 3.5 Refresh

Extend `app/core/scheduler.py`'s existing `run_once()`. It already syncs connections and
captures snapshots per household; add a third step:

```python
try:
    prices_service.refresh(db, household_id)
except Exception as exc:  # noqa: BLE001 - a stale price is not fatal
    log.warning("price refresh failed for %s: %s", household_id, exc)
```

Same "never raises, next tick catches up" posture as the rest of that module. Prices are
idempotent per day for the same reason snapshots are.

A missing price is **not** an error. `market_value` for a security with no price is
reported as `None`, and the UI shows "no price" on that row and excludes it from the
portfolio total with a visible note. Never silently substitute cost base for market
value — that is the sort of quiet lie the existing module's docstring explicitly refuses
to tell.

---

## 4. Currency

Phase 1 is **USD only**, matching `accounts.py`'s `SUPPORTED_CURRENCY = "USD"`. Trades
carry a `currency` column from day one so the data is not lossy, but every conversion
path is a no-op and the UI does not show a currency column.

Phase 2 turns it on:

- `settings.base_currency` (default `"USD"`) is the reporting currency.
- Every holding is computed twice: in `security.currency` (local) and converted to base.
- **Conversion rate choice matters and the sheet is vague about it.** Decision:
  - **Market value** converts at the *latest* rate. It is a snapshot of today.
  - **Cost base** converts at the *trade-date* rate, accumulated per trade. This is what
    tax authorities require and it means the FX move itself shows up as part of the
    unrealized gain, which is correct and is usually what surprises people.
  - Therefore the cost-base fold in §2 accumulates a second running total,
    `cost_base_base_ccy`, using the trade-date rate. One extra `Decimal` in the
    dataclass, no extra pass.
- Rate lookup is "most recent `fx_rates` row with `rated_on <= d`", identical in shape
  to the price lookup. One helper, used by both.

---

## 5. Money-weighted return (XIRR)

The sheet says "money-weighted", which is XIRR: the discount rate that makes the NPV of
a dated cash-flow series zero.

### 5.1 Cash flows

For a period `[start, end]`, from the perspective of the portfolio:

| Event | Sign | Amount |
|---|---|---|
| Portfolio value at `start` | negative | `-value(start)` |
| Contribution (a buy funded from outside) | negative | `-(qty * price + fees)` |
| Withdrawal (proceeds of a sell taken out) | positive | `qty * price - fees` |
| Cash dividend not reinvested | positive | dividend cash |
| Portfolio value at `end` | positive | `+value(end)` |

**The hard part is not the maths, it is deciding what is external.** A buy funded by
selling something else is *not* a contribution; it is a reallocation. Distinguishing
them requires knowing the account's cash balance, which the trade log alone does not
carry.

Phase-2 rule, stated plainly in the UI: **a buy is a contribution and a sell is a
withdrawal, unless another trade in the same account within ±3 days offsets it.**
Same-day buy-after-sell nets out. This is a heuristic, it will occasionally be wrong,
and the UI must say so — one line under the return figure, in the same register as the
existing "your brokerage describes them too tersely to recognise" copy.

The alternative — asking the user to log cash movements into the brokerage as their own
trade type — is more correct and more typing. Offer it as an optional `deposit` /
`withdrawal` trade type in Phase 3 for users who want exact numbers, and let the
heuristic handle everyone else.

### 5.2 The algorithm

```python
def xirr(flows: list[tuple[date, Decimal]], guess: float = 0.1) -> float | None:
    """Money-weighted return: the rate where discounted flows sum to zero.

    Newton-Raphson from `guess`, falling back to bisection over [-0.9999, 10.0] when
    Newton diverges — which it does on portfolios that went to nearly zero and back.
    Returns None when there is no sign change in the flows (no solution exists) or
    neither method converges.
    """
```

Implementation notes:

- Pure stdlib. **No `scipy`, no `numpy`, no `pyxirr`.** It is 40 lines and this backend
  has no numeric stack to hang them on.
- `Decimal` in, `float` for the iteration, `Decimal`/rounded `float` out. Root-finding
  in `Decimal` is slow and pointless; a return of 8.4327% does not need 28 significant
  digits. **This is the one place floats are permitted, and it needs a comment saying
  why**, because the codebase rule is otherwise absolute.
- Day count: `(d - d0).days / 365.0`. Actual/365. Do not import a day-count library.
- Guard: fewer than 2 flows, or all flows the same sign → return `None`, and the UI
  shows "—" rather than a fabricated number.

### 5.3 Where it runs

`app/services/portfolio.py::monthly_performance(db, hid, months=12)`, on read, inside
the `/investments/performance` handler.

Cost per month row: one XIRR over that month's flows (typically <10) plus the
month-boundary valuations. Twelve months is twelve small solves — single-digit
milliseconds total. Compute on read.

Month-boundary portfolio value needs a price for every held security at each month end.
That is a single query — `security_prices` filtered to the month-end dates — provided
the daily fetch has been running. For months before the app existed, the backfill in §8
fills prices from Yahoo's `range=10y` history, so historical months work from day one.

---

## 6. Benchmark comparison

Per §1.6, a benchmark is just a `Security` with `is_benchmark = True`, so its prices
arrive through the same fetcher and live in the same table. `^GSPC` is seeded on first
run; the user can add one more symbol as their custom benchmark.

Two comparisons, and they answer different questions:

1. **Indexed price line.** Both the portfolio's value series and the benchmark's price
   series normalised to 100 at the window start. Answers "did the market go up more
   than my portfolio". Trivially cheap. This is what the sheet's chart shows.
2. **Shadow portfolio.** Replay the user's actual dated contributions as if each had
   bought the benchmark at that day's close. Answers "would I have done better in an
   index fund", which is the question people actually mean. Roughly 15 lines given the
   cash-flow series from §5.1 already exists.

Do **1** in Phase 4 and **2** in Phase 5, if ever. Ship 1 first; it is the one the
sheet has.

Rendering: `AreaChart` from `charts.tsx` takes a single series. Two indexed lines need
either two stacked charts (lazy, works, mobile-friendly) or a small
`MultiAreaChart`/`LineChart` addition to `charts.tsx` using `SERIES[0]` and `SERIES[1]`
from `palette.ts`. **Prefer two stacked charts in Phase 4.** Only extend `charts.tsx` if
the user says the comparison is unreadable that way — and if so, extend it in that file
following its existing `useWidth` + measured-SVG pattern, never with a chart library.

---

## 7. API surface

New router `app/api/investments.py`, `prefix="/investments"`, registered in `main.py`.
Move the two existing `/investments*` handlers out of `api/insights.py` into it — they
are investments endpoints living in the insights file because there was nowhere else to
put them.

Schemas in `app/schemas/investment.py`, following `schemas/account.py`: `Decimal` on the
wire (Pydantic serialises to a JSON string, and `money.ts` already accepts
`string | number` — see its `ponytail:` comment). **Do not use `float` in these
schemas.** Note this is a departure from the current `investments.py` service, which
returns `float` via `_f()`; new endpoints do it right and the old one is left alone.

### Phase 1

```
GET    /investments/securities            -> [SecurityOut]
POST   /investments/securities            {symbol, name?, currency?, is_manual_price?} -> SecurityOut
PATCH  /investments/securities/{id}       {name?, category_id?, quote_symbol?, is_manual_price?}
DELETE /investments/securities/{id}       -> 409 if any trade references it

GET    /investments/trades                ?security_id=&account_id=&from=&to=&limit=200
                                          -> {trades: [TradeOut], total: int}
POST   /investments/trades                TradeIn -> TradeOut
PATCH  /investments/trades/{id}           partial TradeIn -> TradeOut
DELETE /investments/trades/{id}           -> {"status": "ok"}

GET    /investments/holdings              ?as_of=YYYY-MM-DD
                                          -> {holdings: [HoldingOut], totals: {...}, priced_through: date|null}

POST   /investments/prices                {security_id, priced_on, close}  # manual override
POST   /investments/prices/refresh        -> {"updated": int, "failed": [symbol]}

POST   /investments/trades/import         multipart file -> {"imported": n, "skipped": n, "errors": [...]}
```

```jsonc
// TradeIn
{
  "account_id": "uuid",
  "symbol": "VTI",            // resolved to security_id; created if unknown
  "traded_on": "2026-03-14",
  "type": "buy",              // buy | sell | dividend | split
  "quantity": "12.5",
  "price_per_unit": "241.30",
  "fees": "0",
  "split_ratio": null,
  "currency": "USD",
  "notes": null
}

// HoldingOut
{
  "security_id": "uuid",
  "symbol": "VTI",
  "name": "Vanguard Total Stock Market ETF",
  "currency": "USD",
  "category": "Domestic equity",     // null until Phase 2
  "units": "112.5000",
  "avg_cost": "198.4412",
  "cost_base": "22324.63",
  "price": "241.30",                 // null when unpriced
  "priced_on": "2026-07-24",
  "market_value": "27146.25",        // null when unpriced
  "unrealized": "4821.62",
  "unrealized_pct": "21.60",
  "dividends": "412.88",
  "share_pct": "34.2",
  "by_account": [ {"account_id": "uuid", "name": "Roth IRA", "units": "40.0"} ]
}
```

`priced_through` on the holdings response is the oldest `priced_on` across all priced
holdings — the UI uses it to say "prices as of 24 Jul" and to warn when they are stale.

### Phase 2

```
GET    /investments/categories            -> [CategoryOut]   # with target_pct
POST   /investments/categories            {name, target_pct}
PATCH  /investments/categories/{id}
DELETE /investments/categories/{id}

GET    /investments/allocation            -> {rows: [{category, value, actual_pct, target_pct, drift_pct}],
                                              unassigned_value, target_sum}
```

### Phase 3

```
GET    /investments/realized              ?from=&to=&account_id=
                                          -> {rows: [{traded_on, symbol, account, units, proceeds,
                                                      basis, gain}],
                                              by_account: [{account, gain}], total_gain}

GET    /investments/dividends             ?years=5
                                          -> {years: [{year, total, change_pct}], by_security: [...]}
```

### Phase 4

```
GET    /investments/performance           ?months=12
                                          -> {months: [{month, start_value, contributions, withdrawals,
                                                        returns, end_value, dividends, mwr_pct}],
                                              ytd_mwr_pct, since_inception_mwr_pct}

GET    /investments/benchmark             ?months=12&symbol=^GSPC
                                          -> {portfolio: [{on, index}], benchmark: [{on, index}]}
```

### Phase 5

```
POST   /investments/rebalance             {amount: "5000", allow_selling: false}
                                          -> {trades: [{action, symbol, category, units, est_amount}],
                                              after: [{category, pct}], residual_cash}
```

---

## 8. CSV import

`csv_import.py` is 54 lines and gets the important things right: `csv.DictReader` over a
`StringIO`, a sha256 `external_id` for idempotency, pre-load the existing ids into a set,
count imported vs skipped, one commit at the end. Follow it exactly.

New module `app/services/trade_import.py`. Do not touch `csv_import.py`.

### 8.1 Column mapping

The Google Sheet's Trade Log exports with these headers. Accept them case-insensitively
and whitespace-trimmed, plus the short aliases in parentheses:

| Sheet column | Field | Notes |
|---|---|---|
| Date | `traded_on` | Sheet writes MM-DD-YYYY. Also accept ISO. |
| Transaction Type | `type` | See §8.2 |
| Stock/ETF Symbol (`Symbol`) | → `security_id` | Uppercased; created if unknown |
| Quantity of Units (`Quantity`) | `quantity` | |
| Amount per unit (`Price`) | `price_per_unit` | |
| Total Amount (before trading fees) | — | **Ignored.** Derived. Used only to validate. |
| Trading Fees (`Fees`) | `fees` | Blank → 0 |
| Investment Account (`Account`) | `account_id` | Matched by name, case-insensitive |
| Split Ratio | `split_ratio` | |
| Currency | `currency` | Blank → `settings.base_currency` |
| Investment Category | → `securities.category_id` | Phase 2. Phase 1 ignores it. |

Number parsing has to survive the spreadsheet: strip `$`, `,`, and whitespace; treat
`(123.45)` as `-123.45`; treat `""`, `"-"`, and `"#N/A"` as zero/null. This is where
real imports fail, and it belongs in one `_decimal(raw)` helper with those cases as its
docstring.

**`MM-DD-YYYY` is genuinely ambiguous with `DD-MM-YYYY`.** Do not guess per row. Parse
the whole file with the US interpretation, and if any row fails, retry the whole file
with day-first. If both fail, reject the file with the offending row number. Never mix
interpretations within one import — that silently corrupts dates 1–12.

### 8.2 Type mapping

```python
_TYPE_ALIASES = {
    "buy": TradeType.buy, "purchase": TradeType.buy,
    "sell": TradeType.sell, "sale": TradeType.sell,
    "dividend": TradeType.dividend, "div": TradeType.dividend,
    "distribution": TradeType.dividend, "interest": TradeType.dividend,
    "split": TradeType.split, "stock split": TradeType.split,
}
```
Unknown type → that row is an error, not a skip. See §8.4.

### 8.3 Idempotency

```python
def _external_id(row: dict[str, str]) -> str:
    key = f"{date}|{type}|{symbol}|{quantity}|{price}|{account}"
    return hashlib.sha256(key.encode()).hexdigest()
```
Same shape as `csv_import._external_id`. Re-importing the same export is a no-op, which
is what makes "just import it again after you fix the sheet" a safe instruction.

Real risk: two genuinely identical trades on the same day (a split fill) collapse to one.
Accept it — the user can add the second by hand — and say so in the import result copy.
The alternative is a row-index in the hash, which breaks idempotency the moment a row is
inserted above.

### 8.4 Errors

`csv_import.py` returns `ImportResult(imported, skipped)` and raises `ValueError` for a
bad account. A trade import needs more, because a 400-row history will have three bad
rows and the user needs to know which:

```python
@dataclass
class TradeImportResult:
    imported: int
    skipped: int                       # already present
    errors: list[tuple[int, str]]      # (1-based row number, reason)
```

**Import valid rows and report the bad ones.** All-or-nothing on a 400-row file means
one typo blocks the whole history and the user gives up. The response lists the failed
rows with their line numbers so they can be fixed and re-imported — idempotency makes
the second pass safe.

Endpoint mirrors `api/imports.py` exactly: `UploadFile`, `await file.read()`, `.decode()`,
`ValueError` → 404/422.

**Decode defensively.** Sheets exports are UTF-8, but a file that has been through Excel
on Windows may be UTF-8-BOM or cp1252. Try `utf-8-sig`, then `cp1252`. `csv.DictReader`
also needs the BOM gone or the first header key becomes `"﻿Date"` — `utf-8-sig`
handles it.

### 8.5 Price backfill after import

Immediately after a successful import, kick a one-time history fetch: for every security
now in the portfolio, pull `range=10y&interval=1d` from the price provider and bulk-insert
into `security_prices`. One request per symbol, ~2,500 rows each. This is what makes the
historical performance tab work on day one instead of building up over a year.

Run it synchronously inside the import request if the symbol count is under ~10
(a few seconds), otherwise return immediately and let the scheduler's next tick do it.
The threshold exists only so the common case feels instant. **Do not add a job queue for
this.** If it becomes a problem, `asyncio.to_thread` from the endpoint, matching what
`scheduler.py` already does.

---

## 9. Things being cut

**The spin-off tool — dropped entirely.** It generates three trade-log rows. It is used
maybe once every several years. It needs the user to supply the cost-allocation
percentage anyway, which is the only genuinely hard part and which the tool cannot
compute. Replace with a paragraph in the docs: "a spin-off is a sell of the parent at the
allocated basis, a buy of the child at the allocated basis, and a re-buy of the parent."
If the user hits one and hates typing it, build it then.

**The 5-currency limit.** Not a feature.

**"Total Amount" as a stored column.** Derived. Imported for validation only — if it
disagrees with `quantity * price` by more than a cent, that row becomes an import
warning, which is genuinely useful as a typo-catcher.

**A `benchmarks` table.** One boolean on `securities`.

**Per-trade categories.** Category lives on the security. See §1.4.

**Any caching layer.** Prices are already a cache. Positions replay in <10ms. The
tripwire in §2.5 says when to revisit.

**A separate investment-accounts list.** `accounts` with `type = investment` already
exists.

---

## 10. UI

### 10.1 Structure

`/investments` becomes a page with sub-tabs, not five new nav entries. `Shell.tsx`'s
`NAV` array has four items and its mobile tab bar is `flex-1` per item — a fifth makes
each 20% wide and the labels wrap on a small phone. **Do not add to `NAV`.**

```
/investments                 Overview  (default)
/investments/holdings        Holdings
/investments/trades          Trade log
/investments/performance     Performance   (Phase 4)
/investments/rebalance       Rebalance     (Phase 5)
```

Sub-tabs as a horizontal scrolling row of `NavLink`s under `PageHead`, styled like the
existing sidebar links (`rounded-lg px-3 py-2 text-sm`, active = `text-bone` on
`bg-[rgba(198,242,78,0.08)]`), with `overflow-x-auto` and no scrollbar so five tabs fit
a 375px viewport. One new small component in `ui/Shell.tsx` next to `PageHead`.

### 10.2 Per tab

**Overview** — keeps today's page, with the numbers upgraded from feed-derived guesses to
trade-derived facts. Portfolio value from holdings, not account balances. The
`AllocationBar` switches from per-account to per-category once Phase 2 lands — it takes
five slices before folding into "Other", which matches a realistic category count
exactly. `AreaChart` for the value history. The disclaimer paragraph at the bottom gets
rewritten: it currently says share counts and cost basis are unavailable, which will no
longer be true.

**Holdings** — the core new screen. One row per security:

- Desktop: a table — symbol, category, units, avg cost, price, market value, unrealized
  $ and %.
- Mobile: **not a table.** A stacked card per holding — symbol and market value on the
  first line at `text-base`, then a two-column grid of `label`/`tnum` pairs for units,
  avg cost, and unrealized. Same pattern the existing pages use for `Stat`. A horizontally
  scrolling 8-column table on a phone is unusable; do not ship one.
- Expanding a row reveals the per-account unit breakdown from `HoldingOut.by_account`.
- An unpriced holding shows "no price" and a "set price" input, per §3.4.
- `AllocationBar` above the list, sliced by category (Phase 2) or by security (Phase 1).

**Trade log** — a reverse-chronological list plus an "Add trade" form. The form is the
one place typing happens, so it deserves care:

- Fields in the sheet's order: date, type, symbol, quantity, price, fees, account,
  currency. Split ratio appears only when type is `split`; quantity and price hide when
  type is `split`.
- `inputMode="decimal"` on every numeric field. Without it iOS shows the alphabet
  keyboard and entering a portfolio's history on a phone is miserable.
- Live-computed "Total: $3,016.25" under the amount fields so a fat-fingered price is
  visible before saving.
- Symbol field is a datalist of existing securities, free-typed to create a new one.
- One line of help under the type selector: *"A reinvested dividend is two rows — a
  dividend for the cash, then a buy for the units."*
- Filters: security, account, date range. Same shape as `TransactionsPage`.
- CSV import lives here — a file input reusing whatever `AccountDetailPage` does for
  transaction import, with the error rows rendered as a list under the result.

**Performance** (Phase 4) — one `BarChart` of monthly returns and a table of the sheet's
columns. `BarChart` renders negative values at height 0 (see the `Math.max(..., 0)` in
`charts.tsx`), so a month with a loss is invisible. **This must be fixed in `charts.tsx`
before the performance tab ships** — either a zero-baseline variant or, laziest, chart
month-end portfolio value with `AreaChart` and show the return percentages in the table
only. Prefer the lazy option; revisit if the user asks for a returns chart.

Benchmark comparison: two stacked `AreaChart`s, both indexed to 100, per §6.

**Rebalance** (Phase 5) — amount input, an "allow selling" toggle, and a table of
suggested trades. The output is advice, not an action; nothing is written. It must say
so.

### 10.3 Formatting

`money.ts` `usd()` and `usdCompact()` for currency. Units are not currency — they need a
plain `Intl.NumberFormat` with up to 4 fraction digits, added to `money.ts` as `units()`.
Percentages: one decimal, `+`/`−` prefixed, `text-acid` when positive and the existing
muted tone when negative — matching how the current page tones income.

Multi-currency (Phase 2) shows the base-currency figure as primary and the local figure
as a smaller muted line beneath, never side-by-side columns. Columns do not fit a phone.

---

## 11. Phasing

### Phase 1 — the smallest thing that beats the spreadsheet

Tables `securities`, `trades`, `security_prices`. USD only. Average-cost engine handling
all four trade types. Yahoo price fetch on the existing scheduler tick, plus manual
override. CSV import of the sheet's Trade Log with a 10-year price backfill. Holdings tab
and Trade log tab. Overview switches to trade-derived values.

Delivered value: the user imports their sheet and sees real holdings with real cost basis
and real unrealized gain, computed from real prices, on their phone. That alone replaces
the two tabs of the sheet they look at most.

Explicitly **not** in Phase 1: currencies, categories, targets, rebalancing, XIRR,
benchmarks, realized-gains report, dividend-by-year report, spin-offs.

### Phase 2 — categories and allocation
`investment_categories` with `target_pct`. `AllocationBar` by category. Actual-vs-target
drift table. `fx_rates` + multi-currency, if the user actually holds a non-USD security —
**check before building it.**

### Phase 3 — the reports
Realized gains by date range and account (the engine already computes `realized`; this is
a query and a table). Dividends by year with YoY change (same). Both are cheap because
Phase 1 did the hard part.

### Phase 4 — performance
XIRR, monthly performance table, indexed benchmark chart. The `charts.tsx` negative-bar
issue gets decided here.

### Phase 5 — rebalancing
The suggestion engine. Genuinely useful, genuinely the least urgent, and completely
dependent on Phase 2's targets.

**Never:** spin-off tool, position snapshot caching (until the §2.5 tripwire trips), any
job queue.

---

## 12. Testing

Follow `backend/tests/test_investments.py`: real `Session`, small fixtures, one assertion
per behaviour.

The cost-basis engine is the part that must not be wrong, and it is pure — a list of
trades in, positions out, no I/O. Test it directly, not through the API:

- buy → avg cost includes fees
- buy, buy at a different price → weighted average, not arithmetic mean
- sell → realized gain uses average cost, and fees reduce proceeds
- sell everything → units and cost base are both exactly zero
- sell more than held → raises
- 2-for-1 split → units double, cost base unchanged, avg cost halves
- reverse split (`ratio = 0.5`) → units halve
- split applies per account, not globally
- dividend → position untouched, dividend total rises
- two trades on the same day apply in `created_at` order
- the whole thing with `Decimal("0.1") + Decimal("0.2")` values, asserting exact
  equality — the test that proves nobody slipped a float in

XIRR: a hand-checkable case (one −1000 flow, one +1100 flow one year later → ~10%), a
no-solution case returning `None`, and a volatile series that makes naive Newton diverge.

Price providers: `httpx.MockTransport` with a captured Yahoo response body. No network in
tests, matching how the SimpleFIN provider is tested.

CSV import: a fixture file with the real sheet's headers, `$1,234.56` formatting,
`(123.45)` negatives, a blank fee column, one unparseable row, and a duplicate row — one
test asserting `imported`, `skipped`, and `errors` all together.
