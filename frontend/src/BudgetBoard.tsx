import { useEffect, useState } from "react";
import {
  type BudgetItem,
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
        <table className="w-full">
          <tbody>
            {rows.map((r) => {
              const draft = drafts[r.category_id];
              const effective = Number(r.effective_budget);
              const actual = Number(r.actual);
              const fillPct = effective > 0 ? Math.min((actual / effective) * 100, 100) : 0;
              const overPace = r.pace !== null && r.pace > 1;
              return (
                <tr key={r.category_id} className="border-b border-line/60 last:border-0">
                  <td className="py-2 text-sm">{r.category_name}</td>
                  <td className="py-2">
                    <input
                      aria-label={`Budget for ${r.category_name}`}
                      value={draft ?? r.budgeted}
                      onChange={(e) => setDraft(r.category_id, e.target.value)}
                      className="w-24 text-[13px]"
                    />
                  </td>
                  <td className="py-2">
                    <label className="flex items-center gap-1 text-[12px] text-muted">
                      <input
                        type="checkbox"
                        aria-label={`Roll over ${r.category_name}`}
                        checked={r.rollover}
                        onChange={() => toggleRollover(r.category_id, r.rollover, r.budgeted)}
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
            })}
          </tbody>
        </table>
      )}

      {Object.keys(drafts).length > 0 && (
        <button className="mt-4" onClick={save} disabled={upsert.isPending}>
          {upsert.isPending ? "Saving…" : "Save changes"}
        </button>
      )}
      {upsert.isError && (
        <p className="mt-3 text-[13px] text-red-400">{(upsert.error as Error).message}</p>
      )}
    </Card>
  );
}
