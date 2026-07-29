import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { API_BASE } from "./api/client";
import { useAccounts } from "./data";
import {
  TRADE_TYPES,
  grossAmount,
  isInflow,
  useCreateTrade,
  useDeleteTrade,
  useSecurities,
  useTrades,
  type Trade,
  type TradeFilters,
  type TradeImportResult,
  type TradeType,
} from "./investments";
import { longDate, units, usd } from "./money";
import { Empty } from "./ui/Shell";

const TYPE_LABEL: Record<TradeType, string> = {
  buy: "Buy",
  sell: "Sell",
  dividend: "Dividend",
  split: "Split",
};

type Form = {
  traded_on: string;
  type: TradeType;
  symbol: string;
  quantity: string;
  price_per_unit: string;
  fees: string;
  account_id: string;
  currency: string;
  split_ratio: string;
};

const today = () => new Date().toISOString().slice(0, 10);

export function AddTradeForm() {
  const { data: securities = [] } = useSecurities();
  const { data: accounts = [] } = useAccounts();
  const investmentAccounts = accounts.filter((a) => a.type === "investment");
  const create = useCreateTrade();
  const { register, handleSubmit, watch, reset } = useForm<Form>({
    defaultValues: { traded_on: today(), type: "buy", currency: "USD", fees: "0" },
  });

  const type = watch("type");
  const quantity = watch("quantity");
  const price = watch("price_per_unit");
  const total = quantity && price ? Number(quantity) * Number(price) : null;

  const onSubmit = handleSubmit((f) => {
    create.mutate(
      {
        account_id: f.account_id,
        symbol: f.symbol.trim().toUpperCase(),
        traded_on: f.traded_on,
        type: f.type,
        quantity: f.type === "split" ? "0" : f.quantity || "0",
        price_per_unit: f.type === "split" ? "0" : f.price_per_unit || "0",
        fees: f.fees || "0",
        split_ratio: f.type === "split" ? f.split_ratio || null : null,
        currency: f.currency.trim() || "USD",
        notes: null,
      },
      {
        onSuccess: () =>
          reset({
            traded_on: f.traded_on,
            type: f.type,
            symbol: "",
            quantity: "",
            price_per_unit: "",
            fees: "0",
            account_id: f.account_id,
            currency: f.currency,
            split_ratio: "",
          }),
      },
    );
  });

  if (investmentAccounts.length === 0) {
    return (
      <Empty>
        No investment account yet — add one on the accounts page, then come back to log trades.
      </Empty>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="label">Date</span>
          <input type="date" aria-label="Date" {...register("traded_on", { required: true })} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Type</span>
          <select aria-label="Type" {...register("type")}>
            {TRADE_TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABEL[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Symbol</span>
          <input
            list="security-symbols"
            className="w-28"
            placeholder="VTI"
            aria-label="Symbol"
            {...register("symbol", { required: true })}
          />
        </label>
        <datalist id="security-symbols">
          {securities.map((s) => (
            <option key={s.id} value={s.symbol} />
          ))}
        </datalist>

        {type === "split" ? (
          <label className="flex flex-col gap-1.5">
            <span className="label">Split ratio</span>
            <input
              className="tnum w-24"
              inputMode="decimal"
              placeholder="2 = 2-for-1"
              aria-label="Split ratio"
              {...register("split_ratio")}
            />
          </label>
        ) : (
          <>
            <label className="flex flex-col gap-1.5">
              <span className="label">Quantity</span>
              <input
                className="tnum w-24"
                inputMode="decimal"
                aria-label="Quantity"
                {...register("quantity")}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="label">Price</span>
              <input
                className="tnum w-24"
                inputMode="decimal"
                aria-label="Price"
                {...register("price_per_unit")}
              />
            </label>
          </>
        )}

        <label className="flex flex-col gap-1.5">
          <span className="label">Fees</span>
          <input className="tnum w-20" inputMode="decimal" aria-label="Fees" {...register("fees")} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Account</span>
          <select aria-label="Account" {...register("account_id", { required: true })}>
            {investmentAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Currency</span>
          <input className="w-16" aria-label="Currency" {...register("currency")} />
        </label>
        <button className="btn" disabled={create.isPending}>
          {create.isPending ? "Saving…" : "Add trade"}
        </button>
      </div>

      {type !== "split" && total !== null && (
        <p className="tnum text-[13px] text-muted">Total: {usd(total)}</p>
      )}
      <p className="text-[13px] text-muted">
        A reinvested dividend is two rows — a dividend for the cash, then a buy for the units.
      </p>
      {create.isError && <p className="text-sm text-clay">{(create.error as Error).message}</p>}
    </form>
  );
}

export function TradeFiltersControls({
  filters,
  onChange,
}: {
  filters: TradeFilters;
  onChange: (f: TradeFilters) => void;
}) {
  const { data: securities = [] } = useSecurities();
  const { data: accounts = [] } = useAccounts();
  const investmentAccounts = accounts.filter((a) => a.type === "investment");

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1.5">
        <span className="label">Security</span>
        <select
          aria-label="Filter by security"
          value={filters.security_id ?? ""}
          onChange={(e) => onChange({ ...filters, security_id: e.target.value || undefined })}
        >
          <option value="">All</option>
          {securities.map((s) => (
            <option key={s.id} value={s.id}>
              {s.symbol}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">Account</span>
        <select
          aria-label="Filter by account"
          value={filters.account_id ?? ""}
          onChange={(e) => onChange({ ...filters, account_id: e.target.value || undefined })}
        >
          <option value="">All</option>
          {investmentAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">From</span>
        <input
          type="date"
          aria-label="From date"
          value={filters.from ?? ""}
          onChange={(e) => onChange({ ...filters, from: e.target.value || undefined })}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">To</span>
        <input
          type="date"
          aria-label="To date"
          value={filters.to ?? ""}
          onChange={(e) => onChange({ ...filters, to: e.target.value || undefined })}
        />
      </label>
      {(filters.security_id || filters.account_id || filters.from || filters.to) && (
        <button type="button" className="label transition-colors hover:text-bone" onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
    </div>
  );
}

export function TradeLog({ filters }: { filters: TradeFilters }) {
  const { data, isLoading } = useTrades(filters);
  const { data: securities = [] } = useSecurities();
  const { data: accounts = [] } = useAccounts();
  const del = useDeleteTrade();
  const [confirming, setConfirming] = useState<string | null>(null);

  const symbolOf = (t: Trade) =>
    t.symbol ?? securities.find((s) => s.id === t.security_id)?.symbol ?? "—";
  const accountOf = (t: Trade) => accounts.find((a) => a.id === t.account_id)?.name ?? "—";

  if (isLoading) return <Empty>Loading…</Empty>;
  const trades = data?.trades ?? [];
  if (trades.length === 0) return <Empty>No trades logged yet.</Empty>;

  return (
    <div>
      <ul className="divide-y divide-line">
        {trades.map((t) => (
          <li key={t.id} className="flex items-center gap-3 py-3">
            <span className="tnum w-20 shrink-0 text-[13px] text-muted">{longDate(t.traded_on)}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">
                {TYPE_LABEL[t.type]} · {symbolOf(t)}
              </span>
              <span className="label">{accountOf(t)}</span>
            </span>
            <span className="tnum shrink-0 text-right text-sm">
              {t.type === "split" ? (
                `${t.split_ratio ?? "—"}×`
              ) : (
                <>
                  {units(t.quantity)} @ {usd(t.price_per_unit)}
                  <span className={`block text-[11px] ${isInflow(t.type) ? "text-acid" : "text-muted"}`}>
                    {isInflow(t.type) ? "+" : "−"}
                    {usd(grossAmount(t.quantity, t.price_per_unit))}
                  </span>
                </>
              )}
            </span>
            <button
              onClick={() => setConfirming(confirming === t.id ? null : t.id)}
              aria-label={`Remove ${symbolOf(t)} trade on ${t.traded_on}`}
              className="shrink-0 text-[13px] text-muted transition-colors hover:text-clay"
            >
              {confirming === t.id ? "Cancel" : "Remove"}
            </button>
            {confirming === t.id && (
              <button
                onClick={() => {
                  del.mutate(t.id);
                  setConfirming(null);
                }}
                className="shrink-0 text-[13px] text-clay underline underline-offset-2"
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      {data && data.total > trades.length && (
        <p className="mt-3 text-[13px] text-muted">
          Showing {trades.length} of {data.total} — narrow the filters to see the rest.
        </p>
      )}
    </div>
  );
}

export function TradeImport() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [errors, setErrors] = useState<TradeImportResult["errors"]>([]);

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${API_BASE}/investments/trades/import`, {
      method: "POST",
      credentials: "include",
      body,
    });
    const out = await res.json().catch(() => ({}));
    if (res.ok) {
      const result = out as TradeImportResult;
      setStatus(`Imported ${result.imported}, skipped ${result.skipped}`);
      setErrors(result.errors ?? []);
      qc.invalidateQueries({ queryKey: ["trades"] });
      qc.invalidateQueries({ queryKey: ["holdings"] });
      qc.invalidateQueries({ queryKey: ["securities"] });
    } else {
      setStatus(out.detail ?? "Import failed");
      setErrors([]);
    }
    e.target.value = "";
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="label">Import trade log CSV</span>
          <input type="file" accept=".csv" aria-label="Import trade log CSV" onChange={onFile} />
        </label>
        <span className="text-[13px] text-muted">
          {status || "The sheet's Trade Log export. Re-importing the same file is deduped."}
        </span>
      </div>
      {errors.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 text-[13px] text-clay">
          {errors.map(([row, reason]) => (
            <li key={row}>
              Row {row}: {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
