import { BarChart } from "./charts";
import { usd } from "./money";
import type { GroupBy } from "./reports";
import { useIncomeVsExpense, useSpending, useYearInReview } from "./reports";
import { taxExportUrl, useIncomeSummary, useRealizedGains } from "./tax";
import { Card, Empty } from "./ui/Shell";

export function SpendingCard({ start, end, groupBy }: { start: string; end: string; groupBy: GroupBy }) {
  const { data = [], isLoading } = useSpending(start, end, groupBy);
  if (isLoading) return <Empty>Loading…</Empty>;
  if (data.length === 0) return <Empty>Nothing to report for this range.</Empty>;

  return (
    <Card>
      <h2 className="mb-4 text-sm font-medium">Spending by {groupBy}</h2>
      <BarChart bars={data.slice(0, 12).map((b) => ({ label: b.key, value: Number(b.total) }))} />
    </Card>
  );
}

export function CashFlowCard({ months = 12 }: { months?: number }) {
  const { data = [], isLoading } = useIncomeVsExpense(months);
  if (isLoading) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <h2 className="mb-4 text-sm font-medium">Income vs. expense</h2>
      <BarChart bars={data.map((m) => ({ label: m.month.slice(5), value: Number(m.net) }))} />
      <p className="mt-4 text-[13px] text-muted">
        Bars are net (income minus expense) per month — a bar below the line is a month
        that spent more than it took in.
      </p>
    </Card>
  );
}

export function YearInReviewCard({ year }: { year: number }) {
  const { data, isLoading } = useYearInReview(year);
  if (isLoading || !data) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <h2 className="mb-4 text-sm font-medium">{year} in review</h2>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="label">Total in</p>
          <p className="tnum mt-2 text-xl text-acid">{usd(data.total_in)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Total out</p>
          <p className="tnum mt-2 text-xl">{usd(data.total_out)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Savings rate</p>
          <p className="tnum mt-2 text-xl">{data.savings_rate ? `${Number(data.savings_rate).toFixed(1)}%` : "—"}</p>
        </div>
        <div className="card p-4">
          <p className="label">Net worth change</p>
          <p className="tnum mt-2 text-xl">{data.net_worth_delta ? usd(data.net_worth_delta) : "—"}</p>
        </div>
      </div>
      {data.biggest_category && (
        <p className="text-[13px] text-muted">
          Biggest category: <span className="text-bone">{data.biggest_category}</span> (
          {usd(data.biggest_category_amount ?? "0")})
        </p>
      )}
      {data.biggest_transaction_merchant && (
        <p className="mt-1 text-[13px] text-muted">
          Biggest single transaction:{" "}
          <span className="text-bone">{data.biggest_transaction_merchant}</span> (
          {usd(data.biggest_transaction_amount ?? "0")})
        </p>
      )}
      {data.new_subscriptions.length > 0 && (
        <p className="mt-1 text-[13px] text-muted">
          New subscriptions: <span className="text-bone">{data.new_subscriptions.join(", ")}</span>
        </p>
      )}
      {data.cancelled_subscriptions.length > 0 && (
        <p className="mt-1 text-[13px] text-muted">
          Cancelled: <span className="text-bone">{data.cancelled_subscriptions.join(", ")}</span>
        </p>
      )}
    </Card>
  );
}

export function TaxCard({ year }: { year: number }) {
  const { data: gains, isLoading: gainsLoading } = useRealizedGains(year);
  const { data: income, isLoading: incomeLoading } = useIncomeSummary(year);

  if (gainsLoading || incomeLoading || !gains || !income) return <Empty>Loading…</Empty>;

  return (
    <Card className="mt-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-medium">Tax reporting — {year}</h2>
        <a href={taxExportUrl(year)} className="text-[13px] text-acid">
          Export CSV
        </a>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="label">Short-term gain</p>
          <p className="tnum mt-2 text-xl">{usd(gains.short_term_gain)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Long-term gain</p>
          <p className="tnum mt-2 text-xl">{usd(gains.long_term_gain)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Dividends</p>
          <p className="tnum mt-2 text-xl">{usd(income.dividends)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Interest</p>
          <p className="tnum mt-2 text-xl">{usd(income.interest)}</p>
        </div>
      </div>

      {gains.gains.length === 0 ? (
        <Empty>No realized sales in {year}.</Empty>
      ) : (
        <table className="w-full">
          <tbody>
            {gains.gains.map((g, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0">
                <td className="py-2 text-sm">{g.symbol}</td>
                <td className="py-2 text-[13px] text-muted">{g.closed_on}</td>
                <td className="py-2 text-[13px] text-muted">{g.term}</td>
                <td className="tnum py-2 text-right text-sm">{usd(g.gain)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Matches the backend's WASH_SALE_DISCLAIMER (app/services/tax.py) verbatim,
          modulo "below" -> "above" since the gains table renders above this paragraph
          here rather than below it as in the CSV export. */}
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        This export does not detect or adjust for wash sales. If a security was sold at
        a loss and a substantially identical one bought within 30 days, the real
        deductible loss may be lower than the figure above. This is a reporting tool
        only — confirm with a tax professional before filing.
      </p>
    </Card>
  );
}
