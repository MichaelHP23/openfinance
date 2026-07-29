import { useState } from "react";
import { AllocationBar } from "./charts";
import { holdingTotals, useHoldings, useSetPrice, type Holding } from "./investments";
import { longDate, pct, pctTone, units, usd } from "./money";
import { Card, Empty } from "./ui/Shell";

// ponytail: a fixed 3-day window rather than a per-security "expected update
// cadence" — daily prices more than a long weekend old are worth flagging,
// and nothing here needs to be smarter than that.
function isStale(pricedThrough: string | null) {
  if (!pricedThrough) return false;
  const days = (Date.now() - new Date(`${pricedThrough}T00:00:00Z`).getTime()) / 86_400_000;
  return days > 3;
}

function SetPriceForm({ securityId }: { securityId: string }) {
  const [value, setValue] = useState("");
  const setPrice = useSetPrice();

  return (
    <form
      className="flex items-center justify-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!value) return;
        setPrice.mutate(
          // ponytail: always writes today — correcting a historical close needs
          // a date picker this feature doesn't have yet.
          { security_id: securityId, priced_on: new Date().toISOString().slice(0, 10), close: value },
          { onSuccess: () => setValue("") },
        );
      }}
    >
      <input
        className="tnum w-24"
        inputMode="decimal"
        placeholder="Set price"
        aria-label="Set price"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button className="btn-ghost px-2 py-1 text-[13px]" disabled={setPrice.isPending}>
        Save
      </button>
    </form>
  );
}

function ByAccount({ accounts }: { accounts: Holding["by_account"] }) {
  return (
    <ul className="flex flex-col gap-1.5 text-[13px] text-muted">
      {accounts.map((a) => (
        <li key={a.account_id} className="flex justify-between gap-3">
          <span className="truncate">{a.name}</span>
          <span className="tnum shrink-0">{units(a.units)} units</span>
        </li>
      ))}
    </ul>
  );
}

function HoldingRow({ holding: h }: { holding: Holding }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="border-b border-line/60 last:border-0">
        <td className="py-3 pr-3">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="text-left text-sm transition-colors hover:text-acid"
          >
            {h.symbol}
          </button>
        </td>
        <td className="py-3 pr-3 text-sm text-muted">{h.category ?? "—"}</td>
        <td className="tnum py-3 pr-3 text-right text-sm">{units(h.units)}</td>
        <td className="tnum py-3 pr-3 text-right text-sm">{usd(h.avg_cost)}</td>
        <td className="py-3 pr-3 text-right">
          {h.price !== null ? (
            <span className="tnum text-sm">{usd(h.price)}</span>
          ) : (
            <SetPriceForm securityId={h.security_id} />
          )}
        </td>
        <td className="tnum py-3 pr-3 text-right text-sm">
          {h.market_value !== null ? usd(h.market_value) : "no price"}
        </td>
        <td className={`tnum py-3 text-right text-sm ${pctTone(h.unrealized)}`}>
          {usd(h.unrealized)}
          <span className="ml-1 text-[11px]">({pct(h.unrealized_pct)})</span>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-line/60 last:border-0">
          <td colSpan={7} className="pb-3">
            <ByAccount accounts={h.by_account} />
          </td>
        </tr>
      )}
    </>
  );
}

function HoldingCard({ holding: h }: { holding: Holding }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="card p-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-baseline justify-between gap-3 text-left"
      >
        <span className="text-base">{h.symbol}</span>
        <span className="tnum text-base">
          {h.market_value !== null ? usd(h.market_value) : "no price"}
        </span>
      </button>

      <div className="mt-3 grid grid-cols-2 gap-y-2 text-[13px]">
        <span className="label">Units</span>
        <span className="tnum text-right">{units(h.units)}</span>
        <span className="label">Avg cost</span>
        <span className="tnum text-right">{usd(h.avg_cost)}</span>
        <span className="label">Unrealized</span>
        <span className={`tnum text-right ${pctTone(h.unrealized)}`}>
          {usd(h.unrealized)} ({pct(h.unrealized_pct)})
        </span>
      </div>

      {h.price === null && (
        <div className="mt-3 border-t border-line pt-3">
          <SetPriceForm securityId={h.security_id} />
        </div>
      )}

      {h.by_account.length > 1 && (
        <>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="label mt-3 border-t border-line pt-3 transition-colors hover:text-bone"
          >
            {open ? "Hide" : "Show"} by account
          </button>
          {open && (
            <div className="mt-2">
              <ByAccount accounts={h.by_account} />
            </div>
          )}
        </>
      )}
    </li>
  );
}

export function HoldingsList() {
  const { data, isLoading } = useHoldings();
  const holdings = data?.holdings ?? [];
  const totals = holdingTotals(holdings);
  const priced = holdings.filter((h) => h.market_value !== null);

  if (isLoading) return <Empty>Loading…</Empty>;
  if (holdings.length === 0) {
    return (
      <Empty>
        No holdings yet — add a trade or import your sheet&rsquo;s export on the Trade log tab.
      </Empty>
    );
  }

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="label">Market value</p>
          <p className="tnum mt-2 text-xl">{usd(totals.market)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Cost base</p>
          <p className="tnum mt-2 text-xl">{usd(totals.cost)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Unrealized</p>
          <p className={`tnum mt-2 text-xl ${pctTone(totals.unrealized)}`}>{usd(totals.unrealized)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Unrealized %</p>
          <p className={`tnum mt-2 text-xl ${pctTone(totals.unrealizedPct)}`}>
            {pct(totals.unrealizedPct)}
          </p>
        </div>
      </div>

      {data?.priced_through && (
        <p className="mb-4 text-[13px] text-muted">
          Prices as of {longDate(data.priced_through)}
          {isStale(data.priced_through) && <span className="text-clay"> · stale</span>}
          {totals.unpriced > 0 &&
            ` · ${totals.unpriced} holding${totals.unpriced > 1 ? "s" : ""} unpriced, excluded from the total above`}
        </p>
      )}

      {priced.length > 0 && (
        <Card className="mb-4" delay={60}>
          <h2 className="mb-4 text-sm font-medium">Allocation</h2>
          <AllocationBar
            slices={priced.map((h) => ({
              label: h.symbol,
              value: Number(h.market_value),
              share: Number(h.share_pct),
            }))}
          />
        </Card>
      )}

      <Card delay={100}>
        <h2 className="mb-4 text-sm font-medium">Holdings</h2>

        <table className="hidden w-full md:table">
          <thead>
            <tr className="label border-b border-line text-left">
              <th className="pb-2 pr-3 font-normal">Symbol</th>
              <th className="pb-2 pr-3 font-normal">Category</th>
              <th className="pb-2 pr-3 text-right font-normal">Units</th>
              <th className="pb-2 pr-3 text-right font-normal">Avg cost</th>
              <th className="pb-2 pr-3 text-right font-normal">Price</th>
              <th className="pb-2 pr-3 text-right font-normal">Market value</th>
              <th className="pb-2 text-right font-normal">Unrealized</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <HoldingRow key={h.security_id} holding={h} />
            ))}
          </tbody>
        </table>

        {/* Mobile: not a table — a wide, hover-only table is unusable on a phone. */}
        <ul className="flex flex-col gap-3 md:hidden">
          {holdings.map((h) => (
            <HoldingCard key={h.security_id} holding={h} />
          ))}
        </ul>
      </Card>
    </div>
  );
}
