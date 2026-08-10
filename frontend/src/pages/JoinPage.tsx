import { useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useJoinHousehold } from "../auth/settings";

type Form = { email: string; password: string };

export function JoinPage() {
  const { token } = useParams<{ token: string }>();
  const nav = useNavigate();
  const qc = useQueryClient();
  const join = useJoinHousehold();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Form>();

  const onSubmit = async (data: Form) => {
    if (!token) return;
    try {
      await join.mutateAsync({ token, ...data });
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <form onSubmit={handleSubmit(onSubmit)} className="rise flex w-full max-w-sm flex-col gap-4">
        <h1 className="font-display text-4xl">Join household</h1>
        <p className="text-sm text-muted">You've been invited to join a shared household.</p>

        <label className="flex flex-col gap-1.5">
          <span className="label">Email</span>
          <input type="email" autoComplete="email" {...register("email", { required: "Email is required" })} />
        </label>
        {errors.email && <span className="text-sm text-clay">{errors.email.message}</span>}

        <label className="flex flex-col gap-1.5">
          <span className="label">Password</span>
          <input
            type="password"
            autoComplete="new-password"
            {...register("password", {
              required: "Password is required",
              minLength: { value: 6, message: "At least 6 characters" },
            })}
          />
        </label>
        {errors.password && <span className="text-sm text-clay">{errors.password.message}</span>}
        {errors.root && (
          <span className="rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
            {errors.root.message}
          </span>
        )}

        <button disabled={isSubmitting} className="btn mt-1 w-full">
          {isSubmitting ? "…" : "Join"}
        </button>
      </form>
    </main>
  );
}
