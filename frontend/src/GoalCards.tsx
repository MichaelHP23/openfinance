import { useState } from "react";
import { useAccounts } from "./data";
import { goalPercent, useCreateGoal, useDeleteGoal, useGoals, useUpdateGoal } from "./goals";
import type { Goal } from "./goals";
import { shortDate, usd } from "./money";
import { Card, Empty } from "./ui/Shell";

function GoalRing({ percent }: { percent: number }) {
  const r = 26;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - percent / 100);
  return (
    <svg width={64} height={64} viewBox="0 0 64 64" role="img" aria-label={`${Math.round(percent)}% funded`}>
      <circle cx={32} cy={32} r={r} fill="none" stroke="var(--color-line)" strokeWidth={6} />
      <circle
        cx={32}
        cy={32}
        r={r}
        fill="none"
        stroke="#c6f24e"
        strokeWidth={6}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform="rotate(-90 32 32)"
      />
      <text x={32} y={36} textAnchor="middle" className="tnum" fontSize={13} fill="currentColor">
        {Math.round(percent)}%
      </text>
    </svg>
  );
}

function GoalRow({ goal }: { goal: Goal }) {
  const percent = goalPercent(goal);
  const update = useUpdateGoal(goal.id);
  const del = useDeleteGoal();
  return (
    <li className="flex items-center gap-4 border-b border-line py-4 last:border-0">
      <GoalRing percent={percent} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{goal.name}</p>
        <p className="tnum mt-0.5 text-xs text-muted">
          {usd(goal.progress)} of {usd(goal.target_amount)}
          {goal.projected_date && <> · projected {shortDate(goal.projected_date)}</>}
        </p>
      </div>
      <button
        className="text-xs text-muted transition-colors hover:text-bone"
        aria-label={`Archive ${goal.name}`}
        onClick={() => update.mutate({ status: "archived" })}
      >
        Archive
      </button>
      <button
        className="text-xs text-clay"
        aria-label={`Delete ${goal.name}`}
        onClick={() => del.mutate(goal.id)}
      >
        Delete
      </button>
    </li>
  );
}

function NewGoalForm() {
  const { data: accounts = [] } = useAccounts();
  const create = useCreateGoal();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"savings" | "debt_payoff">("savings");
  const [targetAmount, setTargetAmount] = useState("");
  const [accountIds, setAccountIds] = useState<string[]>([]);

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(
          { name, kind, target_amount: targetAmount, account_ids: accountIds },
          {
            onSuccess: () => {
              setName("");
              setTargetAmount("");
              setAccountIds([]);
            },
          },
        );
      }}
    >
      <label className="flex flex-col gap-1 text-xs">
        Goal name
        <input aria-label="Goal name" value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        Kind
        <select aria-label="Goal kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="savings">Savings</option>
          <option value="debt_payoff">Debt payoff</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs">
        Target amount
        <input
          aria-label="Target amount"
          value={targetAmount}
          onChange={(e) => setTargetAmount(e.target.value)}
          inputMode="decimal"
          required
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        Linked accounts
        <select
          aria-label="Linked accounts"
          multiple
          value={accountIds}
          onChange={(e) => setAccountIds(Array.from(e.target.selectedOptions, (o) => o.value))}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      <button className="btn" disabled={create.isPending}>
        Add goal
      </button>
    </form>
  );
}

export function GoalCards() {
  const { data: goalList = [], isLoading } = useGoals();

  return (
    <Card>
      <h2 className="mb-4 text-sm font-medium">Your goals</h2>
      <NewGoalForm />
      <div className="mt-6">
        {isLoading ? null : goalList.length === 0 ? (
          <Empty>No goals yet — add one above.</Empty>
        ) : (
          <ul>
            {goalList.map((g) => (
              <GoalRow key={g.id} goal={g} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
