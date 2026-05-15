
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import React from 'react';
import MigrationWizard from './components/MigrationWizard';
import AppShell from './components/AppShell';
import AuthCallback from './components/AuthCallback';
import './App.css';

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 48, textAlign: "center", fontFamily: "Inter, system-ui, sans-serif" }}>
          <h2 style={{ color: "#dc2626", marginBottom: 8 }}>Something went wrong</h2>
          <p style={{ color: "#64748b", marginBottom: 20, fontSize: 14 }}>
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button
            onClick={() => {
              // Clear potentially corrupted session data
              try { window.sessionStorage.clear(); } catch (_) {}
              this.setState({ hasError: false, error: null });
              window.location.href = "/";
            }}
            style={{
              padding: "10px 28px", borderRadius: 10, border: "none",
              background: "#3b82f6", color: "#fff", fontWeight: 600,
              cursor: "pointer", fontSize: 14,
            }}
          >
            Restart Application
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route path="/*" element={<MigrationWizard />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
