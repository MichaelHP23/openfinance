import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

export type Session = {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  is_current: boolean;
};

export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: () => apiFetch<Session[]>("/auth/sessions") });
}

export function useRevokeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useRevokeOtherSessions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch("/auth/sessions", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiFetch("/auth/password", { method: "POST", body: JSON.stringify(body) }),
  });
}

export type Enrollment = { secret: string; provisioning_uri: string };

export function useEnroll2FA() {
  return useMutation({
    mutationFn: () => apiFetch<Enrollment>("/auth/2fa/enroll", { method: "POST" }),
  });
}

export function useVerify2FA() {
  return useMutation({
    mutationFn: (code: string) =>
      apiFetch("/auth/2fa/verify", { method: "POST", body: JSON.stringify({ code }) }),
  });
}
