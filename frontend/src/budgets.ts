import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type BudgetStatus = {
  category_id: string;
  category_name: string;
  budgeted: string;
  carry_in: string;
  effective_budget: string;
  actual: string;
  remaining: string;
  pace: number | null;
  rollover: boolean;
};

export type BudgetSuggestion = { category_id: string; category_name: string; amount: string };
export type BudgetItem = { category_id: string; amount: string; rollover: boolean };

/** "2026-12" + 1 -> "2027-01". Pure date math on a "YYYY-MM" string, no network. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function useBudgetStatus(month: string) {
  return useQuery({
    queryKey: ["budget-status", month],
    queryFn: () => apiFetch<BudgetStatus[]>(`/budgets/${month}`),
  });
}

export function useUpsertBudgets(month: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: BudgetItem[]) =>
      apiFetch(`/budgets/${month}`, { method: "PUT", body: JSON.stringify({ items }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budget-status", month] }),
  });
}

export function useSuggestBudgets(month: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<BudgetSuggestion[]>(`/budgets/${month}/suggest`, { method: "POST" }),
  });
}

export function useCopyBudgets(month: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (from: string) =>
      apiFetch<{ copied: number }>(`/budgets/${month}/copy`, {
        method: "POST",
        body: JSON.stringify({ from }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budget-status", month] }),
  });
}
