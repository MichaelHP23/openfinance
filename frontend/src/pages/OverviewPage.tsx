import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { AreaChart } from "../charts";
import { useAccounts, useNetWorthHistory, useTransactions, type Txn } from "../data";
import { SERIES } from "../palette";
import { useSafeToSpend } from "../forecast";
import {
  accountGroups,
  cumulativeSpend,
  monthlySeries,
  monthTotals,
  netWorth,
  shortDate,
  signedAmount,
  topMerchants,
  usd,
  usdCompact,
} from "../money";
import { Assistant, NetWorthChart } from "../insights";
import type { Summary } from "../recurring";
import { Card, Empty, PageHead } from "../ui/Shell";
import { ForecastChart } from "../ForecastChart";
import { AlertsCard } from "../AlertsCard";
import { SafeToSpendCard } from "../SafeToSpendCard";

const NOW = new Date();
const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const THIS_MONTH = key(NOW);
const PRIOR_MONTHS = [1, 2, 3].map((back) => key(new Date(NOW.getFullYear(), NOW.getMonth() - back, 1)));
const TODAY = NOW.getDate();
const DAY_MS = 86_400_000;

const GROUP_GLYPH: Record<string, string> = {
  checking: "▤",
  cards: "▭",
  net_cash: "≡",
  savings: "◍",
  investments: "◈",
};

/** The headline: what has gone out this month, the curve it took, and how that compares
 * with where the last three months stood on the same day. */
function SpendHero({ txns }: { txns: Txn[] }) {
  const { data: safe } = useSafeToSpend();
  const month = monthTotals(txns, THIS_MONTH);
  const curve = cumulativeSpend(txns, THIS_MONTH, TODAY);
  // Months with no spending at all are left out of the average: they are missing history,
  // not frugal months.
  const prior = PRIOR_MONTHS.map((k) => cumulativeSpend(txns, k, TODAY).at(-1)?.value ?? 0).filter(
    (v) => v > 0,
  );
  const average = prior.length ? prior.reduce((a, b) => a + b, 0) / prior.length : 0;
  const gap = average - month.outflow;
  // `until` is a date; the days are counted from today's date, not from this instant.
  const paydayIn = safe?.until ? Math.round((Date.parse(safe.until) - TODAY_UTC) / DAY_MS) : null;

  return (
    <section className="card rise mb-4 overflow-hidden">
      <div className="p-5 pb-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[13px] text-muted">Current spend this month</p>
            <p className="tnum mt-1 text-4xl font-medium tracking-tight">{usd(month.outflow)}</p>
          </div>
          {average > 0 && (
            <p className="flex items-center gap-2 text-right text-[13px] leading-tight text-muted">
              <span
                aria-hidden
                className={`flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px] ${
                  gap >= 0 ? "border-acid text-acid" : "border-clay text-clay"
                }`}
              >
                {gap >= 0 ? "✓" : "!"}
              </span>
              <span>
                {usd(Math.abs(gap))} {gap >= 0 ? "below" : "above"}
                <br />
                avg. spend
              </span>
            </p>
          )}
        </div>
        {curve.length >= 2 && (
          <div className="mt-3">
            <AreaChart points={curve} height={120} valueLabel="Spent" />
          </div>
        )}
      </div>
      {paydayIn !== null && (
        <p className="flex items-center gap-3 border-t border-line px-5 py-3 text-sm">
          <span
            aria-hidden
            className="flex h-6 w-8 items-center justify-center rounded-md border border-acid text-[11px] text-acid"
          >
            $
          </span>
          Payday {paydayIn <= 0 ? "today" : `in ${paydayIn} day${paydayIn === 1 ? "" : "s"}`}
        </p>
      )}
      <dl className="grid grid-cols-2 border-t border-line text-sm">
        <div className="px-5 py-3">
          <dt className="text-[13px] text-muted">Income this month</dt>
          <dd className="tnum mt-0.5 text-acid">{usd(month.inflow)}</dd>
        </div>
        <div className="border-l border-line px-5 py-3">
          <dt className="text-[13px] text-muted">Net this month</dt>
          <dd className={`tnum mt-0.5 ${month.net < 0 ? "text-clay" : ""}`}>{usd(month.net)}</dd>
        </div>
      </dl>
    </section>
  );
}

function Row({ glyph, title, sub, value, tone = "" }: {
  glyph: string;
  title: string;
  sub?: string;
  value: string;
  tone?: string;
}) {
  return (
    <li className="flex items-center gap-3 border-b border-line py-3 last:border-0 last:pb-0">
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-sm text-muted"
      >
        {glyph}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{title}</span>
        {sub && <span className="block text-[12px] text-muted">{sub}</span>}
      </span>
      <span className={`tnum shrink-0 text-sm ${tone}`}>{value}</span>
    </li>
  );
}

type Group = ReturnType<typeof accountGroups>[number];

