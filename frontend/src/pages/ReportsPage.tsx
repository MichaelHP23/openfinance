import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { CashFlowCard, SpendingCard, TaxCard, YearInReviewCard } from "../ReportsCards";
import { ChecklistCard, DocumentList, UploadForm } from "../VaultPanel";
import { PageHead } from "../ui/Shell";

function SubTabs() {
  const tabs = [
    { to: "/reports", label: "Spending", end: true },
    { to: "/reports/cash-flow", label: "Cash flow", end: false },
    { to: "/reports/year", label: "Year in review", end: false },
    { to: "/reports/tax", label: "Tax", end: false },
    { to: "/reports/vault", label: "Vault", end: false },
  ];
  return (
    <nav className="rise mb-6 flex gap-1 overflow-x-auto" style={{ scrollbarWidth: "none" } as React.CSSProperties}>
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            [
              "shrink-0 rounded-lg px-3 py-2 text-sm whitespace-nowrap transition-colors",
              isActive ? "bg-[rgba(198,242,78,0.08)] text-bone" : "text-muted hover:bg-[rgba(237,234,228,0.04)] hover:text-bone",
            ].join(" ")
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

function SpendingTab() {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
  const end = new Date(today.getFullYear(), today.getMonth() + 1, 0).toISOString().slice(0, 10);
  const [groupBy, setGroupBy] = useState<"category" | "merchant" | "month">("category");

  return (
    <>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <span className="label">Group by</span>
        <select
          aria-label="Group spending by"
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as "category" | "merchant" | "month")}
        >
          <option value="category">Category</option>
          <option value="merchant">Merchant</option>
          <option value="month">Month</option>
        </select>
      </label>
      <SpendingCard start={start} end={end} groupBy={groupBy} />
    </>
  );
}

export function ReportsPage() {
  const year = new Date().getFullYear();
  return (
    <>
      <PageHead title="Reports" sub="Spending, cash flow, taxes, and the document vault." />
      <SubTabs />
      <Routes>
        <Route index element={<SpendingTab />} />
        <Route path="cash-flow" element={<CashFlowCard />} />
        <Route path="year" element={<YearInReviewCard year={year} />} />
        <Route path="tax" element={<TaxCard year={year} />} />
        <Route
          path="vault"
          element={
            <>
              <UploadForm />
              <ChecklistCard />
              <DocumentList />
            </>
          }
        />
      </Routes>
    </>
  );
}
