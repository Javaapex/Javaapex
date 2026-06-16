import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import AuthCallback from "./pages/auth/AuthCallback";
import "./App.css";

const MigrationWizard = lazy(() => import("./components/MigrationWizard"));

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Suspense
          fallback={
            <div
              style={{
                minHeight: "60vh",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#475569",
                fontSize: 16,
                fontWeight: 600,
              }}
            >
              Loading migration workspace...
            </div>
          }
        >
          <Routes>
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="/*" element={<MigrationWizard />} />
          </Routes>
        </Suspense>
      </AppShell>
    </BrowserRouter>
  );
}
