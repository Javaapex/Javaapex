import { useEffect } from "react";
import type { MigrationResult, RepoAnalysis, RepoInfo } from "../services/api";
import {
  buildPersistedMigrationJob,
  clearLegacyWizardStorage,
  type PersistedWizardFormState,
  removeSessionValue,
  WIZARD_FORM_STATE_KEY,
  WIZARD_MIGRATION_JOB_KEY,
  WIZARD_REPO_ANALYSIS_KEY,
  WIZARD_REPO_URL_KEY,
  WIZARD_SELECTED_REPO_KEY,
  writeSessionJson,
  writeSessionValue,
} from "../utils/migrationWizardStorage";

interface UseMigrationWizardPersistenceParams {
  repoUrl: string;
  selectedRepo: RepoInfo | null;
  repoAnalysis: RepoAnalysis | null;
  migrationJob: MigrationResult | null;
  formState: PersistedWizardFormState;
}

const persistSessionString = (key: string, value: string) => {
  if (value) {
    writeSessionValue(key, value);
    return;
  }

  removeSessionValue(key);
};

const persistSessionJson = (key: string, value: unknown) => {
  if (value) {
    writeSessionJson(key, value);
    return;
  }

  removeSessionValue(key);
};

export function useMigrationWizardPersistence({
  repoUrl,
  selectedRepo,
  repoAnalysis,
  migrationJob,
  formState,
}: UseMigrationWizardPersistenceParams) {
  useEffect(() => {
    // Remove legacy localStorage copies so new browser visits start clean.
    clearLegacyWizardStorage();
  }, []);

  useEffect(() => {
    persistSessionString(WIZARD_REPO_URL_KEY, repoUrl);
  }, [repoUrl]);

  useEffect(() => {
    persistSessionJson(WIZARD_SELECTED_REPO_KEY, selectedRepo);
  }, [selectedRepo]);

  useEffect(() => {
    persistSessionJson(WIZARD_REPO_ANALYSIS_KEY, repoAnalysis);
  }, [repoAnalysis]);

  useEffect(() => {
    persistSessionJson(
      WIZARD_MIGRATION_JOB_KEY,
      migrationJob ? buildPersistedMigrationJob(migrationJob) : null
    );
  }, [migrationJob]);

  useEffect(() => {
    writeSessionJson(WIZARD_FORM_STATE_KEY, formState);
  }, [formState]);
}
