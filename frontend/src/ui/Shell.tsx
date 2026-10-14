import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { apiFetch } from "../api/client";
import { AlertBell } from "../AlertsCard";
import { MoreMenu } from "./MoreMenu";
import { OfflineBanner } from "./OfflineBanner";

// The four destinations the phone tab bar always shows, in the order a money app leads
// with them; everything else sits behind More. The sidebar shows both lists.
// ponytail: this was three tabs (PLAN-CONSTRAINTS.md, Navigation). Four plus More is
// five slots of 78px at 390px wide, which still fits an 11px label.
const NAV = [
  { to: "/", label: "Dashboard", short: "Dashboard", end: true, glyph: "◔" },
  { to: "/recurring", label: "Recurring", short: "Recurring", end: false, glyph: "↻" },
  { to: "/reports", label: "Spending", short: "Spending", end: false, glyph: "▦" },
  { to: "/transactions", label: "Transactions", short: "Transactions", end: false, glyph: "⇅" },
];

// Settings is last on purpose: the sidebar leaves it off (it lives behind the gear by
// the wordmark) and the phone's More sheet keeps it at the bottom.
export const MORE = [
  { to: "/budgets", label: "Budgets", short: "Budgets", end: false, glyph: "▥" },
  { to: "/goals", label: "Goals", short: "Goals", end: false, glyph: "◎" },
  { to: "/accounts", label: "Accounts", short: "Accounts", end: false, glyph: "▤" },
  { to: "/investments", label: "Investments", short: "Invest", end: false, glyph: "◈" },
  { to: "/settings", label: "Settings", short: "Settings", end: false, glyph: "⚙" },
];

const Gear = ({ className = "" }: { className?: string }) => (
  <NavLink to="/settings" aria-label="Settings" className={`text-lg leading-none ${className}`}>
    <span aria-hidden>⚙</span>
  </NavLink>
);

export function Shell({ children, localMode }: { children: ReactNode; localMode: boolean }) {
  const logout = async () => {
    await apiFetch("/auth/logout", { method: "POST" });
    window.location.href = "/login";
  };

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between border-r border-line bg-surface px-5 py-7 md:flex">
        <div>
          <div className="mb-8 flex items-center gap-2">
            <Gear className="text-muted transition-colors hover:text-bone" />
            <span className="font-display text-2xl leading-none text-brand">O</span>
            <span className="text-sm font-medium tracking-[0.2em] uppercase">Finance</span>
          </div>

          <nav aria-label="Main" className="flex flex-col gap-1">
            {[...NAV, ...MORE.filter((n) => n.to !== "/settings")].map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  [
                    "relative flex items-center gap-3 rounded-full px-4 py-2.5 text-sm transition-colors",
                    isActive
                      ? "bg-tint font-medium text-brand"
                      : "text-muted hover:bg-hover hover:text-bone",
                  ].join(" ")
                }
              >
                {() => (
                  <>
                    <span aria-hidden className="w-4 text-center text-base leading-none">
                      {n.glyph}
                    </span>
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
        <header className="band grid grid-cols-[2rem_1fr_2rem] items-center px-4 py-3.5 text-white md:hidden [&_a]:text-white">
          <Gear />
          <span className="flex items-baseline justify-center gap-2">
            <span className="font-display text-2xl leading-none">O</span>
            <span className="text-xs font-medium tracking-[0.2em] uppercase">Finance</span>
          </span>
          <AlertBell />
        </header>

        <main className="relative min-w-0 flex-1 px-5 py-6 pb-28 md:px-10 md:py-10 md:pb-12">
          <div aria-hidden className="band absolute inset-x-0 top-0 h-44 md:h-52" />
          <div className="absolute top-9 right-10 hidden text-white md:block [&_a]:text-white">
            <AlertBell />
          </div>
          <div className="relative mx-auto w-full max-w-5xl">
            <OfflineBanner />
            {children}
          </div>
        </main>
      </div>

      {/* …and a thumb-reachable tab bar, clearing the iPhone home indicator. */}
      <nav
        aria-label="Tabs"
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface/95 backdrop-blur md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              [
                "flex min-w-0 flex-1 flex-col items-center gap-1 border-t-2 py-2.5 text-[11px] transition-colors",
                isActive ? "border-brand text-brand" : "border-transparent text-muted",
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
    <header className="rise mb-6 text-white">
      <h1 className="font-display text-3xl tracking-tight md:text-4xl">{title}</h1>
      {sub && <p className="mt-1 text-sm text-white/80">{sub}</p>}
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
    <p className="rounded-lg border border-dashed border-line bg-surface px-4 py-6 text-center text-sm text-muted">
      {children}
    </p>
  );
}
