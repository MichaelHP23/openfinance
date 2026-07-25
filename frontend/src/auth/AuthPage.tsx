import { useForm } from "react-hook-form";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

type Form = { email: string; password: string };

// ponytail: one component for both modes — the pages differ only in copy + endpoint.
const MODES = {
  register: { title: "Create account", cta: "Sign up", path: "/auth/register", alt: "/login", altText: "Have an account? Log in" },
  login: { title: "Log in", cta: "Log in", path: "/auth/login", alt: "/register", altText: "Need an account? Sign up" },
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
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="mx-auto mt-24 flex max-w-sm flex-col gap-3 p-4"
    >
      <h1 className="text-xl font-semibold">{m.title}</h1>
      <input
        className="rounded border p-2"
        placeholder="Email"
        type="email"
        {...register("email", { required: "Email is required" })}
      />
      {errors.email && <span className="text-sm text-red-600">{errors.email.message}</span>}
      <input
        className="rounded border p-2"
        type="password"
        placeholder="Password"
        {...register("password", { required: "Password is required", minLength: { value: 6, message: "At least 6 characters" } })}
      />
      {errors.password && <span className="text-sm text-red-600">{errors.password.message}</span>}
      {errors.root && <span className="text-sm text-red-600">{errors.root.message}</span>}
      <button disabled={isSubmitting} className="rounded bg-black p-2 text-white">
        {m.cta}
      </button>
      <Link to={m.alt} className="text-sm text-blue-600">
        {m.altText}
      </Link>
    </form>
  );
}
