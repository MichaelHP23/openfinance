import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";
import { BarChart } from "./charts";
import { shortDate, usd } from "./money";
import { TxnRows } from "./transactions";
import { Card, Empty, Stat } from "./ui/Shell";

export type Cadence = "weekly" | "biweekly" | "monthly" | "quarterly" | "yearly";
export type SeriesStatus = "active" | "ended" | "cancelled" | "ignored";

export type Series = {
  id: string;
  label: string;
  merchant_key: string;
  account_id: string | null;
  cadence: Cadence;
  status: SeriesStatus;
  /** -1 for money out, +1 for money in. Part of the series identity server-side. */
  direction: number;
  typical_amount: string;
  last_amount: string;
  min_amount: string;
  max_amount: string;
  amount_varies: boolean;
  price_increase_amount: string | null;
  charge_count: number;
  first_charged_on: string;
  last_charged_on: string;
  next_expected_on: string | null;
  confidence: number;
  cancel_url: string | null;
  notes: string | null;
};

export type Charge = {
  id: string;
  posted_at: string;
  amount: string;
  account_id: string | null;
};

export type SeriesDetail = Series & { charges: Charge[] };

export type Summary = {
  monthly_committed: string;
  monthly_incoming: string;
  active_count: number;
  upcoming: { id: string; label: string; on: string; amount: string }[];
  price_increases: number;
  last_detected_at: string | null;
};

const CADENCE: Record<Cadence, string> = {
  weekly: "Weekly",
  biweekly: "Every 2 weeks",
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
};

/* ---------------------------------------------------------------- data --
 * Everything hangs off the ["recurring", …] key prefix so one
 * invalidateQueries(["recurring"]) after a patch or a rescan refreshes the
 * list, the summary and any open detail together.
 */

function useSummary() {
  return useQuery({
    queryKey: ["recurring", "summary"],
    queryFn: () => apiFetch<Summary>("/recurring/summary"),
  });
}

// ponytail: one `status=all` fetch feeds every card on the page — react-query
// dedupes it — rather than a request per status and client-side merging.
function useSeries() {
  return useQuery({
    queryKey: ["recurring", "list"],
    queryFn: () => apiFetch<Series[]>("/recurring?status=all"),
  });
}

type Patch = { label?: string; status?: SeriesStatus; cancel_url?: string | null; notes?: string };

