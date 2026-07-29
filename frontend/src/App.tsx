import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { apiFetch } from "./api/client";
import { AuthPage } from "./auth/AuthPage";
import { OverviewPage } from "./pages/OverviewPage";
import { AccountsPage } from "./pages/AccountsPage";
import { AccountDetailPage } from "./pages/AccountDetailPage";
import { InvestmentsPage } from "./pages/InvestmentsPage";
import { TransactionsPage } from "./pages/TransactionsPage";
import { RecurringPage } from "./pages/RecurringPage";
import { Shell } from "./ui/Shell";

const qc = new QueryClient();

type Me = { email: string; household_id: string; local_mode: boolean };

function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiFetch<Me>("/auth/me"), retry: false });
}

function Protected({ children }: { children: ReactNode }) {
  const { data, isLoading, isError } = useMe();
  if (isLoading) return <div className="p-10 text-sm text-muted">Loading…</div>;
  if (isError || !data) return <Navigate to="/login" replace />;
  return <Shell localMode={data.local_mode}>{children}</Shell>;
}

/** A local install has no accounts to sign in to — send those URLs home. */
function AuthRoute({ mode }: { mode: "login" | "register" }) {
  const { data, isLoading } = useMe();
  if (isLoading) return <div className="p-10 text-sm text-muted">Loading…</div>;
  if (data?.local_mode) return <Navigate to="/" replace />;
  return <AuthPage mode={mode} />;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<AuthRoute mode="login" />} />
          <Route path="/register" element={<AuthRoute mode="register" />} />
          <Route
            path="/"
            element={
              <Protected>
                <OverviewPage />
              </Protected>
            }
          />
          <Route
            path="/accounts"
            element={
              <Protected>
                <AccountsPage />
              </Protected>
            }
          />
          <Route
            path="/accounts/:accountId"
            element={
              <Protected>
                <AccountDetailPage />
              </Protected>
            }
          />
          <Route
            path="/investments/*"
            element={
              <Protected>
                <InvestmentsPage />
              </Protected>
            }
          />
          <Route
            path="/transactions"
            element={
              <Protected>
                <TransactionsPage />
              </Protected>
            }
          />
          <Route
            path="/recurring"
            element={
              <Protected>
                <RecurringPage />
              </Protected>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
