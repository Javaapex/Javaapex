import React from "react";
import "./DiscoveryPage.css";

export interface DiscoveryPageProps {
  /** Step content rendered by MigrationWizard */
  children: React.ReactNode;
}

/**
 * Discovery Page – Step 2
 *
 * Wraps the repository discovery step where users explore the
 * project structure, review detected frameworks and dependencies,
 * and preview files before proceeding to strategy.
 */
const DiscoveryPage: React.FC<DiscoveryPageProps> = ({ children }) => (
  <section className="page-discovery" data-step="discovery">
    {children}
  </section>
);

export default DiscoveryPage;
