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

export type Invite = {
  id: string;
  role: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
};

export function useInvites() {
  return useQuery({ queryKey: ["invites"], queryFn: () => apiFetch<Invite[]>("/auth/invites") });
}

export function useCreateInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ id: string; token: string; expires_at: string }>("/auth/invites", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }),
  });
}

export function useRevokeInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/auth/invites/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }),
  });
}

export type AuditEvent = {
  id: string;
  user_id: string;
  action: string;
  event_metadata: Record<string, unknown>;
  created_at: string;
};

export function useAuditLog() {
  return useQuery({ queryKey: ["audit-log"], queryFn: () => apiFetch<AuditEvent[]>("/audit-log") });
}

export function useJoinHousehold() {
  return useMutation({
    mutationFn: (body: { token: string; email: string; password: string }) =>
      apiFetch("/auth/join", { method: "POST", body: JSON.stringify(body) }),
  });
}
