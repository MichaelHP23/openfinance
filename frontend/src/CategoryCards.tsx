// Named CategoryCards.tsx, not categories.tsx: Vite's default resolve order picks
// categories.ts over categories.tsx for the bare specifier "./categories", so a same-
// named component file would be unreachable from any importer but itself. See
// CategoryPicker.tsx for the same reasoning.
import { useState } from "react";
import {
  useBackfill,
  useCategoryMap,
  useCreateRule,
  useDeleteRule,
  useReorderRules,
  useRules,
  useSuggest,
  useUncategorized,
  type Suggestion,
} from "./categories";
import { CategoryPicker } from "./CategoryPicker";
import { usd } from "./money";
import { Card, Empty } from "./ui/Shell";

export function RulesCard() {
  const { data: rules = [], isLoading } = useRules();
  const labels = useCategoryMap();
  const remove = useDeleteRule();
  const reorder = useReorderRules();
  const backfill = useBackfill();
  const create = useCreateRule();
  const [pattern, setPattern] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);

  // ponytail: move-up/move-down buttons rather than drag-and-drop. Ordering a handful
  // of rules is a two-click job; a drag library is a dependency and a touch-target
  // problem. Revisit if someone accumulates enough rules to make this tedious.
  // move() computes the new order from `rules`, which only reflects the last reorder
  // once its POST has resolved and invalidated the cache. Two clicks before that lands
  // would both swap from the same stale order and the first move would be dropped, so
  // the buttons are disabled (below) for the length of reorder.isPending instead.
  const move = (index: number, delta: number) => {
    const next = [...rules];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next.map((r) => r.id));
  };

  return (
    <Card className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium">Rules</h2>
        <button onClick={() => backfill.mutate(true)} className="text-[13px] text-acid">
          {backfill.isPending ? "Applying…" : "Apply to history"}
        </button>
      </div>

      {backfill.data && (
        <p className="mb-3 text-[13px] text-muted">
          Categorized {backfill.data.changed} transaction
          {backfill.data.changed === 1 ? "" : "s"}.
        </p>
      )}
      {backfill.isError && (
        <p className="mb-3 text-[13px] text-red-400">{(backfill.error as Error).message}</p>
      )}

      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!pattern.trim() || !categoryId) return;
          create.mutate(
            { pattern, category_id: categoryId },
            { onSuccess: () => setPattern("") },
          );
        }}
      >
        <label className="flex flex-1 flex-col gap-1.5">
          <span className="label">Merchant contains</span>
          <input
            aria-label="Merchant contains"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="whole foods"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="label">Category</span>
          <CategoryPicker value={categoryId} onChange={setCategoryId} ariaLabel="Rule category" />
        </label>
        <button type="submit" disabled={create.isPending}>
          Add rule
        </button>
      </form>

      {create.isError && (
        <p className="mb-3 text-[13px] text-red-400">{(create.error as Error).message}</p>
      )}
      {remove.isError && (
        <p className="mb-3 text-[13px] text-red-400">{(remove.error as Error).message}</p>
      )}
      {reorder.isError && (
        <p className="mb-3 text-[13px] text-red-400">{(reorder.error as Error).message}</p>
      )}

      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : rules.length === 0 ? (
        <Empty>No rules yet. Add one above, or set a category on a transaction.</Empty>
      ) : (
        <table className="w-full">
          <tbody>
            {rules.map((r, i) => (
              <tr key={r.id} className="border-b border-line/60 last:border-0">
                <td className="py-2 text-sm">{r.pattern}</td>
                <td className="py-2 text-[13px] text-muted">
                  {labels.get(r.category_id) ?? "—"}
                </td>
                <td className="py-2 text-right text-[13px]">
                  <button
                    aria-label={`Move ${r.pattern} up`}
                    onClick={() => move(i, -1)}
                    disabled={reorder.isPending}
                  >
                    ↑
                  </button>
                  <button
                    aria-label={`Move ${r.pattern} down`}
                    className="ml-2"
                    onClick={() => move(i, 1)}
                    disabled={reorder.isPending}
                  >
                    ↓
                  </button>
                  <button
                    aria-label={`Delete ${r.pattern}`}
                    className="ml-3 text-muted"
                    onClick={() => remove.mutate(r.id)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export function UncategorizedCard() {
  const { data: rows = [] } = useUncategorized();
  const suggest = useSuggest();
  const create = useCreateRule();
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const toggle = (merchant: string) => {
    const next = new Set(picked);
    if (next.has(merchant)) next.delete(merchant);
    else next.add(merchant);
    setPicked(next);
  };

  const accept = (suggestions: Suggestion[]) => {
    for (const s of suggestions.filter((s) => picked.has(s.merchant))) {
      create.mutate({ pattern: s.merchant, category_id: s.category_id });
    }
    setPicked(new Set());
  };

  if (rows.length === 0) return null;

  return (
    <Card className="mt-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium">Uncategorized</h2>
        <button
          onClick={() => suggest.mutate()}
          disabled={suggest.isPending}
          className="text-[13px] text-acid"
        >
          {suggest.isPending ? "Asking…" : "Suggest categories"}
        </button>
      </div>

      {suggest.isError && (
        <p className="mb-3 text-[13px] text-muted">
          {(suggest.error as Error).message}
        </p>
      )}

      {suggest.data ? (
        <>
          <p className="mb-3 text-[13px] text-muted">
            Proposed by {suggest.data.model}. Nothing is saved until you accept.
          </p>
          <table className="w-full">
            <tbody>
              {suggest.data.suggestions.map((s) => (
                <tr key={s.merchant} className="border-b border-line/60 last:border-0">
                  <td className="py-2">
                    <input
                      type="checkbox"
                      aria-label={`Accept ${s.merchant}`}
                      checked={picked.has(s.merchant)}
                      onChange={() => toggle(s.merchant)}
                    />
                  </td>
                  <td className="py-2 text-sm">{s.merchant}</td>
                  <td className="py-2 text-[13px] text-muted">{s.category_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            className="mt-3"
            disabled={picked.size === 0}
            onClick={() => accept(suggest.data.suggestions)}
          >
            Create {picked.size} rule{picked.size === 1 ? "" : "s"}
          </button>
        </>
      ) : (
        <>
          <table className="w-full">
            <tbody>
              {rows.slice(0, 15).map((r) => (
                <tr
                  key={`${r.merchant}:${r.currency}`}
                  className="border-b border-line/60 last:border-0"
                >
                  <td className="py-2 text-sm">{r.merchant}</td>
                  <td className="tnum py-2 text-[13px] text-muted">{r.count}×</td>
                  <td className="tnum py-2 text-right text-[13px]">
                    {/* ponytail: v1 is USD-only except provider syncs, so a non-USD row just
                        shows the raw amount and its code rather than mis-formatting it as
                        USD. Upgrade path: a real multi-currency formatter once non-USD
                        accounts are more than a provider-sync edge case. */}
                    {r.currency === "USD" ? usd(r.total) : `${r.total} ${r.currency}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 15 && (
            <p className="mt-2 text-[13px] text-muted">
              +{rows.length - 15} more not shown.
            </p>
          )}
        </>
      )}
    </Card>
  );
}
