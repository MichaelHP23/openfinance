import { Link } from "react-router-dom";
import { useAccounts, useTransactions } from "../data";
import { TxnRows } from "../transactions";
import { monthlySeries, monthTotals, netWorth, topMerchants, usd, usdCompact } from "../money";
import { Card, Empty, PageHead } from "../ui/Shell";

const NOW = new Date();
const THIS_MONTH = `${NOW.getFullYear()}-${String(NOW.getMonth() + 1).padStart(2, "0")}`;

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p className={`tnum mt-2 text-xl ${tone}`}>{value}</p>
    </div>
  );
}

export function OverviewPage() {
  const { data: accounts = [] } = useAccounts();
  const { data: txns = [] } = useTransactions();

  const { assets, debts, net } = netWorth(accounts);
  const month = monthTotals(txns, THIS_MONTH);
  const series = monthlySeries(txns, 6, NOW);
  const merchants = topMerchants(txns, 5);
  const peak = Math.max(1, ...series.flatMap((m) => [m.inflow, m.outflow]));
  const merchantPeak = Math.max(1, ...merchants.map((m) => m.total));

  return (
    <>
      <PageHead
        title="Overview"
        sub={NOW.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
      />

      <section className="rise mb-10" style={{ "--d": "60ms" } as React.CSSProperties}>
        <p className="label">Net worth</p>
        <p className="tnum mt-2 text-5xl leading-none md:text-6xl">{usd(net)}</p>
        <p className="mt-3 text-sm text-muted">
          <span className="text-bone">{usd(assets)}</span> in assets
          {debts > 0 && (
            <>
              {" · "}
              <span className="text-clay">{usd(debts)}</span> owed
            </>
          )}
          {accounts.length === 0 && " — add an account to get started"}
        </p>
      </section>

      <div className="mb-8 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Money in · this month" value={usd(month.inflow)} tone="text-acid" />
        <Stat label="Money out · this month" value={usd(month.outflow)} />
        <Stat
          label="Net · this month"
          value={usd(month.net)}
          tone={month.net < 0 ? "text-clay" : ""}
        />
        <Stat label="Accounts" value={String(accounts.length)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card delay={120}>
          <div className="mb-5 flex items-baseline justify-between">
            <h2 className="text-sm font-medium">Cash flow</h2>
            <span className="label">Last 6 months</span>
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
                        className="w-1/2 rounded-t-sm bg-[#3c3c44] transition-all"
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
                  <span className="size-2 rounded-full bg-[#3c3c44]" /> out
                </span>
                <span className="ml-auto tnum">peak {usdCompact(peak)}</span>
              </p>
            </>
          )}
        </Card>

        <Card delay={180}>
          <h2 className="mb-5 text-sm font-medium">Where it goes</h2>
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
                  <div className="h-1.5 overflow-hidden rounded-full bg-[#26262c]">
                    <div
                      className="h-full rounded-full bg-acid/70"
                      style={{ width: `${(m.total / merchantPeak) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-4" delay={240}>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-medium">Recent activity</h2>
          <Link to="/transactions" className="label transition-colors hover:text-bone">
            View all →
          </Link>
        </div>
        {txns.length === 0 ? (
          <Empty>
            Import a CSV or add a transaction from the{" "}
            <Link to="/transactions" className="text-acid">
              transactions page
            </Link>
            .
          </Empty>
        ) : (
          <TxnRows txns={txns.slice(0, 8)} />
        )}
      </Card>
    </>
  );
}
