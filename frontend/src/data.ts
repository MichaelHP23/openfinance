import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type Account = {
  id: string;
  name: string;
  type: string;
  institution: string | null;
  balance: string;
  currency: string;
  beneficiary: string | null;
};

export type Txn = {
  id: string;
  posted_at: string;
  merchant_raw: string;
  amount: string;
  currency: string;
  category_id: string | null;
  ignored: boolean;
  tags: string[];
};

export const ACCOUNT_TYPES = [
  "checking",
  "savings",
  "credit_card",
  "cash",
  "investment",
  "crypto",
  "loan",
  "asset",
  "liability",
] as const;

export function useAccounts() {
  return useQuery({ queryKey: ["accounts"], queryFn: () => apiFetch<Account[]>("/accounts") });
}

export function useTransactions(search = "", tag = "") {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (tag) params.set("tag", tag);
  const query = params.toString();
  return useQuery({
    queryKey: ["transactions", search, tag],
    queryFn: () => apiFetch<Txn[]>(`/transactions${query ? `?${query}` : ""}`),
  });
}

/** Tags already in use, for the filter. Shares the "transactions" key prefix so any
 * transaction write refreshes it. */
export function useTags() {
  return useQuery({
    queryKey: ["transactions", "tags"],
    queryFn: () => apiFetch<string[]>("/transactions/tags"),
  });
}

export type NetWorthPoint = { on: string; assets: number; debts: number; net: number };

export function useNetWorthHistory(days = 90) {
  return useQuery({
    queryKey: ["net-worth", days],
    queryFn: () => apiFetch<NetWorthPoint[]>(`/snapshots/net-worth?days=${days}`),
  });
}