/** One line of the Accounts card. A group with accounts in it opens to list them. */
function AccountGroup({ group }: { group: Group }) {
  const [open, setOpen] = useState(false);
  const tone = group.key === "net_cash" ? (group.total < 0 ? "text-clay" : "text-acid") : "";
  const line = (
    <>
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-sm text-muted"
      >
        {GROUP_GLYPH[group.key]}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm">{group.label}</span>
      <span className={`tnum shrink-0 text-sm ${tone}`}>{usd(group.total)}</span>
    </>
  );
  return (
    <li className="border-b border-line last:border-0">
      {group.accounts.length === 0 ? (
        <div className="flex items-center gap-3 py-3 pr-6">{line}</div>
      ) : (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-3 py-3 text-left"
        >
          {line}
          <span aria-hidden className={`w-3 text-xs text-muted transition-transform ${open ? "rotate-180" : ""}`}>
            ⌄
          </span>
        </button>
      )}
      {open && (
        <ul className="pb-3 pl-12">
          {group.accounts.map((a) => (
            <li key={a.id}>
              <Link
                to={`/accounts/${a.id}`}
                className="flex justify-between gap-3 py-1.5 pr-6 text-[13px] text-muted transition-colors hover:text-bone"
              >
                <span className="truncate">{a.name}</span>
                <span className="tnum shrink-0">{usd(Math.abs(Number(a.balance)))}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

const TODAY_UTC = Date.UTC(NOW.getFullYear(), NOW.getMonth(), TODAY);

/** "Today", "Tomorrow", "In 5 days" — how far off a dated charge is. */
function daysUntil(on: string) {
  const days = Math.round((Date.parse(on) - TODAY_UTC) / DAY_MS);
  if (days < 0) return "Overdue";
  if (days === 0) return "Today";
  return days === 1 ? "Tomorrow" : `In ${days} days`;
}

/** A recurring charge or payday that is due soon, as a small tile. The disc stands in
 * for a merchant logo: an initial on one of the chart colours, picked by name. */
function UpcomingTile({ label, on, amount, direction }: Summary["upcoming"][number]) {
  const incoming = direction > 0;
  const colour = SERIES[label.charCodeAt(0) % SERIES.length];
  return (
    <li className="w-28 shrink-0 overflow-hidden rounded-xl border border-line text-center">
      <div className="flex h-12 items-center justify-center" style={{ background: `${colour}22` }}>
        <span
          aria-hidden
          className="flex size-7 items-center justify-center rounded-full text-xs font-medium text-white"
          style={{ background: colour }}
        >
          {label.trim().charAt(0).toUpperCase() || "·"}
        </span>
      </div>
      <p className="mt-2 truncate px-2 text-[12px] text-muted">{label}</p>
      <p className={`tnum text-sm font-medium ${incoming ? "text-acid" : ""}`}>
        {signedAmount({ amount, direction })}
      </p>
      <p className="label mt-2 border-t border-line py-1.5">{daysUntil(on)}</p>
    </li>
  );
}

function CardHead({ title, to, more }: { title: string; to?: string; more?: string }) {
  return (
    <div className="mb-1 flex items-baseline justify-between">
      <h2 className="label">{title}</h2>
      {to && (
        <Link to={to} className="text-[13px] text-muted transition-colors hover:text-bone">
          {more} →
        </Link>
      )}
    </div>
  );
}

export function OverviewPage() {
  const { data: accounts = [], isPending } = useAccounts();
  const { data: txns = [] } = useTransactions();
  const { data: history = [] } = useNetWorthHistory(90);
  // Same key the Recurring page uses, so the two share one fetch.
  const { data: recurring } = useQuery({
    queryKey: ["recurring", "summary"],
    queryFn: () => apiFetch<Summary>("/recurring/summary"),
  });
  // A question an alert's "Ask advisor" hands to the assistant card further down.
  const [prompt, setPrompt] = useState<{ question: string }>();

  const { assets, debts, net } = netWorth(accounts);
  const groups = accountGroups(accounts);
  const series = monthlySeries(txns, 6, NOW);
  const merchants = topMerchants(txns, 5);
  const peak = Math.max(1, ...series.flatMap((m) => [m.inflow, m.outflow]));
  const merchantPeak = Math.max(1, ...merchants.map((m) => m.total));
  const upcoming = recurring?.upcoming ?? [];

  const head = (
    <PageHead
      title="Dashboard"
      sub={NOW.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
    />
  );

  // An empty install has nothing to chart; a page of $0.00 cards would read as broken.
  if (!isPending && accounts.length === 0) {
    return (
      <>
        {head}
        <Card>
          <p className="text-lg font-medium">Nothing here yet</p>
          <p className="mt-1 mb-4 text-sm text-muted">
            Add an account, then import its transactions or link your bank. Your spending,
            bills and net worth show up here.
          </p>
          <Link to="/accounts" className="btn inline-block">
            Add your first account
          </Link>
        </Card>
        <Assistant prompt={prompt} />
      </>
    );
  }

  return (
    <>
      {head}

      <AlertsCard onAsk={(question) => setPrompt({ question })} />

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="min-w-0">
          <SpendHero txns={txns} />

          <Card className="mb-4" delay={100}>
            <CardHead title="Upcoming" to="/recurring" more="All recurring" />
            {upcoming.length === 0 ? (
              <p className="py-3 text-sm text-muted">Nothing expected soon.</p>
            ) : (
              <ul className="mt-2 flex gap-3 overflow-x-auto pb-1">
                {upcoming.slice(0, 8).map((u) => (
                  <UpcomingTile key={u.id} {...u} />
                ))}
              </ul>
            )}
          </Card>

          <Card className="mb-4" delay={120}>
            <CardHead title="Recent activity" to="/transactions" more="View all" />
            {txns.length === 0 ? (
              <Empty>
                Import a CSV or add a transaction from the{" "}
                <Link to="/transactions" className="text-acid">
                  transactions page
                </Link>
                .
              </Empty>
            ) : (
              <ul>
                {txns.slice(0, 7).map((t) => (
                  <Row
                    key={t.id}
                    glyph={t.merchant_raw.trim().charAt(0).toUpperCase() || "·"}
                    title={t.merchant_normalized || t.merchant_raw}
                    sub={`${shortDate(t.posted_at)}${t.ignored ? " · Ignored" : ""}`}
                    value={Number(t.amount) > 0 ? `+${usd(t.amount)}` : usd(t.amount)}
                    tone={t.ignored ? "opacity-50" : Number(t.amount) > 0 ? "text-acid" : ""}
                  />
                ))}
              </ul>
            )}
          </Card>

          <Card className="mb-4" delay={160}>
            <div className="mb-5 flex items-baseline justify-between">
              <h2 className="label">Cash flow</h2>
              <span className="text-[13px] text-muted">Last 6 months</span>
            </div>
            {txns.length === 0 ? (
              <Empty>No transactions yet.</Empty>
            ) : (
              <>
                <div className="flex h-40 gap-3">
                  {series.map((m) => (
                    <div key={m.key} className="flex flex-1 flex-col items-center gap-2">
                      <div className="flex w-full flex-1 items-end justify-center gap-1">
                        <div
                          title={`In ${usd(m.inflow)}`}
                          className="w-1/2 rounded-t-sm bg-acid/80 transition-all"
                          style={{ height: `${(m.inflow / peak) * 100}%` }}
                        />
                        <div
                          title={`Out ${usd(m.outflow)}`}
                          className="w-1/2 rounded-t-sm bg-out transition-all"
                          style={{ height: `${(m.outflow / peak) * 100}%` }}
                        />
                      </div>
                      <span className="label">{m.label}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-4 flex gap-4 text-[11px] text-muted">
                  <span className="flex items-center gap-1.5">
                    <span className="size-2 rounded-full bg-acid" /> in
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="size-2 rounded-full bg-out" /> out
                  </span>
                  <span className="ml-auto tnum">peak {usdCompact(peak)}</span>
                </p>
              </>
            )}
          </Card>
        </div>

        <div className="min-w-0">
          <Card className="mb-4" delay={80}>
            <div className="mb-1 flex items-baseline justify-between">
              <h2 className="label">Accounts</h2>
              <Link to="/accounts" className="text-[13px] underline underline-offset-2">
                Add account
              </Link>
            </div>
            <ul>
              {groups.map((g) => (
                <AccountGroup key={g.key} group={g} />
              ))}
            </ul>
          </Card>

          <SafeToSpendCard />

          <Card className="mb-4" delay={180}>
            <h2 className="label mb-4">Where it goes</h2>
            {merchants.length === 0 ? (
              <Empty>Nothing spent yet.</Empty>
            ) : (
              <ul className="flex flex-col gap-3.5">
                {merchants.map((m) => (
                  <li key={m.merchant}>
                    <div className="mb-1.5 flex justify-between text-[13px]">
                      <span className="truncate">{m.merchant}</span>
                      <span className="tnum text-muted">{usd(m.total)}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-track">
                      <div
                        className="h-full rounded-full bg-brand/80"
                        style={{ width: `${(m.total / merchantPeak) * 100}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Card className="mb-4" delay={200}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="label">Net worth</h2>
            <p className="tnum mt-1 text-3xl font-medium tracking-tight">{usd(net)}</p>
            <p className="mt-1 text-[13px] text-muted">
              <span className="text-bone">{usd(assets)}</span> in assets
              {debts > 0 && (
                <>
                  {" · "}
                  <span className="text-clay">{usd(debts)}</span> owed
                </>
              )}
            </p>
          </div>
          <span className="text-[13px] text-muted">Last 90 days</span>
        </div>
        <NetWorthChart points={history} />
      </Card>

      <ForecastChart />

      <Assistant prompt={prompt} />
    </>
  );
}
