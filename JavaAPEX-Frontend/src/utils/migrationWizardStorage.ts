import type { MigrationResult } from "../services/api";

export interface PersistedWizardFormState {
  maxVisitedIndicatorStep: number;
  isPrivateRepo: boolean;
  patToken: string;
  currentPath: string;
  targetRepoName: string;
  targetRepoNamesByApproach?: {
    fork: string;
    branch: string;
    local: string;
  };
  targetRepoNameEditedByApproach?: {
    fork: boolean;
    branch: boolean;
    local: boolean;
  };
  targetRepoTimestamp: string;
  selectedSourceVersion: string;
  selectedTargetVersion: string;
  selectedConversions: string[];
  runTests: boolean;
  runSonar: boolean;
  runFossa: boolean;
  fixBusinessLogic: boolean;
  functionalTestToolMethod?: string;
  functionalTestExecutionMode?: string;
  migrationApproach: string;
  riskLevel: string;
  selectedFrameworks: string[];
  isJavaProject: boolean | null;
  pathHistory: string[];
  isHighRiskProject: boolean;
  highRiskConfirmed: boolean;
  suggestedJavaVersion: string;
  detectedFrameworks: { name: string; path: string; type: string }[];
  userSelectedVersion: string | null;
  sourceVersionStatus: "detected" | "not_selected" | "unknown";
  updateSourceVersion: boolean;
  analysisCompletedSeconds: number;
}

export const STEP_ROUTES: Record<number, string> = {
  1: "/",
  2: "/discovery",
  3: "/strategy",
  4: "/migration",
  5: "/migrating",
  6: "/progress",
  7: "/report",
};

export const WIZARD_REPO_URL_KEY = "migration_wizard_repo_url";
export const WIZARD_SELECTED_REPO_KEY = "migration_wizard_selected_repo";
export const WIZARD_REPO_ANALYSIS_KEY = "migration_wizard_repo_analysis";
export const WIZARD_FORM_STATE_KEY = "migration_wizard_form_state";
export const WIZARD_MIGRATION_JOB_KEY = "migration_wizard_migration_job";
const LEGACY_WIZARD_LOCAL_PROJECT_PATH_KEY = "migration_wizard_local_project_path";

export const WIZARD_STORAGE_KEYS = [
  WIZARD_REPO_URL_KEY,
  WIZARD_SELECTED_REPO_KEY,
  WIZARD_REPO_ANALYSIS_KEY,
  WIZARD_FORM_STATE_KEY,
  WIZARD_MIGRATION_JOB_KEY,
];

export const getStepFromPath = (pathname: string) => {
  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const entry = Object.entries(STEP_ROUTES).find(([, route]) => route === normalizedPath);
  return entry ? Number(entry[0]) : 1;
};

export const readPersistedValue = (key: string) => {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(key);
};

export const writeSessionValue = (key: string, value: string) => {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(key, value);
};

export const removeSessionValue = (key: string) => {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(key);
};

export const readSessionJson = <T,>(key: string): T | null => {
  if (typeof window === "undefined") return null;

  try {
    const raw = readPersistedValue(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
};

export const writeSessionJson = (key: string, value: unknown) => {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(key, JSON.stringify(value));
};

export const clearLegacyWizardStorage = () => {
  if (typeof window === "undefined") return;
  [...WIZARD_STORAGE_KEYS, LEGACY_WIZARD_LOCAL_PROJECT_PATH_KEY].forEach((key) =>
    window.localStorage.removeItem(key)
  );
};

export const clearWizardStorage = () => {
  if (typeof window === "undefined") return;
  [...WIZARD_STORAGE_KEYS, LEGACY_WIZARD_LOCAL_PROJECT_PATH_KEY].forEach((key) =>
    window.sessionStorage.removeItem(key)
  );
  clearLegacyWizardStorage();
};

export const buildPersistedMigrationJob = (job: MigrationResult): MigrationResult => ({
  ...job,
  dependencies: [],
  migration_log: [],
  file_diffs: [],
  issues: [],
  sonar_report: null,
  fossa_report: null,
  test_pipeline: null,
});