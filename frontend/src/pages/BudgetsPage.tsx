import { useState } from "react";
import { BudgetBoard } from "../BudgetBoard";
import { PageHead } from "../ui/Shell";

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function BudgetsPage() {
  const [month, setMonth] = useState(currentMonth());
  return (
    <>
      <PageHead title="Budgets" sub="What you meant to spend, next to what actually happened" />
      <BudgetBoard month={month} onMonthChange={setMonth} />
    </>
  );
}
