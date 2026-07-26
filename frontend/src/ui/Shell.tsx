import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { apiFetch } from "../api/client";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/accounts", label: "Accounts", end: false },
  { to: "/investments", label: "Investments", end: false },
  { to: "/transactions", label: "Transactions", end: false },
];

export function Shell({ children, localMode }: { children: ReactNode; localMode: boolean }) {
  const logout = async () => {
    await apiFetch("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  };

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between border-r border-line px-5 py-7 md:flex">
        <div>
          <div className="mb-10 flex items-baseline gap-2">
            <span className="font-display text-3xl leading-none text-acid">O</span>
            <span className="text-sm font-medium tracking-[0.2em] uppercase">Finance</span>
          </div>

          <nav className="flex flex-col gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  [
                    "relative rounded-lg px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-[rgba(198,242,78,0.08)] text-bone"
                      : "text-muted hover:bg-[rgba(237,234,228,0.04)] hover:text-bone",
                  ].join(" ")
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute top-1/2 left-0 h-4 w-[2px] -translate-y-1/2 rounded-full bg-acid" />
                    )}
                    {n.label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="text-[11px] leading-relaxed text-muted">
          {localMode ? (
            <>
              <span className="mb-1 block text-bone">Local install</span>
              Single household, no sign-in. Data lives in your Postgres container.
            </>
          ) : (
            <button onClick={logout} className="text-muted transition-colors hover:text-bone">
              Log out
            </button>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-5 py-8 md:px-10 md:py-12">
        <div className="mx-auto w-full max-w-5xl">{children}</div>
      </main>
    </div>
  );
}

export function PageHead({ title, sub }: { title: string; sub?: string }) {
  return (
    <header className="rise mb-8">
      <h1 className="font-display text-4xl tracking-tight md:text-5xl">{title}</h1>
      {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
    </header>
  );
}

export function Card({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <section
      className={`card rise p-5 ${className}`}
      style={{ "--d": `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-muted">
      {children}
    </p>
  );
}
