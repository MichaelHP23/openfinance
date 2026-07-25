import { useForm } from "react-hook-form";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Form = { email: string; password: string };

// ponytail: one component for both modes — the pages differ only in copy + endpoint.
const MODES = {
  register: {
    title: "Create account",
    cta: "Sign up",
    path: "/auth/register",
    alt: "/login",
    altText: "Have an account? Log in",
  },
  login: {
    title: "Welcome back",
    cta: "Log in",
    path: "/auth/login",
    alt: "/register",
    altText: "Need an account? Sign up",
  },
} as const;

export function AuthPage({ mode }: { mode: keyof typeof MODES }) {
  const m = MODES[mode];
  const nav = useNavigate();
  const qc = useQueryClient();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Form>();

  const onSubmit = async (data: Form) => {
    try {
      await apiFetch(m.path, { method: "POST", body: JSON.stringify(data) });
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between border-r border-line p-12 lg:flex">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl leading-none text-acid">O</span>
          <span className="text-sm font-medium tracking-[0.2em] uppercase">Finance</span>
        </div>
        <div>
          <p className="font-display text-5xl leading-[1.05] text-balance">
            Every account, every transaction, <em className="text-acid">in one place.</em>
          </p>
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-muted">
            Self-hosted. Your data lives in your database, on your machine — no third party
            watching your spending.
          </p>
        </div>
        <p className="label">Household finance · self-hosted</p>
      </aside>

      <main className="flex items-center justify-center p-6">
        <form onSubmit={handleSubmit(onSubmit)} className="rise flex w-full max-w-sm flex-col gap-4">
          <h1 className="font-display text-4xl">{m.title}</h1>

          <label className="flex flex-col gap-1.5">
            <span className="label">Email</span>
            <input
              type="email"
              placeholder="Email"
              autoComplete="email"
              {...register("email", { required: "Email is required" })}
            />
          </label>
          {errors.email && <span className="text-sm text-clay">{errors.email.message}</span>}

          <label className="flex flex-col gap-1.5">
            <span className="label">Password</span>
            <input
              type="password"
              placeholder="Password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
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
            {isSubmitting ? "…" : m.cta}
          </button>

          <Link
            to={m.alt}
            className="btn-ghost w-full text-center transition-colors hover:text-acid"
          >
            {m.altText}
          </Link>
        </form>
      </main>
    </div>
  );
}
