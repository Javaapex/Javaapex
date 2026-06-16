import React from "react";
import "./ResultPage.css";

export interface ResultPageProps {
  /** Step content rendered by MigrationWizard (animation, progress, or report) */
  children: React.ReactNode;
}

/**
 * Result Page – Steps 5 / 6 / 7
 *
 * Wraps the migration results experience:
 *   - Step 5: Migration animation (real-time progress visualisation)
 *   - Step 6: Migration progress (status polling)
 *   - Step 7: Final migration report (full results, downloads, SonarQube, FOSSA)
 */
const ResultPage: React.FC<ResultPageProps> = ({ children }) => (
  <section className="page-result" data-step="result">
    {children}
  </section>
);

export default ResultPage;
