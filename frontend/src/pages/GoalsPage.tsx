import { GoalCards } from "../GoalCards";
import { PageHead } from "../ui/Shell";

export function GoalsPage() {
  return (
    <>
      <PageHead title="Goals" sub="Savings targets and debt payoff, tracked against real balances" />
      <GoalCards />
    </>
  );
}
