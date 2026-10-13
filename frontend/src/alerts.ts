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
