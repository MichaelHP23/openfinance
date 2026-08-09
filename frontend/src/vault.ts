import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, API_BASE } from "./api/client";

export type DocumentKind = "will" | "trust" | "insurance" | "deed" | "title" | "statement" | "other";

export type VaultDocument = {
  id: string;
  kind: DocumentKind;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  notes: string | null;
  created_at: string;
};

export type ChecklistItem = { label: string; satisfied: boolean; detail: string };
export type Checklist = { items: ChecklistItem[]; gaps: number };

export function useDocuments() {
  return useQuery({ queryKey: ["documents"], queryFn: () => apiFetch<VaultDocument[]>("/documents") });
}

export function useChecklist() {
  return useQuery({
    queryKey: ["estate-checklist"],
    queryFn: () => apiFetch<Checklist>("/estate/checklist"),
  });
}

export function documentDownloadUrl(id: string) {
  return `${API_BASE}/documents/${id}/download`;
}

type UploadInput = { file: File; kind: DocumentKind; title: string; notes: string };

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, kind, title, notes }: UploadInput) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      form.append("title", title);
      if (notes) form.append("notes", notes);
      // Not apiFetch: it always sets Content-Type: application/json, which would
      // stomp the multipart boundary the browser sets for FormData automatically.
      const res = await fetch(`${API_BASE}/documents`, { method: "POST", credentials: "include", body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? res.statusText);
      }
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["estate-checklist"] });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["estate-checklist"] });
    },
  });
}
