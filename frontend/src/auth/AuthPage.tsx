import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Form = { email: string; password: string };
type CodeForm = { code: string };

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
  const [preauthToken, setPreauthToken] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Form>();
  const {
    register: registerCode,
    handleSubmit: handleCodeSubmit,
    setError: setCodeError,
    formState: { errors: codeErrors, isSubmitting: codeSubmitting },
  } = useForm<CodeForm>();

  const onSubmit = async (data: Form) => {
    try {
      if (mode === "register") {
        await apiFetch(m.path, { method: "POST", body: JSON.stringify(data) });
        await qc.invalidateQueries({ queryKey: ["me"] });
        nav("/");
        return;
      }
      const result = await apiFetch<{ status: string; preauth_token?: string }>(m.path, {
        method: "POST",
        body: JSON.stringify(data),
      });
      if (result.status === "totp_required" && result.preauth_token) {
        setPreauthToken(result.preauth_token);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  const onCodeSubmit = async (data: CodeForm) => {
    try {
      await apiFetch("/auth/2fa/login-verify", {
        method: "POST",
        body: JSON.stringify({ preauth_token: preauthToken, code: data.code }),
      });
      await qc.invalidateQueries({ queryKey: ["me"] });
      nav("/");
    } catch (e) {
      setCodeError("root", { message: (e as Error).message });
    }
  };

  if (preauthToken) {
    return (
      <div className="grid min-h-screen place-items-center p-6">
        <form onSubmit={handleCodeSubmit(onCodeSubmit)} className="rise flex w-full max-w-sm flex-col gap-4">
          <h1 className="font-display text-4xl">Enter your code</h1>
          <p className="text-sm text-muted">Open your authenticator app and enter the 6-digit code.</p>
          <label className="flex flex-col gap-1.5">
            <span className="label">Code</span>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              {...registerCode("code", { required: "Code is required" })}
            />
          </label>
          {codeErrors.code && <span className="text-sm text-clay">{codeErrors.code.message}</span>}
          {codeErrors.root && (
            <span className="rounded-lg border border-clay/40 bg-clay/10 px-3 py-2 text-sm text-clay">
              {codeErrors.root.message}
            </span>
          )}
          <button disabled={codeSubmitting} className="btn mt-1 w-full">
            {codeSubmitting ? "…" : "Verify"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between border-r border-line p-12 lg:flex">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-3xl leading-none text-brand">O</span>
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
