import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type ForecastDay = { on: string; projected_balance: string; contributions: string[] };

export type GoalAffordability = {
  goal_id: string;
  goal_name: string;
  baseline_date: string | null;
  with_amount_date: string | null;
};

export type AffordResult = {
  baseline: ForecastDay[];
  with_amount: ForecastDay[];
  stays_non_negative: boolean;
  minimum_balance: string;
  goal_impact: GoalAffordability[];
};

export function useForecast(months = 6) {
  return useQuery({
    queryKey: ["forecast", months],
    queryFn: () => apiFetch<ForecastDay[]>(`/forecast?months=${months}`),
  });
}

export function useAfford() {
  return useMutation({
    mutationFn: (body: { amount: string; on_date: string; months: number }) =>
      apiFetch<AffordResult>("/forecast/afford", { method: "POST", body: JSON.stringify(body) }),
  });
}

/** First day the projected balance drops below zero, if any — what the Overview
 * chart's negative-balance marker points at. */
export function firstNegativeDay(days: ForecastDay[]): ForecastDay | null {
  return days.find((d) => Number(d.projected_balance) < 0) ?? null;
}
