import { useState } from "react";
import { Link } from "react-router-dom";
import { RulesCard, UncategorizedCard } from "../CategoryCards";
import { useAccounts } from "../data";
import { CsvUpload, NewTransactionForm, TransactionList } from "../transactions";
import { Card, Empty, PageHead } from "../ui/Shell";

export function TransactionsPage() {
  const { data: accounts = [] } = useAccounts();
  const [selected, setSelected] = useState("");
  const accountId = selected || accounts[0]?.id || "";

  return (
    <>
      <PageHead title="Transactions" sub="Everything that has moved, newest first" />

      <Card delay={60}>
        <h2 className="mb-4 text-sm font-medium">History</h2>
        <TransactionList />
      </Card>

      <UncategorizedCard />

      {accounts.length === 0 ? (
        <Empty>
          You need an account first —{" "}
          <Link to="/accounts" className="text-acid">
            add one
          </Link>
          .
        </Empty>
      ) : (
        <Card className="mt-4" delay={120}>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-sm font-medium">Add to</h2>
            <label className="flex min-w-0 items-center gap-2">
              <span className="label">Account</span>
              <select
                aria-label="Account"
                value={accountId}
                onChange={(e) => setSelected(e.target.value)}
                className="min-w-0"
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <NewTransactionForm accountId={accountId} />
          <div className="mt-5 border-t border-line pt-5">
            <CsvUpload accountId={accountId} />
          </div>
        </Card>
      )}
      <RulesCard />
    </>
  );
}
