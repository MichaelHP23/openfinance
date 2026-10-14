import { useSafeToSpend } from "./forecast";
import { shortDate, usd } from "./money";
import { Card } from "./ui/Shell";

/** What can leave cash before the next payday. The number already has recurring bills
 *  and the month's budgeted spend taken out — see forecast.safe_to_spend. */
export function SafeToSpendCard() {
  const { data } = useSafeToSpend();
  // No data (loading or failed) shows nothing: a placeholder $0 here would read as advice.
  if (!data) return null;
  const spare = Number(data.amount) > 0;
  const bills = `${data.bills_due} bill${data.bills_due === 1 ? "" : "s"} due before then`;
  const window = data.until ? `until payday on ${shortDate(data.until)}` : "over the next 30 days";
  return (
    <Card className="mb-4" delay={50}>
      <p className="label">Safe to spend</p>
      <p className={`tnum mt-2 text-3xl ${spare ? "text-acid" : "text-clay"}`}>
        {usd(data.amount)}
      </p>
      <p className="mt-2 text-sm text-muted">
        {spare ? "" : "Nothing spare — "}
        {window} · {bills}
      </p>
    </Card>
  );
}
