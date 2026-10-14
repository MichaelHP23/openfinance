import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type AlertSeverity = "info" | "warn" | "urgent";

export type Alert = {
  key: string;
  kind: string;
  severity: AlertSeverity;
  title: string;
  body: string;
  href: string;
  occurred_on: string;
};

// One fixed follow-up per kind. The alert's own title and body carry the specifics, so
// the advisor gets the same facts the card shows and looks the rest up with its tools.
const FOLLOW_UP: Record<string, string> = {
  bill_due: "Will I have enough to cover it?",
  price_increase: "What are my options?",
  yearly_renewal: "Is it worth keeping for another year?",
  still_billing: "What should I do to stop it?",
  low_balance: "What is driving it and what can I do?",
  over_budget: "Where did the money go, and how do I get back on track?",
  large_charge: "Is this unusual for me?",
};

export const questionFor = (alert: Alert) =>
  `${alert.title}. ${alert.body} ${FOLLOW_UP[alert.kind] ?? "What should I do about this?"}`;

/** Whether a model is configured. Shared with the assistant card through the cache. */
export function useAdvisorAvailable(enabled = true) {
  const { data } = useQuery({
    queryKey: ["insights-available"],
    queryFn: () => apiFetch<{ available: boolean }>("/insights/available"),
    enabled,
  });
  return data?.available ?? false;
}

export function useAlerts() {
  // The bell sits in the shell, so this would otherwise refetch on every navigation and
  // window focus. A minute of staleness is fine for things measured in days.
  return useQuery({
    queryKey: ["alerts"],
    queryFn: () => apiFetch<Alert[]>("/alerts"),
    staleTime: 60_000,
  });
}

export function useDismissAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiFetch<void>("/alerts/dismiss", { method: "POST", body: JSON.stringify({ key }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
}
