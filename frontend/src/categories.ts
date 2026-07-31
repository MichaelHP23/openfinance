import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type MatchType = "merchant_contains" | "merchant_exact" | "merchant_regex";

export type Category = {
  id: string;
  name: string;
  parent_id: string | null;
  is_system: boolean;
};

export type Rule = {
  id: string;
  match_type: MatchType;
  pattern: string;
  category_id: string;
  min_amount: string | null;
  max_amount: string | null;
  account_id: string | null;
  priority: number;
  source: "user" | "suggested";
};

export type Uncategorized = { merchant: string; count: number; total: string };
export type Suggestion = { merchant: string; category_id: string; category_name: string };

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => apiFetch<Category[]>("/categories"),
    // The taxonomy changes when the user edits it and not otherwise.
    staleTime: 5 * 60 * 1000,
  });
}

/** id → "Group · Leaf", for labelling a transaction row without a join on the server. */
export function useCategoryMap(): Map<string, string> {
  const { data = [] } = useCategories();
  const byId = new Map(data.map((c) => [c.id, c]));
  return new Map(
    data.map((c) => {
      const parent = c.parent_id ? byId.get(c.parent_id) : undefined;
      return [c.id, parent ? `${parent.name} · ${c.name}` : c.name];
    }),
  );
}

export function useRules() {
  return useQuery({ queryKey: ["category-rules"], queryFn: () => apiFetch<Rule[]>("/category-rules") });
}

export function useUncategorized() {
  return useQuery({
    queryKey: ["uncategorized"],
    queryFn: () => apiFetch<Uncategorized[]>("/categorization/uncategorized"),
  });
}

/** Anything that changes categorization invalidates the same three things. */
function useCategorizationInvalidator() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["category-rules"] });
    qc.invalidateQueries({ queryKey: ["uncategorized"] });
    qc.invalidateQueries({ queryKey: ["transactions"] });
  };
}

export type NewRule = {
  pattern: string;
  category_id: string;
  match_type?: MatchType;
  priority?: number;
};

export function useCreateRule() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (rule: NewRule) =>
      apiFetch<Rule>("/category-rules", { method: "POST", body: JSON.stringify(rule) }),
    onSuccess: invalidate,
  });
}

export function useDeleteRule() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/category-rules/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}

export function useReorderRules() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (rule_ids: string[]) =>
      apiFetch("/category-rules/reorder", {
        method: "POST",
        body: JSON.stringify({ rule_ids }),
      }),
    onSuccess: invalidate,
  });
}

export function useBackfill() {
  const invalidate = useCategorizationInvalidator();
  return useMutation({
    mutationFn: (only_uncategorized: boolean) =>
      apiFetch<{ changed: number }>("/categorization/backfill", {
        method: "POST",
        body: JSON.stringify({ only_uncategorized }),
      }),
    onSuccess: invalidate,
  });
}

export function useSuggest() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ suggestions: Suggestion[]; model: string }>("/categories/suggest", {
        method: "POST",
      }),
  });
}
