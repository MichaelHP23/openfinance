import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type GroupBy = "category" | "merchant" | "month";

export type SpendingBucket = { key: string; key_id: string | null; total: string; count: number };
export type MonthFlow = { month: string; income: string; expense: string; net: string };
export type YearInReview = {
  year: number;
  total_in: string;
  total_out: string;
  savings_rate: string | null;
  biggest_category: string | null;
  biggest_category_amount: string | null;
  biggest_transaction_merchant: string | null;
  biggest_transaction_amount: string | null;
  new_subscriptions: string[];
  cancelled_subscriptions: string[];
  net_worth_delta: string | null;
};

export function useSpending(start: string, end: string, groupBy: GroupBy) {
  return useQuery({
    queryKey: ["reports", "spending", start, end, groupBy],
    queryFn: () =>
      apiFetch<SpendingBucket[]>(`/reports/spending?start=${start}&end=${end}&group_by=${groupBy}`),
  });
}

export function useIncomeVsExpense(months = 12) {
  return useQuery({
    queryKey: ["reports", "income-vs-expense", months],
    queryFn: () => apiFetch<MonthFlow[]>(`/reports/income-vs-expense?months=${months}`),
  });
}

export function useYearInReview(year: number) {
  return useQuery({
    queryKey: ["reports", "year-in-review", year],
    queryFn: () => apiFetch<YearInReview>(`/reports/year-in-review?year=${year}`),
  });
}
