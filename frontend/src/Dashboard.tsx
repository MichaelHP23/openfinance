import { useState } from "react";
import { AccountList, NewAccountForm, useAccounts } from "./accounts";
import { CsvUpload, NewTransactionForm, TransactionList } from "./transactions";
import { apiFetch } from "./api/client";

export function Dashboard() {
  const { data: accounts = [] } = useAccounts();
  const [selected, setSelected] = useState("");
  const accountId = selected || accounts[0]?.id || "";

  const logout = async () => {
    await apiFetch("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  };

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">OpenFinance</h1>
        <button onClick={logout} className="text-sm text-blue-600">
          Log out
        </button>
      </header>

      <section className="flex flex-col gap-3">
        <h2 className="font-medium">Accounts</h2>
        <NewAccountForm />
        <AccountList />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="font-medium">Transactions</h2>
        <select
          className="w-fit rounded border p-2"
          aria-label="Account"
          value={accountId}
          onChange={(e) => setSelected(e.target.value)}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <NewTransactionForm accountId={accountId} />
        <CsvUpload accountId={accountId} />
        <TransactionList />
      </section>
    </div>
  );
}