function usePatchSeries(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Patch) =>
      apiFetch<Series>(`/recurring/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recurring"] }),
  });
}

/* ---------------------------------------------------------------- cards -- */

export function RecurringStats() {
  const { data } = useSummary();
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-3">
      <Stat label="Committed · per month" value={usd(data?.monthly_committed ?? 0)} />
      <Stat
        label="Coming in · per month"
        value={usd(data?.monthly_incoming ?? 0)}
        tone="text-acid"
      />
      <Stat label="Active series" value={String(data?.active_count ?? 0)} />
    </div>
  );
}

export function UpcomingCard({ delay = 100 }: { delay?: number }) {
  const { data } = useSummary();
  const upcoming = data?.upcoming ?? [];

  return (
    <Card className="mb-4" delay={delay}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">Next 30 days</h2>
        <span className="label">{upcoming.length} charges</span>
      </div>
      {upcoming.length === 0 ? (
        <Empty>Nothing expected in the next 30 days.</Empty>
      ) : (
        // A month grid on a phone is twelve pixels a cell — the bill calendar is a list.
        <ul className="divide-y divide-line/60">
          {upcoming.map((u) => (
            <li key={`${u.id}-${u.on}`} className="flex items-baseline gap-3 py-2.5">
              <span className="tnum w-16 shrink-0 text-[13px] text-muted">{shortDate(u.on)}</span>
              <span className="min-w-0 flex-1 truncate text-sm">{u.label}</span>
              <span className="tnum shrink-0 text-sm">{usd(u.amount)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function PriceIncreaseCard({ delay = 140 }: { delay?: number }) {
  const { data = [] } = useSeries();
  const risen = data.filter((s) => s.price_increase_amount !== null && s.status === "active");
  if (risen.length === 0) return null;

  return (
    <Card className="mb-4" delay={delay}>
      <h2 className="mb-3 text-sm font-medium">Price went up</h2>
      <ul className="divide-y divide-line/60">
        {risen.map((s) => {
          const rise = Number(s.price_increase_amount);
          return (
            <li key={s.id} className="flex items-baseline gap-3 py-2.5">
              <span className="min-w-0 flex-1 truncate text-sm">{s.label}</span>
              <span className="tnum shrink-0 text-[13px] text-muted">
                {usd(Number(s.last_amount) - rise)} → {usd(s.last_amount)}
              </span>
              <span className="tnum shrink-0 text-sm text-clay">+{usd(rise)}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function AllRecurring({ delay = 180 }: { delay?: number }) {
  const qc = useQueryClient();
  const { data = [], isLoading } = useSeries();
  const { data: summary } = useSummary();
  const [showDismissed, setShowDismissed] = useState(false);

  const rescan = useMutation({
    mutationFn: () => apiFetch("/recurring/refresh", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recurring"] }),
  });

  const dismissed = data.filter((s) => s.status === "ignored");
  const shown = showDismissed ? data : data.filter((s) => s.status !== "ignored");
  const out = shown.filter((s) => s.direction < 0);
  const incoming = shown.filter((s) => s.direction > 0);

  return (
    <Card delay={delay}>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">All recurring</h2>
        <button
          onClick={() => rescan.mutate()}
          disabled={rescan.isPending}
          className="label transition-colors hover:text-bone"
        >
          {rescan.isPending ? "Scanning…" : "Rescan"}
        </button>
      </div>

      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : shown.length === 0 ? (
        <Empty>
          {summary?.last_detected_at
            ? "Nothing repeating found in your history yet."
            : "Scanning your history — this runs after each sync. Rescan to do it now."}
        </Empty>
      ) : (
        <>
          <Group title="Money out" series={out} />
          <Group title="Money in" series={incoming} />
        </>
      )}

      {dismissed.length > 0 && (
        <button
          onClick={() => setShowDismissed(!showDismissed)}
          className="label mt-4 transition-colors hover:text-bone"
        >
          {showDismissed ? "Hide" : "Show"} {dismissed.length} dismissed
        </button>
      )}
    </Card>
  );
}

function Group({ title, series }: { title: string; series: Series[] }) {
  if (series.length === 0) return null;
  return (
    <section className="mt-5 first:mt-0">
      <h3 className="label mb-1">{title}</h3>
      <ul className="divide-y divide-line/60">
        {series.map((s) => (
          <SeriesRow key={s.id} series={s} />
        ))}
      </ul>
    </section>
  );
}

/* ---------------------------------------------------------------- rows -- */

function SeriesRow({ series: s }: { series: Series }) {
  const [open, setOpen] = useState(false);

  return (
    <li>
      {/* Tap to expand in place: a modal on a phone is a step backwards. */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 py-3.5 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">{s.label}</span>
          <span className="label">
            {CADENCE[s.cadence]}
            {s.status === "active" && s.next_expected_on
              ? ` · next ${shortDate(s.next_expected_on)}`
              : ""}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="tnum block text-sm">{usd(s.typical_amount)}</span>
          <Badges series={s} />
        </span>
      </button>
      {open && <SeriesBody series={s} />}
    </li>
  );
}

function Badges({ series: s }: { series: Series }) {
  return (
    <span className="mt-1 flex items-center justify-end gap-2">
      {s.price_increase_amount !== null && (
        <span className="tnum text-[11px] text-clay">↑ {usd(s.price_increase_amount)}</span>
      )}
      {s.status === "ended" && <span className="label">ended</span>}
      {s.status === "cancelled" && <span className="label">cancelled</span>}
      {s.status === "ignored" && <span className="label">dismissed</span>}
      {s.amount_varies && (
        <span
          className="text-[11px] text-muted"
          title={`Varies · ${usd(s.min_amount)}–${usd(s.max_amount)}`}
        >
          ~
        </span>
      )}
      {s.confidence < 75 && (
        <span
          className="size-1.5 rounded-full bg-muted"
          title={`${s.confidence}% confident — treat this one as a guess`}
          aria-label={`${s.confidence}% confident`}
        />
      )}
    </span>
  );
}

// ponytail: a yearly series would label every bar "Aug 14"; those get the year
// instead. Everything else reuses shortDate from money.ts.
const barLabel = (iso: string, cadence: Cadence) =>
  cadence === "yearly"
    ? new Date(iso).toLocaleDateString("en-US", {
        month: "short",
        year: "2-digit",
        timeZone: "UTC",
      })
    : shortDate(iso);

function SeriesBody({ series: s }: { series: Series }) {
  const { data, isLoading } = useQuery({
    queryKey: ["recurring", "detail", s.id],
    queryFn: () => apiFetch<SeriesDetail>(`/recurring/${s.id}`),
  });

  const charges = data?.charges ?? [];
  // Charges arrive newest first; a chart reads oldest → newest.
  const bars = charges
    .slice(0, 12)
    .reverse()
    .map((c) => ({ label: barLabel(c.posted_at, s.cadence), value: Math.abs(Number(c.amount)) }));

  return (
    <div className="pb-4">
      {isLoading ? (
        <Empty>Loading charges…</Empty>
      ) : charges.length === 0 ? (
        <Empty>No charges found for this series.</Empty>
      ) : (
        <>
          <BarChart bars={bars} height={110} />
          {/* ponytail: reusing TxnRows — the charge payload carries no merchant because
              every charge in a series is the same one, so the label stands in for it. */}
          <div className="mt-4">
            <TxnRows
              txns={charges.map((c) => ({
                id: c.id,
                posted_at: c.posted_at,
                merchant_raw: s.label,
                amount: c.amount,
                currency: "USD",
              }))}
            />
          </div>
        </>
      )}
      <Actions series={s} />
    </div>
  );
}

function Actions({ series: s }: { series: Series }) {
  const patch = usePatchSeries(s.id);
  const [label, setLabel] = useState(s.label);
  const [cancelUrl, setCancelUrl] = useState(s.cancel_url ?? "");
  const [cancelling, setCancelling] = useState(false);

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="label">Name</span>
          <input
            className="w-full"
            aria-label={`Rename ${s.label}`}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </label>
        <button
          className="btn-ghost"
          disabled={patch.isPending || !label.trim() || label === s.label}
          onClick={() => patch.mutate({ label: label.trim() })}
        >
          Save
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-4 text-[13px]">
        {s.status === "active" ? (
          <>
            <button
              onClick={() => patch.mutate({ status: "ignored" })}
              className="text-muted transition-colors hover:text-bone"
            >
              Not a subscription
            </button>
            <button
              onClick={() => setCancelling(!cancelling)}
              className="text-muted transition-colors hover:text-clay"
            >
              I cancelled this
            </button>
          </>
        ) : (
          <button
            onClick={() => patch.mutate({ status: "active" })}
            className="text-muted transition-colors hover:text-bone"
          >
            Put back in the list
          </button>
        )}
        {s.cancel_url && (
          <a
            href={s.cancel_url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-acid underline underline-offset-2"
          >
            Cancellation page
          </a>
        )}
      </div>

      {cancelling && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span className="label">Where you cancelled it (optional)</span>
            <input
              className="w-full"
              type="url"
              placeholder="https://…"
              aria-label="Cancellation URL"
              value={cancelUrl}
              onChange={(e) => setCancelUrl(e.target.value)}
            />
          </label>
          <button
            className="btn-ghost"
            disabled={patch.isPending}
            onClick={() => {
              patch.mutate({ status: "cancelled", cancel_url: cancelUrl.trim() || null });
              setCancelling(false);
            }}
          >
            Mark cancelled
          </button>
        </div>
      )}

      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        This app can't cancel anything for you — it's a read-only view of your bank. Cancel with
        the merchant, then come back: if the charges stop, this series will show as ended.
      </p>

      {patch.isError && (
        <p className="mt-2 text-[13px] text-clay">{(patch.error as Error).message}</p>
      )}
    </div>
  );
}
