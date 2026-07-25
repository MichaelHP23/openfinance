import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./api/client";

export type Account = {
  id: string;
  name: string;
  type: string;
  institution: string | null;
  balance: string;
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

export function AccountList() {
  const { data = [] } = useAccounts();
  return (
    <ul className="divide-y rounded border">
      {data.length === 0 && <li className="p-3 text-gray-500">No accounts yet.</li>}
      {data.map((a) => (
        <li key={a.id} className="flex justify-between p-3">
          <span>
            {a.name} <em className="text-gray-500">({a.type})</em>
          </span>
          <span>
            {a.currency} {a.balance}
          </span>
        </li>
      ))}
    </ul>
  );
}

type Form = { name: string; type: string; balance: string };

export function NewAccountForm() {
  const qc = useQueryClient();
  const { register, handleSubmit, reset } = useForm<Form>({
    defaultValues: { type: "checking", balance: "0" },
  });
  const mut = useMutation({
    mutationFn: (f: Form) => apiFetch("/accounts", { method: "POST", body: JSON.stringify(f) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      reset();
    },
  });
  return (
    <form onSubmit={handleSubmit((f) => mut.mutate(f))} className="flex flex-wrap gap-2">
      <input
        className="rounded border p-2"
        placeholder="Name"
        {...register("name", { required: true })}
      />
      <select className="rounded border p-2" aria-label="Account type" {...register("type")}>
        {ACCOUNT_TYPES.map((t) => (
          <option key={t}>{t}</option>
        ))}
      </select>
      <input className="w-28 rounded border p-2" placeholder="Balance" {...register("balance")} />
      <button className="rounded bg-black px-3 text-white">Add</button>
      {mut.isError && <span className="text-sm text-red-600">{(mut.error as Error).message}</span>}
    </form>
  );
}
