import { useState } from "react";
import { Link } from "react-router-dom";
import { AreaChart } from "../charts";
import { useAccounts, useNetWorthHistory, type Account, type NetWorthPoint } from "../data";
import { LIABILITY_TYPES, netWorth, prettyType, usd } from "../money";
import { Card, Empty, PageHead } from "../ui/Shell";

const TABS = ["Summary", "Assets", "Debts"] as const;
type Tab = (typeof TABS)[number];
const SIDE: Record<Tab, keyof Omit<NetWorthPoint, "on">> = {
  Summary: "net",
  Assets: "assets",
  Debts: "debts",
};

function History({ points, tab }: { points: NetWorthPoint[]; tab: Tab }) {
  if (points.length < 2) {
    return (
      <Empty>
        {points.length === 1
          ? "One day recorded so far — the line appears once there are two."
          : "No history yet. Balances are recorded daily from now on."}
      </Empty>
    );
  }
  return (
    <AreaChart
      valueLabel={tab === "Summary" ? "Net worth" : tab}
      points={points.map((p) => ({ label: p.on, value: p[SIDE[tab]] }))}
    />
  );
}

function AccountList({ accounts, empty }: { accounts: Account[]; empty: string }) {
  if (accounts.length === 0) return <p className="py-3 text-sm text-muted">{empty}</p>;
  return (
    <ul>
      {accounts.map((a) => (
        <li key={a.id} className="border-b border-line last:border-0">
          <Link
            to={`/accounts/${a.id}`}
            className="flex items-center gap-3 py-3 transition-colors hover:text-brand"
          >
            <span
              aria-hidden
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-sm text-muted"
            >
              {a.name.trim().charAt(0).toUpperCase() || "·"}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{a.name}</span>
              <span className="block text-[12px] text-muted capitalize">{prettyType(a.type)}</span>
            </span>
            {/* A debt is stored negative; on the Debts tab it reads as what is owed. */}
            <span className="tnum shrink-0 text-sm">{usd(Math.abs(Number(a.balance)))}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function NetWorthPage() {
  const { data: accounts = [] } = useAccounts();
  const { data: history = [] } = useNetWorthHistory(90);
  const [tab, setTab] = useState<Tab>("Summary");

  const { assets, debts, net } = netWorth(accounts);
  const owned = accounts.filter((a) => !LIABILITY_TYPES.has(a.type));
  const owed = accounts.filter((a) => LIABILITY_TYPES.has(a.type));
  const headline = { Summary: net, Assets: assets, Debts: debts }[tab];

  return (
    <>
      <PageHead title="Net Worth" sub="What you own, less what you owe" />

      <div role="tablist" aria-label="Net worth" className="mb-4 inline-flex rounded-full bg-white/20 p-1">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`networth-tab-${t}`}
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
              tab === t ? "bg-surface font-medium text-bone" : "text-white"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-labelledby={`networth-tab-${tab}`}>
        <Card className="mb-4">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h2 className="label">{tab === "Summary" ? "Net worth" : `Total ${tab.toLowerCase()}`}</h2>
              <p className={`tnum mt-1 text-4xl font-medium tracking-tight ${tab === "Debts" ? "text-clay" : ""}`}>
                {usd(headline)}
              </p>
            </div>
            <span className="text-[13px] text-muted">Last 90 days</span>
          </div>
          <History points={history} tab={tab} />
        </Card>

        {tab === "Summary" ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <h2 className="label">Assets</h2>
              <p className="tnum mt-1 text-2xl">{usd(assets)}</p>
              <p className="mt-1 text-[13px] text-muted">
                {owned.length} account{owned.length === 1 ? "" : "s"}
              </p>
            </Card>
            <Card>
              <h2 className="label">Debts</h2>
              <p className="tnum mt-1 text-2xl text-clay">{usd(debts)}</p>
              <p className="mt-1 text-[13px] text-muted">
                {owed.length} account{owed.length === 1 ? "" : "s"}
              </p>
            </Card>
          </div>
        ) : (
          <Card>
            <div className="mb-1 flex items-baseline justify-between">
              <h2 className="label">{tab === "Assets" ? "What you own" : "What you owe"}</h2>
              <Link to="/accounts" className="text-[13px] underline underline-offset-2">
                Link accounts
              </Link>
            </div>
            <AccountList
              accounts={tab === "Assets" ? owned : owed}
              empty={tab === "Assets" ? "No asset accounts yet." : "Nothing owed."}
            />
          </Card>
        )}
      </div>
    </>
  );
}
