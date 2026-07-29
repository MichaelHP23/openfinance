import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { apiFetch } from "../api/client";
import { AllocationBar, AreaChart, BarChart } from "../charts";
import { HoldingsList } from "../holdings";
import { holdingTotals, useHoldings, type TradeFilters } from "../investments";
import { pct, pctTone, usd } from "../money";
import { AddTradeForm, TradeFiltersControls, TradeImport, TradeLog } from "../trades";
import { Card, Empty, PageHead } from "../ui/Shell";

type InvestmentAccount = {
  id: string;
  name: string;
  type: string;
  balance: number;
  income: number;
  share: number;
};

type Summary = {
  total_value: number;
  account_count: number;
  accounts: InvestmentAccount[];
  income_ytd: number;
  income_all_time: number;
  income_by_month: { month: string; total: number }[];
  recent_income: { date: string; account: string; merchant: string; amount: number }[];
  contributions_ytd: number;
  has_income_data: boolean;
};

const monthLabel = (key: string) =>
  new Date(`${key}-01T00:00:00Z`).toLocaleString("en-US", { month: "short", timeZone: "UTC" });

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p className={`tnum mt-2 text-xl ${tone}`}>{value}</p>
    </div>
  );
}

// ponytail: this lives here rather than in ui/Shell.tsx (which the spec suggests) —
// Shell.tsx's nav is owned by a parallel change to the routing shell, and a sub-tab
// row used by exactly one page doesn't need to live in the shared shell file.
function SubTabs() {
  const tabs = [
    { to: "/investments", label: "Overview", end: true },
    { to: "/investments/holdings", label: "Holdings", end: false },
    { to: "/investments/trades", label: "Trade log", end: false },
  ];
  return (
    <nav
      className="rise mb-6 flex gap-1 overflow-x-auto"
      style={{ scrollbarWidth: "none", "--d": "20ms" } as React.CSSProperties}
    >
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            [
              "shrink-0 rounded-lg px-3 py-2 text-sm whitespace-nowrap transition-colors",
              isActive
                ? "bg-[rgba(198,242,78,0.08)] text-bone"
                : "text-muted hover:bg-[rgba(237,234,228,0.04)] hover:text-bone",
            ].join(" ")
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

function OverviewTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["investments"],
    queryFn: () => apiFetch<Summary>("/investments"),
  });
  const { data: history = [] } = useQuery({
    queryKey: ["investment-history"],
    queryFn: () => apiFetch<{ on: string; net: number }[]>("/investments/history?days=90"),
  });
  // Once trades exist they're the source of truth for portfolio value (spec §10.2);
  // before that this falls back to the feed-derived total the page always showed.
  const { data: holdingsData } = useHoldings();
  const holdings = holdingsData?.holdings ?? [];
  const hasTrades = holdings.length > 0;
  const totals = holdingTotals(holdings);
  const portfolioValue = hasTrades ? totals.market : (data?.total_value ?? 0);

  if (isLoading) return <Empty>Loading…</Empty>;

  if (!data || (data.account_count === 0 && !hasTrades)) {
    return (
      <Empty>
        No investment accounts yet. Link a brokerage, or mark an existing account as{" "}
        <em>investment</em> on the{" "}
        <Link to="/accounts" className="text-acid">
          accounts page
        </Link>
        .
      </Empty>
    );
  }

  return (
    <>
      <section className="rise mb-8" style={{ "--d": "60ms" } as React.CSSProperties}>
        <p className="label">Portfolio value</p>
        <p className="tnum mt-2 text-5xl leading-none md:text-6xl">{usd(portfolioValue)}</p>
        {hasTrades && (
          <p className={`tnum mt-2 text-sm ${pctTone(totals.unrealized)}`}>
            {usd(totals.unrealized)} unrealized ({pct(totals.unrealizedPct)})
          </p>
        )}
      </section>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Dividends & interest · YTD" value={usd(data.income_ytd)} tone="text-acid" />
        <Stat label="Contributions · YTD" value={usd(data.contributions_ytd)} />
        <Stat label="Income · all recorded" value={usd(data.income_all_time)} />
      </div>

      <Card delay={100}>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-sm font-medium">Portfolio value</h2>
          <span className="label">Last 90 days</span>
        </div>
        {history.length < 2 ? (
          <Empty>
            {history.length === 1
              ? "One day recorded — the line starts once there are two."
              : "Balances are recorded daily from now on; the line builds from here."}
          </Empty>
        ) : (
          <AreaChart
            valueLabel="Portfolio value"
            points={history.map((p) => ({ label: p.on, value: p.net }))}
          />
        )}
      </Card>

      <Card className="mt-4" delay={140}>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-sm font-medium">Allocation</h2>
          <span className="label">Share of portfolio</span>
        </div>
        <AllocationBar
          slices={data.accounts.map((a) => ({
            label: a.name,
            value: a.balance,
            share: a.share,
          }))}
        />
        <ul className="mt-5 flex flex-col gap-1.5 border-t border-line pt-4">
          {data.accounts
            .filter((a) => a.income > 0)
            .map((a) => (
              <li key={a.id} className="flex justify-between text-[13px]">
                <Link to={`/accounts/${a.id}`} className="truncate text-muted hover:text-acid">
                  {a.name}
                </Link>
                <span className="tnum text-acid">+{usd(a.income)} income</span>
              </li>
            ))}
        </ul>
      </Card>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[3fr_2fr]">
        <Card delay={180}>
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="text-sm font-medium">Dividends & interest</h2>
            <span className="label">By month</span>
          </div>
          {!data.has_income_data ? (
            <Empty>
              No dividends or interest found. Either none were paid in this window, or your
              brokerage describes them too tersely to recognise.
            </Empty>
          ) : (
            <BarChart
              bars={data.income_by_month.map((m) => ({
                label: monthLabel(m.month),
                value: m.total,
              }))}
            />
          )}
        </Card>

        <Card delay={240}>
          <h2 className="mb-4 text-sm font-medium">Recent payouts</h2>
          {data.recent_income.length === 0 ? (
            <Empty>Nothing yet.</Empty>
          ) : (
            <ul className="flex flex-col gap-3">
              {data.recent_income.map((r, i) => (
                <li key={`${r.date}-${i}`} className="flex justify-between gap-3 text-[13px]">
                  <span className="min-w-0">
                    <span className="block truncate">{r.merchant}</span>
                    <span className="label">
                      {r.date} · {r.account}
                    </span>
                  </span>
                  <span className="tnum shrink-0 text-acid">+{usd(r.amount)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="mt-6 text-[13px] leading-relaxed text-muted">
        {hasTrades
          ? "Portfolio value, share counts and cost basis come from your trade log. Dividend, interest and contribution figures above still come from the bank feed, which describes them too tersely to always get right."
          : "Balances and cash flow come from your bank feed. Share counts, cost basis and per-holding performance need a trade log — add trades on the Trade log tab, or import your sheet's export there, to unlock them."}
      </p>
    </>
  );
}

function HoldingsTab() {
  return <HoldingsList />;
}

function TradesTab() {
  const [filters, setFilters] = useState<TradeFilters>({});
  return (
    <>
      <Card delay={60}>
        <h2 className="mb-4 text-sm font-medium">Add a trade</h2>
        <AddTradeForm />
        <div className="mt-5 border-t border-line pt-5">
          <TradeImport />
        </div>
      </Card>

      <Card className="mt-4" delay={120}>
        <h2 className="mb-4 text-sm font-medium">History</h2>
        <div className="mb-4">
          <TradeFiltersControls filters={filters} onChange={setFilters} />
        </div>
        <TradeLog filters={filters} />
      </Card>
    </>
  );
}

export function InvestmentsPage() {
  return (
    <>
      <PageHead title="Investments" />
      <SubTabs />
      <Routes>
        <Route index element={<OverviewTab />} />
        <Route path="holdings" element={<HoldingsTab />} />
        <Route path="trades" element={<TradesTab />} />
      </Routes>
    </>
  );
}
