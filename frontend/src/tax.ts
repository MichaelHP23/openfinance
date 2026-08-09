import { useQuery } from "@tanstack/react-query";
import { apiFetch, API_BASE } from "./api/client";

export type RealizedGain = {
  security_id: string;
  symbol: string;
  account_id: string;
  opened_on: string;
  closed_on: string;
  quantity: string;
  proceeds: string;
  cost_basis: string;
  gain: string;
  term: "short" | "long";
};

export type RealizedGains = {
  year: number;
  gains: RealizedGain[];
  short_term_gain: string;
  long_term_gain: string;
  total_gain: string;
};

export type IncomeSummary = { year: number; dividends: string; interest: string; total: string };

export function useRealizedGains(year: number) {
  return useQuery({
    queryKey: ["tax", "realized-gains", year],
    queryFn: () => apiFetch<RealizedGains>(`/tax/realized-gains?year=${year}`),
  });
}

export function useIncomeSummary(year: number) {
  return useQuery({
    queryKey: ["tax", "income-summary", year],
    queryFn: () => apiFetch<IncomeSummary>(`/tax/income-summary?year=${year}`),
  });
}

export function taxExportUrl(year: number) {
  return `${API_BASE}/tax/export?year=${year}`;
}
