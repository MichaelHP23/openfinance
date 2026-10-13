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
  return useQuery({ queryKey: ["alerts"], queryFn: () => apiFetch<Alert[]>("/alerts") });
}

export function useDismissAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      apiFetch<void>("/alerts/dismiss", { method: "POST", body: JSON.stringify({ key }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
}
