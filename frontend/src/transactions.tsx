import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "./api/client";
import { CategoryPicker } from "./CategoryPicker";
import { useCategoryMap, useCreateRule } from "./categories";
import { useTags, useTransactions, type Txn } from "./data";
import { flowTotals, shortDate, usd } from "./money";
import { OTHER, SERIES } from "./palette";
import { Empty } from "./ui/Shell";

const monthLabel = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

/** A stable colour for a category's disc: the same name always lands on the same one. */
const discColour = (name: string) =>
  SERIES[[...name].reduce((n, ch) => n + ch.charCodeAt(0), 0) % SERIES.length];

/** The transaction list: rows grouped under month headings that carry the month's spend,
 * a tick box per row for acting on several at once, and a panel that opens under a row
 * for everything else. `txns` is expected newest first, as the API returns it. */
export function TxnRows({ txns }: { txns: Txn[] }) {
  const qc = useQueryClient();
  const categories = useCategoryMap();
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());

  const bulk = useMutation({
    // ponytail: one PATCH per row. A bulk endpoint earns its place when someone ticks
    // hundreds at once; the list shows a few dozen.
    mutationFn: (ignored: boolean) =>
      Promise.all(
        txns
          .filter((t) => picked.has(t.id))
          .map((t) =>
            apiFetch(`/transactions/${t.id}`, { method: "PATCH", body: JSON.stringify({ ignored }) }),
          ),
      ),
    onSuccess: () => {
      setPicked(new Set());
      qc.invalidateQueries();
    },
  });

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const months: { key: string; rows: Txn[] }[] = [];
  for (const t of txns) {
    const key = t.posted_at.slice(0, 7);
    const last = months.at(-1);
    if (last?.key === key) last.rows.push(t);
    else months.push({ key, rows: [t] });
  }

  return (
    <div>
      {picked.size > 0 && (
        <div className="sticky top-2 z-10 mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-full bg-bone px-5 py-2 text-sm text-white">
          <span>{picked.size} selected</span>
          <button type="button" disabled={bulk.isPending} onClick={() => bulk.mutate(true)}>
            Ignore selected
          </button>
          <button type="button" disabled={bulk.isPending} onClick={() => bulk.mutate(false)}>
            Count selected
          </button>
          <button type="button" className="ml-auto opacity-70" onClick={() => setPicked(new Set())}>
            Clear
          </button>
        </div>
      )}
      {bulk.isError && (
        <p className="mb-3 text-[13px] text-clay">{(bulk.error as Error).message}</p>
      )}
      {months.map((m) => (
        <section key={m.key} className="mb-4 last:mb-0">
          <h3 className="flex items-baseline justify-between border-b border-line pb-2">
            <span className="label">{monthLabel(m.rows[0].posted_at)}</span>
            <span className="tnum text-[12px] font-normal text-muted">
              {usd(flowTotals(m.rows).outflow)} total spend
            </span>
          </h3>
          <ul>
            {m.rows.map((t, i) => (
              <TxnRow
                key={t.id}
                txn={t}
                index={i}
                category={t.category_id ? categories.get(t.category_id) : undefined}
                picked={picked.has(t.id)}
                onPick={() => toggle(t.id)}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function useCategoryMutation(txn: Txn) {
  const qc = useQueryClient();
  const createRule = useCreateRule();
  const [askAbout, setAskAbout] = useState<string | null>(null);
  // Undefined = defer to server data. Set on change and held until `txn.category_id`
  // itself catches up: invalidating the transactions query on success kicks off a
  // refetch that hasn't landed yet, so clearing this the moment the PATCH resolves
  // would just trade the in-flight snap-back for a post-success one.
  const [pendingCategory, setPendingCategory] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    if (pendingCategory !== undefined && txn.category_id === pendingCategory) {
      setPendingCategory(undefined);
    }
  }, [txn.category_id, pendingCategory]);

  const setCategory = useMutation({
    mutationFn: (categoryId: string | null) =>
      apiFetch(`/transactions/${txn.id}`, {
        method: "PATCH",
        body: JSON.stringify({ category_id: categoryId }),
      }),
    onSuccess: (_data, categoryId) => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["uncategorized"] });
      // Offer the rule rather than writing one: a one-off recategorization is common,
      // and a rule the user didn't ask for is a rule they have to find and delete.
      if (categoryId) setAskAbout(categoryId);
    },
    onError: () => setPendingCategory(undefined),
  });

  return { createRule, askAbout, setAskAbout, pendingCategory, setPendingCategory, setCategory };
}

/** Tag field and Ignore toggle. Its own component because the desktop row and the
 * mobile card both show it, and each needs the mutation's error next to its controls. */
function TxnExtras({ txn }: { txn: Txn }) {
  const qc = useQueryClient();
  // Ignoring a row moves every total in the app, so everything refetches.
  // ponytail: blanket invalidate; narrow to named keys if the refetch storm ever shows.
  const patch = useMutation({
    mutationFn: (body: { ignored: boolean } | { tags: string[] }) =>
      apiFetch(`/transactions/${txn.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const tagText = txn.tags.join(", ");

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {/* Uncontrolled, re-keyed on the saved value: the API trims and lower-cases,
            so the field picks up what was actually stored once the refetch lands. */}
        <input
          key={tagText}
          className="w-44 text-[13px]"
          aria-label={`Tags for ${txn.merchant_raw}`}
          placeholder="Tags, comma separated"
          defaultValue={tagText}
          onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
          onBlur={(e) => {
            if (e.target.value.trim() === tagText) return;
            const tags = e.target.value
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean);
            patch.mutate({ tags });
          }}
        />
        <button
          className="text-[13px] text-muted"
          aria-label={`${txn.ignored ? "Count" : "Ignore"} ${txn.merchant_raw}`}
          title={
            txn.ignored
              ? "Count this in spending totals again"
              : "Leave this out of spending totals and budgets"
          }
          onClick={() => patch.mutate({ ignored: !txn.ignored })}
        >
          {txn.ignored ? "Count it" : "Ignore"}
        </button>
      </div>
      {patch.isError && (
        <p className="mt-1 text-[13px] text-clay">{(patch.error as Error).message}</p>
      )}
    </>
  );
}

function TxnRow({
  txn,
  index,
  category,
  picked,
  onPick,
}: {
  txn: Txn;
  index: number;
  category?: string;
  picked: boolean;
  onPick: () => void;
}) {
  const [open, setOpen] = useState(false);
  // The name someone gave it wins; the bank's own text is still what the controls are
  // labelled with, since that is what a rule would match on.
  const name = txn.merchant_normalized || txn.merchant_raw;
  const dim = txn.ignored ? "opacity-50" : "";
  const amount = Number(txn.amount);

  return (
    <li
      className="rise border-b border-line/60 last:border-0"
      style={{ "--d": `${Math.min(index, 12) * 30}ms` } as React.CSSProperties}
    >
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          aria-label={`Select ${name}`}
          checked={picked}
          onChange={onPick}
          className="size-4 shrink-0 accent-brand"
        />
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-3 py-3 text-left"
        >
          <span
            aria-hidden
            className={`flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-medium text-white ${dim}`}
            style={{ background: category ? discColour(category) : OTHER }}
          >
            {(category ?? name).trim().charAt(0).toUpperCase() || "·"}
          </span>
          <span className={`min-w-0 flex-1 ${dim}`}>
            <span className="block truncate text-sm">{name}</span>
            <span className="block truncate text-[12px] text-muted">
              <span>{shortDate(txn.posted_at)}</span>
              {category && <span> | {category}</span>}
            </span>
          </span>
          <span className="hidden shrink-0 gap-1 sm:flex">
            {txn.tags.map((tag) => (
              <span key={tag} className="rounded-full bg-tint px-2 py-0.5 text-[11px] text-brand">
                {tag}
              </span>
            ))}
          </span>
          {txn.ignored && (
            <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
              Ignored
            </span>
          )}
          <span className={`tnum shrink-0 text-sm ${dim} ${amount > 0 ? "text-acid" : ""}`}>
            {amount > 0 ? `+${usd(txn.amount)}` : usd(txn.amount)}
          </span>
        </button>
      </div>
      {open && <TxnDetail txn={txn} />}
    </li>
  );
}

/** Everything that can be changed about one transaction, shown under its row.
 * ponytail: an inline panel, not a slide-over — no focus trap or overlay to get wrong,
 * and it reads the same on a phone. A side sheet is a restyle of this, not a rewrite. */
function TxnDetail({ txn }: { txn: Txn }) {
  const qc = useQueryClient();
  const { createRule, askAbout, setAskAbout, pendingCategory, setPendingCategory, setCategory } =
    useCategoryMutation(txn);
  const save = useMutation({
    mutationFn: (
      body: { merchant_normalized: string | null } | { notes: string | null } | { tags: string[] },
    ) => apiFetch(`/transactions/${txn.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const taxed = txn.tags.includes("tax");
  // Saves a text field when it loses focus and has actually changed; empty means "unset".
  const onBlur =
    (field: "merchant_normalized" | "notes", was: string) =>
    (e: React.FocusEvent<HTMLInputElement>) => {
      const now = e.target.value.trim();
      if (now === was) return;
      save.mutate(
        field === "notes" ? { notes: now || null } : { merchant_normalized: now || null },
      );
    };
  const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) =>
    e.key === "Enter" && e.currentTarget.blur();

  return (
    <div className="mb-3 grid gap-x-4 gap-y-3 rounded-xl bg-surface-2 p-4 sm:grid-cols-2">
      <div>
        <p className="label mb-1.5">Category</p>
        <CategoryPicker
          value={pendingCategory !== undefined ? pendingCategory : txn.category_id}
          onChange={(id) => {
            setPendingCategory(id);
            setCategory.mutate(id);
          }}
          ariaLabel={`Category for ${txn.merchant_raw}`}
        />
        {setCategory.isError && (
          <p className="mt-1 text-[13px] text-clay">{(setCategory.error as Error).message}</p>
        )}
        {askAbout && (
          <div className="mt-2 text-[13px] text-muted">
            <RuleOffer
              merchant={txn.merchant_raw}
              categoryId={askAbout}
              createRule={createRule}
              onDone={() => setAskAbout(null)}
            />
          </div>
        )}
      </div>
      <div>
        <p className="label mb-1.5">Display name</p>
        <input
          key={txn.merchant_normalized ?? ""}
          className="w-full"
          aria-label={`Name for ${txn.merchant_raw}`}
          placeholder={txn.merchant_raw}
          defaultValue={txn.merchant_normalized ?? ""}
          onKeyDown={blurOnEnter}
          onBlur={onBlur("merchant_normalized", txn.merchant_normalized ?? "")}
        />
      </div>
      <div>
        <p className="label mb-1.5">Note</p>
        <input
          key={txn.notes ?? ""}
          className="w-full"
          aria-label={`Note for ${txn.merchant_raw}`}
          placeholder="Add a note"
          defaultValue={txn.notes ?? ""}
          onKeyDown={blurOnEnter}
          onBlur={onBlur("notes", txn.notes ?? "")}
        />
      </div>
      <div>
        <p className="label mb-1.5">Tags</p>
        <TxnExtras txn={txn} />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="size-4 accent-brand"
          checked={taxed}
          onChange={() =>
            save.mutate({ tags: taxed ? txn.tags.filter((t) => t !== "tax") : [...txn.tags, "tax"] })
          }
        />
        Tax deductible
      </label>
      {save.isError && (
        <p className="text-[13px] text-clay sm:col-span-2">{(save.error as Error).message}</p>
      )}
    </div>
  );
}

function RuleOffer({
  merchant,
  categoryId,
  createRule,
  onDone,
}: {
  merchant: string;
  categoryId: string;
  createRule: ReturnType<typeof useCreateRule>;
  onDone: () => void;
}) {
  return (
    <>
      Always categorize “{merchant}” this way?{" "}
      <button
        className="text-acid"
        onClick={() =>
          createRule.mutate({ pattern: merchant, category_id: categoryId }, { onSuccess: onDone })
        }
      >
        Make it a rule
      </button>{" "}
      <button className="ml-2" onClick={onDone}>
        No
      </button>
      {createRule.isError && <p className="mt-1 text-clay">{(createRule.error as Error).message}</p>}
    </>
  );
}

export function TransactionList() {
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const { data = [], isLoading } = useTransactions(search, tag);
  const { data: tags = [] } = useTags();

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <input
          className="min-w-0 flex-1"
          placeholder="Search merchant…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {/* `tag` stays listed even after its last use is removed, so the filter can
            always be cleared from the control that set it. */}
        {(tags.length > 0 || tag) && (
          <select aria-label="Filter by tag" value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">All tags</option>
            {[...new Set([...tags, ...(tag ? [tag] : [])])].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        )}
      </div>
      {isLoading ? (
        <Empty>Loading…</Empty>
      ) : data.length === 0 ? (
        <Empty>
          {search
            ? `Nothing matching “${search}”.`
            : tag
              ? `Nothing tagged “${tag}”.`
              : "No transactions yet."}
        </Empty>
      ) : (
        <TxnRows txns={data} />
      )}
    </div>
  );
}

type Form = { posted_at: string; amount: string; merchant_raw: string };

export function NewTransactionForm({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const { register, handleSubmit, reset } = useForm<Form>();
  const mut = useMutation({
    mutationFn: (f: Form) =>
      apiFetch("/transactions", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          // <input type="date"> gives YYYY-MM-DD; the API wants a datetime.
          posted_at: `${f.posted_at}T00:00:00Z`,
          amount: f.amount,
          merchant_raw: f.merchant_raw,
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      reset();
    },
  });

  return (
    <form onSubmit={handleSubmit((f) => mut.mutate(f))} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1.5">
        <span className="label">Date</span>
        <input type="date" aria-label="Date" {...register("posted_at", { required: true })} />
      </label>
      <label className="flex flex-1 flex-col gap-1.5">
        <span className="label">Merchant</span>
        <input placeholder="Merchant" {...register("merchant_raw", { required: true })} />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="label">Amount</span>
        <input
          className="tnum w-32"
          aria-label="Amount"
          placeholder="-9.99"
          {...register("amount", { required: true })}
        />
      </label>
      <button disabled={!accountId} className="btn">
        Add transaction
      </button>
      {mut.isError && <span className="text-sm text-clay">{(mut.error as Error).message}</span>}
    </form>
  );
}

export function CsvUpload({ accountId }: { accountId: string }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !accountId) return;
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${API_BASE}/accounts/${accountId}/import`, {
      method: "POST",
      credentials: "include",
      body,
    });
    const out = await res.json().catch(() => ({}));
    setStatus(
      res.ok ? `Imported ${out.imported}, skipped ${out.skipped}` : (out.detail ?? "Import failed"),
    );
    qc.invalidateQueries({ queryKey: ["transactions"] });
    e.target.value = "";
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex flex-col gap-1.5">
        <span className="label">Import CSV</span>
        <input type="file" accept=".csv" aria-label="Import CSV" onChange={onFile} />
      </label>
      <span className="text-[13px] text-muted">
        {status || "Columns: date, amount, merchant. Re-importing the same file is deduped."}
      </span>
    </div>
  );
}
