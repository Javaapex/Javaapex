import React from "react";
import "./ModernizationPage.css";

export interface ModernizationPageProps {
  /** Step content rendered by MigrationWizard */
  children: React.ReactNode;
}

/**
 * Modernization Page – Step 4
 *
 * Wraps the migration configuration and execution step where users
 * review what will be modernized, configure target options, and
 * launch the migration process.
 */
const ModernizationPage: React.FC<ModernizationPageProps> = ({ children }) => (
  <section className="page-modernization" data-step="modernization">
    {children}
  </section>
);

export default ModernizationPage;
