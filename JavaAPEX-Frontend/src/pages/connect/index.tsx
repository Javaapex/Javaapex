import React from "react";
import "./ConnectPage.css";

export interface ConnectPageProps {
  /** Step content rendered by MigrationWizard */
  children: React.ReactNode;
}

/**
 * Connect Page – Step 1
 *
 * Wraps the repository connection step where users enter a GitHub URL
 * or upload a local Java project to begin migration analysis.
 */
const ConnectPage: React.FC<ConnectPageProps> = ({ children }) => (
  <section className="page-connect" data-step="connect">
    {children}
  </section>
);

export default ConnectPage;
