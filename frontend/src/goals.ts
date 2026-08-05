import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type GoalKind = "savings" | "debt_payoff";
export type GoalStatus = "active" | "achieved" | "archived";

export type Goal = {
  id: string;
  name: string;
  kind: GoalKind;
  target_amount: string;
  target_date: string | null;
  monthly_funding: string | null;
  status: GoalStatus;
  account_ids: string[];
  progress: string;
  projected_date: string | null;
};

export type NewGoal = {
  name: string;
  kind: GoalKind;
  target_amount: string;
  target_date?: string | null;
  monthly_funding?: string | null;
  account_ids: string[];
};

export type GoalPatch = Partial<NewGoal> & { status?: GoalStatus };

export function useGoals() {
  return useQuery({ queryKey: ["goals"], queryFn: () => apiFetch<Goal[]>("/goals") });
}

export function useCreateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (goal: NewGoal) =>
      apiFetch<Goal>("/goals", { method: "POST", body: JSON.stringify(goal) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });
}

export function useUpdateGoal(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: GoalPatch) =>
      apiFetch<Goal>(`/goals/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });
}

export function useDeleteGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/goals/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });
}

/** Percentage for a progress ring, clamped to [0, 100] — a debt paid down past its
 * original target, or a savings goal that overshoots, still draws a full ring
 * rather than an SVG arc past a full circle. */
export function goalPercent(goal: Goal): number {
  const target = Number(goal.target_amount);
  if (target <= 0) return 0;
  const pct = (Number(goal.progress) / target) * 100;
  return Math.max(0, Math.min(100, pct));
}
