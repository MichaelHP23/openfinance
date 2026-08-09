import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { apiFetch } from "../api/client";
import { MoreMenu } from "./MoreMenu";

// Three fixed mobile tabs, down from five — see PLAN-CONSTRAINTS.md's Navigation
// section. A fourth slot is the MoreMenu trigger rendered below, not a fourth entry
// here: the trigger isn't a route, so giving it a fake NAV-shaped object just to keep a
// literal "four items in one array" would be a distinction with no behavioral payoff.
const NAV = [
  { to: "/", label: "Overview", short: "Overview", end: true, glyph: "◔" },
  { to: "/accounts", label: "Accounts", short: "Accounts", end: false, glyph: "▤" },
  { to: "/transactions", label: "Transactions", short: "Activity", end: false, glyph: "⇅" },
];

// Destinations that don't fit the mobile tab bar's three fixed slots. Desktop's sidebar
// still shows every one of these, undivided with NAV — the ceiling here is a phone's
// width, not a design preference. P3 and P5 each push one entry onto this array and
// change nothing else; a plan that rebuilds this menu instead is wrong.
export const MORE = [
  { to: "/investments", label: "Investments", short: "Invest", end: false, glyph: "◈" },
  { to: "/recurring", label: "Recurring", short: "Bills", end: false, glyph: "↻" },
  { to: "/budgets", label: "Budgets", short: "Budgets", end: false, glyph: "▥" },
  { to: "/goals", label: "Goals", short: "Goals", end: false, glyph: "◎" },
  { to: "/reports", label: "Reports", short: "Reports", end: false, glyph: "▦" },
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
            {[...NAV, ...MORE].map((n) => (
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

      <div className="flex min-w-0 flex-1 flex-col">
        {/* The sidebar is desktop-only, so small screens get their own header… */}
        <header className="flex items-baseline gap-2 border-b border-line px-5 py-4 md:hidden">
          <span className="font-display text-2xl leading-none text-acid">O</span>
          <span className="text-xs font-medium tracking-[0.2em] uppercase">Finance</span>
        </header>

        <main className="min-w-0 flex-1 px-5 py-6 pb-28 md:px-10 md:py-12 md:pb-12">
          <div className="mx-auto w-full max-w-5xl">{children}</div>
        </main>
      </div>

      {/* …and a thumb-reachable tab bar, clearing the iPhone home indicator. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-ink/95 backdrop-blur md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              [
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] transition-colors",
                isActive ? "text-acid" : "text-muted",
              ].join(" ")
            }
          >
            {({ isActive }) => (
              <>
                <span aria-hidden className="text-base leading-none">
                  {n.glyph}
                </span>
                <span className={isActive ? "font-medium" : ""}>{n.short}</span>
              </>
            )}
          </NavLink>
        ))}
        <MoreMenu items={MORE} />
      </nav>
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

/** ponytail: lifted here when a second page needed it. OverviewPage and
 *  InvestmentsPage still carry their own copies — folding those in is a
 *  cosmetic edit to pages this change has no other reason to touch. */
export function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p className={`tnum mt-2 text-xl ${tone}`}>{value}</p>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-muted">
      {children}
    </p>
  );
}
