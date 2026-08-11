import { useEffect, useState } from "react";
import {
  type BudgetItem,
  type BudgetStatus,
  shiftMonth,
  useBudgetStatus,
  useCopyBudgets,
  useSuggestBudgets,
  useUpsertBudgets,
} from "./budgets";
import { usd } from "./money";
import { Card, Empty } from "./ui/Shell";

function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function fillPctOf(r: BudgetStatus) {
  const effective = Number(r.effective_budget);
  const actual = Number(r.actual);
  return effective > 0 ? Math.min((actual / effective) * 100, 100) : 0;
}

function BudgetRow({
  row: r,
  draft,
  onDraft,
  onToggleRollover,
}: {
  row: BudgetStatus;
  draft: string | undefined;
  onDraft: (v: string) => void;
  onToggleRollover: () => void;
}) {
  const fillPct = fillPctOf(r);
  const overPace = r.pace !== null && r.pace > 1;
  return (
    <tr className="border-b border-line/60 last:border-0">
      <td className="py-2 text-sm">{r.category_name}</td>
      <td className="py-2">
        <input
          aria-label={`Budget for ${r.category_name}`}
          value={draft ?? r.budgeted}
          onChange={(e) => onDraft(e.target.value)}
          className="w-24 text-[13px]"
        />
        {Number(r.carry_in) !== 0 && (
          <span className="ml-2 text-[12px] text-muted">+{usd(r.carry_in)} carried in</span>
        )}
      </td>
      <td className="py-2">
        <label className="flex items-center gap-1 text-[12px] text-muted">
          <input
            type="checkbox"
            aria-label={`Roll over ${r.category_name}`}
            checked={r.rollover}
            onChange={onToggleRollover}
          />
          Roll over
        </label>
      </td>
      <td className="w-32 py-2">
        <div className="h-1.5 w-full rounded-full bg-line/60">
          <div
            className={`h-1.5 rounded-full ${overPace ? "bg-amber-400" : "bg-acid"}`}
            style={{ width: `${fillPct}%` }}
          />
        </div>
      </td>
      <td className="tnum py-2 text-right text-[13px]">{usd(r.actual)}</td>
      <td
        className={`tnum py-2 text-right text-[13px] ${
          Number(r.remaining) < 0 ? "text-amber-400" : "text-muted"
        }`}
      >
        {usd(r.remaining)}
      </td>
    </tr>
  );
}

function BudgetCard({
  row: r,
  draft,
  onDraft,
  onToggleRollover,
}: {
  row: BudgetStatus;
  draft: string | undefined;
  onDraft: (v: string) => void;
  onToggleRollover: () => void;
}) {
  const fillPct = fillPctOf(r);
  const overPace = r.pace !== null && r.pace > 1;
  return (
    <li className="card p-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm">{r.category_name}</span>
        <span
          className={`tnum text-sm ${Number(r.remaining) < 0 ? "text-amber-400" : "text-muted"}`}
        >
          {usd(r.remaining)} left
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-line/60">
        <div
          className={`h-1.5 rounded-full ${overPace ? "bg-amber-400" : "bg-acid"}`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <input
          aria-label={`Budget for ${r.category_name}`}
          value={draft ?? r.budgeted}
          onChange={(e) => onDraft(e.target.value)}
          className="w-24 text-[13px]"
        />
        <span className="tnum text-[13px] text-muted">actual {usd(r.actual)}</span>
      </div>
      <div className="mt-2 flex items-center justify-between text-[12px] text-muted">
        {Number(r.carry_in) !== 0 ? <span>+{usd(r.carry_in)} carried in</span> : <span />}
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            aria-label={`Roll over ${r.category_name}`}
            checked={r.rollover}
            onChange={onToggleRollover}
          />
          Roll over
        </label>
      </div>
    </li>
  );
}

export function BudgetBoard({
  month,
  onMonthChange,
}: {
  month: string;
  onMonthChange: (month: string) => void;
}) {
  const { data: rows = [], isLoading } = useBudgetStatus(month);
  const upsert = useUpsertBudgets(month);
  const suggest = useSuggestBudgets(month);
  const copy = useCopyBudgets(month);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  // A month switch drops any unsaved edits — they belonged to the month being left.
  useEffect(() => setDrafts({}), [month]);

  const setDraft = (categoryId: string, value: string) =>
    setDrafts((d) => ({ ...d, [categoryId]: value }));

  // Blank drafts (e.g. a cleared input) never produce anything to send — so a
  // Save button that's only visible, not also gated on this, would be a dead end.
  const hasSaveableDraft = Object.values(drafts).some((v) => v.trim() !== "");

  const save = () => {
    const items: BudgetItem[] = Object.entries(drafts)
      .filter(([, v]) => v.trim() !== "")
      .map(([category_id, amount]) => {
        const existing = rows.find((r) => r.category_id === category_id);
        return { category_id, amount, rollover: existing?.rollover ?? false };
      });
    if (items.length === 0) return;
    upsert.mutate(items, { onSuccess: () => setDrafts({}) });
  };

  const toggleRollover = (categoryId: string, current: boolean, budgeted: string) => {
    upsert.mutate([{ category_id: categoryId, amount: budgeted, rollover: !current }]);
  };

  const applySuggestions = () => {
    suggest.mutate(undefined, {
      onSuccess: (suggestions) => {
        const next: Record<string, string> = {};
        for (const s of suggestions) next[s.category_id] = s.amount;
        setDrafts(next);
      },
    });
  };

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button aria-label="Previous month" onClick={() => onMonthChange(shiftMonth(month, -1))}>
            ←
          </button>
          <h2 className="text-sm font-medium">{monthLabel(month)}</h2>
          <button aria-label="Next month" onClick={() => onMonthChange(shiftMonth(month, 1))}>
            →
          </button>
        </div>
        <div className="flex gap-3 text-[13px]">
          <button onClick={applySuggestions} disabled={suggest.isPending} className="text-acid">
            {suggest.isPending ? "Asking…" : "Suggest"}
          </button>
          <button onClick={() => copy.mutate(shiftMonth(month, -1))} disabled={copy.isPending}>
            Copy last month
          </button>
        </div>
      </div>

      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : rows.length === 0 ? (
        <Empty>No categories yet.</Empty>
      ) : (
        <>
          <table className="hidden w-full md:table">
            <tbody>
              {rows.map((r) => (
                <BudgetRow
                  key={r.category_id}
                  row={r}
                  draft={drafts[r.category_id]}
                  onDraft={(v) => setDraft(r.category_id, v)}
                  onToggleRollover={() => toggleRollover(r.category_id, r.rollover, r.budgeted)}
                />
              ))}
            </tbody>
          </table>
          <ul className="flex flex-col gap-3 md:hidden">
            {rows.map((r) => (
              <BudgetCard
                key={r.category_id}
                row={r}
                draft={drafts[r.category_id]}
                onDraft={(v) => setDraft(r.category_id, v)}
                onToggleRollover={() => toggleRollover(r.category_id, r.rollover, r.budgeted)}
              />
            ))}
          </ul>
        </>
      )}

      {Object.keys(drafts).length > 0 && (
        <button className="mt-4" onClick={save} disabled={upsert.isPending || !hasSaveableDraft}>
          {upsert.isPending ? "Saving…" : "Save changes"}
        </button>
      )}
      {upsert.isError && (
        <p className="mt-3 text-[13px] text-red-400">{(upsert.error as Error).message}</p>
      )}
    </Card>
  );
}
