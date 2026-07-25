import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type Account = {
  id: string;
  name: string;
  type: string;
  institution: string | null;
  balance: string;
  currency: string;
};

export type Txn = {
  id: string;
  posted_at: string;
  merchant_raw: string;
  amount: string;
  currency: string;
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

export function useTransactions(search = "") {
  return useQuery({
    queryKey: ["transactions", search],
    queryFn: () =>
      apiFetch<Txn[]>(`/transactions${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  });
}
