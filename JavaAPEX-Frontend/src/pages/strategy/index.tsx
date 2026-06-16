import React from "react";
import "./StrategyPage.css";

export interface StrategyPageProps {
  /** Step content rendered by MigrationWizard */
  children: React.ReactNode;
}

/**
 * Strategy Page – Step 3
 *
 * Wraps the migration strategy step where users review the risk
 * assessment, choose the migration approach, select target Java
 * version, and configure conversion options.
 */
const StrategyPage: React.FC<StrategyPageProps> = ({ children }) => (
  <section className="page-strategy" data-step="strategy">
    {children}
  </section>
);

export default StrategyPage;
