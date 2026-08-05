import { useState } from "react";
import { AreaChart } from "./charts";
import { firstNegativeDay, useAfford, useForecast } from "./forecast";
import { usd } from "./money";
import { Card, Empty } from "./ui/Shell";

export function ForecastChart() {
  const { data: days = [] } = useForecast(6);
  const [amount, setAmount] = useState("");
  const [onDate, setOnDate] = useState("");
  const afford = useAfford();

  const negative = firstNegativeDay(days);

  return (
    <Card className="mt-4" delay={200}>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-sm font-medium">Cash flow forecast</h2>
        <span className="label">Next 6 months</span>
      </div>

      {days.length < 2 ? (
        <Empty>Not enough data yet to project a forecast.</Empty>
      ) : (
        <>
          <AreaChart
            valueLabel="Projected balance"
            points={days.map((d) => ({ label: d.on, value: Number(d.projected_balance) }))}
          />
          {negative && (
            <p className="mt-2 text-[11px] text-clay">
              Projected to go negative on {negative.on}
            </p>
          )}
        </>
      )}

      <form
        className="mt-5 flex flex-wrap items-end gap-3 border-t border-line pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          afford.mutate({ amount, on_date: onDate, months: 6 });
        }}
      >
        <label className="flex flex-col gap-1 text-xs">
          Can I afford…
          <input
            aria-label="Amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            placeholder="500"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          Date
          <input aria-label="Date" type="date" value={onDate} onChange={(e) => setOnDate(e.target.value)} />
        </label>
        <button className="btn" disabled={afford.isPending}>
          Check
        </button>
      </form>

      {afford.data && (
        <p className="mt-3 text-sm">
          {afford.data.stays_non_negative
            ? `Yes — the lowest projected balance stays at ${usd(afford.data.minimum_balance)}.`
            : `This would take the balance to ${usd(afford.data.minimum_balance)} — below zero.`}
        </p>
      )}
    </Card>
  );
}
