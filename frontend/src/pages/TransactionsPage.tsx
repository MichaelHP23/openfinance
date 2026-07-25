import { useState } from "react";
import { Link } from "react-router-dom";
import { useAccounts } from "../data";
import { CsvUpload, NewTransactionForm, TransactionList } from "../transactions";
import { Card, Empty, PageHead } from "../ui/Shell";

export function TransactionsPage() {
  const { data: accounts = [] } = useAccounts();
  const [selected, setSelected] = useState("");
  const accountId = selected || accounts[0]?.id || "";

  return (
    <>
      <PageHead title="Transactions" sub="Enter by hand, or import your bank's CSV export" />

      {accounts.length === 0 ? (
        <Empty>
          You need an account first —{" "}
          <Link to="/accounts" className="text-acid">
            add one
          </Link>
          .
        </Empty>
      ) : (
        <Card delay={60}>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-sm font-medium">Add to</h2>
            <label className="flex items-center gap-2">
              <span className="label">Account</span>
              <select
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
            </label>
          </div>
          <NewTransactionForm accountId={accountId} />
          <div className="mt-5 border-t border-line pt-5">
            <CsvUpload accountId={accountId} />
          </div>
        </Card>
      )}

      <Card className="mt-4" delay={120}>
        <h2 className="mb-4 text-sm font-medium">History</h2>
        <TransactionList />
      </Card>
    </>
  );
}
