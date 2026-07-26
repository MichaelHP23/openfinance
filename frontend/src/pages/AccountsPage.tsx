import { AccountList, NewAccountForm } from "../accounts";
import { ConnectBank, ConnectionList } from "../connections";
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

      <div className="rise" style={{ "--d": "60ms" } as React.CSSProperties}>
        <ConnectBank />
      </div>

      <div className="rise mt-4 empty:mt-0" style={{ "--d": "100ms" } as React.CSSProperties}>
        <ConnectionList />
      </div>

      <Card className="mt-4" delay={140}>
        <h2 className="mb-4 text-sm font-medium">Add an account by hand</h2>
        <NewAccountForm />
      </Card>

      <Card className="mt-4" delay={200}>
        <h2 className="mb-4 text-sm font-medium">Your accounts</h2>
        <AccountList />
      </Card>
    </>
  );
}
