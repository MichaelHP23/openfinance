import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { ACCOUNT_TYPES, type Account, type Txn, useAccounts } from "../data";
import { LIABILITY_TYPES, prettyType, usd } from "../money";
import { TxnRows } from "../transactions";
import { Card, Empty, PageHead } from "../ui/Shell";

export function AccountDetailPage() {
  const { accountId = "" } = useParams();
  const qc = useQueryClient();
  const { data: accounts = [] } = useAccounts();
  const account = accounts.find((a) => a.id === accountId);
  const [editing, setEditing] = useState(false);

  const { data: txns = [], isLoading } = useQuery({
    queryKey: ["transactions", { account: accountId }],
    queryFn: () => apiFetch<Txn[]>(`/transactions?account_id=${accountId}`),
    enabled: Boolean(accountId),
  });

  const save = useMutation({
    mutationFn: (patch: Partial<Account>) =>
      apiFetch<Account>(`/accounts/${accountId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["investments"] });
      setEditing(false);
    },
  });

  if (!account) {
    return (
      <>
        <PageHead title="Account" />
        <Empty>
          Not found.{" "}
          <Link to="/accounts" className="text-acid">
            Back to accounts
          </Link>
          .
        </Empty>
      </>
    );
  }

  const isLiability = LIABILITY_TYPES.has(account.type);
  const spent = txns.filter((t) => Number(t.amount) < 0).reduce((n, t) => n + -Number(t.amount), 0);
  const received = txns.filter((t) => Number(t.amount) > 0).reduce((n, t) => n + Number(t.amount), 0);

  return (
    <>
      <PageHead
        title={account.name}
        sub={`${prettyType(account.type)}${account.institution ? ` · ${account.institution}` : ""}`}
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="card p-4">
          <p className="label">{isLiability ? "Owed" : "Balance"}</p>
          <p className={`tnum mt-2 text-xl ${isLiability ? "text-clay" : ""}`}>
            {usd(account.balance)}
          </p>
        </div>
        <div className="card p-4">
          <p className="label">Money out</p>
          <p className="tnum mt-2 text-xl">{usd(spent)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Money in</p>
          <p className="tnum mt-2 text-xl text-acid">{usd(received)}</p>
        </div>
        <div className="card p-4">
          <p className="label">Records</p>
          <p className="tnum mt-2 text-xl">{txns.length}</p>
        </div>
      </div>

      <Card delay={80}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-medium">Details</h2>
          <button onClick={() => setEditing(!editing)} className="btn-ghost">
            {editing ? "Cancel" : "Edit"}
          </button>
        </div>

        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              save.mutate({
                name: String(form.get("name")),
                type: String(form.get("type")),
                institution: String(form.get("institution")),
                beneficiary: String(form.get("beneficiary")),
              });
            }}
            className="flex flex-wrap items-end gap-3"
          >
            <label className="flex flex-col gap-1.5">
              <span className="label">Name</span>
              <input name="name" defaultValue={account.name} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="label">Type</span>
              <select name="type" aria-label="Account type" defaultValue={account.type}>
                {ACCOUNT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {prettyType(t)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="label">Institution</span>
              <input name="institution" defaultValue={account.institution ?? ""} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="label">Beneficiary</span>
              <input name="beneficiary" defaultValue={account.beneficiary ?? ""} placeholder="Optional" />
            </label>
            <button className="btn" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </form>
        ) : (
          <p className="text-[13px] leading-relaxed text-muted">
            Imported as <span className="text-bone">{prettyType(account.type)}</span>. Bank feeds
            don't say what kind of account something is, so it's guessed from the name — if a
            credit card landed as checking, fix it here and net worth follows.
          </p>
        )}
        {save.isError && (
          <p className="mt-3 text-sm text-clay">{(save.error as Error).message}</p>
        )}
      </Card>

      <Card className="mt-4" delay={140}>
        <h2 className="mb-4 text-sm font-medium">Records</h2>
        {isLoading ? (
          <Empty>Loading…</Empty>
        ) : txns.length === 0 ? (
          <Empty>No transactions for this account yet.</Empty>
        ) : (
          <TxnRows txns={txns} />
        )}
      </Card>
    </>
  );
}
