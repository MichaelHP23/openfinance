import { AccountList, ConnectBank, NewAccountForm } from "../accounts";
import { useAccounts } from "../data";
import { netWorth, usd } from "../money";
import { Card, PageHead } from "../ui/Shell";

export function AccountsPage() {
  const { data: accounts = [] } = useAccounts();
  const { net } = netWorth(accounts);

  return (
    <>
      <PageHead
        title="Accounts"
        sub={
          accounts.length
            ? `${accounts.length} account${accounts.length > 1 ? "s" : ""} · ${usd(net)} net`
            : "Add the accounts you want to track"
        }
      />

      <Card delay={60}>
        <h2 className="mb-4 text-sm font-medium">Add an account</h2>
        <NewAccountForm />
      </Card>

      <Card className="mt-4" delay={120}>
        <h2 className="mb-4 text-sm font-medium">Your accounts</h2>
        <AccountList />
      </Card>

      <div className="rise mt-4" style={{ "--d": "180ms" } as React.CSSProperties}>
        <ConnectBank />
      </div>
    </>
  );
}
