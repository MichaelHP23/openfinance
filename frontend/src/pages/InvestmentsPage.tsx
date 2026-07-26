import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/client";
import { usd, usdCompact } from "../money";
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

export function InvestmentsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["investments"],
    queryFn: () => apiFetch<Summary>("/investments"),
  });

  if (isLoading) return <Empty>Loading…</Empty>;

  if (!data || data.account_count === 0) {
    return (
      <>
        <PageHead title="Investments" />
        <Empty>
          No investment accounts yet. Link a brokerage, or mark an existing account as{" "}
          <em>investment</em> on the{" "}
          <Link to="/accounts" className="text-acid">
            accounts page
          </Link>
          .
        </Empty>
      </>
    );
  }

  const peak = Math.max(1, ...data.income_by_month.map((m) => m.total));

  return (
    <>
      <PageHead
        title="Investments"
        sub={`${data.account_count} account${data.account_count > 1 ? "s" : ""}`}
      />

      <section className="rise mb-8" style={{ "--d": "60ms" } as React.CSSProperties}>
        <p className="label">Portfolio value</p>
        <p className="tnum mt-2 text-5xl leading-none md:text-6xl">{usd(data.total_value)}</p>
      </section>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="Dividends & interest · YTD" value={usd(data.income_ytd)} tone="text-acid" />
        <Stat label="Contributions · YTD" value={usd(data.contributions_ytd)} />
        <Stat label="Income · all recorded" value={usd(data.income_all_time)} />
      </div>

      <Card delay={120}>
        <h2 className="mb-4 text-sm font-medium">Holdings by account</h2>
        <ul className="flex flex-col gap-4">
          {data.accounts.map((a) => (
            <li key={a.id}>
              <div className="mb-1.5 flex flex-wrap justify-between gap-2 text-sm">
                <Link to={`/accounts/${a.id}`} className="truncate hover:text-acid">
                  {a.name}
                </Link>
                <span className="tnum">
                  {usd(a.balance)}
                  <span className="ml-2 text-muted">{a.share}%</span>
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[#26262c]">
                <div className="h-full rounded-full bg-acid/70" style={{ width: `${a.share}%` }} />
              </div>
              {a.income > 0 && (
                <p className="label mt-1.5">{usd(a.income)} in dividends & interest</p>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-[3fr_2fr]">
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
            <>
              <div className="flex h-36 gap-2">
                {data.income_by_month.map((m) => (
                  <div key={m.month} className="flex flex-1 flex-col items-center gap-2">
                    <div className="flex w-full flex-1 items-end justify-center">
                      <div
                        title={`${monthLabel(m.month)}: ${usd(m.total)}`}
                        className="w-3/5 rounded-t-sm bg-acid/80"
                        style={{ height: `${(m.total / peak) * 100}%` }}
                      />
                    </div>
                    <span className="label">{monthLabel(m.month)}</span>
                  </div>
                ))}
              </div>
              <p className="tnum mt-4 text-right text-[11px] text-muted">
                peak {usdCompact(peak)}
              </p>
            </>
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
        Balances and cash flow come from your bank feed. Share counts, cost basis and
        per-holding performance need a provider that carries holdings data — SimpleFIN
        doesn't, so none of that is shown rather than guessed at.
      </p>
    </>
  );
}
