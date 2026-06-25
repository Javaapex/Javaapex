import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
  FaArrowLeft,
  FaArrowRight,
  FaCheckCircle,
  FaCode,
  FaCogs,
  FaExclamationCircle,
  FaExclamationTriangle,
  FaFileAlt,
  FaFolderOpen,
  FaInfoCircle,
  FaJava,
  FaLeaf,
  FaLink,
  FaLock,
  FaProjectDiagram,
  FaRocket,
  FaSearch,
  FaShieldAlt,
  FaStopwatch,
  FaTimes,
  FaTools,
  FaUpload,
  FaVial,
} from "react-icons/fa";
import { useLocation, useNavigate } from "react-router-dom";
import "./MigrationWizard.css";
import {
  buildHtmlFilename,
  downloadHtmlDocument,
} from "../utils/migrationWizardPdf";
import {
  analyzeRepoUrl,
  analyzeLocalProject,
  getRepoVisibility,
  listRepoFiles,
  listLocalProjectFiles,
  getFileContent,
  getLocalProjectFileContent,
  getMicroserviceEligibility,
  getLocalProjectMicroserviceEligibility,
  getJavaVersions,
  getJavaVersionRecommendation,
  rerunMigrationTests,
  downloadUnitTestReport,
  generateGithubDocument,
  generateLocalProjectDocument,
    previewMigration,
    getMigrationDetail,
    getMigrationStatusSummary,
    getMigrationLogs,
    startMigration,
  getMigrationFossa,
  previewFunctionalTestScope,
  ApiError,
} from "../services/api";
import type {
  RepoAnalysis,
  RepoFile,
  FossaScanResult,
  MigrationJobSummary,
  MigrationResult,
  GithubDocumentResponse,
  PreviewFileDiff,
  JavaVersionRecommendationResponse,
  DependencyInfo,
  MicroserviceEligibilityResult,
  MicroserviceServiceCandidate,
  SonarReport,
  SonarIssueDetail,
  SonarHotspotDetail,
  StrategyPageContext,
  FunctionalTestScopePreview,
} from "../services/api";
import {
  clearWizardStorage,
  getStepFromPath,
  readSessionJson,
  type PersistedWizardFormState,
  STEP_ROUTES,
  WIZARD_FORM_STATE_KEY,
} from "../utils/migrationWizardStorage";
import { useMigrationWizardPersistence } from "../hooks/useMigrationWizardPersistence";
import { buildWizardAccentVars } from "./wizard/wizardUi";
import { useRepositoryConnect } from "../hooks/useRepositoryConnect";
import { useDiscoveryState } from "../hooks/useDiscoveryState";
import { useStrategyState, type MigrationApproachValue } from "../hooks/useStrategyState";
import { useMigrationExecution } from "../hooks/useMigrationExecution";
import { WizardInfoTooltip } from "./wizard/WizardInfoTooltip";
import { WizardOptionCard } from "./wizard/WizardOptionCard";
import { WizardSectionHeading } from "./wizard/WizardSectionHeading";
import { DiscoveryLoader } from "../pages/discovery/components/DiscoveryLoader";
import MicroserviceAssessment from "../pages/discovery/components/MicroserviceAssessment";
import StrategyChatWidget from "./StrategyChatWidget";
import FunctionalTestPanel, { type FunctionalToolView } from "./FunctionalTestPanel";
import ConnectPage from "../pages/connect";import DiscoveryPage from "../pages/discovery";
import StrategyPage from "../pages/strategy";
import ModernizationPage from "../pages/modernization";
import ResultPage from "../pages/result";

interface DiffLineEntry {
  type: "add" | "remove" | "context" | "hunk";
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
}

interface CodeChangeEntry {
  fileName: string;
  filePath: string;
  changeType: "modified" | "added" | "deleted";
  additions: number;
  deletions: number;
  oldContent: string;
  newContent: string;
  diffLines: DiffLineEntry[];
}

interface PrefetchedBrdDocument {
  filename: string;
  html: string;
}

const renderWizardIconBadge = (
  icon: React.ReactNode,
  accent: string,
  size: "sm" | "md" | "lg" | "xl" = "lg"
) => (
  <span
    className={`wizard-icon-badge wizard-icon-badge-${size}`}
    style={buildWizardAccentVars(accent)}
  >
    {icon}
  </span>
);

const renderBackButtonLabel = () => (
  <span className="wizard-button-content">
    <FaArrowLeft />
    <span>Back</span>
  </span>
);

const renderForwardButtonLabel = (label: string) => (
  <span className="wizard-button-content">
    <span>{label}</span>
    <FaArrowRight />
  </span>
);

const renderForwardLinkLabel = (label: string) => (
  <span className="wizard-link-content">
    <span>{label}</span>
    <FaArrowRight />
  </span>
);

const renderStatusChip = (
  icon: React.ReactNode,
  accent: string,
  label: string,
  value: string,
  tone: "warning" | "success"
) => (
  <div className={`wizard-status-chip is-${tone}`}>
    <span className="wizard-status-chip-label">
      {renderWizardIconBadge(icon, accent, "sm")}
      <span>{label}</span>
    </span>
    <span className="wizard-status-chip-value">{value}</span>
  </div>
);

type TestSummaryMetrics = {
  repo_total_files?: number;
  existing_test_files?: number;
  new_test_files?: number;
  existing_test_cases?: number;
  generated_test_cases?: number;
  total_test_cases?: number;
  java_migration_version?: string;
};

const mergeMigrationSummaryIntoJob = (
  previous: MigrationResult | null,
  summary: MigrationJobSummary
): MigrationResult => ({
  ...(previous ?? {
    dependencies: [],
    migration_log: [],
    issues: [],
    file_diffs: [],
    test_insights: [],
    target_repo: null,
    test_summary: null,
    test_llm_model: null,
    sonar_quality_gate: null,
    sonar_error_message: null,
    fossa_policy_status: null,
    fossa_total_dependencies: 0,
    fossa_license_issues: 0,
    fossa_vulnerabilities: 0,
    fossa_outdated_dependencies: 0,
    fossa_scan_mode: null,
    fossa_real_scan: false,
    fossa_analysis_url: null,
    fossa_error_message: null,
    error_message: null,
    started_at: summary.started_at,
    worker_started_at: summary.worker_started_at ?? null,
    completed_at: summary.completed_at,
    conversion_types: summary.conversion_types,
    source_repo: summary.source_repo,
    source_java_version: summary.source_java_version,
    target_java_version: summary.target_java_version,
    status: summary.status,
    progress_percent: summary.progress_percent,
    current_step: summary.current_step,
    files_modified: summary.files_modified,
    issues_fixed: summary.issues_fixed,
    api_endpoints_validated: summary.api_endpoints_validated,
    api_endpoints_working: summary.api_endpoints_working,
    sonar_bugs: summary.sonar_bugs,
    sonar_vulnerabilities: summary.sonar_vulnerabilities,
    sonar_code_smells: summary.sonar_code_smells,
    sonar_coverage: summary.sonar_coverage,
    tests_run: summary.tests_run,
    tests_passed: summary.tests_passed,
    tests_failed: summary.tests_failed,
    total_errors: summary.total_errors,
    total_warnings: summary.total_warnings,
    errors_fixed: summary.errors_fixed,
    warnings_fixed: summary.warnings_fixed,
    dependency_count: summary.dependency_count,
    job_id: summary.job_id,
  }),
  job_id: summary.job_id,
  status: summary.status,
  source_repo: summary.source_repo,
  target_repo: summary.target_repo,
  source_java_version: summary.source_java_version,
  target_java_version: summary.target_java_version,
  conversion_types: summary.conversion_types,
  started_at: summary.started_at,
  worker_started_at: summary.worker_started_at ?? previous?.worker_started_at ?? null,
  completed_at: summary.completed_at,
  progress_percent: summary.progress_percent,
  current_step: summary.current_step,
  files_modified: summary.files_modified,
  issues_fixed: summary.issues_fixed,
  api_endpoints_validated: summary.api_endpoints_validated,
  api_endpoints_working: summary.api_endpoints_working,
  tests_run: summary.tests_run,
  tests_passed: summary.tests_passed,
  tests_failed: summary.tests_failed,
  sonar_quality_gate: summary.sonar_quality_gate ?? null,
  sonar_bugs: summary.sonar_bugs,
  sonar_vulnerabilities: summary.sonar_vulnerabilities,
  sonar_code_smells: summary.sonar_code_smells,
  sonar_coverage: summary.sonar_coverage,
  sonar_duplications: summary.sonar_duplications,
  sonar_security_hotspots: summary.sonar_security_hotspots,
  sonar_scan_mode: summary.sonar_scan_mode ?? null,
  sonar_real_scan: summary.sonar_real_scan,
  sonar_analysis_url: summary.sonar_analysis_url ?? null,
  sonar_error_message: summary.sonar_error_message ?? null,
  fossa_policy_status: summary.fossa_policy_status ?? null,
  fossa_total_dependencies: summary.fossa_total_dependencies,
  fossa_license_issues: summary.fossa_license_issues,
  fossa_vulnerabilities: summary.fossa_vulnerabilities,
  fossa_outdated_dependencies: summary.fossa_outdated_dependencies,
  fossa_scan_mode: summary.fossa_scan_mode ?? null,
  fossa_real_scan: summary.fossa_real_scan,
  fossa_analysis_url: summary.fossa_analysis_url ?? null,
  fossa_error_message: summary.fossa_error_message ?? null,
  error_message: summary.error_message ?? null,
  total_errors: summary.total_errors,
  total_warnings: summary.total_warnings,
  errors_fixed: summary.errors_fixed,
  warnings_fixed: summary.warnings_fixed,
  dependency_count: summary.dependency_count,
});

const TERMINAL_MIGRATION_STATUSES = new Set(["completed", "failed", "cancelled"]);

const isTerminalMigrationStatus = (status: string | null | undefined): boolean =>
  Boolean(status && TERMINAL_MIGRATION_STATUSES.has(status.toLowerCase()));

const getMigrationPollingDelayMs = (status: string | null | undefined, startedAt?: string | null): number => {
  const normalizedStatus = (status || "").toLowerCase();
  const baseDelayMs =
    normalizedStatus === "queued" || normalizedStatus === "pending"
      ? 8000
      : normalizedStatus === "stale"
        ? 5000
      : normalizedStatus === "cancel_requested"
        ? 3000
        : 2000;

  const startedAtMs = startedAt ? Date.parse(startedAt) : Number.NaN;
  const elapsedMs = Number.isNaN(startedAtMs) ? 0 : Math.max(0, Date.now() - startedAtMs);
  const queueAwareDelayMs =
    (normalizedStatus === "queued" || normalizedStatus === "pending") && elapsedMs >= 60_000
      ? 15000
      : baseDelayMs;

  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    return Math.max(queueAwareDelayMs, 20000);
  }

  return queueAwareDelayMs;
};

type DependencyCategory =
  | "Framework"
  | "Testing"
  | "Logging"
  | "Persistence"
  | "Security"
  | "Build"
  | "Jakarta / Java EE"
  | "Data / JSON"
  | "Utilities"
  | "Other";

type DependencyRiskLevel = "critical" | "high" | "medium" | "low";
type DependencyRiskFilter = DependencyRiskLevel | "all";
type SonarFindingFilter = "all" | "bugs" | "vulnerabilities" | "code_smells" | "security_hotspots";
type CodeSmellSeverityFilter = "all" | "low" | "medium" | "high" | "blocker";

interface CategorizedDependency extends DependencyInfo {
  displayName: string;
  category: DependencyCategory;
  risk: DependencyRiskLevel;
  reason: string;
}

type MicroserviceAccordionKey =
  | "signals"
  | "scores"
  | "services"
  | "concerns"
  | "strategy"
  | "observations";

const REPORT_DIFFS_PAGE_SIZE = 25;
const SONAR_FINDINGS_PAGE_SIZE = 12;
const REPORT_DEPENDENCIES_PAGE_SIZE = 7;
const createDefaultMicroserviceAccordionState = (): Record<MicroserviceAccordionKey, boolean> => ({
  signals: true,
  scores: false,
  services: false,
  concerns: false,
  strategy: false,
  observations: false,
});

const getTestSummaryMetrics = (value: unknown): TestSummaryMetrics | null => {
  if (!value || typeof value !== "object") {
    return null;
  }

  return value as TestSummaryMetrics;
};

const normalizeAssessmentScore = (value: number) => {
  const normalizedScore = value <= 1 ? value * 100 : value;
  return Math.max(5, Math.min(95, Math.round(normalizedScore)));
};

const _getMicroserviceFitScore = (result?: MicroserviceEligibilityResult | null) => {
  if (!result) return 50;
  return normalizeAssessmentScore(typeof result.score === "number" ? result.score : 50);
};

const _getMicroserviceAssessmentLabel = (result?: MicroserviceEligibilityResult | null) => {
  return result?.eligibility || "NOT ELIGIBLE";
};

const _getAssessmentBarColor = (score: number) => {
  if (score >= 75) return "#22c55e";
  if (score >= 60) return "#f59e0b";
  return "#ef4444";
};

const _getMicroserviceScoreTooltip = (metricName: string) => {
  const explanations: Record<string, { title: string; description: string; interpretation: string }> = {
    "Domain separation": {
      title: "How clearly the application is split into business areas",
      description: "This checks whether the code already looks organized into meaningful functional areas such as users, payments, or reporting.",
      interpretation: "Higher is better. A higher score means the system may be easier to split with clear ownership.",
    },
    Coupling: {
      title: "How tightly different parts of the application depend on each other",
      description: "This measures whether modules are tangled together through shared logic, direct calls, or circular dependencies.",
      interpretation: "Higher is better. A higher score means the modules are more independent and easier to separate.",
    },
    "DB independence": {
      title: "How independently each area can manage its own data",
      description: "This checks whether modules can work with their own data boundaries instead of relying heavily on the same shared tables or queries.",
      interpretation: "Higher is better. A higher score means the system is less tied to one shared data model.",
    },
    Scalability: {
      title: "How easily parts of the system could scale on their own",
      description: "This looks for signs that certain workloads could grow independently, such as heavy processing, scheduled jobs, or traffic spikes.",
      interpretation: "Higher is better. A higher score means there are stronger signs that some areas could scale separately.",
    },
    "Deployment independence": {
      title: "How easily parts of the system could be released separately",
      description: "This checks whether modules appear self-contained enough that they could eventually be deployed without moving the whole application together.",
      interpretation: "Higher is better. A higher score means teams may be able to release parts of the system more independently.",
    },
    "Failure isolation": {
      title: "How well problems in one area stay contained",
      description: "This measures whether an issue in one module is likely to remain local instead of spreading across many parts of the application.",
      interpretation: "Higher is better. A higher score means failures may be easier to isolate and control.",
    },
    "Async/event readiness": {
      title: "How prepared the system is for event-driven communication",
      description: "This looks for messaging, background jobs, scheduling, or asynchronous processing patterns that support decoupled communication.",
      interpretation: "Higher is better. A higher score means the application shows more readiness for async or event-based architecture.",
    },
  };

  return (
    explanations[metricName] || {
      title: "How supportive this area is for microservice adoption",
      description: "This score reflects whether this part of the codebase helps or hinders splitting the application into clearer, more independent services.",
      interpretation: "Higher is better. A higher score means this area creates fewer obstacles for service separation.",
    }
  );
};

const _getMicroserviceServiceTagTooltip = (
  tag: string,
  candidate: MicroserviceServiceCandidate
) => {
  const normalizedTag = tag.trim().toLowerCase();
  const integrationPreview = (candidate.external_integrations || []).slice(0, 2).join(", ");

  if (normalizedTag.includes("cpu-intensive")) {
    return {
      title: "CPU-intensive work",
      description:
        "This candidate appears to spend more effort on computation, business rules, transformations, or in-memory processing than on waiting for outside systems.",
      interpretation:
        "Why it is shown: the analyzer found scaling signals suggesting this area may need extra compute capacity when load grows.",
    };
  }

  if (normalizedTag.includes("io-intensive")) {
    return {
      title: "I/O-intensive work",
      description:
        "This candidate appears to spend more time waiting on databases, APIs, files, or network calls than on raw computation.",
      interpretation: integrationPreview
        ? `Why it is shown: the analyzer found access or integration patterns such as ${integrationPreview}, which often benefit from targeted scaling and isolation.`
        : "Why it is shown: the analyzer found access or communication patterns that often benefit from independent scaling and failure isolation.",
    };
  }

  if (
    normalizedTag.includes("rest") ||
    normalizedTag.includes("client") ||
    normalizedTag.includes("api") ||
    normalizedTag.includes("queue") ||
    normalizedTag.includes("event") ||
    normalizedTag.includes("messag")
  ) {
    return {
      title: `External integration: ${tag}`,
      description:
        "This tag indicates the candidate talks to another system or communication layer, such as an API, client, queue, or messaging channel.",
      interpretation:
        "Why it is shown: external integrations are useful service-boundary signals because they affect latency, retries, and failure isolation.",
    };
  }

  return {
    title: tag,
    description:
      "This tag is a workload or integration hint the analyzer found while reviewing the candidate's code structure and dependencies.",
    interpretation:
      "Why it is shown: the analyzer believes this characteristic matters when deciding whether the candidate could become its own service.",
  };
};

const MIGRATION_STEPS = [
  {
    id: 1,
    name: "Connect",
    icon: <FaLink />,
    accent: "#2563eb",
    description: "Connect to GitHub Repository",
    summary: "Enter your GitHub repository URL to start the migration process"
  },
  {
    id: 2,
    name: "Discovery",
    icon: <FaSearch />,
    accent: "#0ea5e9",
    description: "Repository Discovery & Dependencies",
    summary: "Explore repository structure and analyze project dependencies"
  },
  {
    id: 3,
    name: "Strategy",
    icon: <FaProjectDiagram />,
    accent: "#f97316",
    description: "Assessment & Migration Strategy",
    summary: "Review assessment results and define the migration roadmap"
  },
  {
    id: 4,
    name: "Migration",
    icon: <FaRocket />,
    accent: "#f59e0b",
    description: "Build Modernization & Migration",
    summary: "Execute the upgrade using automation tools and refactor legacy components"
  },
  {
    id: 5,
    name: "Result",
    icon: <FaCheckCircle />,
    accent: "#22c55e",
    description: "Migration Results",
    summary: "View migration report and download migrated project"
  },
];

const DEFAULT_TARGET_GITHUB_OWNER = "Javaapex";
const DEFAULT_TARGET_GITHUB_HOST = "github.com";

const getIndicatorStep = (step: number) => Math.min(step, MIGRATION_STEPS.length);

const LLM_PROVIDERS = [
  { value: "huggingface", label: "Hugging Face (Free)" },
  { value: "claude", label: "Claude (Paid)" },
  { value: "groq", label: "Groq" },
  { value: "ollama", label: "Ollama (Local)" },
  { value: "gpt-4", label: "OpenAI (GPT-4)" },
  { value: "offline", label: "Offline (Template)" },
  { value: "deepseek", label: "DeepSeek" },
];
const getJavaVersionRecommendationProviderLabel = (providerUsed?: string | null) => {
  const normalized = String(providerUsed || "").trim().toLowerCase();
  if (normalized === "openai") return "ChatGPT Recommendations";
  if (normalized === "heuristic") return "Smart Recommendations";
  return "Java Upgrade Recommendations";
};

const getJavaVersionRecommendationLoadingLabel = (providerUsed?: string | null) => {
  const normalized = String(providerUsed || "").trim().toLowerCase();
  if (normalized === "openai") return "Fetching recommended target Java version from ChatGPT...";
  return "Fetching recommended target Java version...";
};

let jsPdfModulePromise: Promise<typeof import("jspdf")["jsPDF"]> | null = null;
let zipSyncModulePromise: Promise<typeof import("fflate")["zipSync"]> | null = null;

const loadJsPdf = async () => {
  if (!jsPdfModulePromise) {
    jsPdfModulePromise = import("jspdf").then((module) => module.jsPDF);
  }

  return jsPdfModulePromise;
};

const loadZipSync = async () => {
  if (!zipSyncModulePromise) {
    zipSyncModulePromise = import("fflate").then((module) => module.zipSync);
  }

  return zipSyncModulePromise;
};

// const MigrationCodeChangesSection = React.lazy(async () => {
//   const module = await import("./MigrationCodeChangesPanel");
//   return { default: module.MigrationCodeChangesSection };
// });

const MigrationFossaSection = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationFossaSection };
});

const MigrationIssuesSection = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationIssuesSection };
});

const MigrationJmeterSection = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationJmeterSection };
});

const MigrationLogSection = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationLogSection };
});

const MigrationReportActions = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationReportActions };
});

const MigrationSonarSection = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationSonarSection };
});

const MigrationUnitTestSection = React.lazy(async () => {
  const module = await import("../pages/result/components/MigrationReportSections");
  return { default: module.MigrationUnitTestSection };
});

const DiscoveryFileExplorer = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryFileExplorer };
});

const DiscoveryFrameworkSection = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryFrameworkSection };
});

const DiscoveryHighRiskWarning = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryHighRiskWarning };
});

const DiscoveryNoFrameworkAlert = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryNoFrameworkAlert };
});

const DiscoveryNotJavaAlert = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryNotJavaAlert };
});

const DiscoveryProjectStructureSummary = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryProjectStructureSummary };
});

const DiscoveryTechnicalSpecificationCard = React.lazy(async () => {
  const module = await import("../pages/discovery/components/MigrationDiscoverySections");
  return { default: module.DiscoveryTechnicalSpecificationCard };
});

export default function MigrationWizard() {
  const navigate = useNavigate();
  const location = useLocation();
  const persistedFormState =
    readSessionJson<PersistedWizardFormState>(WIZARD_FORM_STATE_KEY);
  const initialStep =
    typeof window !== "undefined" ? getStepFromPath(window.location.pathname) : 1;
  const generateRepoTimestamp = () => {
    const now = new Date();
    const pad = (value: number) => value.toString().padStart(2, "0");

    return [
      now.getFullYear(),
      pad(now.getMonth() + 1),
      pad(now.getDate()),
      pad(now.getHours()),
      pad(now.getMinutes()),
      pad(now.getSeconds()),
    ].join("");
  };

  const buildTargetRepoUrl = (
    repoName: string,
    timestamp: string,
    owner: string = "owner",
    host: string = "github.com"
  ) => `https://${host}/${owner}/${repoName || "repo"}-Migrated${timestamp}`;

  const buildTargetBranchName = (repoName: string, timestamp: string) =>
    `migration/${repoName || "repo"}-Migrated${timestamp}`;

  const buildLocalTargetFolderName = (repoName: string) =>
    `${repoName || "repo"}-Migrated`;

  const getRepositoryLink = (repoValue: string | null) => {
    if (!repoValue) return null;
    if (repoValue.startsWith("local://")) return null;
    return repoValue.startsWith("http") ? repoValue : `https://github.com/${repoValue}`;
  };

  const isLocalRepoRef = (value: string | null | undefined) => Boolean(value && value.startsWith("local://"));
  const buildLocalRepoRef = (value: string) => `local://${value.trim()}`;
  const extractLocalRepoPath = (value: string) => value.replace(/^local:\/\//, "");
  const getPathBasename = (value: string) => {
    const normalized = value.replace(/[\\/]+$/, "");
    const parts = normalized.split(/[\\/]/).filter(Boolean);
    return parts[parts.length - 1] || "local-project";
  };

  const parseRepositoryContext = (value: string | null | undefined) => {
    if (!value || value.startsWith("local://")) return null;

    const normalized = value.trim().replace(/\.git$/, "").replace(/\/+$/, "");
    if (/^[^/\s]+\/[^/\s]+$/.test(normalized)) {
      const [owner, repo] = normalized.split("/");
      return { platform: "github", host: "github.com", owner, repo };
    }

    try {
      const parsed = new URL(normalized);
      const pathParts = parsed.pathname.split("/").filter(Boolean);
      if (pathParts.length < 2) return null;

      const platform = parsed.hostname.includes("gitlab") ? "gitlab" : "github";
      return {
        platform,
        host: parsed.host,
        owner: pathParts[0],
        repo: pathParts[1],
      };
    } catch {
      return null;
    }
  };

  const [step, setStep] = useState(() => initialStep);
  const [maxVisitedIndicatorStep, setMaxVisitedIndicatorStep] = useState(
    Math.max(persistedFormState?.maxVisitedIndicatorStep ?? 1, getIndicatorStep(initialStep))
  );
  const [error, setError] = useState<string>("");
  const {
    repoAnalysis,
    setRepoAnalysis,
    repoFiles,
    setRepoFiles,
    currentPath,
    setCurrentPath,
    analysisLoading,
    setAnalysisLoading,
    analysisElapsedSeconds,
    setAnalysisElapsedSeconds,
    microserviceResult,
    setMicroserviceResult,
    microserviceLoading,
    setMicroserviceLoading,
    microserviceAccordionState,
    setMicroserviceAccordionState,
    isMicroserviceEligibilityCollapsed: _isMicroserviceEligibilityCollapsed,
    setIsMicroserviceEligibilityCollapsed,
    showAllMicroserviceServices: _showAllMicroserviceServices,
    setShowAllMicroserviceServices,
    activeScoreTooltip: _activeScoreTooltip,
    setActiveScoreTooltip,
    activeServiceTagTooltip: _activeServiceTagTooltip,
    setActiveServiceTagTooltip: _setActiveServiceTagTooltip,
    microserviceExpandedSections,
    setMicroserviceExpandedSections,
    analysisStartedAtMs,
    setAnalysisStartedAtMs,
    analysisCompletedSeconds,
    setAnalysisCompletedSeconds,
    riskLevel,
    setRiskLevel,
    selectedFrameworks,
    setSelectedFrameworks,
    isJavaProject,
    setIsJavaProject,
    selectedFile,
    setSelectedFile,
    fileContent,
    setFileContent,
    editedContent,
    setEditedContent,
    isEditing,
    setIsEditing,
    fileLoading,
    setFileLoading,
    pathHistory,
    setPathHistory,
    showFileExplorer,
    setShowFileExplorer,
    isHighRiskProject,
    setIsHighRiskProject,
    highRiskConfirmed,
    setHighRiskConfirmed,
    suggestedJavaVersion,
    setSuggestedJavaVersion,
    detectedFrameworks,
    setDetectedFrameworks,
    viewingFrameworkFile,
    setViewingFrameworkFile,
    frameworkFileLoading,
    setFrameworkFileLoading,
    repoPreviewInitialized,
    setRepoPreviewInitialized,
    microserviceAssessmentResolved,
    setMicroserviceAssessmentResolved,
  } = useDiscoveryState(persistedFormState, createDefaultMicroserviceAccordionState);
  const [conversionDecision, setConversionDecision] = useState<"yes" | "no" | null>(null);
  const [showFolderStructure, setShowFolderStructure] = useState(false);
  const {
    targetRepoNamesByApproach,
    setTargetRepoNamesByApproach,
    targetRepoNameEditedByApproach,
    setTargetRepoNameEditedByApproach,
    targetRepoTimestamp,
    setTargetRepoTimestamp,
    targetVersions,
    setTargetVersions,
    selectedSourceVersion,
    setSelectedSourceVersion,
    selectedTargetVersion,
    setSelectedTargetVersion,
    selectedConversions,
    setSelectedConversions,
    runTests,
    setRunTests,
    useLLMTests,
    setUseLLMTests,
    selectedLLMProvider,
    setSelectedLLMProvider,
    runSonar,
    setRunSonar,
    runFossa,
    setRunFossa,
    fixBusinessLogic,
    setFixBusinessLogic: _setFixBusinessLogic,
    targetVersionRequiredError,
    setTargetVersionRequiredError,
    targetRepoNameError,
    setTargetRepoNameError,
    migrationApproach,
    setMigrationApproach,
    userSelectedVersion,
    setUserSelectedVersion,
    sourceVersionStatus,
    setSourceVersionStatus,
    updateSourceVersion,
    githubUserLogin,
    setGithubUserLogin,
  } = useStrategyState(persistedFormState, generateRepoTimestamp);

  const {
    loading,
    setLoading,
    migrationTimerNow,
    setMigrationTimerNow,
    migrationJob,
    setMigrationJob,
    migrationDetailLoadedJobId,
    setMigrationDetailLoadedJobId,
    migrationLogs,
    setMigrationLogs,
    fossaResult,
    setFossaResult,
    fossaLoading,
    setFossaLoading,
    rerunTestsLoading,
    setRerunTestsLoading,
    migrationPreview,
    setMigrationPreview,
    codeChanges,
    setCodeChanges,
    selectedDiffFile,
    setSelectedDiffFile,
    showCodeChanges: _showCodeChanges,
    setShowCodeChanges,
    visibleReportDiffCount,
    setVisibleReportDiffCount,
    reportDependencyPage,
    setReportDependencyPage,
    reportAccordionState,
    setReportAccordionState,
    documentGenerationLoading,
    setDocumentGenerationLoading,
    documentPrefetchStatus,
    setDocumentPrefetchStatus,
    prefetchedBrdDocument,
    setPrefetchedBrdDocument,
    animationProgress,
    setAnimationProgress,
  } = useMigrationExecution();
  const {
    repoUrl,
    setRepoUrl,
    selectedRepo,
    setSelectedRepo,
    githubToken,
    setGithubToken,
    isPrivateRepo,
    setIsPrivateRepo,
    patToken,
    setPatToken,
    repoAccessCheckLoading,
    setRepoAccessCheckLoading,
    accessTokenValidationState,
    setAccessTokenValidationState,
    accessTokenValidationMessage,
    setAccessTokenValidationMessage,
    localProjectCapabilities,
    localProjectCapabilitiesLoading,
    localProjectUploadFiles,
    localProjectUploadLoading,
    localProjectUploadCompressing,
    localProjectUploadError,
    localProjectUploadWarning,
    urlValidation,
    showEnterpriseToken,
    activeAccessToken,
    repositoryNeedsAuthentication,
    currentToken,
    shouldShowPatInput,
    resetAccessTokenValidationState,
    handleRepositoryContinue,
    handleLocalProjectFilesChange,
    handleLocalProjectUpload,
  } = useRepositoryConnect({
    persistedIsPrivateRepo: persistedFormState?.isPrivateRepo,
    persistedPatToken: persistedFormState?.patToken,
    setRepoAnalysis,
    setRepoFiles,
    setStep,
    setError,
    resetRepositorySelectionState,
    setTargetRepoNamesByApproach,
    setTargetRepoNameEditedByApproach,
    setTargetRepoNameError,
    buildLocalRepoRef,
    getPathBasename,
    isLocalRepoRef,
    loadZipSync,
  });
  const currentMigrationApproach =
    migrationApproach === "branch"
      ? "branch"
      : migrationApproach === "local"
        ? "local"
        : "fork";
  const targetRepoName = targetRepoNamesByApproach[currentMigrationApproach] ?? "";
  const browserWindow = window as Window & typeof globalThis & {
    folderInputRef?: HTMLInputElement | null;
    zipInputRef?: HTMLInputElement | null;
  };
  const sourceRepositoryContext = parseRepositoryContext(selectedRepo?.url || repoUrl);
  const targetRepositoryHost =
    currentMigrationApproach === "fork"
      ? DEFAULT_TARGET_GITHUB_HOST
      : sourceRepositoryContext?.host || DEFAULT_TARGET_GITHUB_HOST;
  const targetRepositoryOwner =
    currentMigrationApproach === "fork"
      ? DEFAULT_TARGET_GITHUB_OWNER
      : sourceRepositoryContext?.platform === "github" && githubUserLogin
        ? githubUserLogin
        : sourceRepositoryContext?.owner || githubUserLogin || "owner";
  const sourceRepositoryName =
    selectedRepo?.name || sourceRepositoryContext?.repo || repoUrl.split("/").pop()?.replace(".git", "") || "repo";

  const getAutoGeneratedTargetName = useCallback(
    (approach: MigrationApproachValue, repoName: string = sourceRepositoryName) =>
      approach === "branch"
        ? buildTargetBranchName(repoName, targetRepoTimestamp)
        : approach === "local"
          ? buildLocalTargetFolderName(repoName)
          : buildTargetRepoUrl(repoName, targetRepoTimestamp, targetRepositoryOwner, targetRepositoryHost),
    [sourceRepositoryName, targetRepoTimestamp, targetRepositoryOwner, targetRepositoryHost]
  );

  const setTargetRepoNameForApproach = (
    approach: MigrationApproachValue,
    value: string,
    edited: boolean
  ) => {
    setTargetRepoNamesByApproach((prev) => ({ ...prev, [approach]: value }));
    setTargetRepoNameEditedByApproach((prev) => ({ ...prev, [approach]: edited }));
  };

  const handleTargetRepoNameChange = (value: string) => {
    setTargetRepoNameError("");
    setTargetRepoNameForApproach(currentMigrationApproach, value, true);
  };
  const [versionRecommendation, setVersionRecommendation] = useState<JavaVersionRecommendationResponse | null>(null);
  const [versionRecommendationLoading, setVersionRecommendationLoading] = useState(false);
  const [versionRecommendationError, setVersionRecommendationError] = useState("");
  const [dependencyRiskFilter, setDependencyRiskFilter] = useState<DependencyRiskFilter>("all");
  const [sonarFindingFilter, setSonarFindingFilter] = useState<SonarFindingFilter>("all");
  const [codeSmellSeverityFilter, setCodeSmellSeverityFilter] = useState<CodeSmellSeverityFilter>("all");

  // Functional test tool selection for Strategy page (MULTI-select).
  // An empty array means "auto" (use the analyzer's recommended/active set).
  // Seeds from the new persisted key, falling back to the legacy single-string
  // key so in-flight wizard sessions keep their previous selection.
  const [functionalTestToolMethods, setFunctionalTestToolMethods] = useState<string[]>(
    () => {
      const multi = persistedFormState?.functionalTestToolMethods;
      if (Array.isArray(multi) && multi.length > 0) return multi;
      const legacy = persistedFormState?.functionalTestToolMethod;
      return legacy && legacy !== "auto" ? [legacy] : [];
    }
  );

  // Toggle a tool in/out of the multi-select set.
  const toggleFunctionalTestTool = useCallback((id: string) => {
    setFunctionalTestToolMethods((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]
    );
  }, []);

  // Functional test execution mode: "auto" | "external" | "internal"
  const [functionalTestExecutionMode, setFunctionalTestExecutionMode] = useState<string>(
    persistedFormState?.functionalTestExecutionMode ?? "auto"
  );

  const functionalTestingTools = useMemo(() => {
    const endpointCount = repoAnalysis?.api_endpoints?.length ?? 0;
    const hasRest = endpointCount > 0;
    const javaFileCount = repoAnalysis?.java_files?.length ?? 0;
    const depCount = repoAnalysis?.dependencies?.length ?? 0;
    const _hasTests = repoAnalysis?.has_tests ?? false;
    const hasSrcMain = repoAnalysis?.structure?.has_src_main ?? false;
    const hasSrcTest = repoAnalysis?.structure?.has_src_test ?? false;
    const hasBuildTool = Boolean(repoAnalysis?.build_tool) || repoAnalysis?.structure?.has_pom_xml || repoAnalysis?.structure?.has_build_gradle;

    const deps = repoAnalysis?.dependencies ?? [];
    const depArtifacts = deps.map(d => (d.artifact_id || "").toLowerCase());

    const hasSpringBoot = depArtifacts.some(a =>
      a.includes("spring-boot-starter-web") || a.includes("spring-webmvc") || a.includes("spring-boot-starter")
    );
    const hasSpringMvc = depArtifacts.some(a =>
      a.includes("spring-webmvc") || a.includes("spring-boot-starter-web") || a.includes("spring-mvc")
    );
    const hasSpringTest = depArtifacts.some(a =>
      a.includes("spring-boot-starter-test") || a.includes("spring-test")
    );
    const hasThymeleaf = depArtifacts.some(a => a.includes("thymeleaf"));
    const hasJsp = depArtifacts.some(a => a.includes("jsp") || a.includes("jstl") || a.includes("servlet"));

    const allFiles: string[] = ((repoAnalysis as any)?.all_files ?? []).map((f: any) =>
      (typeof f === "string" ? f : (f?.path || "")).toLowerCase()
    );

    const hasStaticAssets = allFiles.some(p =>
      p.includes("/static/") || p.includes("/public/") || p.includes("/resources/templates/") || p.includes("/webapp/")
    );
    const hasWebXml = allFiles.some(p => p.endsWith("web.xml"));
    const hasJspFiles = allFiles.some(p => p.endsWith(".jsp") || p.endsWith(".jspx"));
    const hasHtmlTemplates = allFiles.some(p => p.endsWith(".html") && (p.includes("/templates/") || p.includes("/webapp/")));
    const hasUI = hasStaticAssets || hasThymeleaf || hasJspFiles || hasHtmlTemplates || hasWebXml;

    const hasOpenApiFile = allFiles.some(p =>
      p.includes("openapi") || p.includes("swagger") || p.endsWith("api-docs.json") || p.endsWith("api-docs.yaml")
    );
    const hasSpringDoc = depArtifacts.some(a => a.includes("springdoc") || a.includes("springfox") || a.includes("swagger"));
    const _hasOpenApi = hasOpenApiFile || hasSpringDoc;

    // ── Playwright confidence ──
    let playwrightConf = 5;
    if (hasUI) {
      playwrightConf = 72;
      if (hasThymeleaf || hasHtmlTemplates) playwrightConf += 10;
      if (hasStaticAssets) playwrightConf += 6;
      if (hasJspFiles) playwrightConf += 4;
    } else if (hasSrcMain && hasJsp) {
      playwrightConf = 38;
    } else if (hasSrcMain) {
      playwrightConf = 12;
    }
    playwrightConf = Math.min(playwrightConf, 97);

    const playwrightTag = playwrightConf >= 70 ? "Highly Recommended"
      : playwrightConf >= 35 ? "Potential Fit"
      : "Not Detected";
    const playwrightReason = playwrightConf >= 70
      ? `Highly Recommended: Detected ${[hasThymeleaf && "Thymeleaf templates", hasJspFiles && "JSP pages", hasHtmlTemplates && "HTML templates", hasStaticAssets && "static assets"].filter(Boolean).join(", ") || "UI assets"} in project.`
      : playwrightConf >= 35
        ? "Potential Fit: Some web resources found but no strong UI framework detected."
        : "Not Detected: No web UI assets or templating engine found in this project.";

    // ── Rest Assured confidence ──
    let restAssuredConf = 5;
    if (hasRest) {
      restAssuredConf = 78;
      if (endpointCount >= 5) restAssuredConf += 8;
      if (endpointCount >= 10) restAssuredConf += 6;
      if (hasSpringBoot) restAssuredConf += 3;
    } else if (hasSpringBoot) {
      restAssuredConf = 52;
      if (hasSrcMain && javaFileCount > 10) restAssuredConf += 8;
    } else if (hasBuildTool && javaFileCount > 5) {
      restAssuredConf = 28;
    }
    restAssuredConf = Math.min(restAssuredConf, 97);

    const restAssuredTag = restAssuredConf >= 70 ? "Highly Recommended"
      : restAssuredConf >= 40 ? "Potential Fit"
      : "Low Match";
    const restAssuredReason = restAssuredConf >= 70
      ? `Highly Recommended: Found ${endpointCount} REST endpoint${endpointCount !== 1 ? "s" : ""} across project controllers.`
      : restAssuredConf >= 40
        ? "Potential Fit: Spring web dependencies detected but explicit endpoints not fully mapped."
        : "Low Match: No REST controllers or Spring web dependencies detected.";

    // ── Selenium confidence ──
    let seleniumConf = 3;
    if (hasUI) {
      seleniumConf = 32;
      if (hasJspFiles || hasWebXml) seleniumConf += 12;
      if (!hasThymeleaf && !hasHtmlTemplates) seleniumConf += 6;
    } else if (hasJsp) {
      seleniumConf = 22;
    }
    seleniumConf = Math.min(seleniumConf, 55);

    const seleniumReason = seleniumConf >= 30
      ? "Legacy UI detected — Selenium can test it, but Playwright is preferred for modern stacks."
      : "Not Recommended: No significant UI layer detected for browser-based testing.";

    // ── MockMvc confidence ──
    let mockMvcConf = 3;
    if (hasSpringMvc && hasSpringTest) {
      mockMvcConf = 82;
      if (hasRest) mockMvcConf += 6;
      if (hasSrcTest) mockMvcConf += 5;
    } else if (hasSpringMvc || hasSpringBoot) {
      mockMvcConf = 58;
      if (hasRest) mockMvcConf += 8;
      if (hasSrcTest) mockMvcConf += 5;
    } else if (hasBuildTool && depCount > 3) {
      mockMvcConf = 14;
    }
    mockMvcConf = Math.min(mockMvcConf, 97);

    const mockMvcTag = mockMvcConf >= 70 ? "Highly Recommended"
      : mockMvcConf >= 40 ? "Integration Ready"
      : "Low Match";
    const mockMvcReason = mockMvcConf >= 70
      ? "Highly Recommended: Spring MVC and spring-test detected — MockMvc is ideal for controller-level testing."
      : mockMvcConf >= 40
        ? "Integration Ready: Spring Boot detected — MockMvc can test web layer in isolation."
        : "Low Match: Project does not appear to use Spring MVC.";

    // ── Schemathesis confidence ──
    let schemathesisConf = 3;
    if (hasOpenApiFile) {
      schemathesisConf = 88;
      if (hasRest) schemathesisConf += 6;
    } else if (hasSpringDoc) {
      schemathesisConf = 68;
      if (hasRest) schemathesisConf += 8;
    } else if (hasRest) {
      schemathesisConf = 28;
    }
    schemathesisConf = Math.min(schemathesisConf, 97);

    const schemathesisTag = schemathesisConf >= 70 ? "Highly Recommended"
      : schemathesisConf >= 40 ? "Spec Available"
      : hasRest ? "Spec Not Found" : "Not Applicable";
    const schemathesisReason = schemathesisConf >= 70
      ? "Highly Recommended: OpenAPI/Swagger specification found in the repository."
      : schemathesisConf >= 40
        ? "Spec Available: Springdoc/Springfox dependency detected — API spec likely auto-generated at runtime."
        : hasRest
          ? "Spec Not Found: REST endpoints exist but no OpenAPI specification file detected."
          : "Not Applicable: No REST API layer or OpenAPI specification detected.";

    // ── Active (enabled) state per tool, derived from repo detection ──
    // Rules:
    //  • No UI layer  → Playwright is inactive; every other (API/backend) tool is active.
    //  • Has UI + the repo already ships unit tests → only Playwright (UI) + Rest Assured (API) are active.
    //  • Has UI + no unit tests → all tools are active.
    const toolActive = (id: string): boolean => {
      if (!hasUI) return id !== "PLAYWRIGHT";
      if (_hasTests) return id === "PLAYWRIGHT" || id === "REST_ASSURED";
      return true;
    };

    return [
      {
        id: "PLAYWRIGHT",
        name: "Playwright (UI)",
        description: "Modern web testing for fast, reliable end-to-end tests across browsers.",
        confidence: playwrightConf,
        reason: playwrightReason,
        color: "#22c55e",
        tag: playwrightTag,
        active: toolActive("PLAYWRIGHT"),
      },
      {
        id: "REST_ASSURED",
        name: "Rest Assured (API)",
        description: "Strong for API testing, but doesn't cover UI interactions.",
        confidence: restAssuredConf,
        reason: restAssuredReason,
        color: "#f59e0b",
        tag: restAssuredTag,
        active: toolActive("REST_ASSURED"),
      },
      {
        id: "SELENIUM",
        name: "Selenium (Legacy UI)",
        description: "Widely used but may require significant configuration for your specific stack.",
        confidence: seleniumConf,
        reason: seleniumReason,
        color: "#ef4444",
        tag: "Legacy Support",
        active: toolActive("SELENIUM"),
      },
      {
        id: "MOCK_MVC",
        name: "MockMvc (Spring MVC)",
        description: "Ideal for testing Spring MVC applications in isolation.",
        confidence: mockMvcConf,
        reason: mockMvcReason,
        color: "#3b82f6",
        tag: mockMvcTag,
        active: toolActive("MOCK_MVC"),
      },
      {
        id: "SCHEMATHESIS",
        name: "Schemathesis (OpenAPI Contract)",
        description: "Property-based testing based on your OpenAPI/Swagger definitions.",
        confidence: schemathesisConf,
        reason: schemathesisReason,
        color: "#ec4899",
        tag: schemathesisTag,
        active: toolActive("SCHEMATHESIS"),
      },
    ];
  }, [repoAnalysis]);

  const _recommendedTool = useMemo(() => {
    if (!functionalTestingTools || functionalTestingTools.length === 0) return "REST_ASSURED";
    
    // Find the tool with the highest confidence score
    const bestTool = [...functionalTestingTools].sort((a, b) => b.confidence - a.confidence)[0];
    return bestTool?.id || "REST_ASSURED";
  }, [functionalTestingTools]);

  const renderConfidenceCircle = (percentage: number, color: string) => {
    const radius = 36;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (percentage / 100) * circumference;
    const percentColor = percentage >= 80 ? "#16a34a" : percentage >= 60 ? "#2563eb" : percentage >= 40 ? "#d97706" : "#dc2626";

    return (
      <div style={{ position: "relative", width: 90, height: 90, margin: "0 auto" }}>
        <svg width="90" height="90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r={radius}
            fill="transparent"
            stroke="#f1f5f9"
            strokeWidth="8"
          />
          <circle
            cx="50"
            cy="50"
            r={radius}
            fill="transparent"
            stroke={color}
            strokeWidth="8"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 50 50)"
            style={{ transition: "stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1), stroke 0.4s ease" }}
          />
        </svg>
        <div style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          textAlign: "center"
        }}>
          <div style={{ fontWeight: 800, fontSize: 16, color: percentColor, transition: "color 0.3s ease" }}>{percentage}%</div>
          <div style={{ fontSize: 9, color: "#64748b", fontWeight: 600, marginTop: -2 }}>Confidence</div>
        </div>
      </div>
    );
  };
  const [visibleSonarFindingCounts, setVisibleSonarFindingCounts] = useState<Record<Exclude<SonarFindingFilter, "all">, number>>({
    bugs: SONAR_FINDINGS_PAGE_SIZE,
    vulnerabilities: SONAR_FINDINGS_PAGE_SIZE,
    code_smells: SONAR_FINDINGS_PAGE_SIZE,
    security_hotspots: SONAR_FINDINGS_PAGE_SIZE,
  });
  const currentIndicatorStep = getIndicatorStep(step);

  useEffect(() => {
    setDependencyRiskFilter("all");
  }, [repoAnalysis?.dependencies]);

  useEffect(() => {
    setSonarFindingFilter("all");
    setCodeSmellSeverityFilter("all");
    setVisibleSonarFindingCounts({
      bugs: SONAR_FINDINGS_PAGE_SIZE,
      vulnerabilities: SONAR_FINDINGS_PAGE_SIZE,
      code_smells: SONAR_FINDINGS_PAGE_SIZE,
      security_hotspots: SONAR_FINDINGS_PAGE_SIZE,
    });
  }, [migrationJob?.job_id, migrationJob?.sonar_report, migrationJob?.sonar_scan_mode]);

  const migrationApproachOptions: Array<{
    value: MigrationApproachValue;
    label: string;
    desc: string;
    tooltip: string;
    icon: React.ReactNode;
    color: string;
  }> = [
    {
      value: "fork",
      label: "Create New Repository",
      desc: "Push migrated code to a new repository under the Javaapex GitHub owner",
      tooltip: "Creates an entirely new repository with the migrated code under the Javaapex GitHub owner by default.",
      icon: <FaRocket />,
      color: "#f59e0b",
    },
    {
      value: "branch",
      label: "Existing Repository (New Branch)",
      desc: "Push migrated code to a new branch in the source repository",
      tooltip: "Keeps the existing repository and publishes the migrated code on a separate branch for review and merge.",
      icon: <FaProjectDiagram />,
      color: "#22c55e",
    },
    {
      value: "local",
      label: "Store In Local Folder",
      desc: "Save migrated code into a local folder on this machine",
      tooltip: "Creates a local folder such as {repo-name}-Migrated under the backend migration workspace instead of pushing to GitHub.",
      icon: <FaFolderOpen />,
      color: "#2563eb",
    },
  ];

  const documentPrefetchKeyRef = useRef<string>("");
  const documentPrefetchPromiseRef = useRef<Promise<PrefetchedBrdDocument | null> | null>(null);
  const migrationPollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const migrationPollingInFlightRef = useRef(false);
  const migrationPollingErrorCountRef = useRef(0);
  const fossaLoadedJobIdRef = useRef<string | null>(null);

  const isPrivateRepoAccessError = (message: string) => {
    const normalizedMessage = message.toLowerCase();
    return (
      normalizedMessage.includes("private repository") ||
      normalizedMessage.includes("repository not found or is private") ||
      normalizedMessage.includes("provide a personal access token") ||
      normalizedMessage.includes("access denied") ||
      normalizedMessage.includes("repo scope") ||
      normalizedMessage.includes("does not have access")
    );
  };

  const toggleMicroserviceAccordion = (section: MicroserviceAccordionKey) => {
    setMicroserviceAccordionState((current) => ({
      ...current,
      [section]: !current[section],
    }));
  };

  const _uniqueTextItems = (items: string[] = []) =>
    Array.from(
      new Set(
        items
          .map((item) => item?.trim())
          .filter((item): item is string => Boolean(item))
      )
    );

  const toggleMicroserviceExpandedSection = (sectionKey: string) => {
    setMicroserviceExpandedSections((current) => ({
      ...current,
      [sectionKey]: !current[sectionKey],
    }));
  };

  const _renderMicroserviceEvidenceBlock = ({
    sectionKey,
    title,
    items,
    emptyText,
    previewCount = 3,
    accentColor = "#334155",
    background = "#ffffff",
    borderColor = "#e2e8f0",
    subtitle,
  }: {
    sectionKey: string;
    title: string;
    items: string[];
    emptyText: string;
    previewCount?: number;
    accentColor?: string;
    background?: string;
    borderColor?: string;
    subtitle?: string;
  }) => {
    const isExpanded = microserviceExpandedSections[sectionKey];
    const visibleItems = isExpanded ? items : items.slice(0, previewCount);

    return (
      <div style={{ ...styles.microserviceInsightCard, background, borderColor }}>
        <div style={{ ...styles.microserviceInsightTitle, color: accentColor }}>{title}</div>
        {subtitle && <div style={styles.microserviceEvidenceSubtitle}>{subtitle}</div>}
        {items.length > 0 ? (
          <>
            {visibleItems.map((item, index) => (
              <div key={`${sectionKey}-${index}`} style={{ ...styles.microserviceBulletItem, color: accentColor }}>
                - {item}
              </div>
            ))}
            {items.length > previewCount && (
              <div style={styles.microserviceEvidenceFooter}>
                <button
                  type="button"
                  style={styles.microserviceEvidenceToggle}
                  onClick={() => toggleMicroserviceExpandedSection(sectionKey)}
                >
                  {isExpanded ? "View less" : `View more (${items.length - previewCount} more)`}
                </button>
              </div>
            )}
          </>
        ) : (
          <div style={{ ...styles.microservicePreviewEmpty, color: accentColor }}>{emptyText}</div>
        )}
      </div>
    );
  };

  const getMicroserviceAccordionTone = (
    tone: "slate" | "green" | "red" | "amber" | "blue" | "violet" = "slate"
  ) => {
    switch (tone) {
      case "green":
        return { bg: "#f0fdf4", border: "#bbf7d0", accent: "#166534", muted: "#15803d" };
      case "red":
        return { bg: "#fef2f2", border: "#fecaca", accent: "#991b1b", muted: "#b91c1c" };
      case "amber":
        return { bg: "#fff7ed", border: "#fdba74", accent: "#9a3412", muted: "#c2410c" };
      case "blue":
        return { bg: "#eff6ff", border: "#bfdbfe", accent: "#1d4ed8", muted: "#2563eb" };
      case "violet":
        return { bg: "#faf5ff", border: "#d8b4fe", accent: "#6b21a8", muted: "#7e22ce" };
      default:
        return { bg: "#f8fafc", border: "#e2e8f0", accent: "#0f172a", muted: "#475569" };
    }
  };

  const renderMicroserviceAccordion = ({
    section,
    title,
    subtitle,
    meta,
    tone = "slate",
    children,
  }: {
    section: MicroserviceAccordionKey;
    title: string;
    subtitle: string;
    meta?: string;
    tone?: "slate" | "green" | "red" | "amber" | "blue" | "violet";
    children: React.ReactNode;
  }) => {
    const palette = getMicroserviceAccordionTone(tone);
    const isOpen = microserviceAccordionState[section];

    return (
      <div
        style={{
          ...styles.microserviceAccordionCard,
          background: palette.bg,
          borderColor: palette.border,
        }}
      >
        <button
          type="button"
          style={styles.microserviceAccordionToggle}
          onClick={() => toggleMicroserviceAccordion(section)}
        >
          <div style={styles.microserviceAccordionContentBlock}>
            <div style={{ ...styles.microserviceAccordionTitle, color: palette.accent }}>{title}</div>
            <div style={{ ...styles.microserviceAccordionSubtitle, color: palette.muted }}>{subtitle}</div>
          </div>
          <div style={styles.microserviceAccordionMeta}>
            {meta && (
              <span
                style={{
                  ...styles.microserviceAccordionMetaPill,
                  color: palette.accent,
                  borderColor: palette.border,
                  background: "#ffffff",
                }}
              >
                {meta}
              </span>
            )}
            <span style={{ ...styles.microserviceAccordionChevron, color: palette.accent }}>
              {isOpen ? "Hide" : "Show"}
            </span>
          </div>
        </button>
        {isOpen && <div style={styles.microserviceAccordionBody}>{children}</div>}
      </div>
    );
  };

  const handleAccessTokenValidate = async () => {
    if (!urlValidation.valid) return;

    if (!activeAccessToken) {
      setAccessTokenValidationState("invalid");
      setAccessTokenValidationMessage(
        showEnterpriseToken
          ? "Enter a GitHub Personal Access Token before validating this GitHub Enterprise repository."
          : "Enter a GitHub Personal Access Token with repo scope before validating this private repository."
      );
      return;
    }

    setAccessTokenValidationState("validating");
    setAccessTokenValidationMessage("");

    try {
      const visibility = await getRepoVisibility(urlValidation.normalizedUrl, activeAccessToken);
      const detectedPrivateRepo =
        visibility.requires_token ||
        visibility.visibility === "private" ||
        visibility.visibility === "private_or_inaccessible";

      setIsPrivateRepo(detectedPrivateRepo);
      setError("");
      setAccessTokenValidationState("valid");
      setAccessTokenValidationMessage(
        showEnterpriseToken
          ? "Token validated. Repository authentication looks ready."
          : detectedPrivateRepo
            ? "Token validated. Private repository access looks ready."
            : "Token validated. Repository access looks ready."
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "We couldn't validate this token yet.";
      setAccessTokenValidationState("invalid");
      setAccessTokenValidationMessage(
        isPrivateRepoAccessError(message)
          ? "We couldn't verify private repository access. Check that the PAT is correct and includes repo scope."
          : message
      );
    }
  };

  const getDocumentRepositoryUrl = () =>
    selectedRepo?.url || repoUrl || migrationJob?.source_repo || "";
  const technicalDocumentFallbackRepoName = selectedRepo?.name || repoAnalysis?.name || "repository";

  const resolveGeneratedDocumentAsset = async (result: GithubDocumentResponse) => {
    if (result.url) {
      try {
        const response = await fetch(result.url);

        if (response.ok) {
          const documentBlob = await response.blob();

          const htmlFromUrl = await documentBlob.text();
          if (htmlFromUrl.trim()) {
            return { html: htmlFromUrl } as const;
          }
        }
      } catch {
        // Fall back to inline HTML when the backend download URL is unavailable.
      }
    }

    if (result.html?.trim()) {
      return { html: result.html } as const;
    }

    throw new Error("Generated BRD document did not include HTML content or a download URL.");
  };

  const handleGenerateBrdDocument = async () => {
    const repoReference = getDocumentRepositoryUrl();

    if (!repoReference) {
      setError("Repository URL is required before generating the BRD document.");
      return;
    }

    setDocumentGenerationLoading("brd");
    setError("");

    try {
      const prefetchedAssetReady = prefetchedBrdDocument && documentPrefetchStatus === "ready";
      const activePrefetchPromise =
        !prefetchedAssetReady && documentPrefetchStatus === "loading"
          ? documentPrefetchPromiseRef.current
          : null;
      const generatedAsset = prefetchedAssetReady
        ? prefetchedBrdDocument
        : await (async () => {
            if (activePrefetchPromise) {
              const prefetchedAsset = await activePrefetchPromise;
              if (prefetchedAsset) {
                return prefetchedAsset;
              }
            }

            const result = isLocalRepoRef(repoReference)
              ? await generateLocalProjectDocument({
                  repo_url: repoReference,
                  repository_url: repoReference,
                  source_repo_url: repoReference,
                  source_repo: selectedRepo?.name || repoAnalysis?.name || repoReference,
                  target_repo: migrationJob?.target_repo || null,
                  source_java_version: repoAnalysis?.java_version || selectedSourceVersion || undefined,
                  target_java_version: effectiveTargetVersion || undefined,
                  document_type: "BRD",
                  analysis: repoAnalysis as unknown as Record<string, unknown>,
                })
              : await generateGithubDocument("brd", {
                  repo_url: repoReference,
                  repository_url: repoReference,
                  source_repo_url: repoReference,
                  token: currentToken || undefined,
                  github_token: currentToken || undefined,
                  job_id: migrationJob?.job_id || undefined,
                  migration_job_id: migrationJob?.job_id || undefined,
                  source_repo: migrationJob?.source_repo || repoReference,
                  target_repo: migrationJob?.target_repo || null,
                  source_java_version: repoAnalysis?.java_version || selectedSourceVersion || undefined,
                  target_java_version: effectiveTargetVersion || undefined,
                  document_type: "BRD",
                });

            const resolvedAsset = await resolveGeneratedDocumentAsset(result);
            const filename = buildHtmlFilename(result.filename, technicalDocumentFallbackRepoName);

            if (resolvedAsset.html) {
              return {
                filename,
                html: resolvedAsset.html,
              } satisfies PrefetchedBrdDocument;
            }

            throw new Error("Generated BRD document did not include HTML content or a download URL.");
          })();

      if (!prefetchedAssetReady) {
        setPrefetchedBrdDocument(generatedAsset);
        setDocumentPrefetchStatus("ready");
      }

      if (generatedAsset.html) {
        await downloadHtmlDocument(generatedAsset.html, generatedAsset.filename);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate BRD document");
    } finally {
      setDocumentGenerationLoading(null);
    }
  };

  const detectJavaVersionFromPomContent = (pomContent: string): string | null => {
    const normalize = (version: string) => {
      const trimmed = version.trim();
      return trimmed.startsWith("1.") ? trimmed.replace("1.", "") : trimmed;
    };

    const lookupProperty = (propertyName: string) => {
      const escapedProperty = propertyName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const match = pomContent.match(new RegExp(`<${escapedProperty}>\\s*(\\d+(?:\\.\\d+)?)\\s*</${escapedProperty}>`));
      return match ? normalize(match[1]) : null;
    };

    const directPatterns = [
      /<maven\.compiler\.source>\s*(\d+(?:\.\d+)?)\s*<\/maven\.compiler\.source>/,
      /<maven\.compiler\.target>\s*(\d+(?:\.\d+)?)\s*<\/maven\.compiler\.target>/,
      /<maven\.compiler\.release>\s*(\d+(?:\.\d+)?)\s*<\/maven\.compiler\.release>/,
      /<java\.version>\s*(\d+(?:\.\d+)?)\s*<\/java\.version>/,
      /<javaVersion>\s*(\d+(?:\.\d+)?)\s*<\/javaVersion>/,
      /<source>\s*(\d+(?:\.\d+)?)\s*<\/source>/,
    ];

    for (const pattern of directPatterns) {
      const match = pomContent.match(pattern);
      if (match) return normalize(match[1]);
    }

    const propertyPatterns = [
      /<maven\.compiler\.source>\s*\$\{([^}]+)\}\s*<\/maven\.compiler\.source>/,
      /<maven\.compiler\.target>\s*\$\{([^}]+)\}\s*<\/maven\.compiler\.target>/,
      /<maven\.compiler\.release>\s*\$\{([^}]+)\}\s*<\/maven\.compiler\.release>/,
      /<source>\s*\$\{([^}]+)\}\s*<\/source>/,
    ];

    for (const pattern of propertyPatterns) {
      const match = pomContent.match(pattern);
      if (!match) continue;
      const resolved = lookupProperty(match[1]);
      if (resolved) return resolved;
    }

    return null;
  };

  const handleCheckMicroserviceEligibility = useCallback(async () => {
    if (!repoAnalysis || !selectedRepo?.url) return;
    setMicroserviceLoading(true);
    setMicroserviceAssessmentResolved(false);
    try {
      setMicroserviceResult(null);
      setMicroserviceAccordionState(createDefaultMicroserviceAccordionState());
      setIsMicroserviceEligibilityCollapsed(false);
      setShowAllMicroserviceServices(false);
      setActiveScoreTooltip(null);
      setMicroserviceExpandedSections({});
      const result = isLocalRepoRef(selectedRepo.url)
        ? await getLocalProjectMicroserviceEligibility(extractLocalRepoPath(selectedRepo.url), repoAnalysis)
        : await getMicroserviceEligibility(selectedRepo.url, currentToken, repoAnalysis);
      setMicroserviceResult(result);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("Failed to fetch microservice eligibility", message);
      setError("Unable to determine microservice eligibility from backend. Please try again.");
    } finally {
      setMicroserviceAssessmentResolved(true);
      setMicroserviceLoading(false);
    }
  }, [
    currentToken,
    repoAnalysis,
    selectedRepo?.url,
    setActiveScoreTooltip,
    setIsMicroserviceEligibilityCollapsed,
    setMicroserviceAccordionState,
    setMicroserviceAssessmentResolved,
    setMicroserviceExpandedSections,
    setMicroserviceLoading,
    setMicroserviceResult,
    setShowAllMicroserviceServices,
  ]);

  const handleDownloadMicroserviceReport = async () => {
    if (!microserviceResult) return;
    const JsPdf = await loadJsPdf();
    const pdf = new JsPdf({
      orientation: "portrait",
      unit: "pt",
      format: "a4",
    });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const marginX = 42;
    const topMargin = 44;
    const bottomMargin = 44;
    const contentWidth = pageWidth - marginX * 2;
    const fileSafeProjectName = (microserviceResult.projectName || "microservice-readiness-report")
      .replace(/[^a-z0-9-_]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase();
    const filename = `${fileSafeProjectName || "microservice-readiness-report"}-assessment.pdf`;

    let cursorY = topMargin;

    const ensureSpace = (requiredHeight: number) => {
      if (cursorY + requiredHeight <= pageHeight - bottomMargin) return;
      pdf.addPage();
      cursorY = topMargin;
    };

    const addParagraph = (
      text: string,
      {
        fontSize = 10,
        color = "#334155",
        indent = 0,
        gapAfter = 10,
        bold = false,
      }: {
        fontSize?: number;
        color?: string;
        indent?: number;
        gapAfter?: number;
        bold?: boolean;
      } = {}
    ) => {
      const lines = pdf.splitTextToSize(text || "-", contentWidth - indent);
      const lineHeight = fontSize + 4;
      ensureSpace(lines.length * lineHeight + gapAfter);
      pdf.setFont("helvetica", bold ? "bold" : "normal");
      pdf.setFontSize(fontSize);
      pdf.setTextColor(color);
      pdf.text(lines, marginX + indent, cursorY);
      cursorY += lines.length * lineHeight + gapAfter;
    };

    const addSectionHeading = (title: string) => {
      ensureSpace(28);
      pdf.setDrawColor(226, 232, 240);
      pdf.setLineWidth(1);
      if (cursorY > topMargin) {
        pdf.line(marginX, cursorY - 8, pageWidth - marginX, cursorY - 8);
      }
      pdf.setFont("helvetica", "bold");
      pdf.setFontSize(13);
      pdf.setTextColor("#0f172a");
      pdf.text(title, marginX, cursorY + 8);
      cursorY += 24;
    };

    const addBulletList = (items: string[], emptyText: string) => {
      if (!items.length) {
        addParagraph(emptyText, { color: "#64748b", gapAfter: 12 });
        return;
      }
      items.forEach((item) => addParagraph(`- ${item}`, { indent: 4, gapAfter: 6 }));
      cursorY += 2;
    };

    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(18);
    pdf.setTextColor("#0f172a");
    pdf.text("Microservice Readiness Assessment", marginX, cursorY);
    cursorY += 24;

    addParagraph(`Project: ${microserviceResult.projectName}`, { fontSize: 12, bold: true, color: "#1e293b", gapAfter: 6 });
    addParagraph(
      `Score: ${microserviceResult.score}/100   |   Eligibility: ${microserviceResult.eligibility}   |   Recommended Architecture: ${microserviceResult.recommendedArchitecture}`,
      { fontSize: 10, color: "#475569", gapAfter: 6 }
    );
    addParagraph(
      `Generated: ${microserviceResult.reportGeneratedAt ? new Date(microserviceResult.reportGeneratedAt).toLocaleString() : new Date().toLocaleString()}`,
      { fontSize: 9, color: "#64748b", gapAfter: 16 }
    );

    addSectionHeading("Assessment Summary");
    addParagraph(microserviceResult.summary, { fontSize: 10, color: "#334155", gapAfter: 14 });

    addSectionHeading("Score Breakdown");
    (microserviceResult.scoreBreakdown || []).forEach((metric) => {
      addParagraph(`${metric.name} - ${metric.score}% (${metric.weight}% weight)`, { bold: true, color: "#1e293b", gapAfter: 4 });
      addParagraph(metric.summary, { color: "#475569", gapAfter: 8, indent: 8 });
    });

    addSectionHeading("Strengths");
    addBulletList(microserviceResult.strengths || [], "No major strengths were highlighted.");

    addSectionHeading("Risks");
    addBulletList(microserviceResult.risks || [], "No major risks were highlighted.");

    addSectionHeading("Suggested Service Boundaries");
    if ((microserviceResult.serviceCandidates || []).length === 0) {
      addParagraph("No clear service candidates were identified.", { color: "#64748b", gapAfter: 12 });
    } else {
      microserviceResult.serviceCandidates.forEach((candidate, index) => {
        addParagraph(`${index + 1}. ${candidate.name}`, { bold: true, color: "#1d4ed8", gapAfter: 4 });
        if (candidate.packages?.length) {
          addParagraph(`Packages: ${candidate.packages.join(", ")}`, { color: "#475569", indent: 10, gapAfter: 4 });
        }
        if (candidate.evidence?.length) {
          candidate.evidence.forEach((item) => addParagraph(`- ${item}`, { indent: 16, gapAfter: 4 }));
        }
        if (candidate.scaling_signals?.length) {
          addParagraph(`Scaling signals: ${candidate.scaling_signals.join(", ")}`, { color: "#0f766e", indent: 10, gapAfter: 4 });
        }
        if (candidate.external_integrations?.length) {
          addParagraph(`External integrations: ${candidate.external_integrations.join(", ")}`, { color: "#7c2d12", indent: 10, gapAfter: 4 });
        }
        if (candidate.transactional) {
          addParagraph("Transactional boundary detected.", { color: "#92400e", indent: 10, gapAfter: 6 });
        }
        cursorY += 2;
      });
    }

    addSectionHeading("Coupling Issues");
    addBulletList(microserviceResult.couplingIssues || [], "No major coupling issues detected.");

    addSectionHeading("Database Concerns");
    addBulletList(microserviceResult.databaseConcerns || [], "No major database boundary concerns detected.");

    addSectionHeading("Scaling Candidates");
    addBulletList(microserviceResult.scalingCandidates || [], "No clear independent scaling targets were highlighted.");

    addSectionHeading("Recommended Migration Strategy");
    addBulletList(microserviceResult.recommendedMigrationStrategy || [], "No migration strategy guidance available.");

    addSectionHeading("Architectural Observations");
    addBulletList(
      [...(microserviceResult.observations || []), ...(microserviceResult.architecturalObservations || [])].slice(0, 20),
      "No additional architectural observations were recorded."
    );

    if (microserviceResult.detailedEligibilityReport) {
      addSectionHeading("Detailed Eligibility Report");
      const detailSections: Array<[string, string[]]> = [
        ["Project structure", microserviceResult.detailedEligibilityReport.project_structure || []],
        ["Package structure", microserviceResult.detailedEligibilityReport.package_structure || []],
        ["Module boundaries", microserviceResult.detailedEligibilityReport.module_boundaries || []],
        ["Dependency coupling", microserviceResult.detailedEligibilityReport.dependency_coupling || []],
        ["Database access patterns", microserviceResult.detailedEligibilityReport.database_access_patterns || []],
        ["Communication analysis", microserviceResult.detailedEligibilityReport.communication_analysis || []],
        ["Deployment independence", microserviceResult.detailedEligibilityReport.deployment_independence || []],
        ["Scalability indicators", microserviceResult.detailedEligibilityReport.scalability_indicators || []],
      ];
      detailSections.forEach(([title, items]) => {
        addParagraph(title, { bold: true, color: "#0f172a", gapAfter: 4 });
        addBulletList(items, "No additional findings.");
      });
    }

    pdf.save(filename);
  };

  useEffect(() => {
    if (repoAnalysis && selectedRepo?.url && !microserviceAssessmentResolved && !microserviceLoading) {
      void handleCheckMicroserviceEligibility();
    }
  }, [repoAnalysis, selectedRepo?.url, microserviceAssessmentResolved, microserviceLoading, handleCheckMicroserviceEligibility]);

  const parseJavaVersion = (version: string) => {
    const parsed = parseInt(version, 10);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const shouldHideGeneratedDiffPath = (filePath: string) => {
    const normalized = (filePath || "").replace(/\\/g, "/").toLowerCase();
    return [
      "/.javaapex-cache/",
      "/.scannerwork/",
      "/node_modules/",
      "/target/",
      "/build/",
      "/out/",
      "/dist/",
      "/.gradle/",
    ].some((segment) => normalized.includes(segment)) || normalized.startsWith(".javaapex-cache/") || normalized.startsWith(".scannerwork/");
  };

  const buildCodeChangesFromPreviewDiffs = (fileDiffs: PreviewFileDiff[]): CodeChangeEntry[] => {
    return fileDiffs.flatMap((fileDiff) => {
      const diffLinesRaw = fileDiff.diff.split(/\r?\n/);
      const parsedDiffLines: CodeChangeEntry["diffLines"] = [];
      let oldLineNumber = 0;
      let newLineNumber = 0;
      const fromLine = diffLinesRaw.find((line) => line.startsWith("--- "));
      const toLine = diffLinesRaw.find((line) => line.startsWith("+++ "));

      const changeType: CodeChangeEntry["changeType"] =
        diffLinesRaw.some((line) => line.startsWith("new file mode")) || fromLine?.includes("/dev/null")
          ? "added"
          : diffLinesRaw.some((line) => line.startsWith("deleted file mode")) || toLine?.includes("/dev/null")
            ? "deleted"
            : "modified";

      diffLinesRaw.forEach((line) => {
        if (
          !line ||
          line.startsWith("diff --git") ||
          line.startsWith("index ") ||
          line.startsWith("new file mode") ||
          line.startsWith("deleted file mode") ||
          line.startsWith("rename from ") ||
          line.startsWith("rename to ") ||
          line.startsWith("similarity index ") ||
          line.startsWith("---") ||
          line.startsWith("+++")
        ) {
          return;
        }

        if (line.startsWith("@@")) {
          const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
          parsedDiffLines.push({
            type: "hunk",
            oldLineNumber: null,
            newLineNumber: null,
            content: line,
          });
          if (match) {
            oldLineNumber = Number(match[1]);
            newLineNumber = Number(match[2]);
          }
          return;
        }

        if (line.startsWith("+")) {
          parsedDiffLines.push({
            type: "add",
            oldLineNumber: null,
            newLineNumber,
            content: line.slice(1),
          });
          newLineNumber += 1;
          return;
        }

        if (line.startsWith("-")) {
          parsedDiffLines.push({
            type: "remove",
            oldLineNumber,
            newLineNumber: null,
            content: line.slice(1),
          });
          oldLineNumber += 1;
          return;
        }

        const content = line.startsWith(" ") ? line.slice(1) : line;
        parsedDiffLines.push({
          type: "context",
          oldLineNumber,
          newLineNumber,
          content,
        });
        oldLineNumber += 1;
        newLineNumber += 1;
      });

      const additions = diffLinesRaw.filter((line) => line.startsWith("+") && !line.startsWith("+++")).length;
      const deletions = diffLinesRaw.filter((line) => line.startsWith("-") && !line.startsWith("---")).length;
      const normalizedPath =
        fileDiff.file_path ||
        (toLine && !toLine.includes("/dev/null")
          ? toLine.replace(/^\+\+\+\s+b\//, "")
          : fromLine?.replace(/^---\s+a\//, "")) ||
        "unknown-file";

      if (shouldHideGeneratedDiffPath(normalizedPath)) {
        return [];
      }

      return [{
        fileName: normalizedPath.split("/").pop() || normalizedPath,
        filePath: normalizedPath,
        changeType,
        additions,
        deletions,
        oldContent: "",
        newContent: "",
        diffLines: parsedDiffLines,
      }];
    });
  };

  /*
  const renderCodeChangesViewer = ({
    changes,
    title,
    emptyMessage,
    maxHeight = 420,
    collapsible = false,
  }: {
    changes: CodeChangeEntry[];
    title: string;
    emptyMessage: string;
    maxHeight?: number;
    collapsible?: boolean;
  }) => {
    const isExpanded = collapsible ? showCodeChanges : true;
    const totalAdditions = changes.reduce((sum, change) => sum + change.additions, 0);
    const totalDeletions = changes.reduce((sum, change) => sum + change.deletions, 0);

    const renderLineNumber = (value: number | null) => (value === null ? "" : value);

    return (
      <div
        style={{
          border: "1px solid #d0d7de",
          borderRadius: 8,
          overflow: "hidden",
          backgroundColor: "#fff",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            padding: "12px 16px",
            backgroundColor: "#f6f8fa",
            borderBottom: "1px solid #d0d7de",
          }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
            <span style={{ fontWeight: 600, color: "#1e293b" }}>{title}</span>
            <span style={{ color: "#334155", fontSize: 13 }}>{changes.length} files changed</span>
            <span style={{ color: "#16a34a", fontSize: 13 }}>+{totalAdditions}</span>
            <span style={{ color: "#dc2626", fontSize: 13 }}>-{totalDeletions}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                fontSize: 11,
                padding: "4px 10px",
                backgroundColor: "#ddf4ff",
                borderRadius: 999,
                color: "#0969da",
              }}
            >
              Read only
            </span>
            {collapsible && (
              <button
                onClick={() => setShowCodeChanges(!showCodeChanges)}
                style={{
                  background: "none",
                  border: "1px solid #d0d7de",
                  borderRadius: 6,
                  padding: "6px 12px",
                  cursor: "pointer",
                  fontSize: 12,
                  color: "#24292f",
                }}
              >
                {showCodeChanges ? "Collapse" : "Expand"}
              </button>
            )}
          </div>
        </div>

        {isExpanded &&
          (changes.length > 0 ? (
            <div style={{ maxHeight, overflowY: "auto" }}>
              {changes.map((change, idx) => (
                <div key={`${change.filePath}-${idx}`}>
                  <div
                    onClick={() =>
                      setSelectedDiffFile(selectedDiffFile === change.filePath ? null : change.filePath)
                    }
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "10px 16px",
                      backgroundColor: selectedDiffFile === change.filePath ? "#f0f6fc" : "#fafbfc",
                      borderBottom: "1px solid #d0d7de",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                      <span style={{ fontSize: 14 }}>{selectedDiffFile === change.filePath ? "v" : ">"}</span>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "2px 6px",
                          borderRadius: 999,
                          fontSize: 11,
                          fontWeight: 700,
                          backgroundColor:
                            change.changeType === "added"
                              ? "#dcfce7"
                              : change.changeType === "deleted"
                                ? "#fee2e2"
                                : "#fef3c7",
                          color:
                            change.changeType === "added"
                              ? "#166534"
                              : change.changeType === "deleted"
                                ? "#991b1b"
                                : "#92400e",
                        }}
                      >
                        {change.changeType.toUpperCase()}
                      </span>
                      <span
                        style={{
                          fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                          fontSize: 13,
                          color: "#0969da",
                          wordBreak: "break-all",
                        }}
                      >
                        {change.filePath}
                      </span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                      <span style={{ color: "#16a34a", fontSize: 12, fontWeight: 600 }}>+{change.additions}</span>
                      <span style={{ color: "#dc2626", fontSize: 12, fontWeight: 600 }}>-{change.deletions}</span>
                    </div>
                  </div>

                  {selectedDiffFile === change.filePath && (
                    <div
                      style={{
                        backgroundColor: "#0d1117",
                        borderBottom: "1px solid #d0d7de",
                        overflowX: "auto",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "8px 16px",
                          backgroundColor: "#161b22",
                          borderBottom: "1px solid #30363d",
                        }}
                      >
                        <span
                          style={{
                            fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                            fontSize: 12,
                            color: "#8b949e",
                          }}
                        >
                          {change.fileName}
                        </span>
                        <div style={{ display: "flex", gap: 12 }}>
                          <span style={{ fontSize: 11, color: "#3fb950" }}>+{change.additions} lines</span>
                          <span style={{ fontSize: 11, color: "#f85149" }}>-{change.deletions} lines</span>
                        </div>
                      </div>

                      <div
                        style={{
                          fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                          fontSize: 12,
                          lineHeight: 1.5,
                        }}
                      >
                        {change.diffLines.length > 0 ? (
                          change.diffLines.map((line, lineIdx) => {
                            if (line.type === "hunk") {
                              return (
                                <div
                                  key={lineIdx}
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    backgroundColor: "#111827",
                                    color: "#93c5fd",
                                    borderTop: "1px solid #30363d",
                                    borderBottom: "1px solid #30363d",
                                  }}
                                >
                                  <span
                                    style={{
                                      minWidth: 60,
                                      padding: "2px 10px",
                                      color: "#6e7681",
                                      borderRight: "1px solid #30363d",
                                      userSelect: "none",
                                    }}
                                  />
                                  <span
                                    style={{
                                      minWidth: 60,
                                      padding: "2px 10px",
                                      color: "#6e7681",
                                      borderRight: "1px solid #30363d",
                                      userSelect: "none",
                                    }}
                                  />
                                  <span
                                    style={{
                                      minWidth: 24,
                                      padding: "2px 6px",
                                      textAlign: "center",
                                      color: "#93c5fd",
                                      userSelect: "none",
                                    }}
                                  >
                                    @
                                  </span>
                                  <span
                                    style={{
                                      flex: 1,
                                      padding: "2px 10px",
                                      whiteSpace: "pre",
                                    }}
                                  >
                                    {line.content}
                                  </span>
                                </div>
                              );
                            }

                            const backgroundColor =
                              line.type === "add"
                                ? "rgba(63, 185, 80, 0.15)"
                                : line.type === "remove"
                                  ? "rgba(248, 81, 73, 0.15)"
                                  : "transparent";

                            const contentColor =
                              line.type === "add"
                                ? "#aff5b4"
                                : line.type === "remove"
                                  ? "#ffa198"
                                  : "#c9d1d9";

                            const symbolColor =
                              line.type === "add"
                                ? "#3fb950"
                                : line.type === "remove"
                                  ? "#f85149"
                                  : "#8b949e";

                            return (
                              <div
                                key={lineIdx}
                                style={{
                                  display: "flex",
                                  backgroundColor,
                                  borderLeft: `4px solid ${
                                    line.type === "add"
                                      ? "#3fb950"
                                      : line.type === "remove"
                                        ? "#f85149"
                                        : "transparent"
                                  }`,
                                }}
                              >
                                <span
                                  style={{
                                    minWidth: 60,
                                    padding: "2px 10px",
                                    textAlign: "right",
                                    color: "#6e7681",
                                    backgroundColor:
                                      line.type === "add"
                                        ? "rgba(63, 185, 80, 0.1)"
                                        : line.type === "remove"
                                          ? "rgba(248, 81, 73, 0.1)"
                                          : "#161b22",
                                    borderRight: "1px solid #30363d",
                                    userSelect: "none",
                                  }}
                                >
                                  {renderLineNumber(line.oldLineNumber)}
                                </span>
                                <span
                                  style={{
                                    minWidth: 60,
                                    padding: "2px 10px",
                                    textAlign: "right",
                                    color: "#6e7681",
                                    backgroundColor:
                                      line.type === "add"
                                        ? "rgba(63, 185, 80, 0.1)"
                                        : line.type === "remove"
                                          ? "rgba(248, 81, 73, 0.1)"
                                          : "#161b22",
                                    borderRight: "1px solid #30363d",
                                    userSelect: "none",
                                  }}
                                >
                                  {renderLineNumber(line.newLineNumber)}
                                </span>
                                <span
                                  style={{
                                    minWidth: 24,
                                    padding: "2px 6px",
                                    textAlign: "center",
                                    color: symbolColor,
                                    fontWeight: 600,
                                    userSelect: "none",
                                  }}
                                >
                                  {line.type === "add" ? "+" : line.type === "remove" ? "-" : " "}
                                </span>
                                <span
                                  style={{
                                    flex: 1,
                                    padding: "2px 10px",
                                    color: contentColor,
                                    whiteSpace: "pre",
                                  }}
                                >
                                  {line.content || " "}
                                </span>
                              </div>
                            );
                          })
                        ) : (
                          <div
                            style={{
                              padding: "12px 16px",
                              color: "#8b949e",
                              fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                            }}
                          >
                            No line-level diff is available for this file.
                          </div>
                        )}
                      </div>
                    </div>

                  )}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: 40, textAlign: "center", color: "#57606a" }}>{emptyMessage}</div>
          ))}
      </div>
    );
  };
  */

  const isDetectedDependencyStatus = (status: string) => {
    const normalizedStatus = status.trim().toLowerCase();
    return normalizedStatus === "upgraded" || normalizedStatus.startsWith("analyzing");
  };

  const getDependencyStatusLabel = (status: string) => {
    return isDetectedDependencyStatus(status)
      ? "ANALYZED"
      : status.replace(/_/g, " ").toUpperCase();
  };

  const parseVersionParts = (version: string | null | undefined) => {
    const normalized = (version || "").trim();
    const match = normalized.match(/(\d+)(?:\.(\d+))?(?:\.(\d+))?/);
    if (!match) {
      return null;
    }

    return {
      major: Number.parseInt(match[1], 10),
      minor: Number.parseInt(match[2] || "0", 10),
      patch: Number.parseInt(match[3] || "0", 10),
      raw: normalized,
    };
  };

  const classifyDependencyCategory = (dep: DependencyInfo): DependencyCategory => {
    const artifactId = (dep.artifact_id || "").toLowerCase();
    const groupId = (dep.group_id || "").toLowerCase();
    const coordinate = `${groupId}:${artifactId}`;

    if (
      artifactId.includes("junit") ||
      artifactId.includes("mockito") ||
      artifactId.includes("assertj") ||
      artifactId.includes("testng") ||
      artifactId.includes("surefire")
    ) {
      return "Testing";
    }
    if (
      artifactId.includes("log4j") ||
      artifactId.includes("slf4j") ||
      artifactId.includes("logback") ||
      artifactId.includes("commons-logging")
    ) {
      return "Logging";
    }
    if (
      artifactId.includes("hibernate") ||
      artifactId.includes("jpa") ||
      artifactId.includes("jdbc") ||
      artifactId.includes("mybatis") ||
      artifactId.includes("dynamodb") ||
      artifactId.includes("persistence")
    ) {
      return "Persistence";
    }
    if (
      artifactId.includes("security") ||
      coordinate.includes("spring-security") ||
      artifactId.includes("oauth") ||
      artifactId.includes("jwt") ||
      artifactId.includes("auth")
    ) {
      return "Security";
    }
    if (
      artifactId.includes("maven") ||
      artifactId.includes("gradle") ||
      artifactId.includes("plugin") ||
      artifactId.includes("wrapper")
    ) {
      return "Build";
    }
    if (
      groupId.startsWith("javax.") ||
      artifactId.startsWith("javax.") ||
      groupId.startsWith("jakarta.") ||
      artifactId.startsWith("jakarta.") ||
      artifactId.includes("servlet") ||
      artifactId.includes("jaxb")
    ) {
      return "Jakarta / Java EE";
    }
    if (
      artifactId.includes("jackson") ||
      artifactId.includes("gson") ||
      artifactId.includes("json") ||
      artifactId.includes("xml") ||
      artifactId.includes("yaml")
    ) {
      return "Data / JSON";
    }
    if (
      artifactId.includes("commons") ||
      artifactId.includes("guava") ||
      artifactId.includes("lombok") ||
      artifactId.includes("lang3") ||
      artifactId.includes("collections")
    ) {
      return "Utilities";
    }
    if (
      coordinate.includes("spring") ||
      coordinate.includes("apache") ||
      coordinate.includes("struts") ||
      coordinate.includes("quarkus") ||
      coordinate.includes("micronaut")
    ) {
      return "Framework";
    }
    return "Other";
  };

  const classifyDependencyRisk = (dep: DependencyInfo): { risk: DependencyRiskLevel; reason: string } => {
    const artifactId = (dep.artifact_id || "").toLowerCase();
    const groupId = (dep.group_id || "").toLowerCase();
    const status = (dep.status || "").toLowerCase();
    const version = dep.current_version || "";
    const parsedVersion = parseVersionParts(version);
    const coordinate = `${groupId}:${artifactId}`;
    const unknownVersion = !version || version.toLowerCase() === "unknown";
    const snapshotVersion = /snapshot|alpha|beta|rc|milestone|release/i.test(version);
    const isLegacyJavax = groupId.startsWith("javax.") || artifactId.startsWith("javax.");
    const isLegacyLog4j = artifactId.includes("log4j") && parsedVersion && parsedVersion.major < 2;
    const isLegacyStruts = coordinate.includes("struts");
    const isCommonsLogging = coordinate.includes("commons-logging");
    const dependencyLabel = coordinate !== ":" ? coordinate : dep.artifact_id || dep.group_id || "This dependency";
    const versionContext = unknownVersion
      ? "Version information could not be resolved from the repository metadata."
      : version
        ? `Current version: ${version}.`
        : "";

    if (isLegacyJavax) {
      return {
        risk: "critical",
        reason: `${dependencyLabel} is marked critical because it still relies on the legacy javax namespace, which usually needs explicit Jakarta migration work. ${versionContext}`.trim(),
      };
    }

    if (isLegacyLog4j) {
      return {
        risk: "critical",
        reason: `${dependencyLabel} is marked critical because it appears to be on Log4j 1.x, a legacy logging stack that usually needs urgent replacement before migration. ${versionContext}`.trim(),
      };
    }

    if (isLegacyStruts) {
      return {
        risk: "critical",
        reason: `${dependencyLabel} is marked critical because Struts-era dependencies are highly migration-sensitive and often require code changes, not just a version bump. ${versionContext}`.trim(),
      };
    }

    if (isCommonsLogging) {
      return {
        risk: "critical",
        reason: `${dependencyLabel} is marked critical because commons-logging is a legacy logging abstraction that frequently needs replacement or bridge cleanup during modernization. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("junit") && parsedVersion && parsedVersion.major < 5) {
      return {
        risk: "high",
        reason: `${dependencyLabel} is marked high because it appears to be on a pre-JUnit 5 generation, which commonly needs test migration updates and runner changes. ${versionContext}`.trim(),
      };
    }

    if (status === "outdated") {
      return {
        risk: "high",
        reason: `${dependencyLabel} is marked high because the repository analysis already flagged it as outdated, so it deserves manual review before migration. ${versionContext}`.trim(),
      };
    }

    if (unknownVersion) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because its version could not be identified from repository metadata, so compatibility needs to be validated during migration.`,
      };
    }

    if (snapshotVersion) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because it uses a pre-release version tag such as snapshot, alpha, beta, or release candidate, which can introduce migration instability. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("spring")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because Spring dependencies usually need coordinated version alignment with the broader application stack during migration. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("hibernate")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because Hibernate upgrades often require ORM compatibility checks, dialect validation, and configuration review. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("jpa")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because JPA-related dependencies can be affected by persistence API and Jakarta namespace changes during migration. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("servlet")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because servlet APIs are often impacted by container compatibility and javax-to-jakarta migration changes. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("jackson")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because Jackson libraries sit on the serialization path and should be compatibility-checked for runtime behavior changes. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("security")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because security libraries are configuration-sensitive and should be reviewed carefully for authentication or authorization changes. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("dynamodb")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because AWS DynamoDB client libraries are runtime-facing and may need API or SDK compatibility validation during migration. ${versionContext}`.trim(),
      };
    }

    if (artifactId.includes("jdbc")) {
      return {
        risk: "medium",
        reason: `${dependencyLabel} is marked medium because JDBC drivers are tightly coupled to database connectivity and should be validated for driver and runtime compatibility. ${versionContext}`.trim(),
      };
    }

    return {
      risk: "low",
      reason: `${dependencyLabel} is marked low because no strong migration-risk indicators were detected from the repository metadata. ${versionContext}`.trim(),
    };
  };

  const categorizeDependencies = (dependencies: DependencyInfo[]): CategorizedDependency[] => {
    return dependencies.map((dep) => {
      const { risk, reason } = classifyDependencyRisk(dep);
      return {
        ...dep,
        displayName: `${dep.group_id}:${dep.artifact_id}`,
        category: classifyDependencyCategory(dep),
        risk,
        reason,
      };
    });
  };

  const getDependencyRiskColors = (risk: DependencyRiskLevel) => {
    if (risk === "critical") {
      return {
        background: "linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%)",
        border: "#fca5a5",
        badgeBackground: "#dc2626",
        badgeColor: "#fff",
        textColor: "#991b1b",
      };
    }
    if (risk === "high") {
      return {
        background: "linear-gradient(180deg, #fff7ed 0%, #ffedd5 100%)",
        border: "#fdba74",
        badgeBackground: "#f97316",
        badgeColor: "#fff",
        textColor: "#9a3412",
      };
    }
    if (risk === "medium") {
      return {
        background: "linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%)",
        border: "#fcd34d",
        badgeBackground: "#f59e0b",
        badgeColor: "#fff",
        textColor: "#92400e",
      };
    }
    return {
      background: "linear-gradient(180deg, #ecfdf5 0%, #dcfce7 100%)",
      border: "#86efac",
      badgeBackground: "#22c55e",
      badgeColor: "#fff",
      textColor: "#166534",
    };
  };

  const handleTargetVersionChange = (value: string) => {
    setSelectedTargetVersion(value);
    if (value) {
      setTargetVersionRequiredError(false);
    }
  };

  const validateTargetBranchName = (branchName: string) => {
    const trimmed = branchName.trim();
    if (!trimmed) {
      return "Target branch name is required.";
    }
    if (/\s/.test(trimmed)) {
      return "Branch names cannot contain spaces.";
    }
    const hasInvalidBranchCharacters = ["\\", "^", ":", "?", "*", "[", "]", "~"].some((char) =>
      trimmed.includes(char)
    );
    if (
      trimmed.startsWith("/") ||
      trimmed.endsWith("/") ||
      trimmed.endsWith(".") ||
      trimmed.endsWith(".lock") ||
      trimmed.includes("..") ||
      trimmed.includes("//") ||
      trimmed.includes("@{") ||
      hasInvalidBranchCharacters
    ) {
      return "Enter a valid Git branch name.";
    }
    return "";
  };

  const validateTargetRepositoryName = (targetValue: string) => {
    const trimmed = targetValue.trim().replace(/\.git$/, "").replace(/\/+$/, "");
    if (!trimmed) {
      return "Target repository name is required.";
    }

    const platform = sourceRepositoryContext?.platform || "github";
    const repoNamePattern = /^[A-Za-z0-9._-]+$/;

    if (repoNamePattern.test(trimmed)) {
      return "";
    }

    const shortFormatMatch = trimmed.match(/^([^/\s]+)\/([^/\s]+)$/);
    if (shortFormatMatch) {
      const [, , repo] = shortFormatMatch;
      if (!repoNamePattern.test(repo)) {
        return "Enter a valid repository name.";
      }
      return "";
    }

    if (!/^https?:\/\//i.test(trimmed)) {
      return "Enter a full repository URL or a repository name.";
    }

    try {
      const parsed = new URL(trimmed);
      const pathParts = parsed.pathname.split("/").filter(Boolean);
      if (pathParts.length !== 2) {
        return "Repository URL must include both owner and repository name.";
      }

      const [, repo] = pathParts;
      if (!repoNamePattern.test(repo)) {
        return "Enter a valid repository name.";
      }
      if (platform === "gitlab" && !parsed.hostname.includes("gitlab")) {
        return "Use a GitLab repository URL for GitLab migrations.";
      }
      if (platform === "github" && !parsed.hostname.includes("github")) {
        return "Use a GitHub repository URL for GitHub migrations.";
      }
      return "";
    } catch {
      return "Enter a valid repository URL.";
    }
  };

  const validateTargetLocalFolderName = (targetValue: string) => {
    const trimmed = targetValue.trim();
    if (!trimmed) {
      return "Target local folder is required.";
    }

    const isWindowsAbsolutePath = /^[A-Za-z]:[\\/]/.test(trimmed);
    const isUnixAbsolutePath = trimmed.startsWith("/");

    if (!isWindowsAbsolutePath && !isUnixAbsolutePath && /[\\/]/.test(trimmed)) {
      return "Enter either a folder name or a full absolute path.";
    }

    const normalizedPath = trimmed.replace(/[\\/]+$/, "");
    const segments = isWindowsAbsolutePath
      ? normalizedPath.slice(2).split(/[\\/]+/).filter(Boolean)
      : isUnixAbsolutePath
        ? normalizedPath.split(/[\\/]+/).filter(Boolean)
        : [normalizedPath];

    if (segments.length === 0) {
      return "Enter a valid local folder path.";
    }

    for (const segment of segments) {
      const hasControlCharacter = [...segment].some((char) => char.charCodeAt(0) < 32);
      if (hasControlCharacter || /[<>:"/\\|?*]/.test(segment)) {
        return "Enter a valid local folder path.";
      }
      if (/[. ]$/.test(segment)) {
        return "Folder names cannot end with a space or period.";
      }
    }

    return "";
  };

  const continueWithTargetVersion = (nextStep: number) => {
    if (!effectiveTargetVersion) {
      setTargetVersionRequiredError(true);
      return;
    }

    const targetNameError =
      currentMigrationApproach === "branch"
        ? validateTargetBranchName(targetRepoName)
        : currentMigrationApproach === "local"
          ? validateTargetLocalFolderName(targetRepoName)
          : validateTargetRepositoryName(targetRepoName);
    if (targetNameError) {
      setTargetRepoNameError(targetNameError);
      return;
    }

    setTargetVersionRequiredError(false);
    setTargetRepoNameError("");
    setStep(nextStep);
  };

  const renderCategorizedDependencies = (dependencies: DependencyInfo[]) => {
    const categorizedDependencies = categorizeDependencies(dependencies);
    const riskCounts = categorizedDependencies.reduce(
      (acc, dep) => {
        acc[dep.risk] += 1;
        return acc;
      },
      { critical: 0, high: 0, medium: 0, low: 0 } as Record<DependencyRiskLevel, number>
    );
    const visibleDependencies =
      dependencyRiskFilter === "all"
        ? categorizedDependencies
        : categorizedDependencies.filter((dep) => dep.risk === dependencyRiskFilter);
    const attentionDependencies = visibleDependencies.filter((dep) => dep.risk !== "low");
    const otherDependencies = visibleDependencies.filter((dep) => dep.risk === "low");
    const dominantRisk: DependencyRiskLevel =
      riskCounts.critical > 0 ? "critical" : riskCounts.high > 0 ? "high" : riskCounts.medium > 0 ? "medium" : "low";
    const topAttentionNames = attentionDependencies.slice(0, 5).map((dep) => dep.artifact_id).join(", ");
    const activeFilterLabel = dependencyRiskFilter === "all" ? "All Dependencies" : `${dependencyRiskFilter.toUpperCase()} Only`;

    const getSummaryCardStyle = (risk: DependencyRiskFilter) => {
      const isActive = dependencyRiskFilter === risk;
      const colors = risk === "all" ? getDependencyRiskColors(dominantRisk) : getDependencyRiskColors(risk);

      return {
        ...styles.dependencySummaryCard,
        borderColor: colors.border,
        background: isActive ? colors.background : "#fff",
        boxShadow: isActive ? `0 0 0 2px ${colors.border}33` : styles.dependencySummaryCard.boxShadow,
        cursor: "pointer",
      };
    };

    const handleRiskFilterClick = (risk: DependencyRiskFilter) => {
      if (risk === "all") {
        setDependencyRiskFilter("all");
        return;
      }

      setDependencyRiskFilter((currentFilter) => (currentFilter === risk ? "all" : risk));
    };

    const renderDependencyCard = (dep: CategorizedDependency, idx: number) => {
      const colors = getDependencyRiskColors(dep.risk);
      return (
        <div
          key={`${dep.displayName}:${idx}`}
          style={{
            ...styles.categorizedDependencyCard,
            background: colors.background,
            borderColor: colors.border,
          }}
          title={dep.reason}
        >
          <div style={styles.categorizedDependencyHeader}>
            <div style={styles.categorizedDependencyName}>{dep.displayName}</div>
            <span
              style={{
                ...styles.dependencyRiskBadge,
                backgroundColor: colors.badgeBackground,
                color: colors.badgeColor,
              }}
            >
              {dep.risk.toUpperCase()}
            </span>
          </div>
          <div style={styles.categorizedDependencyVersion}>{dep.current_version || "Unknown version"}</div>
          <div style={styles.dependencyMetaRow}>
            <span style={styles.dependencyCategoryBadge}>{dep.category}</span>
            {dep.status && (
              <span style={{ ...styles.dependencyStatusPill, color: colors.textColor }}>
                {getDependencyStatusLabel(dep.status)}
              </span>
            )}
          </div>
          <div style={{ ...styles.dependencyReasonText, color: colors.textColor }}>{dep.reason}</div>
        </div>
      );
    };

    return (
      <div style={styles.dependencyInsightsPanel}>
        <div style={styles.dependencyInsightsHeader}>
          <div style={styles.dependencyInsightsTitle}>Total Dependencies ({categorizedDependencies.length})</div>
          <div style={styles.dependencyInsightsSubtitle}>
            Categorized from repository analysis. Risk levels are heuristic migration signals, not live CVE results.
          </div>
        </div>

        <div style={styles.dependencySummaryGrid}>
          <div style={getSummaryCardStyle("all")} onClick={() => handleRiskFilterClick("all")}>
            <div style={styles.dependencySummaryLabel}>Overall Risk</div>
            <div style={styles.dependencySummaryValue}>{dominantRisk.toUpperCase()}</div>
          </div>
          <div style={getSummaryCardStyle("critical")} onClick={() => handleRiskFilterClick("critical")}>
            <div style={styles.dependencySummaryLabel}>Critical</div>
            <div style={{ ...styles.dependencySummaryValue, color: "#dc2626" }}>{riskCounts.critical}</div>
          </div>
          <div style={getSummaryCardStyle("high")} onClick={() => handleRiskFilterClick("high")}>
            <div style={styles.dependencySummaryLabel}>High</div>
            <div style={{ ...styles.dependencySummaryValue, color: "#f97316" }}>{riskCounts.high}</div>
          </div>
          <div style={getSummaryCardStyle("medium")} onClick={() => handleRiskFilterClick("medium")}>
            <div style={styles.dependencySummaryLabel}>Medium</div>
            <div style={{ ...styles.dependencySummaryValue, color: "#d97706" }}>{riskCounts.medium}</div>
          </div>
          <div style={getSummaryCardStyle("low")} onClick={() => handleRiskFilterClick("low")}>
            <div style={styles.dependencySummaryLabel}>Low</div>
            <div style={{ ...styles.dependencySummaryValue, color: "#16a34a" }}>{riskCounts.low}</div>
          </div>
        </div>

        <div style={styles.dependencyFilterBar}>
          <span style={styles.dependencyFilterLabel}>Showing: {activeFilterLabel}</span>
          {dependencyRiskFilter !== "all" && (
            <button
              type="button"
              style={styles.dependencyFilterClearButton}
              onClick={() => setDependencyRiskFilter("all")}
            >
              Clear Filter
            </button>
          )}
        </div>

        {attentionDependencies.length > 0 && (
          <>
            <div style={styles.dependencyAlertBox}>
              <div style={styles.dependencyAlertTitle}>Warning: {attentionDependencies.length} dependencies need migration attention</div>
              <div style={styles.dependencyAlertText}>
                Review runtime-facing, legacy, or incomplete-version dependencies first.
                {topAttentionNames ? ` Priority artifacts: ${topAttentionNames}${attentionDependencies.length > 5 ? "..." : ""}` : ""}
              </div>
            </div>
            <div style={styles.categorizedDependenciesSection}>
              <div style={styles.categorizedDependenciesSectionTitle}>Dependencies Requiring Attention ({attentionDependencies.length})</div>
              <div style={styles.categorizedDependenciesGrid}>
                {attentionDependencies.map(renderDependencyCard)}
              </div>
            </div>
          </>
        )}

        {otherDependencies.length > 0 && (
          <div style={styles.categorizedDependenciesSection}>
            <div style={{ ...styles.categorizedDependenciesSectionTitle, color: "#166534" }}>
              Other Dependencies ({otherDependencies.length})
            </div>
            <div style={styles.categorizedDependenciesGrid}>
              {otherDependencies.map(renderDependencyCard)}
            </div>
          </div>
        )}

        {visibleDependencies.length === 0 && (
          <div style={styles.dependencyEmptyState}>
            No dependencies match the selected risk filter.
          </div>
        )}
      </div>
    );
  };

  const enrichAnalysisWithPomVersion = useCallback(async (
    analysis: RepoAnalysis,
    repoUrlToAnalyze: string,
    token: string
  ) => {
    const javaVersionFromAnalysis = analysis.java_version || analysis.java_version_from_build;
    const needsPomFallback =
      (analysis.build_tool === "maven" || analysis.structure?.has_pom_xml) &&
      (!javaVersionFromAnalysis || javaVersionFromAnalysis === "unknown" || javaVersionFromAnalysis === "not_specified");

    if (!needsPomFallback) {
      return analysis;
    }

    try {
      const response = isLocalRepoRef(repoUrlToAnalyze)
        ? await getLocalProjectFileContent(extractLocalRepoPath(repoUrlToAnalyze), "pom.xml")
        : await getFileContent(repoUrlToAnalyze, "pom.xml", token);
      const fallbackJavaVersion = detectJavaVersionFromPomContent(response.content || "");
      if (!fallbackJavaVersion) {
        return analysis;
      }

      return {
        ...analysis,
        java_version: fallbackJavaVersion,
        java_version_from_build: fallbackJavaVersion,
        java_version_detected_from_build: true,
      };
    } catch {
      return analysis;
    }
  }, []);

  const applyRepositoryAnalysis = useCallback((analysis: RepoAnalysis) => {
    setRepoAnalysis(analysis);
    const javaVersionFromBuild = analysis.java_version || analysis.java_version_from_build || null;
    const hasJavaIndicators =
      (Array.isArray(analysis.java_files) && analysis.java_files.length > 0) ||
      (javaVersionFromBuild !== "unknown" && javaVersionFromBuild !== null) ||
      analysis.build_tool === "maven" || analysis.build_tool === "gradle" ||
      analysis.structure?.has_pom_xml || analysis.structure?.has_build_gradle ||
      (analysis.dependencies && analysis.dependencies.length > 0);
    setIsJavaProject(hasJavaIndicators);

    const hasBuildConfig = analysis.structure?.has_pom_xml || analysis.structure?.has_build_gradle ||
      analysis.build_tool === "maven" || analysis.build_tool === "gradle";
    const hasKnownJavaVersion = javaVersionFromBuild && javaVersionFromBuild !== "unknown";

    if (hasJavaIndicators && (!hasBuildConfig || !hasKnownJavaVersion)) {
      setIsHighRiskProject(true);
      if (hasKnownJavaVersion) {
        setSuggestedJavaVersion(javaVersionFromBuild!);
        setSourceVersionStatus("detected");
      } else {
        setSuggestedJavaVersion("17");
        setSourceVersionStatus("unknown");
      }
    } else {
      setIsHighRiskProject(false);
    }

    const frameworks: { name: string; path: string; type: string }[] = [];
    if (analysis.dependencies) {
      analysis.dependencies.forEach((dep: DependencyInfo & { file_path?: string }) => {
        const artifactId = dep.artifact_id?.toLowerCase() || "";
        const groupId = dep.group_id?.toLowerCase() || "";

        if (artifactId.includes("junit") || groupId.includes("junit")) {
          frameworks.push({ name: "JUnit", path: dep.file_path || "pom.xml", type: "Testing Framework" });
        }
        if (artifactId.includes("spring") || groupId.includes("springframework")) {
          frameworks.push({ name: "Spring Framework", path: dep.file_path || "pom.xml", type: "Application Framework" });
        }
        if (artifactId.includes("hibernate") || groupId.includes("hibernate")) {
          frameworks.push({ name: "Hibernate", path: dep.file_path || "pom.xml", type: "ORM Framework" });
        }
        if (artifactId.includes("lombok")) {
          frameworks.push({ name: "Lombok", path: dep.file_path || "pom.xml", type: "Code Generation" });
        }
        if (artifactId.includes("mockito")) {
          frameworks.push({ name: "Mockito", path: dep.file_path || "pom.xml", type: "Mocking Framework" });
        }
        if (artifactId.includes("log4j") || artifactId.includes("slf4j") || artifactId.includes("logback")) {
          frameworks.push({ name: dep.artifact_id, path: dep.file_path || "pom.xml", type: "Logging" });
        }
        if (artifactId.includes("jackson") || artifactId.includes("gson")) {
          frameworks.push({ name: dep.artifact_id, path: dep.file_path || "pom.xml", type: "JSON Processing" });
        }
        if (artifactId.includes("apache-commons") || groupId.includes("commons-")) {
          frameworks.push({ name: dep.artifact_id, path: dep.file_path || "pom.xml", type: "Utility Library" });
        }
      });
    }

    const uniqueFrameworks = frameworks.filter((fw, index, self) =>
      index === self.findIndex(f => f.name === fw.name)
    );
    setDetectedFrameworks(uniqueFrameworks);

    if (javaVersionFromBuild && javaVersionFromBuild !== "unknown") {
      setSelectedSourceVersion(javaVersionFromBuild);
    }

    const hasTests = analysis.has_tests;
    const hasBuildTool = analysis.build_tool !== null;
    if (hasTests && hasBuildTool) setRiskLevel("low");
    else if (hasBuildTool) setRiskLevel("medium");
    else setRiskLevel("high");
  }, [
    setDetectedFrameworks,
    setIsHighRiskProject,
    setIsJavaProject,
    setRepoAnalysis,
    setRiskLevel,
    setSelectedSourceVersion,
    setSourceVersionStatus,
    setSuggestedJavaVersion,
  ]);

  function resetRepositorySelectionState() {
    setError("");
    setRepoAnalysis(null);
    setRepoFiles([]);
    setRepoPreviewInitialized(false);
    setCurrentPath("");
    setPathHistory([""]);
    setSelectedFile(null);
    setFileContent("");
    setEditedContent("");
    setIsEditing(false);
    setIsJavaProject(null);
    setDetectedFrameworks([]);
    setMicroserviceResult(null);
    setMicroserviceLoading(false);
    setMicroserviceAssessmentResolved(false);
    setMicroserviceAccordionState(createDefaultMicroserviceAccordionState());
    setIsMicroserviceEligibilityCollapsed(false);
    setShowAllMicroserviceServices(false);
    setActiveScoreTooltip(null);
    setMicroserviceExpandedSections({});
    setPrefetchedBrdDocument(null);
    setDocumentPrefetchStatus("idle");
    documentPrefetchKeyRef.current = "";
    documentPrefetchPromiseRef.current = null;
  }

  const testsRun = migrationJob?.tests_run ?? 0;
  const testsFailed = migrationJob?.tests_failed ?? 0;
  const hasExecutedTests = testsRun > 0;
  const functionalTesting = migrationJob?.test_pipeline?.functional_testing ?? (migrationJob as any)?.functional_pipeline ?? null;
  const functionalTestsRun = typeof functionalTesting?.total_tests_run === "number"
    ? functionalTesting.total_tests_run
    : typeof functionalTesting?.tests_run === "number"
      ? functionalTesting.tests_run
      : 0;
  const functionalTestsPassed = typeof functionalTesting?.tests_passed === "number"
    ? functionalTesting.tests_passed
    : typeof functionalTesting?.passed === "number"
      ? functionalTesting.passed
      : Math.max(0, (typeof functionalTesting?.total_tests === "number" ? functionalTesting.total_tests : (functionalTesting?.total_tests_run ?? 0)) - (typeof functionalTesting?.tests_failed === "number" ? functionalTesting.tests_failed : 0));
  const functionalTestsFailed = typeof functionalTesting?.tests_failed === "number"
    ? functionalTesting.tests_failed
    : 0;
  const functionalTotalTests = typeof functionalTesting?.total_tests === "number"
    ? functionalTesting.total_tests
    : typeof functionalTesting?.total_tests_run === "number"
      ? functionalTesting.total_tests_run
      : functionalTestsRun;
  const hasExecutedFunctionalTests = functionalTestsRun > 0;

  const testSummaryMetrics = getTestSummaryMetrics(migrationJob?.test_pipeline?.test_summary_metrics);
  const repoTotalFiles = testSummaryMetrics?.repo_total_files ?? 0;
  const existingTestFiles = testSummaryMetrics?.existing_test_files ?? 0;
  const newTestFiles = testSummaryMetrics?.new_test_files ?? 0;
  const existingTestCases = testSummaryMetrics?.existing_test_cases ?? 0;
  const generatedTestCases = testSummaryMetrics?.generated_test_cases ?? 0;
  const totalTestCases = testSummaryMetrics?.total_test_cases ?? (existingTestCases + generatedTestCases);
  const migrationJavaVersion = testSummaryMetrics?.java_migration_version ?? "";
  const jacocoCoverageAvailable = migrationJob?.test_pipeline?.coverage_result?.available;
  const jacocoCoveragePct =
    jacocoCoverageAvailable === false
      ? null
      : migrationJob?.test_pipeline?.coverage_result?.line_coverage_pct ??
        migrationJob?.test_pipeline?.coverage_result?.line_coverage ??
        null;
  const testSummaryReportDate = migrationJob?.completed_at
    ? new Date(migrationJob.completed_at).toLocaleDateString()
    : new Date().toLocaleDateString();
  const testSummaryFallback = testsRun === 0
    ? "Tests not executed yet"
    : testsFailed > 0
      ? `${testsFailed} test${testsFailed === 1 ? "" : "s"} failed`
      : "All unit tests passed successfully";
  const testSummaryText = migrationJob?.test_summary ?? testSummaryFallback;
  const testInsights = migrationJob?.test_insights ?? [];
  const testModel = migrationJob?.test_llm_model;
  const hasTestFailures = hasExecutedTests && testsFailed > 0;
  const testStatusIcon = !hasExecutedTests
    ? <FaExclamationCircle />
    : hasTestFailures
      ? <FaExclamationTriangle />
      : <FaCheckCircle />;
  const testStatusColors = !hasExecutedTests
    ? { background: "#fffbeb", borderColor: "#fcd34d", textColor: "#92400e" }
    : hasTestFailures
      ? { background: "#fee2e2", borderColor: "#fca5a5", textColor: "#991b1b" }
      : { background: "#dcfce7", borderColor: "#86efac", textColor: "#166534" };
  const testSummaryItems = [
    { label: "Total Files In Repo", value: repoTotalFiles },
    { label: "Existing Test Files", value: existingTestFiles },
    { label: "New Test Files", value: newTestFiles },
    { label: "Existing Test Cases", value: existingTestCases },
    { label: "Generated Test Cases", value: `+${generatedTestCases}` },
    { label: "Total Test Cases", value: totalTestCases },
    {
      label: "BL Business logic coverage %",
      value: typeof migrationJob?.bl_coverage === "number" ? `${migrationJob.bl_coverage.toFixed(1)}%` : "N/A",
    },
    {
      label: "JaCoCo Coverage",
      value: typeof jacocoCoveragePct === "number" ? `${jacocoCoveragePct.toFixed(1)}%` : "N/A",
    },
  ];

  const handleRerunTests = useCallback(async () => {
    if (!migrationJob) return;
    setRerunTestsLoading(true);
    try {
      const updated = await rerunMigrationTests(
        migrationJob.job_id,
        selectedLLMProvider,
        useLLMTests
      );
      setMigrationJob((prev) => (prev ? { ...prev, ...updated } : prev));
      const logs = await getMigrationLogs(migrationJob.job_id);
      setMigrationLogs(logs.logs || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to re-run tests");
    } finally {
      setRerunTestsLoading(false);
    }
  }, [migrationJob, selectedLLMProvider, setMigrationJob, setMigrationLogs, setRerunTestsLoading, useLLMTests]);

  const handleDownloadUnitTestReport = useCallback(async () => {
    if (!migrationJob) return;
    try {
      const blob = await downloadUnitTestReport(migrationJob.job_id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `unit-test-report-${migrationJob.job_id}.html`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download unit test report");
    }
  }, [migrationJob]);

  const handleOpenFrameworkFile = useCallback(async (framework: { name: string; path: string; type: string }) => {
    if (!selectedRepo) return;

    setFrameworkFileLoading(true);
    setViewingFrameworkFile({ name: framework.name, path: framework.path, content: "" });
    try {
      const response = isLocalRepoRef(selectedRepo.url)
        ? await getLocalProjectFileContent(extractLocalRepoPath(selectedRepo.url), framework.path)
        : await getFileContent(selectedRepo.url, framework.path, currentToken);
      setViewingFrameworkFile({ name: framework.name, path: framework.path, content: response.content });
    } catch {
      setViewingFrameworkFile({ name: framework.name, path: framework.path, content: `// Error loading file: ${framework.path}` });
    } finally {
      setFrameworkFileLoading(false);
    }
  }, [currentToken, selectedRepo, setFrameworkFileLoading, setViewingFrameworkFile]);

  const technicalSpecificationButtonLabel =
    documentGenerationLoading === "brd"
      ? "Generating Document..."
      : documentPrefetchStatus === "loading"
          ? "Preparing Document..."
          : "Generate Document";

  const technicalSpecificationHelperText = documentPrefetchStatus === "loading"
      ? "Preparing the Technical Specification Document in the background."
      : documentPrefetchStatus === "ready"
          ? "The Technical Specification Document is ready to download."
          : "The Technical Specification Document will be generated when you choose to download it.";

  useEffect(() => {
    let retryTimeout: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const fetchVersions = () => {
      getJavaVersions()
        .then((versions) => {
          if (!cancelled) {
            setTargetVersions(versions.target_versions);
          }
        })
        .catch(() => {
          // Backend may not be running yet — retry after 5 seconds
          if (!cancelled) {
            retryTimeout = setTimeout(fetchVersions, 5000);
          }
        });
    };

    fetchVersions();

    return () => {
      cancelled = true;
      if (retryTimeout) clearTimeout(retryTimeout);
    };
  }, [setTargetVersions]);

  useEffect(() => {
    const routeStep = getStepFromPath(location.pathname);
    setStep((currentStep) => (routeStep !== currentStep ? routeStep : currentStep));
  }, [location.pathname]);

  useEffect(() => {
    setMaxVisitedIndicatorStep((currentMax) =>
      Math.max(currentMax, getIndicatorStep(step))
    );
  }, [step]);

  useEffect(() => {
  window.scrollTo({ top: 0, behavior: "auto" });
  }, [step]);

  useEffect(() => {
    const targetRoute = STEP_ROUTES[step] || "/";
    const currentRoute = location.pathname.replace(/\/+$/, "") || "/";

    // if (currentRoute !== targetRoute) {
    //   navigate(targetRoute);
    // }
    if (currentRoute !== targetRoute) {
  navigate(targetRoute, { replace: step === 7 });
}

  }, [step, location.pathname, navigate]);

  // Load GitHub token from localStorage on component mount
  useEffect(() => {
    const token = localStorage.getItem("github_token");
    if (token) {
      setGithubToken(token);
    }
    try {
      const storedGithubUser = localStorage.getItem("github_user");
      if (storedGithubUser) {
        const parsedUser = JSON.parse(storedGithubUser) as { login?: string };
        if (parsedUser?.login) {
          setGithubUserLogin(parsedUser.login);
        }
      }
    } catch {
      setGithubUserLogin("");
    }
  }, [setGithubToken, setGithubUserLogin]);

  const persistedWizardFormState = useMemo(
    () =>
      ({
      maxVisitedIndicatorStep,
      isPrivateRepo,
      patToken,
      currentPath,
      targetRepoName,
      targetRepoNamesByApproach,
      targetRepoNameEditedByApproach,
      targetRepoTimestamp,
      selectedSourceVersion,
      selectedTargetVersion,
      selectedConversions,
      runTests,
      runSonar,
      runFossa,
      fixBusinessLogic,
      functionalTestToolMethods,
      functionalTestExecutionMode,
      migrationApproach,
      riskLevel,
      selectedFrameworks,
      isJavaProject,
      pathHistory,
      isHighRiskProject,
      highRiskConfirmed,
      suggestedJavaVersion,
      detectedFrameworks,
      userSelectedVersion,
      sourceVersionStatus,
      updateSourceVersion,
      analysisCompletedSeconds,
    } satisfies PersistedWizardFormState),
    [
    maxVisitedIndicatorStep,
    isPrivateRepo,
    patToken,
    currentPath,
    targetRepoName,
    targetRepoNamesByApproach,
    targetRepoNameEditedByApproach,
    targetRepoTimestamp,
    selectedSourceVersion,
    selectedTargetVersion,
    selectedConversions,
    runTests,
    runSonar,
    runFossa,
    fixBusinessLogic,
    functionalTestExecutionMode,
    migrationApproach,
    riskLevel,
    selectedFrameworks,
    isJavaProject,
    pathHistory,
    isHighRiskProject,
    highRiskConfirmed,
    suggestedJavaVersion,
    detectedFrameworks,
    userSelectedVersion,
    sourceVersionStatus,
    updateSourceVersion,
    analysisCompletedSeconds,
    ]
  );

  useMigrationWizardPersistence({
    repoUrl,
    selectedRepo,
    repoAnalysis,
    migrationJob,
    formState: persistedWizardFormState,
  });

  useEffect(() => {
    if (migrationJob?.fossa_report) {
      setFossaResult(migrationJob.fossa_report);
      fossaLoadedJobIdRef.current = migrationJob.job_id;
      return;
    }

    if (fossaResult && migrationJob?.job_id !== fossaLoadedJobIdRef.current) {
      setFossaResult(null);
    }
  }, [fossaResult, migrationJob?.job_id, migrationJob?.fossa_report, setFossaResult]);

  // Load detailed FOSSA results only when the report view needs them.
  useEffect(() => {
    const jobId = migrationJob?.job_id;
    const shouldLoadFossa =
      Boolean(jobId) &&
      step === 7 &&
      reportAccordionState.fossa &&
      (runFossa ||
        migrationJob?.fossa_policy_status != null ||
        migrationJob?.fossa_scan_mode != null ||
        migrationJob?.fossa_error_message != null ||
        migrationJob?.fossa_report != null);

    if (!jobId || !shouldLoadFossa) {
      return;
    }

    if (migrationJob?.fossa_report || fossaLoadedJobIdRef.current === jobId) {
      return;
    }

    let cancelled = false;
    setFossaLoading(true);

    getMigrationFossa(jobId)
      .then(({ fossa }) => {
        if (cancelled) return;

        fossaLoadedJobIdRef.current = jobId;
        setFossaResult(fossa);
        setMigrationJob((prev) =>
          prev
            ? {
                ...prev,
                fossa_policy_status: fossa.compliance_status ?? prev.fossa_policy_status,
                fossa_total_dependencies: fossa.total_dependencies ?? prev.fossa_total_dependencies,
                fossa_license_issues: fossa.license_issues ?? prev.fossa_license_issues,
                fossa_vulnerabilities:
                  typeof fossa.vulnerabilities === "number"
                    ? fossa.vulnerabilities
                    : fossa.vulnerabilities && typeof fossa.vulnerabilities === "object"
                      ? Object.values(fossa.vulnerabilities).reduce((sum, value) => sum + (Number(value) || 0), 0)
                      : prev.fossa_vulnerabilities,
                fossa_outdated_dependencies: fossa.outdated_dependencies ?? prev.fossa_outdated_dependencies,
                fossa_scan_mode: fossa.scan_mode ?? prev.fossa_scan_mode,
                fossa_real_scan: fossa.real_scan ?? prev.fossa_real_scan,
                fossa_analysis_url: fossa.analysis_url ?? prev.fossa_analysis_url,
                fossa_error_message: fossa.error_message ?? prev.fossa_error_message,
                fossa_report: fossa,
              }
            : prev
        );
      })
      .catch(() => {
        if (!cancelled) {
          fossaLoadedJobIdRef.current = null;
        }
      })
      .finally(() => {
        if (!cancelled) {
          setFossaLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    migrationJob?.fossa_error_message,
    migrationJob?.fossa_policy_status,
    migrationJob?.fossa_report,
    migrationJob?.fossa_scan_mode,
    migrationJob?.job_id,
    reportAccordionState.fossa,
    runFossa,
    setFossaLoading,
    setFossaResult,
    setMigrationJob,
    step,
  ]);

  const getFossaVulnerabilityTotal = (report: FossaScanResult | null | undefined, fallbackValue: number = 0) => {
    if (report?.details_available === false && report?.issue_count != null) return null;
    const value = report?.vulnerabilities;
    if (typeof value === "number") return value;
    if (value && typeof value === "object") {
      return Object.values(value).reduce((sum, item) => sum + (Number(item) || 0), 0);
    }
    return fallbackValue;
  };

  const getFossaLicenseIssueCount = (report: FossaScanResult | null | undefined, fallbackValue: number = 0) => {
    if (report?.details_available === false && report?.issue_count != null) return null;
    if (typeof report?.license_issues === "number") return report.license_issues;
    if (report?.licenses && typeof report.licenses === "object") {
      return Number(report.licenses.UNKNOWN || 0);
    }
    return fallbackValue;
  };

  const getFossaSeverityCounts = (report: FossaScanResult | null | undefined) => {
    if (!report?.vulnerabilities || typeof report.vulnerabilities !== "object") {
      return null;
    }
    return {
      critical: Number(report.vulnerabilities.critical || 0),
      high: Number(report.vulnerabilities.high || 0),
      medium: Number(report.vulnerabilities.medium || 0),
      low: Number(report.vulnerabilities.low || 0),
    };
  };

  const getFossaScanModeLabel = (mode: string | null | undefined) => {
    switch (mode) {
      case "real":
        return "Real scan";
      case "real_limited":
        return "Real scan, limited details";
      case "simulated":
        return "Simulated result";
      case "unavailable":
        return "Unavailable";
      case "pending":
        return "Pending";
      default:
        return mode || "N/A";
    }
  };

  const formatSonarTimestamp = (value: string | null | undefined) => {
    if (!value) return "N/A";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
  };

  const getSonarSeverityColor = (severity: string | null | undefined) => {
    const normalized = (severity || "").toUpperCase();
    if (normalized === "BLOCKER" || normalized === "CRITICAL") return { background: "#fee2e2", color: "#991b1b" };
    if (normalized === "MAJOR" || normalized === "HIGH") return { background: "#ffedd5", color: "#9a3412" };
    if (normalized === "MINOR" || normalized === "MEDIUM") return { background: "#fef3c7", color: "#92400e" };
    return { background: "#e0f2fe", color: "#1d4ed8" };
  };

  const getSonarStatusColor = (status: string | null | undefined) => {
    const normalized = (status || "").toUpperCase();
    if (normalized === "OPEN" || normalized === "TO_REVIEW") return { background: "#fee2e2", color: "#991b1b" };
    if (normalized === "CONFIRMED" || normalized === "IN_REVIEW") return { background: "#ffedd5", color: "#9a3412" };
    if (normalized === "ACCEPTED" || normalized === "SAFE") return { background: "#dcfce7", color: "#166534" };
    return { background: "#f1f5f9", color: "#475569" };
  };

  const getSonarIssueSeverityValue = (issue: SonarIssueDetail | SonarHotspotDetail) =>
    ((issue as SonarHotspotDetail).vulnerability_probability ??
      (issue as SonarIssueDetail).severity ??
      null);

  const getCodeSmellSeverityBucket = (
    severity: string | null | undefined
  ): Exclude<CodeSmellSeverityFilter, "all"> => {
    const normalized = (severity || "").toUpperCase();
    if (normalized === "BLOCKER") return "blocker";
    if (normalized === "CRITICAL") return "high";
    if (normalized === "MAJOR") return "medium";
    return "low";
  };

  const reportCodeChanges = useMemo(
    () => buildCodeChangesFromPreviewDiffs(migrationJob?.file_diffs || []),
    [migrationJob?.file_diffs]
  );
  const visibleReportCodeChanges = useMemo(
    () => reportCodeChanges.slice(0, visibleReportDiffCount),
    [reportCodeChanges, visibleReportDiffCount]
  );
  const hasMoreReportCodeChanges = visibleReportDiffCount < reportCodeChanges.length;

  useEffect(() => {
    setVisibleReportDiffCount(REPORT_DIFFS_PAGE_SIZE);
  }, [migrationJob?.job_id, setVisibleReportDiffCount]);

  useEffect(() => {
    setReportDependencyPage(1);
  }, [migrationJob?.dependencies?.length, migrationJob?.job_id, setReportDependencyPage]);

  useEffect(() => {
    if (step !== 7 || !migrationJob?.job_id) {
      return;
    }

    if (migrationDetailLoadedJobId === migrationJob.job_id) {
      return;
    }

    let cancelled = false;

    getMigrationDetail(migrationJob.job_id)
        .then((job) => {
          if (cancelled) return;
          setMigrationJob(job);
        setMigrationDetailLoadedJobId(job.job_id);
      })
      .catch(() => {
        if (cancelled) return;
      });

    return () => {
      cancelled = true;
    };
  }, [migrationDetailLoadedJobId, migrationJob?.job_id, setMigrationDetailLoadedJobId, setMigrationJob, step]);

  useEffect(() => {
    const activeChanges = step === 7 ? visibleReportCodeChanges : codeChanges;

    if (activeChanges.length === 0) {
      if (selectedDiffFile !== null) {
        setSelectedDiffFile(null);
      }
      return;
    }

    const selectedStillExists =
      selectedDiffFile !== null &&
      activeChanges.some((change) => change.filePath === selectedDiffFile);

    if (!selectedStillExists) {
      setSelectedDiffFile(activeChanges[0].filePath);
    }
  }, [codeChanges, selectedDiffFile, setSelectedDiffFile, step, visibleReportCodeChanges]);

  const detectedJavaVersion = (repoAnalysis?.java_version || repoAnalysis?.java_version_from_build || "").toString().trim();
  const detectedJavaStructureLabel = detectedJavaVersion ? `Java ${detectedJavaVersion}` : "Java version missing";
  const detectedSourceBuildTool = repoAnalysis?.build_tool ||
    // (repoAnalysis?.structure?.has_pom_xml ? "maven" : repoAnalysis?.structure?.has_build_gradle ? "gradle" : null);
    (repoAnalysis?.structure?.has_pom_xml ? "maven" : (repoAnalysis?.structure?.has_build_gradle || repoAnalysis?.structure?.has_build_gradle_kts) ? "gradle" : null);

  // const plannedBuildTool =
  //   selectedConversions.includes("maven_to_gradle")
  //     ? "gradle"
  //     : selectedConversions.includes("gradle_to_maven")
  //       ? "maven"
  //       : detectedSourceBuildTool;
  // const buildToolDisplayLabel =
  //   detectedSourceBuildTool && plannedBuildTool && detectedSourceBuildTool !== plannedBuildTool
  //     ? `${detectedSourceBuildTool} -> ${plannedBuildTool}`
  //     : plannedBuildTool || "Not Detected";
  
  const buildToolDisplayLabel = detectedSourceBuildTool || "Not Detected";
  const strategyRiskExplanation =
    riskLevel === "low"
      ? "The project is already on a modern migration path with build tooling and tests detected."
      : riskLevel === "medium"
        ? "The project has build tooling, but tests are missing or limited."
        : "The project needs extra review because build tooling or Java metadata was not detected.";
  const selectedSourceVersionNumber = parseJavaVersion(selectedSourceVersion);
  const highestSupportedTargetVersion = useMemo(() => {
    return targetVersions.reduce<number | null>((highest, version) => {
      const parsed = parseJavaVersion(version.value);
      if (parsed === null) {
        return highest;
      }
      return highest === null || parsed > highest ? parsed : highest;
    }, null);
  }, [targetVersions]);
  const sourceAlreadyAtLatestSupportedVersion =
    selectedSourceVersionNumber !== null &&
    highestSupportedTargetVersion !== null &&
    selectedSourceVersionNumber >= highestSupportedTargetVersion;

  const availableTargetVersions = useMemo(() => {
    if (selectedSourceVersionNumber === null) {
      return [];
    }

    return targetVersions.filter((version) => {
      const targetVersionNumber = parseJavaVersion(version.value);
      return targetVersionNumber !== null && targetVersionNumber > selectedSourceVersionNumber;
    });
  }, [selectedSourceVersionNumber, targetVersions]);
  const effectiveTargetVersion = sourceAlreadyAtLatestSupportedVersion
    ? selectedSourceVersion
    : selectedTargetVersion;

  const versionRecommendationCards = useMemo(() => {
    if (!versionRecommendation) {
      return [];
    }

    const ltsJavaVersions = new Set(["8", "11", "17", "21", "25"]);

    const orderedVersions = [
      ...(versionRecommendation.recommended_versions?.length
        ? versionRecommendation.recommended_versions
        : [versionRecommendation.recommended_target_version]),
      ...versionRecommendation.alternatives,
    ].filter(
      (value, index, values) =>
        Boolean(value) &&
        values.indexOf(value) === index &&
        ltsJavaVersions.has(value)
    );

    const cards = orderedVersions
      .map((version, index) => {
        const matchedVersion = availableTargetVersions.find((item) => item.value === version);
        if (!matchedVersion) {
          return null;
        }

        const alternativeDetail = versionRecommendation.alternative_options?.find((option) => option.version === version);
        const isPrimary = version === versionRecommendation.recommended_target_version;
        const isLts = ltsJavaVersions.has(version);
        const description = isPrimary
          ? versionRecommendation.rationale.slice(0, 2).join(" ")
          : alternativeDetail?.reason || `Compatible upgrade path from Java ${selectedSourceVersion}.`;

        return {
          version,
          label: matchedVersion.label,
          eyebrow: isPrimary ? (isLts ? "Recommended LTS" : "Recommended") : (isLts ? "LTS" : "Feature Release"),
          description,
          helper: isPrimary
            ? `Confidence: ${versionRecommendation.confidence}`
            : alternativeDetail?.risk
              ? `Risk: ${alternativeDetail.risk}`
              : `Click to select Java ${version}`,
          badgeBackground: isLts ? "#dcfce7" : "#ffedd5",
          badgeColor: isLts ? "#15803d" : "#c2410c",
          rank: index,
        };
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item));

    if (cards.length > 0) {
      return cards;
    }

    const fallbackTarget =
      availableTargetVersions.find((item) => ltsJavaVersions.has(item.value)) ||
      availableTargetVersions[availableTargetVersions.length - 1];

    if (!fallbackTarget) {
      return [];
    }

    return [
      {
        version: fallbackTarget.value,
        label: fallbackTarget.label,
        eyebrow: "Recommended LTS",
        description:
          versionRecommendation.rationale.slice(0, 2).join(" ") ||
          `Recommended upgrade path from Java ${selectedSourceVersion}.`,
        helper: `Confidence: ${versionRecommendation.confidence}`,
        badgeBackground: "#dcfce7",
        badgeColor: "#15803d",
        rank: 0,
      },
    ];
  }, [availableTargetVersions, selectedSourceVersion, versionRecommendation]);

  const categorizedStrategyDependencies = useMemo(() => categorizeDependencies(repoAnalysis?.dependencies || []), [repoAnalysis?.dependencies]);
  const dependencyRiskSummary = useMemo(() => {
    return categorizedStrategyDependencies.reduce(
      (acc, dependency) => {
        acc[dependency.risk] += 1;
        return acc;
      },
      { critical: 0, high: 0, medium: 0, low: 0 } as Record<DependencyRiskLevel, number>
    );
  }, [categorizedStrategyDependencies]);
  const attentionStrategyDependencies = useMemo(
    () =>
      categorizedStrategyDependencies
        .filter((dependency) => dependency.risk !== "low")
        .slice(0, 8)
        .map((dependency) => ({
          display_name: dependency.displayName,
          current_version: dependency.current_version,
          risk: dependency.risk,
          reason: dependency.reason,
          status: dependency.status,
          category: dependency.category,
        })),
    [categorizedStrategyDependencies]
  );

  const strategyAssistantContext = useMemo<StrategyPageContext>(() => {
    const dependencyOverview = (repoAnalysis?.dependencies || [])
      .slice(0, 6)
      .map((dependency) => ({
        group_id: dependency.group_id,
        artifact_id: dependency.artifact_id,
        current_version: dependency.current_version,
        status: dependency.status,
      }));

    const recommendation = versionRecommendation
      ? {
          recommended_target_version: versionRecommendation.recommended_target_version,
          recommended_versions: versionRecommendation.recommended_versions?.slice(0, 3) ?? [],
          confidence: versionRecommendation.confidence,
          rationale: versionRecommendation.rationale.slice(0, 2),
          alternatives: versionRecommendation.alternatives.slice(0, 2),
          alternative_options: versionRecommendation.alternative_options?.slice(0, 3) ?? [],
        }
      : undefined;

    return {
      page: "Assessment & Migration Strategy",
      repository: {
        name: selectedRepo?.name ?? repoAnalysis?.name ?? null,
        full_name: selectedRepo?.full_name ?? repoAnalysis?.full_name ?? null,
        url: selectedRepo?.url ?? repoUrl ?? null,
        language: repoAnalysis?.language ?? null,
      },
      assessment: {
        risk_level: riskLevel || "unknown",
        risk_reason: strategyRiskExplanation,
        build_tool: buildToolDisplayLabel,
        java_version: repoAnalysis?.java_version || repoAnalysis?.java_version_from_build || null,
        has_tests: typeof repoAnalysis?.has_tests === "boolean" ? repoAnalysis.has_tests : null,
        dependency_count: repoAnalysis?.dependencies?.length ?? 0,
      },
      strategy: {
        source_java_version: selectedSourceVersion || null,
        target_java_version: effectiveTargetVersion || null,
        selected_conversions: selectedConversions.slice(0, 5),
        source_already_at_latest_supported_version: sourceAlreadyAtLatestSupportedVersion,
      },
      migration_destination: {
        approach: currentMigrationApproach,
        label:
          migrationApproachOptions.find((option) => option.value === currentMigrationApproach)?.label ||
          null,
        description:
          migrationApproachOptions.find((option) => option.value === currentMigrationApproach)?.desc ||
          null,
        target_repo_name: targetRepoName || getAutoGeneratedTargetName(currentMigrationApproach),
        target_repo_owner: targetRepositoryOwner,
        target_repo_host: targetRepositoryHost,
        target_repo_name_editable: currentMigrationApproach !== "fork",
        target_repo_name_source: targetRepoNameEditedByApproach[currentMigrationApproach]
          ? "manual"
          : "auto-generated",
      },
      migration_approach_options: migrationApproachOptions.map((option) => ({
        value: option.value,
        label: option.label,
        desc: option.desc,
        tooltip: option.tooltip,
      })),
      recommendation,
      dependency_overview: dependencyOverview,
      dependency_risk_summary: dependencyRiskSummary,
      attention_dependencies: attentionStrategyDependencies,
      conversion_options: [
        {
          key: "java_version",
          title: "Java Version Upgrade",
          status: "active",
          description: "Upgrade Java version with dependency updates",
        },
        {
          key: "build_conversion",
          title: "Maven -> Gradle | Gradle -> Maven",
          status: "coming_soon",
          description: "Convert pom.xml to build.gradle with dependency mapping",
        },
        {
          key: "business_logic",
          title: "Business Logic Refactoring",
          status: "coming_soon",
          description: "Analyze and rewrite migration-sensitive code paths",
        },
      ],
    };
  }, [
    buildToolDisplayLabel,
    effectiveTargetVersion,
    repoAnalysis?.dependencies,
    repoAnalysis?.full_name,
    repoAnalysis?.java_version,
    repoAnalysis?.java_version_from_build,
    repoAnalysis?.language,
    repoAnalysis?.name,
    repoUrl,
    riskLevel,
    selectedConversions,
    selectedRepo?.full_name,
    selectedRepo?.name,
    selectedRepo?.url,
    selectedSourceVersion,
    sourceAlreadyAtLatestSupportedVersion,
    strategyRiskExplanation,
    dependencyRiskSummary,
    attentionStrategyDependencies,
    versionRecommendation,
    currentMigrationApproach,
    targetRepoName,
    targetRepoNameEditedByApproach,
    targetRepositoryHost,
    targetRepositoryOwner,
    migrationApproachOptions,
    getAutoGeneratedTargetName,
  ]);

  const plannedCodeRefactoringTooltip = useMemo(() => {
    const previewDescriptions = migrationPreview
      ? Array.from(
          new Map(
            Object.values(migrationPreview.changes.file_changes)
              .flatMap((fileChanges) => fileChanges)
              .map((change) => [change.description, change])
          ).values()
        )
      : [];

    const refactoringSteps = previewDescriptions.length > 0
      ? previewDescriptions.slice(0, 5).map((change) => {
          const occurrences = change.occurrences && change.occurrences > 1
            ? ` (${change.occurrences} matches)`
            : "";
          return `${change.description}${occurrences}`;
        })
      : [
          `Upgrade Java language and build compatibility from Java ${selectedSourceVersion} to Java ${effectiveTargetVersion || "the selected target version"}`,
          "Refactor deprecated or incompatible Java APIs to supported equivalents",
          "Modernize exception handling, imports, and resource-management patterns",
          "Adjust framework and dependency usage for target-version compatibility",
        ];

    if (migrationPreview?.changes.dependencies_to_update?.length) {
      refactoringSteps.push(
        `Update ${migrationPreview.changes.dependencies_to_update.length} dependency version${migrationPreview.changes.dependencies_to_update.length === 1 ? "" : "s"} for compatibility`
      );
    } else if (repoAnalysis?.dependencies?.length) {
      refactoringSteps.push("Adjust framework and dependency usage for target-version compatibility");
    }

    if (fixBusinessLogic && !refactoringSteps.some((stepItem) => stepItem.toLowerCase().includes("business logic"))) {
      refactoringSteps.push("Apply business-logic-safe fixes where migration introduces risky behavior changes");
    }

    const endpointCount = repoAnalysis?.api_endpoints?.length ?? 0;
    if (endpointCount > 0) {
      refactoringSteps.push(`Preserve and validate ${endpointCount} detected API endpoint${endpointCount === 1 ? "" : "s"} during refactoring`);
    }

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8, color: "#0f172a" }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Planned refactoring</div>
        <div style={{ fontSize: 12, lineHeight: 1.45 }}>
          {refactoringSteps.map((stepItem, index) => (
            <div key={index} style={{ marginBottom: index === refactoringSteps.length - 1 ? 0 : 6 }}>
              {index + 1}. {stepItem}
            </div>
          ))}
        </div>
      </div>
    );
  }, [
    fixBusinessLogic,
    migrationPreview,
    repoAnalysis?.api_endpoints,
    repoAnalysis?.dependencies?.length,
    effectiveTargetVersion,
    selectedSourceVersion,
  ]);

  const plannedDependenciesTooltip = useMemo(() => {
    const dependencyUpdateCount = migrationPreview?.changes.dependencies_to_update?.length ?? 0;
    const discoveredDependencyCount = repoAnalysis?.dependencies?.length ?? 0;
    const dependencyHighlights = dependencyUpdateCount > 0
      ? migrationPreview!.changes.dependencies_to_update.slice(0, 5).map((dependency) => {
          const targetVersion = dependency.new_version || "latest compatible version";
          return `${dependency.dependency}: ${dependency.current_version} -> ${targetVersion}`;
        })
      : [
          `Review ${discoveredDependencyCount} detected dependenc${discoveredDependencyCount === 1 ? "y" : "ies"} for target-version compatibility`,
          "Upgrade framework, plugin, and build-tool packages that block the migration",
          "Preserve safe versions while removing deprecated or conflicting transitive libraries",
          "Validate dependency alignment before code generation and testing",
        ];

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8, color: "#0f172a" }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Dependency upgrade plan</div>
        <div style={{ fontSize: 12, lineHeight: 1.45 }}>
          {dependencyHighlights.map((item, index) => (
            <div key={index} style={{ marginBottom: index === dependencyHighlights.length - 1 ? 0 : 6 }}>
              {index + 1}. {item}
            </div>
          ))}
        </div>
      </div>
    );
  }, [migrationPreview, repoAnalysis?.dependencies]);

  const plannedBusinessLogicTooltip = useMemo(() => {
    const endpointCount = repoAnalysis?.api_endpoints?.length ?? 0;
    const businessLogicSteps = [
      "Protect runtime behavior while upgrading null handling, error handling, and resource usage",
      "Reduce migration regressions by tightening reliability-sensitive paths before final validation",
      "Modernize risky code patterns only where the migration introduces compatibility pressure",
    ];

    if (endpointCount > 0) {
      businessLogicSteps.push(`Keep ${endpointCount} detected API endpoint${endpointCount === 1 ? "" : "s"} stable during modernization`);
    }

    if (runTests) {
      businessLogicSteps.push("Verify behavior changes against the configured test suite after refactoring");
    }

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8, color: "#0f172a" }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Business logic safeguards</div>
        <div style={{ fontSize: 12, lineHeight: 1.45 }}>
          {businessLogicSteps.map((item, index) => (
            <div key={index} style={{ marginBottom: index === businessLogicSteps.length - 1 ? 0 : 6 }}>
              {index + 1}. {item}
            </div>
          ))}
        </div>
      </div>
    );
  }, [repoAnalysis?.api_endpoints, runTests]);

  const formattedAnalysisElapsed = `${Math.floor(analysisElapsedSeconds / 60)
    .toString()
    .padStart(2, "0")}:${(analysisElapsedSeconds % 60).toString().padStart(2, "0")}`;
   
  const formattedAnalysisCompleted = `${Math.floor(analysisCompletedSeconds / 60)
  .toString()
  .padStart(2, "0")}:${(analysisCompletedSeconds % 60).toString().padStart(2, "0")}`;
  const isTechnicalDocumentWarmPending =
    Boolean(repoAnalysis) &&
    documentPrefetchStatus !== "ready" &&
    documentPrefetchStatus !== "error";
  const isDiscoveryPending =
    analysisLoading ||
    Boolean(
      repoAnalysis &&
      (!repoPreviewInitialized || !microserviceAssessmentResolved || isTechnicalDocumentWarmPending)
    );
 
  const getMigrationElapsedSeconds = () => {
    if (!migrationJob?.started_at) return 0;

    const startedAtMs = Date.parse(migrationJob.started_at);
    if (Number.isNaN(startedAtMs)) return 0;

    const completedAtMs = migrationJob.completed_at ? Date.parse(migrationJob.completed_at) : NaN;
    const endTimeMs = !Number.isNaN(completedAtMs) ? completedAtMs : migrationTimerNow;

    return Math.max(0, Math.floor((endTimeMs - startedAtMs) / 1000));
  };

  const getElapsedSecondsFromTimestamp = (startedAt: string | null | undefined) => {
    if (!startedAt) return 0;

    const startedAtMs = Date.parse(startedAt);
    if (Number.isNaN(startedAtMs)) return 0;

    const completedAtMs = migrationJob?.completed_at ? Date.parse(migrationJob.completed_at) : NaN;
    const endTimeMs = !Number.isNaN(completedAtMs) ? completedAtMs : migrationTimerNow;

    return Math.max(0, Math.floor((endTimeMs - startedAtMs) / 1000));
  };

  const migrationElapsedSeconds = getMigrationElapsedSeconds();

  const renderMigrationTimer = () => {
    if (!migrationJob?.started_at) return null;

    const normalizedTimerState = `${migrationJob?.status || ""} ${migrationJob?.current_step || ""}`.toLowerCase();
    const elapsedHours = Math.floor(migrationElapsedSeconds / 3600);
    const elapsedMinutes = Math.floor((migrationElapsedSeconds % 3600) / 60);
    const elapsedSeconds = migrationElapsedSeconds % 60;
    const elapsedSegments =
      elapsedHours > 0
        ? [
            { value: elapsedHours.toString().padStart(2, "0"), unit: "h" },
            { value: elapsedMinutes.toString().padStart(2, "0"), unit: "m" },
            { value: elapsedSeconds.toString().padStart(2, "0"), unit: "s" },
          ]
        : [
            { value: elapsedMinutes.toString().padStart(2, "0"), unit: "m" },
            { value: elapsedSeconds.toString().padStart(2, "0"), unit: "s" },
          ];
    const timerTheme = (() => {
      if (migrationJob?.status === "completed") {
        return {
          accent: "#059669",
          accentSoft: "rgba(16, 185, 129, 0.14)",
          border: "rgba(16, 185, 129, 0.24)",
          surface: "linear-gradient(135deg, #f3fff9 0%, #ecfdf5 48%, #ffffff 100%)",
          glow: "0 24px 54px rgba(16, 185, 129, 0.15)",
        };
      }

      if (migrationJob?.status === "failed") {
        return {
          accent: "#dc2626",
          accentSoft: "rgba(239, 68, 68, 0.14)",
          border: "rgba(239, 68, 68, 0.24)",
          surface: "linear-gradient(135deg, #fff7f7 0%, #fef2f2 45%, #ffffff 100%)",
          glow: "0 24px 54px rgba(239, 68, 68, 0.12)",
        };
      }

      if (normalizedTimerState.includes("analy")) {
        return {
          accent: "#0284c7",
          accentSoft: "rgba(14, 165, 233, 0.16)",
          border: "rgba(56, 189, 248, 0.26)",
          surface: "linear-gradient(135deg, #f2fbff 0%, #eef8ff 42%, #ffffff 100%)",
          glow: "0 24px 54px rgba(14, 165, 233, 0.12)",
        };
      }

      if (normalizedTimerState.includes("test") || normalizedTimerState.includes("sonar") || normalizedTimerState.includes("fossa")) {
        return {
          accent: "#d97706",
          accentSoft: "rgba(245, 158, 11, 0.16)",
          border: "rgba(251, 191, 36, 0.28)",
          surface: "linear-gradient(135deg, #fffaf0 0%, #fff7ed 45%, #ffffff 100%)",
          glow: "0 24px 54px rgba(245, 158, 11, 0.13)",
        };
      }

      return {
        accent: "#7c3aed",
        accentSoft: "rgba(124, 58, 237, 0.14)",
        border: "rgba(167, 139, 250, 0.3)",
        surface: "linear-gradient(135deg, #f8f5ff 0%, #f5f3ff 44%, #ffffff 100%)",
        glow: "0 24px 54px rgba(124, 58, 237, 0.14)",
      };
    })();

    return (
      <div style={styles.migrationTimerSection}>
        <div style={styles.migrationTimerCard}>
          <div style={styles.migrationTimerHero}>
            <div
              style={{
                ...styles.migrationTimerOrb,
                background: `radial-gradient(circle at 30% 30%, #ffffff 0%, ${timerTheme.accentSoft} 58%, rgba(255,255,255,0.92) 100%)`,
                border: `1px solid ${timerTheme.border}`,
                boxShadow: `inset 0 1px 0 rgba(255,255,255,0.72), 0 10px 22px ${timerTheme.accentSoft}`,
              }}
            >
              <div
                style={{
                  ...styles.migrationTimerOrbInner,
                  color: timerTheme.accent,
                  background: "#ffffff",
                  boxShadow: `0 0 0 8px ${timerTheme.accentSoft}`,
                }}
              >
                <FaStopwatch />
              </div>
            </div>

            <div style={styles.migrationTimerCopy}>
              <div style={{ ...styles.migrationTimerLabel, color: timerTheme.accent }}>Elapsed Time</div>
              <div style={styles.migrationTimerValue}>
                {elapsedSegments.map((segment) => (
                  <span key={`${segment.value}${segment.unit}`} style={styles.migrationTimerSegment}>
                    <span style={styles.migrationTimerDigits}>{segment.value}</span>
                    <span style={styles.migrationTimerUnit}>{segment.unit}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };
  useEffect(() => {
    if (!isDiscoveryPending) {
      return;
    }

    const startedAt = analysisStartedAtMs ?? Date.now();
    if (!analysisStartedAtMs) {
      setAnalysisStartedAtMs(startedAt);
      setAnalysisElapsedSeconds(0);
    }

    const updateElapsed = () => {
      setAnalysisElapsedSeconds(Math.max(1, Math.floor((Date.now() - startedAt) / 1000)));
    };

    updateElapsed();
    const interval = window.setInterval(updateElapsed, 1000);

    return () => window.clearInterval(interval);
  }, [isDiscoveryPending, analysisStartedAtMs, setAnalysisElapsedSeconds, setAnalysisStartedAtMs]);

  useEffect(() => {
    if (!isDiscoveryPending && analysisStartedAtMs) {
      const elapsed = Math.max(1, Math.floor((Date.now() - analysisStartedAtMs) / 1000));
      setAnalysisCompletedSeconds(elapsed);
      setAnalysisStartedAtMs(null);
    }
  }, [isDiscoveryPending, analysisStartedAtMs, setAnalysisCompletedSeconds, setAnalysisStartedAtMs]);

  useEffect(() => {
    setMigrationTimerNow(Date.now());

    if (!(step >= 5 && step <= 6 && migrationJob?.started_at)) {
      return;
    }

    if (isTerminalMigrationStatus(migrationJob.status)) {
      return;
    }

    const interval = window.setInterval(() => {
      setMigrationTimerNow(Date.now());
    }, 1000);

    return () => window.clearInterval(interval);
  }, [migrationJob?.completed_at, migrationJob?.started_at, migrationJob?.status, setMigrationTimerNow, step]);

  // Keep the progress bar aligned with the backend-reported migration phase.
  useEffect(() => {
    if (step === 5 && migrationJob) {
      const actualProgress = migrationJob.progress_percent || 0;
      if (migrationJob.status === "completed") {
        setAnimationProgress(100);
      } else if (migrationJob.status === "failed") {
        setAnimationProgress(Math.min(Math.max(actualProgress, 5), 99));
      } else {
        setAnimationProgress(Math.min(Math.max(actualProgress, 5), 99));
      }
    } else if (step !== 5) {
      setAnimationProgress(0);
    }
  }, [migrationJob, migrationJob?.progress_percent, migrationJob?.status, setAnimationProgress, step]);

  useEffect(() => {
    if (step === 2 && selectedRepo && !repoAnalysis) {
      setAnalysisLoading(true);
      setError("");

      const analyzePromise = isLocalRepoRef(selectedRepo.url)
          ? analyzeLocalProject(extractLocalRepoPath(selectedRepo.url))
            .then(async (result) => enrichAnalysisWithPomVersion(result.analysis, selectedRepo.url, ""))
        : analyzeRepoUrl(selectedRepo.url, currentToken, true)
            .then(async (result) => enrichAnalysisWithPomVersion(result.analysis, selectedRepo.url, currentToken));

      analyzePromise
        .then((analysis) => applyRepositoryAnalysis(analysis))
        .catch((err) => {
          const message = err?.message || "Failed to analyze repository.";
          if (isPrivateRepoAccessError(message)) {
            setIsPrivateRepo(true);
            setStep(1);
            setError("");
            if (currentToken.trim()) {
              // Token was provided but still failed — may be insufficient scope or expired
              setAccessTokenValidationState("invalid");
              setAccessTokenValidationMessage(
                "The provided PAT could not access this repository. Verify that your token has 'repo' scope and has not expired."
              );
            } else {
              setAccessTokenValidationState("invalid");
              setAccessTokenValidationMessage(
                "Add a GitHub Personal Access Token with repo scope to continue analyzing this private repository."
              );
            }
            return;
          }
          setError(message);
        })
        .finally(() => setAnalysisLoading(false));
    }
  }, [
    applyRepositoryAnalysis,
    currentToken,
    enrichAnalysisWithPomVersion,
    repoAnalysis,
    selectedRepo,
    setAccessTokenValidationMessage,
    setAccessTokenValidationState,
    setAnalysisLoading,
    setIsPrivateRepo,
    showEnterpriseToken,
    step,
  ]);

  useEffect(() => {
    if (step !== 3 || !repoAnalysis || !selectedSourceVersion || sourceAlreadyAtLatestSupportedVersion) {
      if (sourceAlreadyAtLatestSupportedVersion) {
        setVersionRecommendation(null);
        setVersionRecommendationLoading(false);
        setVersionRecommendationError("");
      }
      if (step !== 3) {
        setVersionRecommendation(null);
        setVersionRecommendationLoading(false);
        setVersionRecommendationError("");
      }
      return;
    }

    let cancelled = false;
    setVersionRecommendationLoading(true);
    setVersionRecommendationError("");

    getJavaVersionRecommendation({
      source_java_version: selectedSourceVersion,
      detected_java_version: repoAnalysis.java_version,
      build_tool: repoAnalysis.build_tool,
      dependencies: repoAnalysis.dependencies || [],
      has_tests: repoAnalysis.has_tests,
      api_endpoint_count: repoAnalysis.api_endpoints?.length ?? 0,
      risk_level: riskLevel || "unknown",
      llm_provider: "openai",
    })
      .then((recommendation) => {
        if (cancelled) return;
        setVersionRecommendation(recommendation);
      })
      .catch((err) => {
        if (cancelled) return;
        setVersionRecommendation(null);
        setVersionRecommendationError(err?.message || "Failed to get Java version recommendation.");
      })
      .finally(() => {
        if (!cancelled) {
          setVersionRecommendationLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [step, repoAnalysis, selectedSourceVersion, riskLevel, sourceAlreadyAtLatestSupportedVersion]);

  useEffect(() => {
    if (step !== 1 || !urlValidation.valid || showEnterpriseToken || patToken.trim()) {
      setRepoAccessCheckLoading(false);
      return;
    }

    const normalizedUrl = urlValidation.normalizedUrl;
    let cancelled = false;

    // Show loading immediately so the "Have a PAT?" hyperlink doesn't flash
    // before the debounced visibility check starts.
    setRepoAccessCheckLoading(true);

    const timer = setTimeout(() => {

        getRepoVisibility(normalizedUrl, currentToken)
        .then((visibility) => {
          if (cancelled) return;
          if (
            visibility.requires_token ||
            visibility.visibility === "private" ||
            visibility.visibility === "private_or_inaccessible"
          ) {
            setIsPrivateRepo(true);
            setError("");
            resetAccessTokenValidationState();
            return;
          }

          setIsPrivateRepo(false);
          setError("");
        })
        .catch((err) => {
          if (cancelled) return;
          // If the backend returned 400 (invalid URL parse), don't show PAT card.
          // For all other errors (network failures, 500, timeouts, etc.),
          // conservatively treat as private — the backend's anonymous fallback
          // succeeds for public repos, so reaching here means the repo is
          // genuinely private/inaccessible or the server couldn't be reached.
          const isUrlError = err?.status === 400;
          const message = err instanceof Error ? err.message : "";
          const shouldShowPrivateRepoState = !isUrlError && isPrivateRepoAccessError(message);
          setIsPrivateRepo(shouldShowPrivateRepoState);
          setError(shouldShowPrivateRepoState ? "" : message || "");
          if (shouldShowPrivateRepoState) {
            resetAccessTokenValidationState();
          }
        })
        .finally(() => {
          if (!cancelled) {
            setRepoAccessCheckLoading(false);
          }
        });
    }, 700);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    currentToken,
    patToken,
    resetAccessTokenValidationState,
    setIsPrivateRepo,
    setRepoAccessCheckLoading,
    showEnterpriseToken,
    step,
    urlValidation.normalizedUrl,
    urlValidation.valid,
  ]);

  useEffect(() => {
    if (step === 2 && selectedRepo && repoAnalysis && !analysisLoading) {
      const filesPromise = isLocalRepoRef(selectedRepo.url)
        ? listLocalProjectFiles(extractLocalRepoPath(selectedRepo.url), currentPath)
        : listRepoFiles(selectedRepo.url, currentToken, currentPath);
      filesPromise
        .then((response) => {
          setRepoFiles(response.files);
        })
        .catch((err) => setError(err.message || "Failed to list repository files."))
        .finally(() => {
          if (!currentPath) {
            setRepoPreviewInitialized(true);
          }
        });
    }
  }, [
    analysisLoading,
    currentPath,
    currentToken,
    repoAnalysis,
    selectedRepo,
    setRepoFiles,
    setRepoPreviewInitialized,
    step,
  ]);

  useEffect(() => {
    const repoReference = selectedRepo?.url || repoUrl || migrationJob?.source_repo || "";

    if (!repoAnalysis || !repoReference) {
      return;
    }

    const prefetchKey = [
      repoReference,
      currentToken || "",
      migrationJob?.job_id || "",
      repoAnalysis?.java_version || "",
      String(repoAnalysis?.java_files?.length || 0),
      String(repoAnalysis?.dependencies?.length || 0),
      String(repoAnalysis?.api_endpoints?.length || 0),
      selectedSourceVersion || "",
      effectiveTargetVersion || "",
    ].join("::");
    if (documentPrefetchKeyRef.current === prefetchKey) {
      return;
    }

    documentPrefetchKeyRef.current = prefetchKey;
    setDocumentPrefetchStatus("loading");
    setPrefetchedBrdDocument(null);

    let cancelled = false;
    const githubRequest = {
      repo_url: repoReference,
      repository_url: repoReference,
      source_repo_url: repoReference,
      token: currentToken || undefined,
      github_token: currentToken || undefined,
      job_id: migrationJob?.job_id || undefined,
      migration_job_id: migrationJob?.job_id || undefined,
      source_repo: migrationJob?.source_repo || repoReference,
      target_repo: migrationJob?.target_repo || null,
      source_java_version: repoAnalysis?.java_version || selectedSourceVersion || undefined,
      target_java_version: effectiveTargetVersion || undefined,
      document_type: "BRD",
    };
    const localProjectRequest = {
      repo_url: repoReference,
      repository_url: repoReference,
      source_repo_url: repoReference,
      source_repo: selectedRepo?.name || repoAnalysis?.name || repoReference,
      target_repo: migrationJob?.target_repo || null,
      source_java_version: repoAnalysis?.java_version || selectedSourceVersion || undefined,
      target_java_version: effectiveTargetVersion || undefined,
      document_type: "BRD",
      analysis: repoAnalysis as unknown as Record<string, unknown>,
    };

    const prefetchPromise = (isLocalRepoRef(repoReference)
      ? generateLocalProjectDocument(localProjectRequest)
      : generateGithubDocument("brd", githubRequest))
      .then(async (result) => {
        if (cancelled) return null;
        const generatedAsset = await resolveGeneratedDocumentAsset(result);
        const filename = buildHtmlFilename(result.filename, technicalDocumentFallbackRepoName);
        if (cancelled) return null;

        if (generatedAsset.html) {
          return {
            filename,
            html: generatedAsset.html,
          } satisfies PrefetchedBrdDocument;
        }

        throw new Error("Generated BRD document did not include HTML content or a download URL.");
      })
      .then((preparedAsset) => {
        if (cancelled || !preparedAsset) return null;
        setPrefetchedBrdDocument(preparedAsset);
        setDocumentPrefetchStatus("ready");
        return preparedAsset;
      })
      .catch((err) => {
        if (cancelled) return null;
        console.error("Failed to prefetch technical specification document", err);
        setDocumentPrefetchStatus("error");
        return null;
      })
      .finally(() => {
        if (documentPrefetchPromiseRef.current === prefetchPromise) {
          documentPrefetchPromiseRef.current = null;
        }
      });
    documentPrefetchPromiseRef.current = prefetchPromise;

    return () => {
      cancelled = true;
    };
  }, [
    currentToken,
    effectiveTargetVersion,
    migrationJob?.job_id,
    migrationJob?.source_repo,
    migrationJob?.target_repo,
    repoAnalysis,
    repoUrl,
    selectedRepo?.name,
    selectedRepo?.url,
    selectedSourceVersion,
    setDocumentPrefetchStatus,
    setPrefetchedBrdDocument,
    technicalDocumentFallbackRepoName,
  ]);

  // Auto-fill target names for each migration approach until the user customizes them.
  useEffect(() => {
    setTargetRepoNamesByApproach((prev) => {
      let hasChanges = false;
      const next = { ...prev };

      (["fork", "branch", "local"] as MigrationApproachValue[]).forEach((approach) => {
        if (targetRepoNameEditedByApproach[approach]) {
          return;
        }

        const generatedValue = getAutoGeneratedTargetName(approach);
        if (next[approach] !== generatedValue) {
          next[approach] = generatedValue;
          hasChanges = true;
        }
      });

      return hasChanges ? next : prev;
    });
  }, [
    getAutoGeneratedTargetName,
    setTargetRepoNamesByApproach,
    targetRepoNameEditedByApproach,
  ]);

  useEffect(() => {
    if (sourceAlreadyAtLatestSupportedVersion) {
      if (selectedTargetVersion !== selectedSourceVersion) {
        setSelectedTargetVersion(selectedSourceVersion);
      }
      if (targetVersionRequiredError) {
        setTargetVersionRequiredError(false);
      }
      return;
    }

    if (!selectedTargetVersion || targetVersions.length === 0) {
      return;
    }

    const isStillValid = availableTargetVersions.some((version) => version.value === selectedTargetVersion);
    if (!isStillValid) {
      setSelectedTargetVersion("");
    }
  }, [
    availableTargetVersions,
    selectedSourceVersion,
    selectedTargetVersion,
    setSelectedTargetVersion,
    setTargetVersionRequiredError,
    sourceAlreadyAtLatestSupportedVersion,
    targetVersionRequiredError,
    targetVersions.length,
  ]);

  useEffect(() => {
    const jobId = migrationJob?.job_id;

    if (
      step < 5 ||
      step > 6 ||
      !jobId ||
      isTerminalMigrationStatus(migrationJob?.status)
    ) {
      if (migrationPollingTimerRef.current) {
        clearTimeout(migrationPollingTimerRef.current);
        migrationPollingTimerRef.current = null;
      }
      migrationPollingInFlightRef.current = false;
      migrationPollingErrorCountRef.current = 0;
      return;
    }

    let cancelled = false;

    const clearScheduledPoll = () => {
      if (migrationPollingTimerRef.current) {
        clearTimeout(migrationPollingTimerRef.current);
        migrationPollingTimerRef.current = null;
      }
    };

    const scheduleNextPoll = (delayMs: number) => {
      clearScheduledPoll();
      migrationPollingTimerRef.current = window.setTimeout(() => {
        void pollSummary();
      }, delayMs);
    };

    const pollSummary = async () => {
      if (cancelled || migrationPollingInFlightRef.current) {
        return;
      }

      migrationPollingInFlightRef.current = true;

      try {
        const summary = await getMigrationStatusSummary(jobId);
        if (cancelled) {
          return;
        }

        migrationPollingErrorCountRef.current = 0;
        setError("");
        setMigrationJob((prev) => mergeMigrationSummaryIntoJob(prev, summary));
        getMigrationLogs(summary.job_id)
          .then((logs) => {
            if (cancelled) return;
            const nextLogs = logs.logs || [];
            setMigrationLogs(nextLogs);
            setMigrationJob((prev) =>
              prev ? { ...prev, migration_log: nextLogs } : prev
            );
          })
          .catch(() => undefined);

        const isTerminal = isTerminalMigrationStatus(summary.status);
        if (summary.status === "completed") {
          setStep(7);
        }

        if (isTerminal) {
          clearScheduledPoll();
          return;
        }

        scheduleNextPoll(getMigrationPollingDelayMs(summary.status, summary.started_at));
      } catch (err) {
        if (cancelled) {
          return;
        }

        if (err instanceof ApiError && err.status === 404 && err.code === "MIGRATION_JOB_NOT_FOUND") {
          setMigrationJob((prev) =>
            prev
              ? {
                  ...prev,
                  status: "failed",
                  current_step: "Migration session expired",
                }
              : prev
          );
          setError(
            "Migration status is no longer available. The backend likely restarted and lost the in-memory job state. Please restart the migration."
          );
          clearScheduledPoll();
          return;
        }

        migrationPollingErrorCountRef.current += 1;
        const retryDelayMs = Math.min(15000, 2000 * migrationPollingErrorCountRef.current);
        setError("Failed to fetch migration status.");
        scheduleNextPoll(retryDelayMs);
      } finally {
        migrationPollingInFlightRef.current = false;
      }
    };

    scheduleNextPoll(0);

    return () => {
      cancelled = true;
      clearScheduledPoll();
      migrationPollingInFlightRef.current = false;
    };
  }, [migrationJob?.job_id, migrationJob?.status, setMigrationJob, setMigrationLogs, step]);

  /* useEffect(() => {
      
      // Check if migration appears to be stuck (same status for > 30 seconds)
      stuckCheckInterval = setInterval(() => {
        const timeSinceLastUpdate = Date.now() - lastUpdateTime;
        if (timeSinceLastUpdate > 30000 && migrationJob?.status === "cloning") {
          setError("Warning: migration appears to be stuck on cloning. This may be due to a large repository or network issues. Please wait a bit longer or restart the migration.");
        }
      }, 15000);
    }
    
    return () => { 
      if (interval) clearInterval(interval);
      if (stuckCheckInterval) clearInterval(stuckCheckInterval);
    };
    }, [step, migrationJob?.job_id, migrationJob?.status]);
  */
  useEffect(() => {
      if ((step === 5 || step === 6) && migrationJob?.status === "completed") {
        setStep(7);
      }
    }, [step, migrationJob?.status]);

  const toggleReportAccordion = (section: "sonar" | "fossa" | "issues") => {
    setReportAccordionState((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const buildMigrationRequest = useCallback(() => {
    const repoName = sourceRepositoryName;
    const finalTargetRepoName = targetRepoName.trim() || getAutoGeneratedTargetName(currentMigrationApproach, repoName);

    const detectPlatform = (url: string) => {
      if (url.includes("gitlab.com")) return "gitlab";
      if (url.includes("github.com")) return "github";
      return "github";
    };

    return {
      source_repo_url: selectedRepo?.url || repoUrl,
      target_repo_name: finalTargetRepoName,
      platform: detectPlatform(selectedRepo?.url || repoUrl),
      source_java_version: userSelectedVersion || selectedSourceVersion,
      target_java_version: effectiveTargetVersion,
      token: currentToken,
      github_token: currentToken,
      build_tool: repoAnalysis?.build_tool || null,
      migration_approach: migrationApproach,
      conversion_types: selectedConversions,
      run_tests: runTests,
      use_llm_tests: runTests && useLLMTests,
      llm_test_provider: selectedLLMProvider,
      run_sonar: runSonar,
      run_fossa: runFossa,
      fix_business_logic: fixBusinessLogic,
      functional_test_method: functionalTestToolMethods.length > 0 ? functionalTestToolMethods : undefined,
      functional_test_execution_mode: functionalTestExecutionMode === "auto" ? undefined : functionalTestExecutionMode,
    };
  }, [
    sourceRepositoryName,
    targetRepoName,
    getAutoGeneratedTargetName,
    currentMigrationApproach,
    selectedRepo?.url,
    repoUrl,
    userSelectedVersion,
    selectedSourceVersion,
    effectiveTargetVersion,
    currentToken,
    repoAnalysis?.build_tool,
    migrationApproach,
    selectedConversions,
    runTests,
    useLLMTests,
    selectedLLMProvider,
    runSonar,
    runFossa,
    fixBusinessLogic,
    functionalTestToolMethods,
    functionalTestExecutionMode,
  ]);

  useEffect(() => {
    if (step !== 4 || !effectiveTargetVersion || (!selectedRepo && !repoUrl)) {
      return;
    }

    let cancelled = false;

    previewMigration(buildMigrationRequest())
      .then((preview) => {
        if (cancelled) return;
        setMigrationPreview(preview);
        const previewCodeChanges = buildCodeChangesFromPreviewDiffs(preview.file_diffs || []);
        setCodeChanges(previewCodeChanges);
        setSelectedDiffFile((current) => current ?? previewCodeChanges[0]?.filePath ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setMigrationPreview(null);
        setCodeChanges([]);
        setSelectedDiffFile(null);
      })

    return () => {
      cancelled = true;
    };
  }, [
    buildMigrationRequest,
    effectiveTargetVersion,
    currentToken,
    fixBusinessLogic,
    migrationApproach,
    repoUrl,
    runFossa,
    runSonar,
    runTests,
    selectedConversions,
    selectedRepo,
    selectedSourceVersion,
    selectedTargetVersion,
    setCodeChanges,
    setMigrationPreview,
    setSelectedDiffFile,
    step,
    targetRepoName,
    targetRepoTimestamp,
    userSelectedVersion,
  ]);

  const handleStartMigration = () => {
    if (!selectedRepo && !repoUrl) {
      setError("Please select a repository or enter a repository URL");
      return;
    }

    if (!effectiveTargetVersion) {
      setError("Please select a target Java version before starting the migration.");
      return;
    }

    // Require at least one analysis tool selected before starting migration
    // if (!runSonar && !runFossa) {
    //   setError("Please select SonarQube or FOSSA before starting migration.");
    //   return;
    // }

    setLoading(true);
    setError("");
    setMigrationLogs([]);
    setMigrationJob(null);
    setMigrationDetailLoadedJobId(null);
    setStep(5);

    const migrationRequest = buildMigrationRequest();

    startMigration(migrationRequest)
      .then((job) => {
        setMigrationJob(job);
        setMigrationDetailLoadedJobId(null);

        if (job.status === "completed") {
          setStep(7);
          getMigrationLogs(job.job_id).then((logs) => setMigrationLogs(logs.logs || []));
          return;
        }

        setStep(5); // Go to Migration Progress step
      })
      .catch((err) => {
        console.error("Migration error:", err);
        setMigrationJob(null);
        setStep(4);
        setError(err.message || "Failed to start migration.");
        setLoading(false);
      })
      .finally(() => setLoading(false));
  };

  const resetWizard = () => {
    setStep(1);
    setMaxVisitedIndicatorStep(1);
    setRepoUrl("");
    setSelectedRepo(null);
    setRepoAnalysis(null);
    setRepoFiles([]);
    setCurrentPath("");
    setTargetRepoNamesByApproach({ fork: "", branch: "", local: "" });
    setTargetRepoNameEditedByApproach({ fork: false, branch: false, local: false });
    setTargetRepoTimestamp(generateRepoTimestamp());
    setSelectedSourceVersion("8");
    setSelectedTargetVersion("17");
    setSelectedConversions(["java_version"]);
    setRunTests(true);
    setRunSonar(false);
    setRunFossa(false);
    setLoading(false);
    setAnalysisLoading(false);
    setMigrationJob(null);
    setMigrationDetailLoadedJobId(null);
    setFossaResult(null);
    setFossaLoading(false);
    setMigrationPreview(null);
    setMigrationLogs([]);
    setError("");
    setTargetVersionRequiredError(false);
    setTargetRepoNameError("");
    setMigrationApproach("fork");
    setRiskLevel("");
    setSelectedFrameworks([]);
    setIsJavaProject(null);
    setSelectedFile(null);
    setFileContent("");
    setEditedContent("");
    setIsEditing(false);
    setPathHistory([""]);
    setShowFileExplorer(true);
    // Reset high-risk project states
    setIsHighRiskProject(false);
    setHighRiskConfirmed(false);
    setSuggestedJavaVersion("17");
    setDetectedFrameworks([]);
    setViewingFrameworkFile(null);
   // Reset code diff states
    setCodeChanges([]);
    setSelectedDiffFile(null);
    setShowCodeChanges(true);
    setVisibleReportDiffCount(REPORT_DIFFS_PAGE_SIZE);

    clearWizardStorage();
  };

  const renderStepIndicator = () => (
    <div style={styles.stepIndicator}>
      {MIGRATION_STEPS.map((s, index) => {
        const isCompleted = currentIndicatorStep > s.id;
        const isActive = currentIndicatorStep === s.id;
        const isUnlocked = s.id <= maxVisitedIndicatorStep;

        return (
        <React.Fragment key={s.id}>
          <div 
            style={{ 
              display: "flex", 
              flexDirection: "column", 
              alignItems: "center", 
              gap: 8,
              opacity: 1,
              cursor: isUnlocked && !isActive ? "pointer" : "default",
              transition: "all 0.3s ease"
            }} 
            onClick={() => isUnlocked && !isActive && setStep(s.id)}
          >
            <div
              className={`wizard-step-circle${isCompleted ? " is-complete" : isActive ? " is-active" : ""}`}
              style={buildWizardAccentVars(s.accent)}
            >
              {s.icon}
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ 
                fontWeight: isActive ? 700 : 500, 
                fontSize: 13, 
                color: isActive ? "#3b82f6" : isCompleted ? "#22c55e" : "#64748b",
                marginBottom: 2
              }}>
                {s.name}
              </div>
              <div style={{ 
                fontSize: 10, 
                color: isActive ? "#64748b" : "#94a3b8",
                maxWidth: 100,
                lineHeight: 1.3
              }}>
                {s.description}
              </div>
            </div>
          </div>
          {/* Connector Line */}
          {index < MIGRATION_STEPS.length - 1 && (
            <div style={{
              flex: 1,
              height: 3,
              backgroundColor: currentIndicatorStep > s.id ? "#22c55e" : "#e5e7eb",
              marginTop: -50,
              marginLeft: -10,
              marginRight: -10,
              borderRadius: 2,
              transition: "background-color 0.3s ease"
            }} />
          )}
        </React.Fragment>
        );
      })}
    </div>
  );

  const renderStep1 = () => {
    const localProjectMessage = localProjectCapabilitiesLoading
      ? "Checking local project support..."
      : localProjectCapabilities?.message ||
        "Upload projects using the folder picker or ZIP archive uploader below. The backend will extract and analyze your uploaded files.";
    const authenticationBannerText = showEnterpriseToken
      ? "GitHub Enterprise repository detected - authentication required"
      : "Private repository detected - authentication required";
    const tokenCardTitle = showEnterpriseToken
      ? "Enterprise Repository - Enter Personal Access Token"
      : "Private Repository - Enter Personal Access Token";
    const tokenDescription = showEnterpriseToken
      ? "This repository requires authentication. Provide a GitHub Personal Access Token before analysis."
      : "This repository requires authentication. Provide a GitHub Personal Access Token with repo scope.";
    const tokenStatusColor =
      accessTokenValidationState === "valid"
        ? "#166534"
        : accessTokenValidationState === "invalid"
          ? "#b45309"
          : "#9a3412";
    const tokenStatusIcon =
      accessTokenValidationState === "valid"
        ? <FaCheckCircle />
        : accessTokenValidationState === "invalid"
          ? <FaExclamationTriangle />
          : <FaInfoCircle />;
    return (
      <div style={styles.card}>
        <div style={styles.stepHeader}>
          {renderWizardIconBadge(<FaLink />, "#2563eb", "xl")}
          <div>
            <h2 style={styles.title}>Connect Repository</h2>
            <p style={styles.subtitle}>Enter a GitHub repository URL or analyze a local Java project to start migration analysis.</p>
          </div>
        </div>

        <div style={styles.field}>
          <label style={{ ...styles.label, display: "flex", alignItems: "center", gap: 8 }}>
            Repository URL
            <WizardInfoTooltip label="Repository URL formats" placement="left" width={220}>
              <div style={{ fontWeight: 600, marginBottom: 6, color: "#94a3b8" }}>Supported formats:</div>
              <div>- https://github.com/owner/repo</div>
              <div>- github.com/owner/repo</div>
              <div>- owner/repo</div>
            </WizardInfoTooltip>
          </label>
          <input
            type="text"
            style={{ ...styles.input, borderColor: urlValidation.valid ? '#22c55e' : repoUrl ? '#ef4444' : '#e2e8f0' }}
            value={repoUrl}
            onChange={(e) => {
              setRepoUrl(e.target.value);
              setSelectedRepo(null);
              setRepoAnalysis(null);
              setIsPrivateRepo(false);
              setPatToken("");
              resetAccessTokenValidationState();
              setError("");
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && urlValidation.valid) {
                void handleRepositoryContinue();
              }
            }}
            placeholder="https://github.com/owner/repository"
          />
          {!shouldShowPatInput && (
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 12, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span>Public GitHub repositories can be analyzed without a token.</span>
              <button
                type="button"
                onClick={() => {
                  setIsPrivateRepo(true);
                  resetAccessTokenValidationState();
                  setError("");
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "#2563eb",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 600,
                  padding: 0,
                  textDecoration: "underline",
                }}
              >
                Have a Private Access Token (PAT)?
              </button>
            </div>
          )}
          {repoAccessCheckLoading && !shouldShowPatInput && (
            <div style={{ fontSize: 12, color: '#2563eb', marginTop: 8 }}>
              Checking repository access...
            </div>
          )}
          {shouldShowPatInput && (
            <div style={{ marginTop: 16 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 14,
                  color: "#f59e0b",
                  fontSize: 14,
                  fontWeight: 600,
                }}
              >
                <FaLock />
                <span>{authenticationBannerText}</span>
              </div>
              <div
                style={{
                  border: "1px solid #fbbf24",
                  borderRadius: 18,
                  padding: 20,
                  background: "linear-gradient(180deg, #fff8db 0%, #fff4c2 100%)",
                  boxShadow: "0 8px 18px rgba(245, 158, 11, 0.12)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 10,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: "#fff",
                      color: "#d97706",
                      boxShadow: "0 2px 8px rgba(217, 119, 6, 0.12)",
                    }}
                  >
                    <FaLock />
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "#9a3412" }}>{tokenCardTitle}</div>
                    <div style={{ fontSize: 13, color: "#b45309", marginTop: 4 }}>{tokenDescription}</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <input
                    type="password"
                    style={{
                      ...styles.input,
                      flex: "1 1 420px",
                      marginBottom: 0,
                      background: "#fff",
                      borderColor:
                        accessTokenValidationState === "valid"
                          ? "#22c55e"
                          : accessTokenValidationState === "invalid"
                            ? "#f59e0b"
                            : activeAccessToken
                              ? "#22c55e"
                              : "#e2e8f0",
                    }}
                    value={showEnterpriseToken ? githubToken : patToken}
                    onChange={(e) => {
                      resetAccessTokenValidationState();
                      if (showEnterpriseToken) {
                        setGithubToken(e.target.value);
                      } else {
                        setPatToken(e.target.value);
                      }
                    }}
                    placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    style={{
                      ...styles.primaryBtn,
                      minWidth: 132,
                      opacity: accessTokenValidationState === "validating" ? 0.8 : 1,
                    }}
                    disabled={accessTokenValidationState === "validating"}
                    onClick={() => void handleAccessTokenValidate()}
                  >
                    {accessTokenValidationState === "validating" ? "Validating..." : "Validate"}
                  </button>
                </div>
                <div style={{ fontSize: 12, color: tokenStatusColor, marginTop: 10, display: "flex", alignItems: "center", gap: 8 }}>
                  {tokenStatusIcon}
                  <span>
                    {accessTokenValidationMessage || (
                      <a href="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token" target="_blank" rel="noopener noreferrer">
                        How to create a Personal Access Token?
                      </a>
                    )}
                  </span>
                </div>
                {accessTokenValidationState === "valid" && (
                  <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
                    <button
                      type="button"
                      style={{
                        ...styles.primaryBtn,
                        background: "linear-gradient(135deg, #16a34a, #15803d)",
                        border: "none",
                        minWidth: 260,
                        fontWeight: 700,
                        fontSize: 15,
                        boxShadow: "0 4px 14px rgba(22,163,74,0.25)",
                      }}
                      onClick={() => void handleRepositoryContinue()}
                    >
                      {renderForwardButtonLabel("Continue with Authenticated Repository")}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
          {repositoryNeedsAuthentication && !activeAccessToken && accessTokenValidationState === "idle" && (
            <div style={{ fontSize: 12, color: "#b45309", marginTop: 8 }}>
              Add a PAT above before continuing with repository analysis.
            </div>
          )}
          {repoUrl && !urlValidation.valid && (
            <div style={{ fontSize: 12, color: '#ef4444', marginTop: 6 }}>
              Warning: {urlValidation.message}
            </div>
          )}
          {urlValidation.valid && (
            <div style={{ fontSize: 12, color: '#22c55e', marginTop: 6 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <FaCheckCircle />
                Valid repository URL
              </span>
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
          <div style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
          <div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.08em" }}>OR</div>
          <div style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
        </div>

        <div className="wizard-local-project-panel">
          <div className="wizard-local-project-header">
            {renderWizardIconBadge(<FaFolderOpen />, "#f59e0b", "lg")}
            <div>
              <div className="wizard-local-project-title">
                Upload Local Project
              </div>
              <div className="wizard-local-project-subtitle">
                Select a folder from your computer or upload a ZIP file for analysis.
              </div>
            </div>
          </div>

          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
            {localProjectMessage}
          </div>

          <div style={{ fontSize: 13, color: "#475569", marginBottom: 12 }}>
            Select a folder from your computer OR upload a ZIP archive. This sends the project contents to the backend for analysis.
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="wizard-picker-grid">
                <div style={{ flex: 1, minWidth: 200 }}>
                  <input
                    ref={(el) => {
                      if (el) {
                        browserWindow.folderInputRef = el;
                        el.setAttribute('webkitdirectory', '');
                        el.setAttribute('directory', '');
                      }
                    }}
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={(e) => handleLocalProjectFilesChange(e.target.files)}
                  />
                  <div
                    onClick={() => {
                      browserWindow.folderInputRef?.click();
                    }}
                    className="wizard-picker-option"
                    style={buildWizardAccentVars("#f59e0b")}
                  >
                    <span className="wizard-picker-option-label">
                      {renderWizardIconBadge(<FaFolderOpen />, "#f59e0b", "sm")}
                      <span>Select Folder</span>
                    </span>
                  </div>
                </div>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <input
                    ref={(el) => {
                      if (el) browserWindow.zipInputRef = el;
                    }}
                    type="file"
                    accept=".zip"
                    style={{ display: "none" }}
                    onChange={(e) => handleLocalProjectFilesChange(e.target.files)}
                  />
                  <div
                    onClick={() => {
                      browserWindow.zipInputRef?.click();
                    }}
                    className="wizard-picker-option"
                    style={buildWizardAccentVars("#8b5cf6")}
                  >
                    <span className="wizard-picker-option-label">
                      {renderWizardIconBadge(<FaFileAlt />, "#8b5cf6", "sm")}
                      <span>Select ZIP File</span>
                    </span>
                  </div>
                </div>
              </div>
              {localProjectUploadFiles.length > 0 && (
                <div style={{ fontSize: 13, color: "#334155" }}>
                  Selected {localProjectUploadFiles.length} file{localProjectUploadFiles.length === 1 ? "" : "s"}.
                </div>
              )}
              {localProjectUploadWarning && (
                <div style={{ fontSize: 13, color: "#b45309" }}>{localProjectUploadWarning}</div>
              )}
              {localProjectUploadCompressing && (
                <div style={{ fontSize: 13, color: "#0f766e" }}>Compressing selected folder to ZIP before upload...</div>
              )}
              {localProjectUploadError && (
                <div style={{ fontSize: 13, color: "#b91c1c" }}>{localProjectUploadError}</div>
              )}
              <button
                style={{ ...styles.primaryBtn, minWidth: 140, opacity: localProjectUploadFiles.length === 0 || localProjectUploadLoading || localProjectCapabilities?.enabled === false ? 0.5 : 1, display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}
                disabled={localProjectUploadFiles.length === 0 || localProjectUploadLoading || localProjectCapabilities?.enabled === false}
                onClick={() => void handleLocalProjectUpload()}
              >
                {localProjectUploadLoading ? (
                  "Uploading..."
                ) : (
                  <span className="wizard-button-content">
                    {renderWizardIconBadge(<FaUpload />, "#2563eb", "sm")}
                    <span>Upload and Analyze</span>
                  </span>
                )}
              </button>
            </div>
        </div>

        <div style={styles.btnRow}>
          <button
            style={{
              ...styles.primaryBtn,
              opacity:
                !urlValidation.valid || (shouldShowPatInput && accessTokenValidationState !== "valid")
                  ? 0.5
                  : 1,
            }}
            disabled={!urlValidation.valid || (shouldShowPatInput && accessTokenValidationState !== "valid")}
            onClick={() => void handleRepositoryContinue()}
          >
            {renderForwardButtonLabel(
              shouldShowPatInput && accessTokenValidationState === "valid"
                ? "Continue with Authenticated Repository"
                : shouldShowPatInput
                  ? "Validate PAT to Continue"
                  : "Continue"
            )}
          </button>
        </div>
      </div>
    );
  };

  // Consolidated Step 2: Discovery (Repository discovery + Dependencies)
  const renderDiscoveryStep = () => {
    // Helper function to handle file click
    const handleFileClick = async (file: RepoFile) => {
      if (file.type === "dir") {
        setPathHistory(prev => [...prev, file.path]);
        setCurrentPath(file.path);
        setSelectedFile(null);
        setFileContent("");
        setEditedContent("");
        setIsEditing(false);
      } else {
        setFileLoading(true);
        setSelectedFile(file);
        try {
          const response = isLocalRepoRef(selectedRepo!.url)
            ? await getLocalProjectFileContent(extractLocalRepoPath(selectedRepo!.url), file.path)
            : await getFileContent(selectedRepo!.url, file.path, currentToken);
          setFileContent(response.content);
          setEditedContent(response.content);
        } catch {
          setError("Failed to load file content");
        } finally {
          setFileLoading(false);
        }
      }
    };

    // Helper to navigate back in folder structure
    const navigateBack = () => {
      if (pathHistory.length > 1) {
        const newHistory = [...pathHistory];
        newHistory.pop();
        setPathHistory(newHistory);
        setCurrentPath(newHistory[newHistory.length - 1]);
        setSelectedFile(null);
        setFileContent("");
        setEditedContent("");
        setIsEditing(false);
      }
    };

    // Helper to navigate to root
    const navigateToRoot = () => {
      setPathHistory([""]);
      setCurrentPath("");
      setSelectedFile(null);
      setFileContent("");
      setEditedContent("");
      setIsEditing(false);
    };

    const detectedBuildType = repoAnalysis?.build_tool ||
      (repoAnalysis?.structure?.has_pom_xml ? "maven" : repoAnalysis?.structure?.has_build_gradle ? "gradle" : null);
    const detectedJavaVersion = repoAnalysis?.java_version || repoAnalysis?.java_version_from_build || null;
    const buildConversionLabel = detectedBuildType === "maven"
      ? "Maven to Gradle build"
      : detectedBuildType === "gradle"
        ? "Gradle to Maven build"
        : "Proceed with migration";

    const buildConversionNote = detectedBuildType === "maven"
      ? "Detected Maven project; convert to a Gradle build."
      : detectedBuildType === "gradle"
        ? "Detected Gradle project; convert to a Maven build."
        : "No specific build tool conversion detected.";

    return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        {renderWizardIconBadge(<FaSearch />, "#0ea5e9", "xl")}
        <div>
          <h2 style={styles.discoveryStepTitle}>Repository Discovery & Dependencies</h2>
          <p style={styles.discoveryStepSubtitle}>{MIGRATION_STEPS[1].summary}</p>
        </div>
        {isDiscoveryPending &&
          renderStatusChip(
            <FaStopwatch />,
            "#f97316",
            "Analysing...",
            formattedAnalysisElapsed,
            "warning"
          )}
        {!isDiscoveryPending &&
          repoAnalysis &&
          renderStatusChip(
            <FaCheckCircle />,
            "#22c55e",
            "Completed",
            formattedAnalysisCompleted,
            "success"
          )}
      </div>

      {selectedRepo && (
        <React.Suspense
          fallback={
            <DiscoveryLoader
              compact
              title="Loading discovery workspace"
              subtitle="Preparing the repository intelligence panels and analysis surfaces."
              elapsedSeconds={0}
            />
          }
        >
        <>
          {isDiscoveryPending ? (
            <DiscoveryLoader
              title="Analyzing your repository"
              subtitle="Mapping structure, previewing changes, reading dependencies, and estimating microservice readiness."
              elapsedLabel={formattedAnalysisElapsed}
              elapsedSeconds={analysisElapsedSeconds}
            />
          ) : (
            <>
              {/* Not a Java Project Alert or No Framework Detected */}
              {isJavaProject === false ? (
                <DiscoveryNotJavaAlert
                  onChooseDifferentRepository={() => {
                    setStep(1);
                    setSelectedRepo(null);
                    setRepoAnalysis(null);
                    setIsJavaProject(null);
                    setRepoUrl("");
                  }}
                />
              ) : null}

              {/* Java project but no framework detected */}
              <DiscoveryNoFrameworkAlert
                isVisible={Boolean(isJavaProject && detectedFrameworks.length === 0)}
              />

              {/* Show discovery content only if it's a Java project */}
              {isJavaProject !== false && (
                <>
                  {/* High Risk Project Warning (no pom.xml/build.gradle or unknown Java version) */}
                  <DiscoveryHighRiskWarning
                    isVisible={Boolean(isHighRiskProject && !highRiskConfirmed)}
                    missingBuildFiles={Boolean(!repoAnalysis?.structure?.has_pom_xml && !repoAnalysis?.structure?.has_build_gradle)}
                    missingJavaVersion={Boolean(!((repoAnalysis?.java_version || repoAnalysis?.java_version_from_build)) || (repoAnalysis?.java_version || repoAnalysis?.java_version_from_build) === "unknown")}
                    missingSrcMain={Boolean(!repoAnalysis?.structure?.has_src_main)}
                    sourceVersionStatus={sourceVersionStatus}
                    suggestedJavaVersion={suggestedJavaVersion}
                    buildConversionLabel={buildConversionLabel}
                    buildConversionNote={buildConversionNote}
                    onSuggestedJavaVersionChange={(value) => {
                      setSuggestedJavaVersion(value);
                      setSelectedSourceVersion(value === "auto" ? "8" : value);
                      setUserSelectedVersion(value);
                      setSourceVersionStatus("detected");
                    }}
                    onConfirm={() => {
                      setHighRiskConfirmed(true);
                      setSelectedSourceVersion(suggestedJavaVersion);
                    }}
                    onChooseDifferentRepository={() => {
                      setStep(1);
                      setSelectedRepo(null);
                      setRepoAnalysis(null);
                      setIsJavaProject(null);
                      setIsHighRiskProject(false);
                      setRepoUrl("");
                    }}
                  />
                  
                  {/* Show content only after high-risk confirmation or if not high-risk */}
                  {(!isHighRiskProject || highRiskConfirmed) && (
	                  <>
	                  <DiscoveryFileExplorer
                    styles={styles}
                    repositoryName={selectedRepo.name}
                    currentPath={currentPath}
                    showFileExplorer={showFileExplorer}
                    selectedFile={selectedFile}
                    repoFiles={repoFiles}
                    fileLoading={fileLoading}
                    fileContent={fileContent}
                    isEditing={isEditing}
                    editedContent={editedContent}
                    onToggleExplorer={() => setShowFileExplorer(!showFileExplorer)}
                    onNavigateRoot={navigateToRoot}
                    onNavigateBack={navigateBack}
                    onFileClick={handleFileClick}
                    onCloseSelectedFile={() => {
                      setSelectedFile(null);
                      setFileContent("");
                      setEditedContent("");
                      setIsEditing(false);
                    }}
                    onEditedContentChange={setEditedContent}
                  />

                  {/* Discovery Info */}
                  {/* <div style={styles.discoveryContent}>
                    <div style={styles.discoveryItem}>
                      <span style={styles.discoveryIcon}>Repo</span>
                      <div>
                        <div style={styles.discoveryTitle}>Repository Analysis</div>
                        <div style={styles.discoveryDesc}>Scanning {selectedRepo.name} for Java components</div>
                      </div>
                    </div>
                    <div style={styles.discoveryItem}>
                      <span style={styles.discoveryIcon}>Build</span>
                      <div>
                        <div style={styles.discoveryTitle}>Build Tool: {buildToolDisplayLabel || "Detecting..."}</div>
                        <div style={styles.discoveryDesc}>Identified build system for dependency management</div>
                      </div>
                    </div>
                    <div style={styles.discoveryItem}>
                      <span style={styles.discoveryIcon}>Java</span>
                      <div>
                        <div style={styles.discoveryTitle}>Java Version: {(repoAnalysis?.java_version || repoAnalysis?.java_version_from_build) || "Detecting..."}</div>
                        <div style={styles.discoveryDesc}>Current Java version detected in the project</div>
                      </div>
                    </div>
                  </div> */}

                  {/* {(detectedJavaVersion || detectedBuildType) && (
                    <div style={styles.detectedConfigCard}>
                      <div style={styles.detectedConfigHeader}>
                        <div>
                          <div style={styles.detectedConfigTitle}>Detected Configuration</div>
                          <div style={styles.detectedConfigSubtitle}>
                            Restored discovery summary for the detected Java and build setup.
                          </div>
                        </div>
                      </div>

                      <div style={styles.detectedConfigActions}>
                        <button type="button" style={styles.detectedConfigChip}>
                          Java Version Detected: {detectedJavaVersion ? `Java ${detectedJavaVersion}` : "Unknown"}
                        </button>
                        <button type="button" style={styles.detectedConfigChip}>
                          Build Detected: {detectedBuildType ? detectedBuildType.charAt(0).toUpperCase() + detectedBuildType.slice(1) : "Unknown"}
                        </button>
                        <button type="button" style={styles.detectedConfigChip}>
                          Framework Detected: {primaryDetectedFramework || "None detected"}
                        </button>
                        {hasRecommendedBuildConversion && recommendedBuildConversionId && (
                          <button
                            type="button"
                            style={{
                              ...styles.detectedConfigActionBtn,
                              ...(selectedConversions.includes(recommendedBuildConversionId)
                                ? styles.detectedConfigActionBtnActive
                                : {}),
                            }}
                            onClick={applyRecommendedBuildConversion}
                          >
                            {selectedConversions.includes(recommendedBuildConversionId)
                              ? `${buildConversionLabel} Selected`
                              : buildConversionLabel}
                          </button>
                        )}
                      </div>

                      <div style={styles.detectedConfigNote}>{buildConversionNote}</div>
                    </div>
                  )} */}

                  <DiscoveryFrameworkSection
                    styles={styles}
                    detectedFrameworks={detectedFrameworks}
                    dependencies={repoAnalysis?.dependencies}
                    viewingFrameworkFile={viewingFrameworkFile}
                    frameworkFileLoading={frameworkFileLoading}
                    onClosePreview={() => setViewingFrameworkFile(null)}
                    onOpenFramework={handleOpenFrameworkFile}
                  />

                  {repoAnalysis && (
                    <DiscoveryProjectStructureSummary
                      styles={styles}
                      structure={repoAnalysis.structure}
                      detectedJavaVersion={detectedJavaVersion}
                      detectedJavaStructureLabel={detectedJavaStructureLabel}
                    />
                  )}

                  {repoAnalysis && (
                    <MicroserviceAssessment
                    repoAnalysis={repoAnalysis}
                    microserviceResult={microserviceResult}
                    microserviceLoading={microserviceLoading}
                    loading={analysisLoading}
                    handleCheckMicroserviceEligibility={handleCheckMicroserviceEligibility}
                    conversionDecision={conversionDecision}
                    setConversionDecision={setConversionDecision}
                    showFolderStructure={showFolderStructure}
                    setShowFolderStructure={setShowFolderStructure}
                    styles={styles}
                    />
                  )}

                  {repoAnalysis && (
                    <DiscoveryTechnicalSpecificationCard
                      styles={styles}
                      disabled={documentGenerationLoading !== null || !repoAnalysis}
                      buttonLabel={technicalSpecificationButtonLabel}
                      helperText={technicalSpecificationHelperText}
                      onGenerate={() => {
                        void handleGenerateBrdDocument();
                      }}
                    />
                  )}

                </>
              )}
                    </>
                  )}
            </>
          )}
        </>
        </React.Suspense>
      )}

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(1)}>{renderBackButtonLabel()}</button>
        <button 
          style={{ ...styles.primaryBtn, opacity: isJavaProject === false || (isHighRiskProject && !highRiskConfirmed) || isDiscoveryPending || !repoAnalysis ? 0.5 : 1 }} 
          onClick={() => setStep(3)}
          disabled={isJavaProject === false || (isHighRiskProject && !highRiskConfirmed) || isDiscoveryPending || !repoAnalysis}
        >
          {renderForwardButtonLabel("Continue to Strategy")}
        </button>
      </div>
    </div>
    );
  };

  // Consolidated Step 3: Strategy (Assessment + Migration Strategy + Planning)
  const renderStrategyStep = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        {renderWizardIconBadge(<FaProjectDiagram />, "#f97316", "xl")}
        <div>
          <h2 style={styles.title}>Assessment & Migration Strategy</h2>
          <p style={styles.subtitle}>{MIGRATION_STEPS[2].summary}</p>
        </div>
      </div>

      {/* Assessment Section */}
      {selectedRepo && repoAnalysis && (
        <>
          <WizardSectionHeading
            title="Application Assessment"
            style={{ marginBottom: 14, marginTop: 20 }}
          />
          
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
  <div
    style={{
      ...styles.riskBadge,
      backgroundColor:
        riskLevel === "low"
          ? "#dcfce7"
          : riskLevel === "medium"
            ? "#fef3c7"
            : "#fee2e2",
      color:
        riskLevel === "low"
          ? "#166534"
          : riskLevel === "medium"
            ? "#92400e"
            : "#991b1b",
      marginBottom: 0,
    }}
  >
    Risk Level: {riskLevel.toUpperCase()}
  </div>

  <WizardInfoTooltip
    label="Risk level explanation"
    width={300}
    placement="left"
    panelStyle={{ borderRadius: 10, padding: "16px 20px", boxShadow: "0 18px 35px rgba(15, 23, 42, 0.25)" }}
  >
    <div style={{ color: "#86efac", fontWeight: 800, fontSize: 14, marginBottom: 12 }}>
      ANALYSIS
    </div>
    <div style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.45 }}>
      {riskLevel === "low"
        ? "The project is already on a modern migration path with build tooling and tests detected."
        : riskLevel === "medium"
          ? "The project has build tooling, but tests are missing or limited."
          : "The project needs extra review because build tooling or Java metadata was not detected."}
    </div>
  </WizardInfoTooltip>
</div>



          <div style={styles.assessmentGrid}>
            { <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Build Tool</div><div style={styles.assessmentValue}>{buildToolDisplayLabel}</div></div> }
            { <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Java Version</div><div style={styles.assessmentValue}>{repoAnalysis.java_version || "Unknown"}</div></div> }
            <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Has Tests</div><div style={styles.assessmentValue}>{repoAnalysis.has_tests ? "Yes" : "No"}</div></div>
            <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Dependencies</div><div style={styles.assessmentValue}>{repoAnalysis.dependencies?.length || 0} found</div></div>
          </div>

          {repoAnalysis.dependencies && repoAnalysis.dependencies.length > 0 && (
            <div style={styles.field}>
              {renderCategorizedDependencies(repoAnalysis.dependencies)}
            </div>
          )}
                 
        <div
        style={{
          background: "#fff",
          border: "1px solid #dbe3ef",
          borderRadius: 14,
          padding: "26px 30px",
          boxShadow: "0 2px 8px rgba(15, 23, 42, 0.06)",
          marginBottom: 26,
        }}>
        <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 20,
          fontWeight: 800,
          color: "#0f172a",
          marginBottom: 18,
        }}
        >
        <span>Setup</span>
        <span>Conversion Type</span>
        </div>

      <div style={{ height: 1, background: "#dbe3ef", marginBottom: 18 }} />

      <p style={{ fontSize: 17, color: "#475569", margin: "0 0 22px" }}>
        Available modernization pathways for your project:
      </p>  
        
        <div style={{ display: "grid",gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
          {[
            {
              key: "java_version",
              title: "Java Version Upgrade",
              desc: "Upgrade Java version with Dependencies update",
              icon: <FaJava />,
              color: "#2563eb",
              status: "active" as const,
            },
            {
              key: "build_conversion",
              title: "Maven -> Gradle | Gradle -> Maven",
              desc: "Convert pom.xml to build.gradle with dependency mapping",
              icon: <FaCogs />,
              color: "#8b5cf6",
              status: "coming_soon" as const,
            },
            {
              key: "microservices",
              title: "Monolithic -> Microservices",
              desc: "Decompose monolith into microservices architecture",
              icon: <FaProjectDiagram />,
              color: "#0ea5e9",
              status: "coming_soon" as const,
            },
            {
              key: "jakarta",
              title: "javax -> Jakarta EE | Jakarta EE -> javax",
              desc: "Migrate javax.* packages to jakarta.*",
              icon: <FaCode />,
              color: "#f59e0b",
              status: "coming_soon" as const,
            },
            {
              key: "spring_boot",
              title: "Spring -> Spring Boot",
              desc: "Upgrade Spring Boot 2.x to 3.x with Jakarta EE",
              icon: <FaLeaf />,
              color: "#22c55e",
              status: "coming_soon" as const,
            },
            {
              key: "ui_modernization",
              title: "JSP/JSF -> Angular/React",
              desc: "Modernize legacy JSP/JSF views to Angular or React SPA",
              icon: <FaCode />,
              color: "#06b6d4",
              status: "coming_soon" as const,
            },
          ].map((pathway) => {
            const isActivePathway = pathway.key === "java_version" && selectedConversions.includes("java_version");
            const isDisabledPathway = pathway.status === "coming_soon";

            return (
              <WizardOptionCard
                key={pathway.key}
                onClick={() => {
                  if (isDisabledPathway) return;
                  setSelectedConversions(["java_version"]);
                }}
                accent={pathway.color}
                selected={isActivePathway}
                disabled={isDisabledPathway}
                iconBadge={renderWizardIconBadge(pathway.icon, pathway.color, "sm")}
                title={pathway.title}
                description={pathway.desc}
                topRight={
                  <div className={`wizard-pathway-status${isDisabledPathway ? " is-disabled" : ""}`}>
                    {isDisabledPathway ? "Coming Soon" : "Active"}
                  </div>
                }
                containerStyle={{
                  minHeight: 96,
                  justifyContent: "center",
                }}
                titleStyle={{ color: isActivePathway ? pathway.color : "#1e293b" }}
                descriptionStyle={{ color: isDisabledPathway ? "#475569" : "#334155" }}
              />
            );
          })}
        </div>
      </div> 
        </>
      )}

        <div style={styles.row}>
            <div style={styles.field}>
              <label style={styles.label}>Source Java Version</label>
              <div style={{
                padding: "12px 14px",
                fontSize: 14,
                borderRadius: 8,
                border: "1px solid #d1d5db",
                backgroundColor: "#f9fafb",
                color: userSelectedVersion ? "#1e293b" : "#6b7280",
                fontWeight: userSelectedVersion ? 600 : 500
              }}>
                {userSelectedVersion
                  ? `Java ${selectedSourceVersion} (manually selected)`
                  : (repoAnalysis?.java_version && repoAnalysis?.java_version !== "unknown"
                      ? `Java ${repoAnalysis.java_version} (detected)`
                      : "Source don't have a java version")
                }
              </div>
              <p style={styles.helpText}>
                {userSelectedVersion
                  ? "Source version manually selected in discovery step"
                  : (repoAnalysis?.java_version && repoAnalysis?.java_version !== "unknown"
                      ? "Java version detected from build configuration"
                      : "No Java version found - please select a source version below")
                }
              </p>
              {/* Show version selector when not detected */}
              {!userSelectedVersion && (!((repoAnalysis?.java_version || repoAnalysis?.java_version_from_build)) || (repoAnalysis?.java_version || repoAnalysis?.java_version_from_build) === "unknown") && (
                <div style={{ marginTop: 12 }}>
                  <select
                    value={selectedSourceVersion}
                    onChange={(e) => {
                      setSelectedSourceVersion(e.target.value);
                      setUserSelectedVersion(e.target.value); // Mark as user-selected
                    }}
                    style={{
                      padding: "10px 14px",
                      borderRadius: 6,
                      border: "1px solid #d97706",
                      fontSize: 14,
                      backgroundColor: "#fff",
                      cursor: "pointer",
                      width: "100%"
                    }}
                  >
                    <option value="7">Java 7 (Legacy)</option>
                    <option value="8">Java 8 (LTS)</option>
                    <option value="11">Java 11 (LTS)</option>
                    <option value="17">Java 17 (LTS)</option>
                    <option value="21">Java 21 (LTS)</option>
                    <option value="22">Java 22</option>
                    <option value="23">Java 23</option>
                    <option value="24">Java 24</option>
                    <option value="25">Java 25 (LTS)</option>
                  </select>
                  <div style={{ fontSize: 11, color: "#a16207", marginTop: 6 }}>
                    Select the correct Java version for your project. This will be used as the source version for migration.
                  </div>
                </div>
              )}
            </div>
          <div style={styles.field}>
            <label style={{ ...styles.label, ...(targetVersionRequiredError && !sourceAlreadyAtLatestSupportedVersion ? styles.labelError : {}) }}>
              Target Java Version <span style={styles.requiredMark}>*</span>
            </label>
            <select
              style={{ ...styles.select, ...(targetVersionRequiredError && !sourceAlreadyAtLatestSupportedVersion ? styles.selectError : {}) }}
              value={effectiveTargetVersion}
              onChange={(e) => handleTargetVersionChange(e.target.value)}
              disabled={sourceAlreadyAtLatestSupportedVersion}
            >
              {sourceAlreadyAtLatestSupportedVersion ? (
                <option value={selectedSourceVersion}>Java {selectedSourceVersion} (already current)</option>
              ) : (
                <>
                  <option value="" disabled>Select Java Version</option>
                  {availableTargetVersions.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
                </>
              )}
            </select>
            {targetVersionRequiredError && !sourceAlreadyAtLatestSupportedVersion && (
              <p style={styles.fieldErrorText}>Target Java Version is required.</p>
            )}
            <p style={styles.helpText}>
              {sourceAlreadyAtLatestSupportedVersion
                ? `Java ${selectedSourceVersion} is already the highest supported target version, so no upgrade selection is required.`
                : "Only versions newer than the source Java version are available"}
            </p>
          </div>
        </div>

      {!sourceAlreadyAtLatestSupportedVersion && versionRecommendationLoading && (
        <div style={{ ...styles.infoBox, marginBottom: 20 }}>
          {getJavaVersionRecommendationLoadingLabel("openai")}
        </div>
      )}
      {!sourceAlreadyAtLatestSupportedVersion && !versionRecommendationLoading && versionRecommendationError && (
        <div style={{ ...styles.errorBox, marginBottom: 20 }}>
          {versionRecommendationError}
        </div>
      )}
      {!sourceAlreadyAtLatestSupportedVersion && !versionRecommendationLoading && !versionRecommendationError && versionRecommendation && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#1d4ed8", textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 10 }}>
            {getJavaVersionRecommendationProviderLabel(versionRecommendation.provider_used)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            {versionRecommendationCards.map((card) => {
              const isSelected = selectedTargetVersion === card.version;
              return (
                <button
                  key={card.version}
                  type="button"
                  onClick={() => handleTargetVersionChange(card.version)}
                  style={{
                    textAlign: "left",
                    padding: 12,
                    borderRadius: 10,
                    border: `2px solid ${isSelected ? "#22c55e" : "#e2e8f0"}`,
                    background: isSelected
                      ? "linear-gradient(135deg, #ecfdf5 0%, #f0fdf4 100%)"
                      : "#fff",
                    boxShadow: isSelected
                      ? "0 8px 24px rgba(34, 197, 94, 0.18)"
                      : "0 2px 8px rgba(15, 23, 42, 0.06)",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "2px 7px",
                        borderRadius: 999,
                        backgroundColor: isSelected ? "#22c55e" : card.badgeBackground,
                        color: isSelected ? "#fff" : card.badgeColor,
                        fontSize: 9,
                        fontWeight: 800,
                        textTransform: "uppercase",
                        letterSpacing: "0.4px",
                      }}
                    >
                      {isSelected ? "Selected" : card.eyebrow}
                    </span>
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: "#1e293b", marginBottom: 3 }}>
                    Java {card.version}
                  </div>
                  <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600, marginBottom: 7 }}>
                    {card.label}
                  </div>
                  <div style={{ fontSize: 11, color: "#334155", lineHeight: 1.4, minHeight: 48 }}>
                    {card.description}
                  </div>
                  <div style={{ fontSize: 9, color: isSelected ? "#16a34a" : "#94a3b8", marginTop: 8, fontWeight: 700 }}>
                    {isSelected ? `Selected for migration` : card.helper}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Strategy Section */}
      <WizardSectionHeading
        title="Migration Destination"
        style={{ marginBottom: 14, marginTop: 20 }}
      />
      <div style={styles.field}>
        <label style={styles.label}>Destination repository setup</label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
          {migrationApproachOptions.map((opt) => (
            <WizardOptionCard
              key={opt.value}
              accent={opt.color}
              selected={migrationApproach === opt.value}
              iconBadge={renderWizardIconBadge(opt.icon, opt.color, "md")}
              title={opt.label}
              description={opt.desc}
              onClick={() => {
                setMigrationApproach(opt.value);
                setTargetRepoNameError("");
              }}
              topRight={
                <div style={{ position: "absolute", top: 12, right: 12 }}>
                  <WizardInfoTooltip
                    label={`${opt.label} details`}
                    triggerClassName="ui-info-trigger ui-info-trigger-light"
                  >
                    <div style={{ fontWeight: 600, marginBottom: 8, color: "#94a3b8" }}>
                      {opt.label} Details
                    </div>
                    <div>{opt.tooltip}</div>
                  </WizardInfoTooltip>
                </div>
              }
              headerStyle={{ alignItems: "center" }}
              titleStyle={{ marginBottom: 4 }}
            />
          ))}
        </div>
      </div>

      <div style={styles.field}>
        <label style={{ ...styles.label, ...(targetRepoNameError ? styles.labelError : {}) }}>
          {migrationApproach === "branch"
            ? "Target Branch Name"
            : migrationApproach === "local"
              ? "Target Local Folder Path"
              : "Target Repository Name"}
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input 
            type="text" 
            style={{
              ...styles.input,
              flex: 1,
              backgroundColor: migrationApproach === "fork" ? "#f8fafc" : "#f0fdf4",
              borderColor: targetRepoNameError ? "#ef4444" : "#22c55e",
              color: migrationApproach === "fork" ? "#64748b" : styles.input.color,
            }} 
            value={targetRepoName} 
            onChange={(e) => handleTargetRepoNameChange(e.target.value)} 
            readOnly={migrationApproach === "fork"}
            placeholder={
              migrationApproach === "branch"
                ? getAutoGeneratedTargetName("branch")
                : migrationApproach === "local"
                  ? getAutoGeneratedTargetName("local")
                  : getAutoGeneratedTargetName("fork")
            }
          />
        </div>
        {targetRepoNameError && (
          <p style={styles.fieldErrorText}>{targetRepoNameError}</p>
        )}
        <p style={styles.helpText}>
          Format: <code style={{ backgroundColor: "#f1f5f9", padding: "2px 6px", borderRadius: 4, fontSize: 11 }}>
            {migrationApproach === "branch"
              ? <>migration/{'{source-repo}'}-Migrated{'{timestamp}'}</>
              : migrationApproach === "local"
                ? <>{'{source-repo}'}-Migrated or C:\Users\you\Desktop\{'{source-repo}'}-Migrated</>
                : <>https://{targetRepositoryHost}/{targetRepositoryOwner}/{'{source-repo}'}-Migrated{'{timestamp}'}</>}
          </code> {migrationApproach === "fork" ? "(auto-generated, read only)" : "(auto-generated, editable)"}
        </p>
        {migrationApproach === "fork" && (
          <p style={styles.helpText}>
            New repository targets are generated automatically for the configured GitHub owner.
          </p>
        )}
        {migrationApproach === "local" && (
          <p style={styles.helpText}>
            Enter either a folder name or a full absolute path. If only a folder name is provided, the backend migration workspace will be used.
          </p>
        )}
      </div>

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(2)}>{renderBackButtonLabel()}</button>
        <button style={styles.primaryBtn} onClick={() => continueWithTargetVersion(4)}>{renderForwardButtonLabel("Continue to Migration")}</button>
      </div>
    </div>
  );

  // Consolidated Step 4: Migration (Build Modernization & Refactor + Code Migration + Testing)
  const [testSuiteTab, setTestSuiteTab] = useState<"unit" | "functional">("functional");
  const [hoveredToolId, setHoveredToolId] = useState<string | null>(null);
  const [hoveredScopeCard, setHoveredScopeCard] = useState<string | null>(null);
  const [scopePreview, setScopePreview] = useState<FunctionalTestScopePreview | null>(null);
  const [scopePreviewLoading, setScopePreviewLoading] = useState(false);
  const [scopePreviewError, setScopePreviewError] = useState<string | null>(null);

  // Build the payload sent to the functional-test-scope preview API.
  const buildScopePreviewArgs = () => {
    const endpoints = (repoAnalysis as any)?.api_endpoints || [];
    const uiRoutes = (repoAnalysis as any)?.uiRoutes || [];
    const pageData = (repoAnalysis as any)?.page_data || {};
    const projectName =
      selectedRepo?.name || repoUrl.split("/").pop()?.replace(".git", "") || "Project";
    return { endpoints, uiRoutes, pageData, projectName };
  };

  // Load (without downloading) the functional test scope preview so the inline
  // UI/API test-case lists and existing-test-file data show immediately.
  const loadScopePreview = async (force = false): Promise<FunctionalTestScopePreview | null> => {
    if (scopePreviewLoading) return scopePreview;
    if (scopePreview && !force) return scopePreview;
    try {
      setScopePreviewLoading(true);
      setScopePreviewError(null);
      const { endpoints, uiRoutes, pageData, projectName } = buildScopePreviewArgs();
      const result = await previewFunctionalTestScope(
        projectName,
        endpoints,
        uiRoutes,
        pageData,
        functionalTestToolMethods,
        repoUrl,
        currentToken || "",
      );
      setScopePreview(result);
      return result;
    } catch (err: any) {
      setScopePreviewError(err?.message || "Failed to generate test scope");
      return null;
    } finally {
      setScopePreviewLoading(false);
    }
  };

  // Download the generated UI / API scope HTML document.
  const downloadScopeHtml = async (which: "ui" | "api") => {
    const result = scopePreview || (await loadScopePreview());
    if (!result) return;
    const html = which === "ui" ? result.uiScopeHtml : result.apiScopeHtml;
    const { projectName } = buildScopePreviewArgs();
    const safeName = (selectedRepo?.name || projectName || "project").replace(/[^a-zA-Z0-9_-]/g, "-").toLowerCase();
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${which}-test-scope-${safeName}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Auto-load the scope preview when the user reaches the functional test step.
  useEffect(() => {
    if (step === 4 && testSuiteTab === "functional" && repoAnalysis && !scopePreview && !scopePreviewLoading) {
      void loadScopePreview();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, testSuiteTab, repoAnalysis]);

  const getConfidenceColor = (percentage: number) => {
    if (percentage >= 80) return "#22c55e";
    if (percentage >= 60) return "#3b82f6";
    if (percentage >= 40) return "#f59e0b";
    return "#ef4444";
  };

  // Compact "existing test files" count badges (JUnit / MockMvc / Test Framework / E2E).
  // Reused on the migration page so both the Unit Tests and Functional Tests
  // sections surface how many test files already exist in the repository.
  const renderExistingTestCountBadges = (
    badges: { label: string; count: number; kind: "UNIT" | "E2E"; color: string; icon: string }[],
  ) => {
    const visible = badges.filter((b) => b.count > 0);
    if (visible.length === 0) return null;
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {visible.map((b) => (
          <div
            key={b.label}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 11px", borderRadius: 9,
              border: "1px solid #e2e8f0", background: "#fff",
              boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
            }}
          >
            <span style={{ fontSize: 13 }}>{b.icon}</span>
            <span style={{ fontWeight: 800, fontSize: 14, color: b.color }}>{b.count}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#334155" }}>{b.label}</span>
            <span style={{
              fontSize: 8.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
              padding: "2px 6px", borderRadius: 4,
              background: b.kind === "E2E" ? "#dbeafe" : "#f1f5f9",
              color: b.kind === "E2E" ? "#2563eb" : "#64748b",
            }}>
              {b.kind}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const renderMigrationStep = () => {
    const apiEndpointCount = repoAnalysis?.api_endpoints?.length ?? 0;
    const existingCounts = scopePreview?.existingTestFileCounts;
    const unitTestCountBadges = existingCounts
      ? [
          { label: "JUnit", count: existingCounts.junit ?? 0, kind: "UNIT" as const, color: "#7c3aed", icon: "🧪" },
          { label: "MockMvc", count: existingCounts.mockMvc ?? 0, kind: "UNIT" as const, color: "#16a34a", icon: "🌱" },
        ]
      : [];
    const unitTestFilesTotal = unitTestCountBadges.reduce((sum, b) => sum + b.count, 0);

    return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        {renderWizardIconBadge(<FaRocket />, "#f59e0b", "xl")}
        <div>
          <h2 style={styles.title}>Build Modernization & Migration</h2>
          <p style={styles.subtitle}>{MIGRATION_STEPS[3].summary}</p>
        </div>
      </div>

      {/* ── CI / CD & Quality Gates ─────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20, marginTop: 28, marginBottom: 32 }}>
        {/* Continuous Integration */}
        <div style={{
          background: "#fff",
          borderRadius: 14,
          border: "1px solid #e2e8f0",
          padding: "24px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          position: "relative",
        }}>
          <span style={{
            position: "absolute", top: 12, right: 14,
            fontSize: 9, fontWeight: 700, color: "#94a3b8",
            background: "#f1f5f9", padding: "3px 8px", borderRadius: 6,
            textTransform: "uppercase", letterSpacing: 0.5,
          }}>Coming Soon</span>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 18, color: "#0f172a" }}>⚙️</span>
            <span style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>Continuous Integration</span>
          </div>
          <span style={{ fontSize: 12, color: "#64748b", lineHeight: 1.5 }}>
            Automated build and artifact generation pipeline.
          </span>
        </div>

        {/* Continuous Delivery */}
        <div style={{
          background: "#fff",
          borderRadius: 14,
          border: "1px solid #e2e8f0",
          padding: "24px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          position: "relative",
        }}>
          <span style={{
            position: "absolute", top: 12, right: 14,
            fontSize: 9, fontWeight: 700, color: "#94a3b8",
            background: "#f1f5f9", padding: "3px 8px", borderRadius: 6,
            textTransform: "uppercase", letterSpacing: 0.5,
          }}>Coming Soon</span>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 18, color: "#0f172a" }}>🚀</span>
            <span style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>Continuous Delivery</span>
          </div>
          <span style={{ fontSize: 12, color: "#64748b", lineHeight: 1.5 }}>
            Automated deployment across staging environments.
          </span>
        </div>

        {/* Quality Gates */}
        <div style={{
          background: "#fff",
          borderRadius: 14,
          border: "1px solid #e2e8f0",
          padding: "24px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 18, color: "#0f172a" }}>🛡️</span>
            <span style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>Quality Gates</span>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            {/* SonarQube card */}
            <div
              onClick={() => setRunSonar(!runSonar)}
              style={{
                flex: 1, padding: "10px 12px", borderRadius: 10,
                border: `1.5px solid ${runSonar ? "#2563eb" : "#e2e8f0"}`,
                background: runSonar ? "#eff6ff" : "#fff",
                cursor: "pointer", transition: "all 0.15s ease",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 12, color: "#0f172a", marginBottom: 2 }}>
                <FaSearch style={{ marginRight: 6, fontSize: 10, color: "#2563eb" }} />
                SonarQube
              </div>
              <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4 }}>
                Static analysis for bug and vulnerability detection.
              </div>
              <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: runSonar ? "#22c55e" : "#94a3b8",
                }} />
                <span style={{ fontSize: 10, fontWeight: 700, color: runSonar ? "#16a34a" : "#94a3b8" }}>
                  {runSonar ? "ACTIVE" : "INACTIVE"}
                </span>
              </div>
            </div>
            {/* FOSSA card */}
            <div
              onClick={() => setRunFossa(!runFossa)}
              style={{
                flex: 1, padding: "10px 12px", borderRadius: 10,
                border: `1.5px solid ${runFossa ? "#2563eb" : "#e2e8f0"}`,
                background: runFossa ? "#eff6ff" : "#fff",
                cursor: "pointer", transition: "all 0.15s ease",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 12, color: "#0f172a", marginBottom: 2 }}>
                <FaShieldAlt style={{ marginRight: 6, fontSize: 10, color: "#f59e0b" }} />
                FOSSA
              </div>
              <div style={{ fontSize: 10, color: "#64748b", lineHeight: 1.4 }}>
                Open-source license compliance and security.
              </div>
              <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: runFossa ? "#22c55e" : "#94a3b8",
                }} />
                <span style={{ fontSize: 10, fontWeight: 700, color: runFossa ? "#16a34a" : "#94a3b8" }}>
                  {runFossa ? "ACTIVE" : "INACTIVE"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Test Suites Selection ───────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <FaVial style={{ fontSize: 18, color: "#0f172a" }} />
            <span style={{ fontWeight: 800, fontSize: 18, color: "#0f172a" }}>Test Suites Selection</span>
          </div>
          <span style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            Configure Unit &amp; Functional test suites
          </span>
        </div>

        {/* ── Stacked layout: Unit Tests (top) + Functional Tests (full width) ── */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr",
          gap: 20,
          alignItems: "start",
        }}>
          {/* ── Unit Tests column ── */}
          <div style={{
            background: "#fff", borderRadius: 14,
            border: "1px solid #e2e8f0", padding: "18px 20px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <span style={{ fontSize: 16 }}>🧪</span>
              <span style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>Unit Tests</span>
            </div>
            {unitTestFilesTotal > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#334155", marginBottom: 8 }}>
                  Existing Unit Test Files ({unitTestFilesTotal})
                </div>
                {renderExistingTestCountBadges(unitTestCountBadges)}
              </div>
            )}
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "14px 18px", borderRadius: 12,
              border: `2px solid ${runTests ? "#22c55e" : "#e2e8f0"}`,
              background: runTests ? "#f0fdf4" : "#fff",
              cursor: "pointer", transition: "all 0.15s ease",
            }}
              onClick={() => setRunTests(!runTests)}
            >
              <input
                type="checkbox" checked={runTests}
                onChange={(e) => setRunTests(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "#22c55e", cursor: "pointer" }}
              />
              <div>
                <div style={{ fontWeight: 700, fontSize: 14, color: "#0f172a" }}>Run Unit Test Suite</div>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
                  Execute automated unit tests after migration to verify functionality.
                </div>
              </div>
              <span style={{
                marginLeft: "auto", fontSize: 10, fontWeight: 700,
                padding: "3px 10px", borderRadius: 6,
                background: "#dcfce7", color: "#166534",
              }}>RECOMMENDED</span>
            </div>

            {runTests && (
              <div style={{
                padding: "14px 18px", borderRadius: 12,
                border: "1px solid #e2e8f0", background: "#f8fafc",
              }}>
                <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <input
                    type="checkbox" checked={useLLMTests}
                    onChange={(e) => setUseLLMTests(e.target.checked)}
                    style={{ width: 16, height: 16, accentColor: "#3b82f6" }}
                  />
                  <span style={{ fontWeight: 600, fontSize: 13, color: "#1e293b" }}>Use LLM Test Generator</span>
                </label>
                <div style={{ maxWidth: 320 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, color: "#64748b", marginBottom: 4, display: "block" }}>LLM Provider</label>
                  <select
                    style={{ ...styles.select, width: "100%", backgroundColor: useLLMTests ? "#fff" : "#f1f5f9" }}
                    value={selectedLLMProvider}
                    onChange={(e) => setSelectedLLMProvider(e.target.value)}
                    disabled={!useLLMTests}
                  >
                    {LLM_PROVIDERS.map((p) => (
                      <option key={p.value} value={p.value}>{p.label}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </div>
          </div>{/* ── end Unit Tests column ── */}

          {/* ── Functional Tests column ── */}
          <div style={{
            background: "#fff", borderRadius: 14,
            border: "1px solid #e2e8f0", padding: "18px 20px",
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <span style={{ fontSize: 16 }}>🎯</span>
              <span style={{ fontWeight: 800, fontSize: 15, color: "#0f172a" }}>Functional Tests</span>
            </div>
          <div>
            <p style={{
              fontSize: 13, color: "#64748b", marginBottom: 20,
              textAlign: "center", textTransform: "uppercase", letterSpacing: 1.2, fontWeight: 600,
            }}>
              Select Functional Testing Tool
            </p>

            {/* ── Validation Mode Selector ── */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              gap: 8, marginBottom: 22,
            }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: "#475569", letterSpacing: 0.3 }}>
                Validation Mode:
              </span>
              {([
                { id: "auto", label: "Auto", icon: "⚡", tip: "Pipeline decides the best approach" },
                { id: "internal", label: "Internal", icon: "🔍", tip: "Source-code analysis only — fast, no build required" },
                { id: "external", label: "External", icon: "🚀", tip: "Build & start the app, then run real test runners" },
              ] as const).map((mode) => {
                const isActive = functionalTestExecutionMode === mode.id;
                return (
                  <button
                    key={mode.id}
                    title={mode.tip}
                    onClick={() => setFunctionalTestExecutionMode(mode.id)}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "7px 16px", borderRadius: 8,
                      fontSize: 12, fontWeight: isActive ? 700 : 500,
                      cursor: "pointer",
                      border: `1.5px solid ${isActive ? "#2563eb" : "#e2e8f0"}`,
                      background: isActive
                        ? "linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)"
                        : "#fff",
                      color: isActive ? "#1d4ed8" : "#64748b",
                      boxShadow: isActive
                        ? "0 2px 8px rgba(37,99,235,0.15)"
                        : "0 1px 2px rgba(0,0,0,0.04)",
                      transition: "all 0.25s ease",
                    }}
                  >
                    <span>{mode.icon}</span>
                    <span>{mode.label}</span>
                  </button>
                );
              })}
            </div>
            {functionalTestExecutionMode === "external" && (
              <div style={{
                background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8,
                padding: "10px 14px", marginBottom: 18,
                fontSize: 12, color: "#92400e", lineHeight: 1.6, textAlign: "center",
              }}>
                <strong>External Validation</strong> will build the application, start it on a dynamic port,
                and execute real Playwright / RestAssured / Selenium runners against the live app.
                This requires a working build environment (JDK, Maven/Gradle) on the server.
              </div>
            )}
            {functionalTestExecutionMode === "internal" && (
              <div style={{
                background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8,
                padding: "10px 14px", marginBottom: 18,
                fontSize: 12, color: "#166534", lineHeight: 1.6, textAlign: "center",
              }}>
                <strong>Internal Validation</strong> analyzes the project source code to verify endpoint
                annotations, route files, and controller definitions — no build or external tools required.
              </div>
            )}

            <FunctionalTestPanel
              tools={functionalTestingTools as FunctionalToolView[]}
              selectedToolIds={functionalTestToolMethods}
              onToggleTool={toggleFunctionalTestTool}
              onResetAuto={() => setFunctionalTestToolMethods([])}
              preview={scopePreview}
              loading={scopePreviewLoading}
              error={scopePreviewError}
              onDownloadUi={() => void downloadScopeHtml("ui")}
              onDownloadApi={() => void downloadScopeHtml("api")}
            />
          </div>
          </div>{/* ── end Functional Tests column ── */}
        </div>{/* ── end two-column grid ── */}
      </div>

      {/* ── Legacy Test Scope Documents — now rendered inside <FunctionalTestPanel /> above ── */}
      {false && testSuiteTab === "functional" && (
        <div style={{
          background: "#fff",
          borderRadius: 14,
          border: "1px solid #e2e8f0",
          padding: "20px 24px",
          marginBottom: 24,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <FaFileAlt style={{ fontSize: 16, color: "#0f172a" }} />
            <span style={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>Functional Test Scope Documents</span>
          </div>
          <p style={{ fontSize: 12, color: "#64748b", lineHeight: 1.6, marginBottom: 16 }}>
            Download a business-friendly overview of the test cases that will be generated and validated
            for your project. These documents describe the scope in clear business language for stakeholder review.
          </p>
          {/* ── 50/50 Card Grid for Scope Documents ── */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 16,
          }}>
            {/* ── UI Test Scope Card ── */}
            <div
              onClick={async () => {
                if (scopePreviewLoading) return;
                try {
                  setScopePreviewLoading(true);
                  setScopePreviewError(null);
                  const endpoints = (repoAnalysis as any)?.api_endpoints || [];
                  const uiRoutes = (repoAnalysis as any)?.uiRoutes || [];
                  const pageData = (repoAnalysis as any)?.page_data || {};
                  const result = await previewFunctionalTestScope(
                    selectedRepo?.name || repoUrl.split("/").pop()?.replace(".git", "") || "Project",
                    endpoints,
                    uiRoutes,
                    pageData,
                    functionalTestToolMethods,
                    repoUrl,
                    currentToken || "",
                  );
                  const blob = new Blob([result.uiScopeHtml], { type: "text/html" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `ui-test-scope-${(selectedRepo?.name || "project").replace(/[^a-zA-Z0-9_-]/g, "-").toLowerCase()}.html`;
                  a.click();
                  URL.revokeObjectURL(url);
                  setScopePreview(result);
                } catch (err: any) {
                  setScopePreviewError(err?.message || "Failed to generate scope document");
                } finally {
                  setScopePreviewLoading(false);
                }
              }}
              onMouseEnter={() => setHoveredScopeCard("ui")}
              onMouseLeave={() => setHoveredScopeCard(null)}
              style={{
                background: "#fff",
                borderRadius: 14,
                border: `2px solid ${hoveredScopeCard === "ui" ? "#2563eb" : "#e2e8f0"}`,
                padding: "24px 20px 20px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                cursor: scopePreviewLoading ? "not-allowed" : "pointer",
                transition: "all 0.35s cubic-bezier(0.4,0,0.2,1)",
                transform: hoveredScopeCard === "ui" ? "translateY(-4px) scale(1.01)" : "translateY(0) scale(1)",
                boxShadow: hoveredScopeCard === "ui"
                  ? "0 8px 24px rgba(37,99,235,0.18), 0 2px 8px rgba(37,99,235,0.08)"
                  : "0 1px 3px rgba(0,0,0,0.06)",
                opacity: scopePreviewLoading ? 0.6 : 1,
              }}
            >
              <div style={{
                width: 48, height: 48, borderRadius: 12,
                background: hoveredScopeCard === "ui" ? "#dbeafe" : "#eff6ff",
                display: "flex",
                alignItems: "center", justifyContent: "center",
                marginBottom: 14, fontSize: 22,
                transition: "all 0.3s ease",
                transform: hoveredScopeCard === "ui" ? "scale(1.1)" : "scale(1)",
              }}>
                📄
              </div>
              <h4 style={{
                fontWeight: 700, fontSize: 14, color: "#0f172a", marginBottom: 8, lineHeight: 1.3,
              }}>
                UI Test Scope
              </h4>
              <span style={{
                fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
                marginBottom: 10, padding: "3px 10px", borderRadius: 4,
                background: "#dbeafe", color: "#2563eb",
              }}>
                Page Interactions
              </span>
              <p style={{
                fontSize: 11, color: "#64748b", lineHeight: 1.5, marginBottom: 18, minHeight: 40,
              }}>
                Validates page loads, form submissions, table rendering, and navigation flows across all detected UI routes.
              </p>
              <button
                disabled={scopePreviewLoading}
                style={{
                  marginTop: "auto", width: "100%", padding: "10px 0",
                  borderRadius: 8, fontWeight: 700, fontSize: 12,
                  border: "none",
                  background: hoveredScopeCard === "ui"
                    ? "#2563eb"
                    : "#eff6ff",
                  color: hoveredScopeCard === "ui" ? "#fff" : "#1d4ed8",
                  boxShadow: hoveredScopeCard === "ui"
                    ? "0 2px 8px rgba(37,99,235,0.25)"
                    : "inset 0 0 0 1.5px #bfdbfe",
                  cursor: scopePreviewLoading ? "not-allowed" : "pointer",
                  transition: "all 0.3s cubic-bezier(0.4,0,0.2,1)",
                }}
              >
                {scopePreviewLoading ? "⏳ Generating..." : "📄 Download UI Test Scope"}
              </button>
            </div>

            {/* ── API Test Scope Card ── */}
            <div
              onClick={async () => {
                if (scopePreviewLoading) return;
                try {
                  setScopePreviewLoading(true);
                  setScopePreviewError(null);
                  const endpoints = (repoAnalysis as any)?.api_endpoints || [];
                  const uiRoutes = (repoAnalysis as any)?.uiRoutes || [];
                  const pageData = (repoAnalysis as any)?.page_data || {};
                  const result = await previewFunctionalTestScope(
                    selectedRepo?.name || repoUrl.split("/").pop()?.replace(".git", "") || "Project",
                    endpoints,
                    uiRoutes,
                    pageData,
                    functionalTestToolMethods,
                    repoUrl,
                    currentToken || "",
                  );
                  const blob = new Blob([result.apiScopeHtml], { type: "text/html" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `api-test-scope-${(selectedRepo?.name || "project").replace(/[^a-zA-Z0-9_-]/g, "-").toLowerCase()}.html`;
                  a.click();
                  URL.revokeObjectURL(url);
                  setScopePreview(result);
                } catch (err: any) {
                  setScopePreviewError(err?.message || "Failed to generate scope document");
                } finally {
                  setScopePreviewLoading(false);
                }
              }}
              onMouseEnter={() => setHoveredScopeCard("api")}
              onMouseLeave={() => setHoveredScopeCard(null)}
              style={{
                background: "#fff",
                borderRadius: 14,
                border: `2px solid ${hoveredScopeCard === "api" ? "#16a34a" : "#e2e8f0"}`,
                padding: "24px 20px 20px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                textAlign: "center",
                cursor: scopePreviewLoading ? "not-allowed" : "pointer",
                transition: "all 0.35s cubic-bezier(0.4,0,0.2,1)",
                transform: hoveredScopeCard === "api" ? "translateY(-4px) scale(1.01)" : "translateY(0) scale(1)",
                boxShadow: hoveredScopeCard === "api"
                  ? "0 8px 24px rgba(22,163,74,0.18), 0 2px 8px rgba(22,163,74,0.08)"
                  : "0 1px 3px rgba(0,0,0,0.06)",
                opacity: scopePreviewLoading ? 0.6 : 1,
              }}
            >
              <div style={{
                width: 48, height: 48, borderRadius: 12,
                background: hoveredScopeCard === "api" ? "#bbf7d0" : "#f0fdf4",
                display: "flex",
                alignItems: "center", justifyContent: "center",
                marginBottom: 14, fontSize: 22,
                transition: "all 0.3s ease",
                transform: hoveredScopeCard === "api" ? "scale(1.1)" : "scale(1)",
              }}>
                🔗
              </div>
              <h4 style={{
                fontWeight: 700, fontSize: 14, color: "#0f172a", marginBottom: 8, lineHeight: 1.3,
              }}>
                API Test Scope
              </h4>
              <span style={{
                fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5,
                marginBottom: 10, padding: "3px 10px", borderRadius: 4,
                background: "#dcfce7", color: "#16a34a",
              }}>
                Endpoint Validation
              </span>
              <p style={{
                fontSize: 11, color: "#64748b", lineHeight: 1.5, marginBottom: 18, minHeight: 40,
              }}>
                Validates CRUD operations, response schemas, error handling, and auth guards across all detected API endpoints.
              </p>
              <button
                disabled={scopePreviewLoading}
                style={{
                  marginTop: "auto", width: "100%", padding: "10px 0",
                  borderRadius: 8, fontWeight: 700, fontSize: 12,
                  border: "none",
                  background: hoveredScopeCard === "api"
                    ? "#16a34a"
                    : "#f0fdf4",
                  color: hoveredScopeCard === "api" ? "#fff" : "#15803d",
                  boxShadow: hoveredScopeCard === "api"
                    ? "0 2px 8px rgba(22,163,74,0.25)"
                    : "inset 0 0 0 1.5px #bbf7d0",
                  cursor: scopePreviewLoading ? "not-allowed" : "pointer",
                  transition: "all 0.3s cubic-bezier(0.4,0,0.2,1)",
                }}
              >
                {scopePreviewLoading ? "⏳ Generating..." : "🔗 Download API Test Scope"}
              </button>
            </div>
          </div>
          {scopePreview && (
            <div style={{
              marginTop: 12, padding: "10px 14px", borderRadius: 8,
              background: "#f0fdf4", border: "1px solid #bbf7d0",
              fontSize: 12, color: "#166534",
            }}>
              ✓ Generated: {scopePreview?.uiTestCount} UI tests + {scopePreview?.apiTestCount} API tests
            </div>
          )}
          {scopePreviewError && (
            <div style={{
              marginTop: 12, padding: "10px 14px", borderRadius: 8,
              background: "#fef2f2", border: "1px solid #fecaca",
              fontSize: 12, color: "#dc2626",
            }}>
              ⚠ {scopePreviewError}
            </div>
          )}
        </div>
      )}

      {/* ── Action buttons ─────────────────────────────────── */}
      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(3)}>{renderBackButtonLabel()}</button>
        <button style={{ ...styles.primaryBtn, opacity: loading ? 0.5 : 1 }} onClick={handleStartMigration} disabled={loading}>
          {loading ? "Starting..." : "Start Migration"}
        </button>
      </div>
    </div>
  );

  };

  const renderMigrationAnimation = () => (
    (() => {
      const isInitializingMigration = loading && !migrationJob?.job_id;
      const normalizedMigrationStatus = (() => {
        if (isInitializingMigration) return "starting";
        const currentStepText = (migrationJob?.current_step || "").toLowerCase();
        if (currentStepText.includes("fossa")) return "fossa_analysis";
        if (currentStepText.includes("sonar")) return "sonar_analysis";
        if (currentStepText.includes("test")) return "testing";
        return (migrationJob?.status || "pending").toLowerCase();
      })();

      const phaseRank: Record<string, number> = {
        pending: 0,
        cloning: 1,
        analyzing: 2,
        migrating: 3,
        testing: 4,
        sonar_analysis: 5,
        fossa_analysis: 6,
        pushing: 7,
        completed: 8,
        failed: 8,
      };

      const currentPhaseRank = phaseRank[normalizedMigrationStatus] ?? 0;
      const visibleProgress = isInitializingMigration
        ? 5
        : migrationJob?.status === "completed"
          ? 100
          : Math.min(Math.max(animationProgress, 5), 99);
      const qualityPhase = runFossa
        ? "fossa_analysis"
        : runSonar
          ? "sonar_analysis"
          : runTests
            ? "testing"
            : "migrating";

      const analysisComplete = currentPhaseRank > phaseRank.analyzing || migrationJob?.status === "completed";
      const dependencyComplete =
        currentPhaseRank > phaseRank.migrating ||
        migrationJob?.status === "completed" ||
        animationProgress >= 40;
      const transformationsComplete =
        currentPhaseRank > phaseRank.migrating ||
        migrationJob?.status === "completed" ||
        animationProgress >= 55;
      const qualityComplete =
        currentPhaseRank > phaseRank[qualityPhase] ||
        migrationJob?.status === "completed";
      const reportComplete = migrationJob?.status === "completed";
      const analysisVisible = currentPhaseRank >= phaseRank.analyzing || visibleProgress >= 10;
      const dependencyVisible = currentPhaseRank >= phaseRank.migrating || visibleProgress >= 30;
      const transformationsVisible = currentPhaseRank >= phaseRank.migrating || visibleProgress >= 50;
      const qualityVisible = currentPhaseRank >= phaseRank.testing || visibleProgress >= 60;
      const reportVisible = currentPhaseRank >= phaseRank.pushing || visibleProgress >= 90;
      const currentStepLabel = isInitializingMigration
        ? "Creating migration job and preparing the workspace..."
        : migrationJob?.current_step || "Initializing migration...";

      return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        {renderWizardIconBadge(<FaRocket />, "#f59e0b", "xl")}
        <div>
          <h2 style={styles.title}>Migration in Progress</h2>
          <p style={styles.subtitle}>Your project is being migrated... Please wait.</p>
        </div>
      </div>

      {/* {renderMigrationTimer()} */}

      {/* Animated Migration Progress */}
      <div style={styles.animationContainer}>
        <div style={styles.migrationAnimation}>
          <div style={styles.animationHeader}>
            <div style={styles.migratingText}>
            <span style={{ color: "#7c3aed" }}>Modernizing</span>{" "} {selectedRepo?.name || repoUrl.split("/").pop()?.replace(".git", "") || "Java Project"}
            </div>
            {/* <div style={styles.migratingText}>Migrating Java Project</div> */}
            <div style={styles.versionTransition}>
              Java {selectedSourceVersion} {"->"} Java {effectiveTargetVersion || "Select Java Version"}
            </div>
          </div>

          {/* Animated Steps */}
          <div style={styles.animationSteps}>
            <div style={{ ...styles.animationStep, opacity: analysisVisible ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>{renderWizardIconBadge(<FaSearch />, "#0ea5e9", "md")}</div>
              <div style={styles.stepText}>Analyzing Source Code</div>
              {analysisComplete && <div style={styles.checkMarkAnimated}><FaCheckCircle /></div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: dependencyVisible ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>{renderWizardIconBadge(<FaCogs />, "#7c3aed", "md")}</div>
              <div style={styles.stepText}>Updating Dependencies</div>
              {dependencyComplete && <div style={styles.checkMarkAnimated}><FaCheckCircle /></div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: transformationsVisible ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>{renderWizardIconBadge(<FaCode />, "#22c55e", "md")}</div>
              <div style={styles.stepText}>Applying Code Transformations</div>
              {transformationsComplete && <div style={styles.checkMarkAnimated}><FaCheckCircle /></div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: qualityVisible ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>{renderWizardIconBadge(<FaVial />, "#f59e0b", "md")}</div>
              <div style={styles.stepText}>Running Tests & Quality Checks</div>
              {qualityComplete && <div style={styles.checkMarkAnimated}><FaCheckCircle /></div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: reportVisible ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>{renderWizardIconBadge(<FaFileAlt />, "#22c55e", "md")}</div>
              <div style={styles.stepText}>Generating Migration Report</div>
              {reportComplete && <div style={styles.checkMarkAnimated}><FaCheckCircle /></div>}
            </div>
          </div>

          {/* Progress Bar with Animation */}
          <div style={styles.progressExperienceSection}>
            <div style={styles.animatedProgressSection}>
              <div style={styles.animatedProgressHeader}>
                <span>Migration Progress</span>
                <span>{visibleProgress}%</span>
              </div>
              <div style={styles.animatedProgressBar}>
                <div style={{
                  ...styles.animatedProgressFill,
                  width: `${visibleProgress}%`,
                  background: `linear-gradient(90deg, #3b82f6 ${Math.max(visibleProgress - 10, 0)}%, #22c55e ${visibleProgress}%)`
                }} />
              </div>
            </div>

            <div style={styles.progressInsightRow}>
              {renderMigrationTimer()}

              <div style={styles.statusHeroBlock}>
                <div style={styles.currentStatusHeadline}>{currentStepLabel}</div>
              </div>
            </div>
            {isInitializingMigration && (
              <div style={{ ...styles.recentLog, color: "#2563eb", fontSize: 12 }}>
                Info: loading the progress session. Large repositories can take a little longer to initialize.
              </div>
            )}
            {migrationJob?.status === "cloning" && (
              <div style={{ ...styles.recentLog, color: '#f59e0b', fontSize: 12 }}>
                Info: cloning repository... this may take a few minutes for large repositories. Please wait.
              </div>
            )}
          </div>
        </div>
      </div>
      
    </div>
      );
    })()
  );

  const renderMigrationProgress = () => {
    if (!migrationJob) return null;
    return (
      <div style={styles.card}>
        <div style={styles.stepHeader}>
          {migrationJob?.status === "completed"
            ? renderWizardIconBadge(<FaCheckCircle />, "#22c55e", "xl")
            : migrationJob?.status === "failed"
              ? renderWizardIconBadge(<FaExclamationCircle />, "#ef4444", "xl")
              : renderWizardIconBadge(<FaRocket />, "#f59e0b", "xl")}
          <div>
            <h2 style={styles.title}>{migrationJob?.status === "completed" ? "Migration Completed!" : migrationJob?.status === "failed" ? "Migration Failed" : "Migration in Progress"}</h2>
            <p style={styles.subtitle}>{migrationJob?.current_step || "Processing..."}</p>
          </div>
        </div>
        {renderMigrationTimer()}
        {migrationJob?.status === "failed" && (
          <div style={{ ...styles.errorBox, padding: 20, marginBottom: 20, borderRadius: 8, backgroundColor: '#fee2e2', borderLeft: '4px solid #dc2626' }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#7f1d1d', marginBottom: 10 }}>Migration Failed</div>
            {migrationJob?.error_message && (
              <div style={{ color: '#991b1b', marginBottom: 10, fontFamily: 'monospace', fontSize: 14, padding: 10, backgroundColor: '#fecaca', borderRadius: 4 }}>
                {migrationJob?.error_message}
              </div>
            )}
            {migrationJob?.migration_log && migrationJob.migration_log.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#7f1d1d', marginBottom: 8 }}>Recent Logs:</div>
                <div style={{ fontSize: 12, color: '#7f1d1d', fontFamily: 'monospace', maxHeight: 150, overflow: 'auto' }}>
                  {migrationJob!.migration_log.slice(-5).map((log, idx) => (
                    <div key={idx} style={{ marginBottom: 4 }}>- {log}</div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        <div style={styles.progressSection}>
          <div style={styles.progressHeader}><span>Overall Progress</span><span>{migrationJob?.progress_percent ?? 0}%</span></div>
          <div style={styles.progressBar}><div style={{ ...styles.progressFill, width: `${migrationJob?.progress_percent ?? 0}%` }} /></div>
        </div>
        <div style={styles.statsGrid}>
          <div style={styles.statBox}><div style={styles.statValue}>{migrationJob.files_modified}</div><div style={styles.statLabel}>Files Modified</div></div>
          <div style={styles.statBox}><div style={styles.statValue}>{migrationJob.issues_fixed}</div><div style={styles.statLabel}>Issues Fixed</div></div>
          <div style={styles.statBox}><div style={{ ...styles.statValue, color: migrationJob.total_errors > 0 ? "#ef4444" : "#22c55e" }}>{migrationJob.total_errors}</div><div style={styles.statLabel}>Errors</div></div>
          <div style={styles.statBox}><div style={{ ...styles.statValue, color: migrationJob.total_warnings > 0 ? "#f59e0b" : "#22c55e" }}>{migrationJob.total_warnings}</div><div style={styles.statLabel}>Warnings</div></div>
        </div>
        {migrationJob.status === "completed" && migrationJob.target_repo && (
          <div style={styles.successBox}>
            <div style={styles.successTitle}>Migration Successful!</div>
            <a href={getRepositoryLink(migrationJob.target_repo) || "#"} target="_blank" rel="noreferrer" style={styles.repoLink}>
              {renderForwardLinkLabel("View Migrated Repository")}
            </a>
          </div>
        )}
        <div style={styles.btnRow}>
          {(migrationJob.status === "cloning" || migrationJob.status === "analyzing" || migrationJob.status === "migrating") && (
            <button 
              style={{ ...styles.secondaryBtn, marginRight: 10, backgroundColor: '#ef4444', color: 'white' }}
              onClick={() => {
                setError("");
                resetWizard();
              }}
            >
              Cancel Migration
            </button>
          )}
          {migrationJob.status === "failed" && (
            <button 
              style={{ ...styles.primaryBtn, marginRight: 10 }}
              onClick={() => {
                setError("");
                resetWizard();
              }}
            >
              Try Again
            </button>
          )}
          {migrationJob.status !== "cloning" && migrationJob.status !== "analyzing" && migrationJob.status !== "migrating" && migrationJob.status !== "pending" && migrationJob.status !== "failed" && (
            <button style={styles.primaryBtn} onClick={() => setStep(7)}>{renderForwardButtonLabel("View Migration Report")}</button>
          )}
        </div>
      </div>
    );
  };

  const renderStep11 = () => {
    const sonarReport = (migrationJob?.sonar_report ?? null) as SonarReport | null;
    const sonarBugDetails = sonarReport?.bug_details ?? [];
    const sonarVulnerabilityDetails = sonarReport?.vulnerability_details ?? [];
    const sonarCodeSmellDetails = sonarReport?.code_smell_details ?? [];
    const sonarHotspotDetails = sonarReport?.security_hotspot_details ?? [];
    const codeSmellSeverityCounts = sonarCodeSmellDetails.reduce(
      (acc, issue) => {
        acc[getCodeSmellSeverityBucket(issue.severity)] += 1;
        return acc;
      },
      { low: 0, medium: 0, high: 0, blocker: 0 } as Record<Exclude<CodeSmellSeverityFilter, "all">, number>
    );
    const filteredCodeSmellDetails =
      codeSmellSeverityFilter === "all"
        ? sonarCodeSmellDetails
        : sonarCodeSmellDetails.filter((issue) => getCodeSmellSeverityBucket(issue.severity) === codeSmellSeverityFilter);
    const sonarDetailsAvailable =
      sonarBugDetails.length > 0 ||
      sonarVulnerabilityDetails.length > 0 ||
      sonarCodeSmellDetails.length > 0 ||
      sonarHotspotDetails.length > 0;
    const sonarTotalFindings =
      (migrationJob?.sonar_vulnerabilities ?? 0) +
      (migrationJob?.sonar_code_smells ?? 0) +
      (migrationJob?.sonar_bugs ?? 0) +
      (migrationJob?.sonar_security_hotspots ?? 0);
    const sonarCategoryCards = [
      {
        key: "bugs" as const,
        label: "Bugs",
        count: migrationJob?.sonar_bugs ?? 0,
        accent: "#2563eb",
        note: "Correctness issues",
        icon: <FaCode />,
        surface: "linear-gradient(180deg, #f8fbff 0%, #ffffff 100%)",
        tint: "#dbeafe",
      },
      {
        key: "vulnerabilities" as const,
        label: "Vulnerabilities",
        count: migrationJob?.sonar_vulnerabilities ?? 0,
        accent: "#ef4444",
        note: "Security defects",
        icon: <FaExclamationTriangle />,
        surface: "linear-gradient(180deg, #fff7f7 0%, #ffffff 100%)",
        tint: "#fecaca",
      },
      {
        key: "code_smells" as const,
        label: "Code Smells",
        count: migrationJob?.sonar_code_smells ?? 0,
        accent: "#f59e0b",
        note: "Maintainability debt",
        icon: <FaTools />,
        surface: "linear-gradient(180deg, #fffdf6 0%, #ffffff 100%)",
        tint: "#fde68a",
      },
      {
        key: "security_hotspots" as const,
        label: "Security Hotspots",
        count: migrationJob?.sonar_security_hotspots ?? 0,
        accent: "#14b8a6",
        note: "Needs manual review",
        icon: <FaShieldAlt />,
        surface: "linear-gradient(180deg, #f3fffd 0%, #ffffff 100%)",
        tint: "#99f6e4",
      },
    ];
    const visibleSonarSections = [
      {
        key: "vulnerabilities" as const,
        title: "Vulnerabilities",
        count: migrationJob?.sonar_vulnerabilities ?? 0,
        details: sonarVulnerabilityDetails as Array<SonarIssueDetail | SonarHotspotDetail>,
        accentColor: "#dc2626",
        emptyMessage:
          (migrationJob?.sonar_vulnerabilities ?? 0) > 0
            ? "Summary count is available, but detailed vulnerability items were not returned by the current Sonar API response."
            : "No vulnerability findings were reported.",
      },
      {
        key: "code_smells" as const,
        title: "Code Smells",
        count: migrationJob?.sonar_code_smells ?? 0,
        details: filteredCodeSmellDetails as Array<SonarIssueDetail | SonarHotspotDetail>,
        accentColor: "#d97706",
        emptyMessage:
          (migrationJob?.sonar_code_smells ?? 0) > 0
            ? codeSmellSeverityFilter === "all"
              ? "Summary count is available, but detailed code smell items were not returned by the current Sonar API response."
              : "No code smell findings match the selected severity filter."
            : "No code smell findings were reported.",
      },
      {
        key: "security_hotspots" as const,
        title: "Security Hotspots",
        count: migrationJob?.sonar_security_hotspots ?? 0,
        details: sonarHotspotDetails as Array<SonarIssueDetail | SonarHotspotDetail>,
        accentColor: "#b45309",
        emptyMessage:
          (migrationJob?.sonar_security_hotspots ?? 0) > 0
            ? "Summary count is available, but detailed hotspot items were not returned by the current Sonar API response."
            : "No security hotspot findings were reported.",
      },
      {
        key: "bugs" as const,
        title: "Bugs",
        count: migrationJob?.sonar_bugs ?? 0,
        details: sonarBugDetails as Array<SonarIssueDetail | SonarHotspotDetail>,
        accentColor: "#2563eb",
        emptyMessage:
          (migrationJob?.sonar_bugs ?? 0) > 0
            ? "Summary count is available, but detailed bug items were not returned by the current Sonar API response."
            : "No bug findings were reported.",
      },
    ].filter((section) => sonarFindingFilter === "all" || section.key === sonarFindingFilter);

    const renderSonarIssueCard = (
      issue: SonarIssueDetail | SonarHotspotDetail,
      index: number,
      findingType: string,
      accentColor: string
    ) => {
      const severityColors = getSonarSeverityColor(getSonarIssueSeverityValue(issue));
      const statusColors = getSonarStatusColor(issue.status || null);
      const fileLabel = `${issue.component || "N/A"}${issue.line ? `:${issue.line}` : ""}`;
      return (
        <div
          key={`${issue.key || findingType}-${index}`}
          style={{
            ...styles.sonarFindingCard,
            borderColor: `${accentColor}33`,
            boxShadow: `inset 3px 0 0 ${accentColor}`,
          }}
        >
          <div style={styles.sonarFindingHeader}>
            <div style={styles.sonarFindingTitle}>{issue.message || issue.rule || "Unnamed Sonar finding"}</div>
            <div style={styles.sonarFindingBadgeRow}>
              {getSonarIssueSeverityValue(issue) && (
                <span style={{ ...styles.sonarFindingBadge, ...severityColors }}>
                  {(getSonarIssueSeverityValue(issue) || "").toString().toUpperCase()}
                </span>
              )}
              {issue.status && (
                <span style={{ ...styles.sonarFindingBadge, ...statusColors }}>
                  {issue.status.toUpperCase()}
                </span>
              )}
            </div>
          </div>
          <div style={styles.sonarFindingMeta}>
            <span style={styles.sonarFindingMetaPill}><strong>File:</strong> {fileLabel}</span>
            {issue.rule && <span><strong>Rule:</strong> {issue.rule}</span>}
            {"security_category" in issue && issue.security_category && (
              <span><strong>Category:</strong> {issue.security_category}</span>
            )}
            {("effort" in issue && issue.effort) && <span><strong>Effort:</strong> {issue.effort}</span>}
            {("resolution" in issue && issue.resolution) && <span><strong>Resolution:</strong> {issue.resolution}</span>}
            {issue.author && <span><strong>Author:</strong> {issue.author}</span>}
            {issue.update_date && <span><strong>Updated:</strong> {formatSonarTimestamp(issue.update_date)}</span>}
          </div>
        </div>
      );
    };

    const renderSonarFindingSection = (
      sectionKey: Exclude<SonarFindingFilter, "all">,
      title: string,
      count: number,
      details: Array<SonarIssueDetail | SonarHotspotDetail>,
      accentColor: string,
      emptyMessage: string
    ) => {
      const visibleCount = visibleSonarFindingCounts[sectionKey] ?? SONAR_FINDINGS_PAGE_SIZE;
      const visibleItems = details.slice(0, visibleCount);
      const remainingCount = Math.max(details.length - visibleItems.length, 0);
      const loadNextSonarFindings = () => {
        if (remainingCount <= 0) return;
        setVisibleSonarFindingCounts((current) => ({
          ...current,
          [sectionKey]: Math.min((current[sectionKey] ?? SONAR_FINDINGS_PAGE_SIZE) + SONAR_FINDINGS_PAGE_SIZE, details.length),
        }));
      };

      return (
        <div
          style={{
            ...styles.sonarFindingSection,
            borderColor: `${accentColor}33`,
            background: `linear-gradient(180deg, ${accentColor}08 0%, #ffffff 34%)`,
          }}
        >
          <div style={styles.sonarFindingSectionHeader}>
            <div style={styles.sonarFindingSectionTitleRow}>
              <h4 style={styles.sonarFindingSectionTitle}>{title}</h4>
              <span style={{ ...styles.sonarFindingCountBadge, color: accentColor, borderColor: `${accentColor}33`, background: `${accentColor}12` }}>
                {count}
              </span>
            </div>
            <div style={styles.sonarFindingSectionDescription}>
              {details.length > 0
                ? `Showing ${visibleItems.length} of ${details.length} detailed ${title.toLowerCase()}.`
                : emptyMessage}
            </div>
          </div>
          {details.length > 0 ? (
            <>
              <div
                style={styles.sonarFindingsList}
                onScroll={(event) => {
                  if (remainingCount <= 0) return;
                  const target = event.currentTarget;
                  const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
                  if (distanceFromBottom <= 24) {
                    loadNextSonarFindings();
                  }
                }}
              >
                {visibleItems.map((issue, index) => renderSonarIssueCard(issue, index, title, accentColor))}
              </div>
              {details.length > SONAR_FINDINGS_PAGE_SIZE && (
                <div style={styles.sonarFindingNote}>
                  Scroll inside this section to review the loaded findings. When you reach the bottom, the next set loads automatically.
                </div>
              )}
            </>
          ) : (
            <div style={styles.sonarFindingEmpty}>{emptyMessage}</div>
          )}
        </div>
      );
    };

    const effectiveFossa = fossaResult ?? migrationJob?.fossa_report ?? null;
    const fossaPolicyStatus = effectiveFossa?.compliance_status ?? migrationJob?.fossa_policy_status ?? "N/A";
    const fossaScanMode = effectiveFossa?.scan_mode ?? migrationJob?.fossa_scan_mode ?? (runFossa ? "requested" : null);
    const fossaLicenseIssueCount = getFossaLicenseIssueCount(effectiveFossa, migrationJob?.fossa_license_issues ?? 0);
    const fossaVulnerabilityTotal = getFossaVulnerabilityTotal(effectiveFossa, migrationJob?.fossa_vulnerabilities ?? 0);
    const fossaOutdatedCount = effectiveFossa?.details_available === false
      ? null
      : (effectiveFossa?.outdated_dependencies ?? migrationJob?.fossa_outdated_dependencies ?? 0);
    const fossaAnalysisUrl = effectiveFossa?.analysis_url ?? migrationJob?.fossa_analysis_url ?? null;
    const fossaErrorMessage = effectiveFossa?.error_message ?? migrationJob?.fossa_error_message ?? null;
    const fossaEnrichmentErrorMessage =
      effectiveFossa?.enrichment_error_message &&
      effectiveFossa?.enrichment_error_message !== fossaErrorMessage
        ? effectiveFossa.enrichment_error_message
        : null;
    const fossaIssueCount = effectiveFossa?.issue_count ?? null;
    const fossaDetailsAvailable = effectiveFossa?.details_available !== false;
    const fossaIsRealScan = Boolean(effectiveFossa?.real_scan ?? migrationJob?.fossa_real_scan);
    const fossaSeverityCounts = getFossaSeverityCounts(effectiveFossa);
    const hasFossaSecurityData =
      effectiveFossa != null ||
      migrationJob?.fossa_scan_mode != null ||
      migrationJob?.fossa_policy_status != null;
    const fossaScanModeLabel = getFossaScanModeLabel(fossaScanMode);
    const fossaStatusColor =
      fossaPolicyStatus === "PASSED"
        ? "#22c55e"
        : fossaPolicyStatus === "UNAVAILABLE" || fossaScanMode === "pending"
          ? "#f59e0b"
          : "#ef4444";
    const detectedDependencyCount = migrationJob?.dependency_count ?? migrationJob?.dependencies?.length ?? 0;
    const dependencyUpdates = (migrationJob?.dependencies || []).filter((dep) => {
      const normalizedStatus = (dep.status || "").toLowerCase();
      return normalizedStatus === "upgraded" || normalizedStatus === "updated" || Boolean(dep.new_version);
    });
    const dependencyUpgradeCount = dependencyUpdates.length;
    const warningsRemaining = Math.max(
      (migrationJob?.total_warnings ?? 0) - (migrationJob?.warnings_fixed ?? 0),
      0,
    );
    const sonarVulnerabilityCount = migrationJob?.sonar_vulnerabilities ?? 0;
    const dependencyVulnerabilityCount = typeof fossaVulnerabilityTotal === "number" ? fossaVulnerabilityTotal : null;
    const combinedVulnerabilityCount =
      sonarVulnerabilityCount + (dependencyVulnerabilityCount ?? 0);
    const reportedVulnerabilityCount =
      dependencyVulnerabilityCount === null && hasFossaSecurityData && sonarVulnerabilityCount === 0
        ? null
        : combinedVulnerabilityCount;
    const scannedDependencyCount =
      effectiveFossa?.total_dependencies ?? migrationJob?.fossa_total_dependencies ?? detectedDependencyCount;
    const vulnerabilityMeta =
      reportedVulnerabilityCount === null
        ? fossaIssueCount != null
          ? `FOSSA reported ${fossaIssueCount} issues, but the vulnerability-only breakdown is unavailable.`
          : "Vulnerability details are still being prepared."
        : reportedVulnerabilityCount > 0
          ? dependencyVulnerabilityCount != null
            ? `${reportedVulnerabilityCount} remaining after final scans (${sonarVulnerabilityCount} code, ${dependencyVulnerabilityCount} dependency).`
            : `${reportedVulnerabilityCount} code vulnerabilities remaining after final scans.`
          : scannedDependencyCount > 0
            ? `0 remaining across ${scannedDependencyCount} scanned dependencies and the latest code scan.`
            : warningsRemaining > 0
              ? `${warningsRemaining} warnings remain after migration.`
              : "No active vulnerability findings reported.";
    const reportStatusLabel =
      migrationJob?.status === "completed"
        ? "Completed"
        : migrationJob?.status === "failed"
          ? "Needs Attention"
          : "In Progress";
    const reportStatusTone =
      migrationJob?.status === "completed"
        ? { bg: "linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%)", border: "#86efac", text: "#166534" }
        : migrationJob?.status === "failed"
          ? { bg: "linear-gradient(135deg, #fee2e2 0%, #fecaca 100%)", border: "#fca5a5", text: "#991b1b" }
          : { bg: "linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)", border: "#93c5fd", text: "#1d4ed8" };
    const reportHeroStats = [
      {
        label: "Files Modified",
        value: String(migrationJob?.files_modified ?? 0),
        accent: "#2563eb",
        meta: `Java ${migrationJob?.source_java_version ?? "?"} -> Java ${migrationJob?.target_java_version ?? "?"}`,
        surface: "linear-gradient(180deg, #eef6ff 0%, #e1efff 100%)",
        borderColor: "#c7dcff",
        shadow: "0 16px 30px rgba(37, 99, 235, 0.12)",
      },
      {
        label: "Issues Fixed",
        value: String(migrationJob?.issues_fixed ?? 0),
        accent: "#10b981",
        meta: `${migrationJob?.issues_fixed ?? 0} migration issues marked fixed`,
        surface: "linear-gradient(180deg, #ecfdf5 0%, #dcfce7 100%)",
        borderColor: "#bbf7d0",
        shadow: "0 16px 30px rgba(16, 185, 129, 0.12)",
      },
      {
        label: "Upgraded",
        value: String(dependencyUpgradeCount),
        accent: "#7c3aed",
        meta: `${detectedDependencyCount} dependencies detected in analysis`,
        surface: "linear-gradient(180deg, #f6f0ff 0%, #efe6ff 100%)",
        borderColor: "#ddd6fe",
        shadow: "0 16px 30px rgba(124, 58, 237, 0.12)",
      },
      {
        label: "Vulnerabilities",
        value: reportedVulnerabilityCount == null ? "N/A" : String(reportedVulnerabilityCount),
        accent:
          reportedVulnerabilityCount == null
            ? "#d97706"
            : reportedVulnerabilityCount > 0
              ? "#dc2626"
              : "#16a34a",
        meta: vulnerabilityMeta,
        surface:
          reportedVulnerabilityCount == null
            ? "linear-gradient(180deg, #fff7ed 0%, #ffedd5 100%)"
            : reportedVulnerabilityCount > 0
            ? "linear-gradient(180deg, #fff1f2 0%, #ffe4e6 100%)"
            : "linear-gradient(180deg, #f0fdf4 0%, #dcfce7 100%)",
        borderColor:
          reportedVulnerabilityCount == null
            ? "#fdba74"
            : reportedVulnerabilityCount > 0
              ? "#fecdd3"
              : "#bbf7d0",
        shadow:
          reportedVulnerabilityCount == null
            ? "0 16px 30px rgba(217, 119, 6, 0.10)"
            : reportedVulnerabilityCount > 0
            ? "0 16px 30px rgba(220, 38, 38, 0.10)"
            : "0 16px 30px rgba(22, 163, 74, 0.10)",
      },
    ];
    const reportHeroSummary =
      migrationJob?.status === "completed"
        ? `The migration finished successfully${migrationJob?.target_repo ? " and the destination is ready to review." : "."}`
        : "The migration report below captures the current progress, results, and follow-up details.";
      const totalDependencyPages = Math.max(
        1,
        Math.ceil((dependencyUpdates.length || 0) / REPORT_DEPENDENCIES_PAGE_SIZE)
    );
    const currentDependencyPage = Math.min(reportDependencyPage, totalDependencyPages);
    const dependencyStartIndex = (currentDependencyPage - 1) * REPORT_DEPENDENCIES_PAGE_SIZE;
    const paginatedDependencies = dependencyUpdates.slice(
      dependencyStartIndex,
      dependencyStartIndex + REPORT_DEPENDENCIES_PAGE_SIZE
    );
    const dependencyRangeStart = dependencyUpdates.length ? dependencyStartIndex + 1 : 0;
    const dependencyRangeEnd = Math.min(
      dependencyStartIndex + REPORT_DEPENDENCIES_PAGE_SIZE,
      dependencyUpdates.length || 0
    );

    return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        {renderWizardIconBadge(<FaCheckCircle />, "#22c55e", "xl")}
        <div>
          <h2 style={styles.title}>Migration Report</h2>
          <p style={styles.subtitle}>Complete migration summary with all results and metrics.</p>
        </div>
      </div>
      <React.Suspense
        fallback={
          <div style={styles.reportContainer}>
            <div style={styles.loadingBox}>
              <div style={styles.spinner}></div>
              <span>Loading migration report...</span>
            </div>
          </div>
        }
      >
      {migrationJob && (
        <div style={styles.reportContainer}>
          <div style={styles.reportHeroShell}>
            <div style={styles.reportHeroHeader}>
              <div style={styles.reportHeroContent}>
                <div style={styles.reportHeroBadgeRow}>
                  <div style={styles.reportHeroEyebrow}>Modernization Overview</div>
                  <span style={styles.reportHeroFeatureBadge}>AI-Powered Summary</span>
                </div>
                <div style={styles.reportHeroTitleRow}>
                  <h3 style={styles.reportHeroTitle}>Modernization Overview</h3>
                  <span
                    style={{
                      ...styles.reportHeroStatusPill,
                      background: reportStatusTone.bg,
                      borderColor: reportStatusTone.border,
                      color: reportStatusTone.text,
                    }}
                  >
                    {reportStatusLabel}
                  </span>
                </div>
                <p style={styles.reportHeroSubtitle}>{reportHeroSummary}</p>
              </div>
              <div style={styles.reportHeroAside}>
                {migrationJob?.started_at && (
                  <div style={styles.reportHeroElapsed} title="Total elapsed time">
                    <div style={styles.reportHeroElapsedLabel}>Total Modernization Time</div>
                    <div style={styles.reportHeroElapsedValue}>
                      <FaStopwatch style={{ marginRight: 8 }} />
                      {(() => {
                        const secs = getMigrationElapsedSeconds();
                        const h = Math.floor(secs / 3600);
                        const m = Math.floor((secs % 3600) / 60)
                          .toString()
                          .padStart(2, "0");
                        const s = (secs % 60).toString().padStart(2, "0");
                        return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
                      })()}
                    </div>
                  </div>
                )}
                <div style={styles.reportHeroMiniMeta}>
                  <span style={styles.reportHeroMetaPill}>Java {migrationJob.source_java_version} to Java {migrationJob.target_java_version}</span>
                  <span style={styles.reportHeroMetaPill}>
                    Completed {migrationJob.completed_at ? new Date(migrationJob.completed_at).toLocaleString() : "in progress"}
                  </span>
                </div>
              </div>
            </div>
            <div style={styles.reportHeroStatsGrid}>
              {reportHeroStats.map((stat) => (
                <div
                  key={stat.label}
                  style={{
                    ...styles.reportHeroStatCard,
                    background: stat.surface,
                    borderColor: stat.borderColor,
                    boxShadow: stat.shadow,
                  }}
                >
                  <span style={{ ...styles.reportHeroStatValue, color: stat.accent }}>{stat.value}</span>
                  <span style={styles.reportHeroStatLabel}>{stat.label}</span>
                  <span style={styles.reportHeroStatMeta}>{stat.meta}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Source and Target Repository Information */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>Repository Information</h3>
            <div style={styles.reportGrid}>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Source Repository</span>
                <span style={styles.reportValue}>
                  {migrationJob.source_repo && migrationJob.source_repo.startsWith('http') ? (
                    <a href={migrationJob.source_repo} target="_blank" rel="noopener noreferrer" style={{ color: '#2563eb', textDecoration: 'none' }}>
                      {migrationJob.source_repo}
                    </a>
                  ) : (
                    migrationJob.source_repo
                  )}
                </span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Target Repository</span>
                <span style={styles.reportValue}>
                  {migrationJob.target_repo && migrationJob.target_repo.startsWith('http') ? (
                    <a href={migrationJob.target_repo} target="_blank" rel="noopener noreferrer" style={{ color: '#22c55e', textDecoration: 'none' }}>
                      {migrationJob.target_repo}
                    </a>
                  ) : (
                    migrationJob.target_repo || "N/A"
                  )}
                </span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Java Version Migration</span>
                <span style={styles.reportValue}>{migrationJob.source_java_version} {"->"} {migrationJob.target_java_version}</span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Migration Completed</span>
                <span style={styles.reportValue}>{migrationJob.completed_at ? new Date(migrationJob.completed_at).toLocaleString() : "In Progress"}</span>
              </div>
            </div>
          </div>

          {/* Changes Made */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>Changes Made</h3>
            <div style={styles.changesGrid}>
              <div style={styles.changeItem}>
                <span style={styles.changeIcon}><FaFolderOpen /></span>
                <div>
                  <div style={styles.changeTitle}>Files Modified</div>
                  <div style={styles.changeValue}>{migrationJob.files_modified} files updated</div>
                </div>
              </div>
              <div style={styles.changeItem}>
                <span style={styles.changeIcon}><FaCode /></span>
                <div>
                  <div style={styles.changeTitle}>Code Transformations</div>
                  <div style={styles.changeValue}>{migrationJob.issues_fixed} migration issues fixed</div>
                </div>
              </div>
              <div style={styles.changeItem}>
                <span style={styles.changeIcon}><FaCogs /></span>
                <div>
                  <div style={styles.changeTitle}>Dependencies Updated</div>
                  <div style={styles.changeValue}>{dependencyUpgradeCount} dependencies upgraded</div>
                </div>
              </div>
            </div>
          </div>

          {/* Dependency Updates */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>Dependency Updates</h3>
            {dependencyUpdates.length > REPORT_DEPENDENCIES_PAGE_SIZE && (
              <div style={styles.reportPagerBar}>
                <span style={styles.reportPagerHint}>
                  Showing {dependencyRangeStart}-{dependencyRangeEnd} of {dependencyUpdates.length} upgraded dependencies
                </span>
                <div style={styles.reportPagerActions}>
                  <button
                    type="button"
                    style={{ ...styles.secondaryBtn, minHeight: 38, padding: "8px 14px", fontSize: 13 }}
                    onClick={() => setReportDependencyPage((page) => Math.max(1, page - 1))}
                    disabled={currentDependencyPage === 1}
                  >
                    Previous
                  </button>
                  <span style={styles.reportPagerPage}>
                    Page {currentDependencyPage} of {totalDependencyPages}
                  </span>
                  <button
                    type="button"
                    style={{ ...styles.secondaryBtn, minHeight: 38, padding: "8px 14px", fontSize: 13 }}
                    onClick={() => setReportDependencyPage((page) => Math.min(totalDependencyPages, page + 1))}
                    disabled={currentDependencyPage === totalDependencyPages}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
            {dependencyUpdates.length > 0 ? (
              <div style={styles.dependenciesReport}>
                {paginatedDependencies.map((dep, idx) => (
                  <div key={idx} style={styles.dependencyReportItem}>
                    <span style={styles.dependencyName}>{dep.group_id}:{dep.artifact_id}</span>
                    <span style={styles.dependencyChange}>
                      {(dep.current_version || "managed version")} {"->"} {dep.new_version || "updated version"}
                    </span>
                    <span style={{ ...styles.dependencyStatus, backgroundColor: '#ede9fe', color: '#6d28d9' }}>
                      {((dep.status || "updated").replace('_', ' ')).toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={styles.noData}>No dependency upgrades were recorded for this migration.</div>
            )}
          </div>

          {/* <MigrationCodeChangesSection
            styles={styles}
            reportCodeChanges={reportCodeChanges}
            visibleReportCodeChanges={visibleReportCodeChanges}
            hasMoreReportCodeChanges={hasMoreReportCodeChanges}
            showCodeChanges={showCodeChanges}
            selectedDiffFile={selectedDiffFile}
            setShowCodeChanges={setShowCodeChanges}
            setSelectedDiffFile={setSelectedDiffFile}
            setVisibleReportDiffCount={setVisibleReportDiffCount}
            reportDiffsPageSize={REPORT_DIFFS_PAGE_SIZE}
          /> */}
          {/* SonarQube Code Coverage */}
          {(runSonar ||
            migrationJob?.sonar_quality_gate != null ||
            migrationJob?.sonar_scan_mode != null ||
            migrationJob?.sonar_error_message != null ||
            migrationJob?.sonar_report != null) && (
            <MigrationSonarSection
              styles={styles}
              migrationJob={migrationJob}
              isOpen={reportAccordionState.sonar}
              onToggle={() => toggleReportAccordion("sonar")}
              sonarDetailsAvailable={sonarDetailsAvailable}
              sonarTotalFindings={sonarTotalFindings}
              sonarFindingFilter={sonarFindingFilter}
              setSonarFindingFilter={setSonarFindingFilter}
              codeSmellSeverityFilter={codeSmellSeverityFilter}
              setCodeSmellSeverityFilter={setCodeSmellSeverityFilter}
              codeSmellSeverityCounts={codeSmellSeverityCounts}
              sonarCategoryCards={sonarCategoryCards}
              visibleSonarSections={visibleSonarSections}
              renderSonarFindingSection={(section) =>
                renderSonarFindingSection(
                  section.key,
                  section.title,
                  section.count,
                  section.details,
                  section.accentColor,
                  section.emptyMessage
                )
              }
            />
          )}
          {/* FOSSA License & Dependency Report */}
          {(runFossa || migrationJob?.fossa_policy_status != null || migrationJob?.fossa_total_dependencies != null || fossaResult) && (migrationJob || fossaResult) && (
            <MigrationFossaSection
              styles={styles}
              migrationJob={migrationJob}
              isOpen={reportAccordionState.fossa}
              onToggle={() => toggleReportAccordion("fossa")}
              fossaLoading={fossaLoading}
              effectiveFossa={effectiveFossa}
              fossaPolicyStatus={fossaPolicyStatus}
              fossaScanModeLabel={fossaScanModeLabel}
              fossaIsRealScan={fossaIsRealScan}
              fossaAnalysisUrl={fossaAnalysisUrl}
              fossaErrorMessage={fossaErrorMessage}
              fossaEnrichmentErrorMessage={fossaEnrichmentErrorMessage}
              fossaDetailsAvailable={fossaDetailsAvailable}
              fossaIssueCount={fossaIssueCount}
              fossaStatusColor={fossaStatusColor}
              fossaLicenseIssueCount={fossaLicenseIssueCount}
              fossaVulnerabilityTotal={fossaVulnerabilityTotal}
              fossaOutdatedCount={fossaOutdatedCount}
              fossaSeverityCounts={fossaSeverityCounts}
            />
          )}

          <MigrationUnitTestSection
            styles={styles}
            migrationJob={migrationJob}
            testSummaryReportDate={testSummaryReportDate}
            migrationJavaVersion={migrationJavaVersion}
            summaryItems={testSummaryItems}
            testStatusColors={testStatusColors}
            testStatusIcon={testStatusIcon}
            testSummaryText={testSummaryText}
            testModel={testModel}
            testInsights={testInsights}
            testsRun={testsRun}
            rerunTestsLoading={rerunTestsLoading}
            onRerunTests={handleRerunTests}
            onDownloadUnitTestReport={handleDownloadUnitTestReport}
          />

          <MigrationJmeterSection
            styles={styles}
            apiEndpointsValidated={migrationJob?.api_endpoints_validated}
            apiEndpointsWorking={migrationJob?.api_endpoints_working}
          />

          <MigrationLogSection
            styles={styles}
            migrationLogs={migrationLogs}
          />

          <MigrationIssuesSection
            styles={styles}
            issues={migrationJob.issues}
            isOpen={reportAccordionState.issues}
            onToggle={() => toggleReportAccordion("issues")}
          />
        </div>
      )}

      <MigrationReportActions
        styles={styles}
        migrationJob={migrationJob}
        migrationLogs={migrationLogs}
        resetWizard={resetWizard}
        onBack={() => setStep(4)}
        onError={(message) => setError(message)}
      />
      </React.Suspense>
    </div>
    );
  };

  return (
    <div style={styles.container}>
      {step === 3 && <StrategyChatWidget repoUrl={selectedRepo?.url} strategyContext={strategyAssistantContext} />}
      <div style={styles.stepIndicatorContainer}>{renderStepIndicator()}</div>
      <div style={styles.main}>
        {error && <div style={styles.errorBanner}><span>{error}</span><button style={styles.errorClose} onClick={() => setError("")}><FaTimes /></button></div>}
        {step === 1 && <ConnectPage>{renderStep1()}</ConnectPage>}
        {step === 2 && <DiscoveryPage>{renderDiscoveryStep()}</DiscoveryPage>}
        {step === 3 && <StrategyPage>{renderStrategyStep()}</StrategyPage>}
        {step === 4 && <ModernizationPage>{renderMigrationStep()}</ModernizationPage>}
        {step === 5 && <ResultPage>{renderMigrationAnimation()}</ResultPage>}
        {step === 6 && <ResultPage>{renderMigrationProgress()}</ResultPage>}
        {step === 7 && <ResultPage>{renderStep11()}</ResultPage>}
      </div>
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  container: { minHeight: "100vh", width: "100%", maxWidth: "100vw", margin: 0, padding: 0, background: "#f8fafc", fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", overflow: "hidden" },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 40px", width: "100%", boxSizing: "border-box", background: "#fff", borderBottom: "1px solid #e2e8f0" },
  logo: { display: "flex", alignItems: "center", gap: 12 },
  stepIndicatorContainer: { background: "#fff", borderBottom: "1px solid #e2e8f0", padding: "24px 40px", width: "100%", boxSizing: "border-box", overflowX: "auto" },
  stepIndicator: { display: "flex", gap: 0, justifyContent: "center", alignItems: "flex-start", minWidth: "fit-content", flexWrap: "nowrap" },
  stepItem: { display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", borderRadius: 8, transition: "all 0.2s ease", cursor: "pointer", whiteSpace: "nowrap" },
  stepCircle: { width: 44, height: 44, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, fontWeight: 600, transition: "all 0.2s ease" },
  stepLabel: { display: "flex", flexDirection: "column" },
  main: { width: "100%", maxWidth: "100vw", padding: "24px 40px", minHeight: "calc(100vh - 160px)", boxSizing: "border-box" },
  card: { background: "#fff", borderRadius: 12, padding: "28px 32px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)", marginBottom: 20, width: "100%", boxSizing: "border-box", border: "1px solid #e2e8f0" },
  stepHeader: { display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 24, paddingBottom: 20, borderBottom: "1px solid #e2e8f0", flexWrap: "wrap" },
  stepIcon: { fontSize: 36 },
  timerBadge: { marginLeft: "auto", display: "flex",flexDirection: "row",alignItems: "center" /*flexDirection: "column", alignItems: "flex-end"*/, gap: 10, padding: "10px 14px", borderRadius: 10, background: "#fff2e7", opacity:0.7, border: "1px solid #f5c6a5", /*minWidth: 110*/minWidth: 210,
  whiteSpace: "nowrap",flexWrap: "nowrap", },
   icon: {
    fontSize: "28px"
  },
  timerLabel: { fontSize: 18, display:"inline-flex", alignItems:"center", fontWeight: 700, color: "#000000", fontFamily: "Arial", letterSpacing: "0.5px" },
  timerValue: { fontSize: 18, fontWeight: 700, color: "#000000", fontVariantNumeric: "tabular-nums", whiteSpace:"nowrap" },
  migrationTimerSection: { marginBottom: 0 },
  migrationTimerCard: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-start",
    padding: 0,
    borderRadius: 0,
    background: "transparent",
    border: "none",
    boxShadow: "none",
  },
  migrationTimerHero: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    justifyContent: "flex-start",
    flexWrap: "nowrap",
  },
  migrationTimerOrb: {
    width: 64,
    height: 64,
    borderRadius: 20,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  migrationTimerOrbInner: {
    width: 38,
    height: 38,
    borderRadius: 12,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 17,
    opacity: 0.9,
  },
  migrationTimerLabel: {
    fontSize: 11,
    fontWeight: 800,
    fontFamily: "'Manrope', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    textTransform: "uppercase",
    letterSpacing: "0.18em",
    marginBottom: 6,
    textAlign: "left",
  },
  migrationTimerCopy: {
    minWidth: 0,
    flex: "0 1 auto",
    textAlign: "left",
  },
  migrationTimerValue: {
    color: "#0f172a",
    fontFamily: "'Manrope', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    display: "flex",
    alignItems: "baseline",
    gap: 10,
    lineHeight: 0.92,
    fontVariantNumeric: "tabular-nums",
    fontFeatureSettings: '"tnum" 1, "lnum" 1',
    textAlign: "left",
  },
  migrationTimerSegment: {
    display: "inline-flex",
    alignItems: "baseline",
    gap: 2,
  },
  migrationTimerDigits: {
    fontSize: 40,
    fontWeight: 700,
    letterSpacing: "-0.05em",
  },
  migrationTimerUnit: {
    fontSize: 22,
    fontWeight: 600,
    letterSpacing: "-0.02em",
    color: "#334155",
    opacity: 0.72,
  },
  title: { fontSize: 22, fontWeight: 700, marginBottom: 6, color: "#1e293b" },
  subtitle: { fontSize: 14, color: "#64748b", margin: 0, lineHeight: 1.5 },
  discoveryStepTitle: {
    fontSize: 22,
    fontWeight: 700,
    marginBottom: 6,
    color: "#1e293b",
    lineHeight: 1.2,
    letterSpacing: 0,
    textTransform: "none",
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  discoveryStepSubtitle: {
    fontSize: 14,
    color: "#64748b",
    margin: 0,
    lineHeight: 1.5,
    letterSpacing: 0,
    textTransform: "none",
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  sectionTitle: { fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 14, marginTop: 20, display: "flex", alignItems: "center", gap: 8 },
  field: { marginBottom: 20, width: "100%", boxSizing: "border-box" },
  label: { fontWeight: 600, fontSize: 14, marginBottom: 8, display: "block", color: "#374151" },
  labelError: { color: "#b91c1c" },
  requiredMark: { color: "#dc2626", marginLeft: 4 },
  input: { width: "100%", padding: "12px 14px", fontSize: 14, borderRadius: 8, border: "1px solid #d1d5db", boxSizing: "border-box", transition: "all 0.2s ease", backgroundColor: "#fff" },
  select: { width: "100%", padding: "12px 14px", fontSize: 14, borderRadius: 8, border: "1px solid #d1d5db", backgroundColor: "#fff", transition: "all 0.2s ease", cursor: "pointer" },
  selectError: { border: "1px solid #f87171", boxShadow: "0 0 0 3px rgba(248, 113, 113, 0.15)", backgroundColor: "#fffafa" },
  fieldErrorText: { fontSize: 12, color: "#b91c1c", marginTop: 6, fontWeight: 600 },
  helpText: { fontSize: 13, color: "#64748b", marginTop: 6, lineHeight: 1.4 },
  infoButtonContainer: { position: "relative", display: "inline-block", zIndex: 100 },
  infoButton: { width: 22, height: 22, borderRadius: "50%", background: "#e5e7eb", border: "none", cursor: "pointer", fontSize: 12, color: "#6b7280", display: "inline-flex", alignItems: "center", justifyContent: "center", transition: "all 0.2s ease", padding: 0, fontWeight: 600 },
  tooltip: { display: "none", position: "absolute", bottom: "calc(100% + 10px)", left: 0, width: 280, background: "#1e293b", color: "#f1f5f9", padding: "14px", borderRadius: 8, fontSize: 13, zIndex: 1001, boxShadow: "0 10px 25px rgba(0,0,0,0.2)" },
  link: { color: "#2563eb", textDecoration: "none", fontWeight: 500 },
  infoBox: { background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 8, padding: 16, marginBottom: 20, fontSize: 14, color: "#1e40af", width: "100%", boxSizing: "border-box", lineHeight: 1.5 },
  warningBox: { background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 8, padding: 16, marginBottom: 20, width: "100%", boxSizing: "border-box" },
  warningTitle: { fontWeight: 600, marginBottom: 10, color: "#78350f", fontSize: 14 },
  warningList: { margin: 0, paddingLeft: 18, fontSize: 14, color: "#92400e", lineHeight: 1.6 },
  errorBanner: { background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "12px 16px", marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "center", color: "#991b1b", width: "100%", boxSizing: "border-box" },
  errorClose: { background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "#dc2626" },
  errorBox: { background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "14px 16px", marginBottom: 20, color: "#991b1b", width: "100%", boxSizing: "border-box" },
  btnRow: { display: "flex", gap: 12, marginTop: 24, justifyContent: "flex-end", flexWrap: "wrap", alignItems: "center" },
  primaryBtn: {
    background: "linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)",
    color: "#fff",
    border: "1px solid #1d4ed8",
    borderRadius: 12,
    padding: "12px 20px",
    fontWeight: 700,
    cursor: "pointer",
    fontSize: 14,
    lineHeight: 1.2,
    minHeight: 46,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    boxShadow: "0 10px 24px rgba(37, 99, 235, 0.18)",
    transition: "all 0.2s ease",
  },
  secondaryBtn: {
    background: "#fff",
    color: "#1e293b",
    border: "1px solid #cbd5e1",
    borderRadius: 12,
    padding: "12px 20px",
    fontWeight: 600,
    cursor: "pointer",
    fontSize: 14,
    lineHeight: 1.2,
    minHeight: 46,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    boxShadow: "0 6px 18px rgba(15, 23, 42, 0.06)",
    transition: "all 0.2s ease",
  },
  reportActionsBar: {
    display: "flex",
    flexDirection: "row-reverse",
    justifyContent: "space-between",
    gap: 16,
    marginTop: 28,
    flexWrap: "wrap",
    alignItems: "center",
  },
  reportActionGroup: {
    display: "flex",
    gap: 12,
    flexWrap: "wrap",
    alignItems: "center",
  },
  row: { display: "flex", gap: 20 },
  loadingBox: { display: "flex", alignItems: "center", justifyContent: "center", gap: 12, padding: 40, color: "#2563eb", fontWeight: 500, fontSize: 15 },
  spinner: { width: 24, height: 24, border: "3px solid #e5e7eb", borderTop: "3px solid #2563eb", borderRadius: "50%", animation: "spin 0.8s linear infinite" },
  repoList: { display: "flex", flexDirection: "column", gap: 8, maxHeight: 300, overflowY: "auto", paddingRight: 6 },
  repoItem: { display: "flex", alignItems: "center", gap: 12, padding: "14px 16px", border: "1px solid #e2e8f0", borderRadius: 8, cursor: "pointer", transition: "all 0.2s ease", backgroundColor: "#fff" },
  repoIcon: { fontSize: 20 },
  repoInfo: { flex: 1 },
  repoName: { fontWeight: 600, fontSize: 14, color: "#1e293b" },
  repoPath: { fontSize: 12, color: "#64748b", marginTop: 2 },
  repoLanguage: { fontSize: 11, padding: "4px 10px", background: "#eff6ff", borderRadius: 12, color: "#2563eb", fontWeight: 500 },
  arrow: { fontSize: 16, color: "#2563eb" },
  emptyText: { textAlign: "center", color: "#64748b", padding: 40, fontSize: 14 },
  selectedRepoBox: { display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", background: "#eff6ff", borderRadius: 8, marginBottom: 20, border: "1px solid #bfdbfe" },
  changeBtn: { marginLeft: "auto", background: "none", border: "none", color: "#2563eb", cursor: "pointer", fontSize: 13, fontWeight: 600 },
  riskBadge: { display: "inline-block", padding: "8px 16px", borderRadius: 16, fontSize: 13, fontWeight: 600, marginBottom: 14 },
  assessmentGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 20 },
  assessmentItem: { background: "#fff", padding: 18, borderRadius: 10, textAlign: "center", border: "1px solid #e2e8f0" },
  assessmentLabel: { fontSize: 11, color: "#64748b", marginBottom: 8, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" },
  assessmentValue: { fontSize: 20, fontWeight: 700, color: "#1e293b" },
  structureBox: { background: "#f8fafc", padding: 18, borderRadius: 10, marginBottom: 20, border: "1px solid #e2e8f0" },
  structureTitle: { fontSize: 14, fontWeight: 600, marginBottom: 12, color: "#1e293b" },
  structureGrid: { display: "flex", gap: 14, flexWrap: "wrap" },
  structureFound: { color: "#059669", fontWeight: 600 },
  structureMissing: { color: "#9ca3af", fontWeight: 500 },
  dependenciesBox: { marginBottom: 20 },
  dependenciesList: {
    background: "#f8fffb",
    borderRadius: 16,
    padding: 16,
    border: "1px solid #d8f3e4",
    maxHeight: 320,
    overflowY: "auto",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.8)",
  },
  dependenciesGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 },
  dependencyCard: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    minHeight: 92,
    padding: 14,
    borderRadius: 12,
    border: "1px solid #dcefe3",
    background: "linear-gradient(180deg, #eefbf2 0%, #e9f8ee 100%)",
    boxShadow: "0 6px 16px rgba(15, 23, 42, 0.04)",
  },
  dependencyCardName: {
    color: "#334155",
    fontSize: 13,
    fontWeight: 600,
    lineHeight: 1.35,
    wordBreak: "break-word",
  },
  dependencyVersionCard: {
    color: "#64748b",
    fontSize: 12,
    fontFamily: "'JetBrains Mono', monospace",
  },
  dependencyStatusBadge: {
    alignSelf: "flex-start",
    fontSize: 10,
    letterSpacing: 0.6,
    padding: "4px 8px",
    borderRadius: 999,
    fontWeight: 700,
  },
  dependencyItem: { display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid #f1f5f9", fontSize: 13 },
  dependencyVersion: { color: "#2563eb", fontFamily: "'JetBrains Mono', monospace", fontWeight: 500 },
  moreItems: { textAlign: "center", color: "#2563eb", fontSize: 12, paddingTop: 10, fontWeight: 500 },
  dependencyInsightsPanel: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 16,
    padding: 18,
    boxShadow: "0 6px 20px rgba(15, 23, 42, 0.04)",
  },
  dependencyInsightsHeader: {
    marginBottom: 16,
  },
  dependencyInsightsTitle: {
    fontSize: 17,
    fontWeight: 700,
    color: "#1e293b",
    marginBottom: 6,
  },
  dependencyInsightsSubtitle: {
    fontSize: 13,
    color: "#64748b",
    lineHeight: 1.5,
  },
  dependencySummaryGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 12,
    marginBottom: 16,
  },
  dependencySummaryCard: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 14,
    padding: 14,
    textAlign: "center",
    boxShadow: "0 6px 16px rgba(15, 23, 42, 0.04)",
    transition: "all 0.2s ease",
  },
  dependencySummaryLabel: {
    fontSize: 11,
    color: "#64748b",
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    marginBottom: 8,
  },
  dependencySummaryValue: {
    fontSize: 24,
    fontWeight: 800,
    color: "#1e293b",
  },
  dependencyFilterBar: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
    marginBottom: 16,
  },
  dependencyFilterLabel: {
    fontSize: 13,
    color: "#475569",
    fontWeight: 600,
  },
  dependencyFilterClearButton: {
    border: "1px solid #cbd5e1",
    background: "#fff",
    color: "#334155",
    borderRadius: 999,
    padding: "6px 12px",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  },
  dependencyAlertBox: {
    background: "#fff7ed",
    border: "1px solid #fdba74",
    borderRadius: 14,
    padding: 16,
    marginBottom: 18,
  },
  dependencyAlertTitle: {
    fontSize: 14,
    fontWeight: 700,
    color: "#c2410c",
    marginBottom: 6,
  },
  dependencyAlertText: {
    fontSize: 13,
    color: "#9a3412",
    lineHeight: 1.55,
  },
  categorizedDependenciesSection: {
    marginTop: 18,
  },
  categorizedDependenciesSectionTitle: {
    fontSize: 14,
    fontWeight: 700,
    color: "#92400e",
    marginBottom: 12,
  },
  categorizedDependenciesGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12,
    maxHeight: 420,
    overflowY: "auto",
    paddingRight: 4,
  },
  dependencyEmptyState: {
    border: "1px dashed #cbd5e1",
    borderRadius: 14,
    padding: 20,
    textAlign: "center",
    color: "#64748b",
    background: "#f8fafc",
  },
  categorizedDependencyCard: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
    minHeight: 150,
    padding: 14,
    borderRadius: 14,
    border: "1px solid #e2e8f0",
    boxShadow: "0 4px 12px rgba(15, 23, 42, 0.04)",
  },
  categorizedDependencyHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 10,
  },
  categorizedDependencyName: {
    color: "#1e293b",
    fontSize: 13,
    fontWeight: 700,
    lineHeight: 1.4,
    wordBreak: "break-word",
  },
  categorizedDependencyVersion: {
    color: "#64748b",
    fontSize: 12,
    fontFamily: "'JetBrains Mono', monospace",
  },
  dependencyRiskBadge: {
    flexShrink: 0,
    fontSize: 10,
    letterSpacing: 0.6,
    padding: "4px 8px",
    borderRadius: 999,
    fontWeight: 800,
  },
  dependencyMetaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    alignItems: "center",
  },
  dependencyCategoryBadge: {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.72)",
    color: "#334155",
    fontSize: 11,
    fontWeight: 700,
  },
  dependencyStatusPill: {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.52)",
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: "0.04em",
  },
  dependencyReasonText: {
    fontSize: 12,
    lineHeight: 1.5,
  },
  microservicePanel: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  microserviceSectionHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    flexWrap: "wrap",
  },
  microserviceSectionHeaderContent: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  microserviceSectionSummary: {
    fontSize: 13,
    color: "#64748b",
    lineHeight: 1.5,
  },
  microserviceSectionToggle: {
    border: "1px solid #cbd5e1",
    background: "#ffffff",
    color: "#334155",
    borderRadius: 999,
    padding: "8px 14px",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  },
  microserviceHero: {
    border: "1px solid #e2e8f0",
    borderRadius: 20,
    padding: 20,
    boxShadow: "0 12px 28px rgba(15, 23, 42, 0.06)",
  },
  microserviceHeroHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    flexWrap: "wrap",
    marginBottom: 18,
  },
  microserviceHeroStatusRow: {
    display: "flex",
    alignItems: "flex-start",
    gap: 14,
    flex: 1,
    minWidth: 280,
  },
  microserviceHeroIcon: {
    width: 56,
    height: 56,
    borderRadius: 18,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: "0.12em",
    flexShrink: 0,
  },
  microserviceHeroStatusCopy: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    flex: 1,
  },
  microserviceHeroStatusLabel: {
    fontSize: 24,
    fontWeight: 800,
    lineHeight: 1.1,
  },
  microserviceHeroSummary: {
    fontSize: 14,
    color: "#334155",
    lineHeight: 1.7,
    maxWidth: 920,
  },
  microserviceHeroFooter: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-end",
    gap: 16,
    flexWrap: "wrap",
  },
  microserviceHeroProgressBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    flex: 1,
    minWidth: 260,
  },
  microserviceHeroProgressMeta: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    fontSize: 13,
    color: "#334155",
  },
  microserviceHeroProgressTrack: {
    width: "100%",
    height: 9,
    borderRadius: 999,
    background: "rgba(226, 232, 240, 0.95)",
    overflow: "hidden",
  },
  microserviceHeroProgressFill: {
    height: "100%",
    borderRadius: 999,
    transition: "width 0.35s ease",
  },
  microserviceHeroMetaRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    justifyContent: "flex-end",
  },
  microserviceHeroMetaPill: {
    display: "inline-flex",
    alignItems: "center",
    borderRadius: 999,
    padding: "8px 12px",
    background: "rgba(255,255,255,0.88)",
    border: "1px solid rgba(148, 163, 184, 0.28)",
    color: "#334155",
    fontSize: 12,
    fontWeight: 700,
  },
  microserviceHeroNote: {
    marginTop: 14,
    padding: "10px 12px",
    borderRadius: 12,
    background: "rgba(255,255,255,0.72)",
    border: "1px solid rgba(251, 191, 36, 0.35)",
    color: "#92400e",
    fontSize: 12,
    lineHeight: 1.5,
  },
  microserviceHeroDecisionShell: {
    marginTop: 16,
    paddingTop: 16,
    borderTop: "1px solid rgba(148, 163, 184, 0.22)",
    display: "grid",
    gap: 12,
  },
  microserviceHeroDecisionHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap",
  },
  microserviceHeroDecisionTitle: {
    fontSize: 14,
    fontWeight: 800,
    color: "#991b1b",
  },
  microserviceHeroDecisionToggle: {
    border: "1px solid rgba(248, 113, 113, 0.35)",
    background: "#ffffff",
    color: "#b91c1c",
    borderRadius: 999,
    padding: "6px 12px",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  },
  microserviceMetricGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 12,
  },
  microserviceMetricCard: {
    background: "#ffffff",
    border: "1px solid #e2e8f0",
    borderRadius: 16,
    padding: 16,
    boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
  },
  microserviceMetricValue: {
    fontSize: 24,
    fontWeight: 800,
    color: "#0f172a",
    marginBottom: 6,
  },
  microserviceMetricLabel: {
    fontSize: 12,
    color: "#64748b",
    fontWeight: 700,
    lineHeight: 1.5,
  },
  microservicePreviewGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12,
  },
  microservicePreviewCard: {
    border: "1px solid #e2e8f0",
    borderRadius: 18,
    padding: 16,
    boxShadow: "0 8px 22px rgba(15, 23, 42, 0.04)",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  microservicePreviewTitle: {
    fontSize: 13,
    fontWeight: 800,
    letterSpacing: "0.03em",
  },
  microservicePreviewList: {
    display: "grid",
    gap: 8,
  },
  microservicePreviewListItem: {
    fontSize: 13,
    lineHeight: 1.6,
    color: "#475569",
  },
  microservicePreviewEmpty: {
    fontSize: 12,
    lineHeight: 1.5,
    color: "#94a3b8",
    fontStyle: "italic",
  },
  microservicePreviewHint: {
    fontSize: 11,
    color: "#64748b",
    lineHeight: 1.45,
  },
  microserviceRecommendationValue: {
    fontSize: 24,
    fontWeight: 800,
    color: "#7c2d12",
    lineHeight: 1.15,
  },
  microserviceScoreHighlight: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "10px 12px",
    borderRadius: 12,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid #dbeafe",
    color: "#1e3a8a",
    fontSize: 13,
  },
  microserviceAccordionCard: {
    border: "1px solid #e2e8f0",
    borderRadius: 18,
    padding: 16,
    boxShadow: "0 10px 24px rgba(15, 23, 42, 0.04)",
  },
  microserviceAccordionToggle: {
    width: "100%",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 14,
    background: "transparent",
    border: "none",
    padding: 0,
    cursor: "pointer",
    textAlign: "left",
    fontFamily: "inherit",
  },
  microserviceAccordionContentBlock: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    flex: 1,
    minWidth: 220,
  },
  microserviceAccordionTitle: {
    fontSize: 17,
    fontWeight: 800,
    lineHeight: 1.2,
  },
  microserviceAccordionSubtitle: {
    fontSize: 13,
    lineHeight: 1.6,
  },
  microserviceAccordionMeta: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 10,
    flexWrap: "wrap",
  },
  microserviceAccordionMetaPill: {
    display: "inline-flex",
    alignItems: "center",
    borderStyle: "solid",
    borderWidth: 1,
    borderRadius: 999,
    padding: "7px 10px",
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: "0.03em",
  },
  microserviceAccordionChevron: {
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
  },
  microserviceAccordionBody: {
    marginTop: 16,
  },
  microserviceAccordionSectionGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
    gap: 12,
  },
  microserviceInsightCard: {
    border: "1px solid #e2e8f0",
    borderRadius: 16,
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 8,
    minHeight: 100,
  },
  microserviceInsightTitle: {
    fontSize: 14,
    fontWeight: 800,
    color: "#1e293b",
  },
  microserviceInsightText: {
    fontSize: 13,
    color: "#334155",
    lineHeight: 1.7,
  },
  microserviceEvidenceSubtitle: {
    fontSize: 12,
    color: "#64748b",
    lineHeight: 1.55,
  },
  microserviceBulletItem: {
    fontSize: 13,
    color: "#334155",
    lineHeight: 1.6,
  },
  microserviceEvidenceFooter: {
    marginTop: 8,
    display: "flex",
    justifyContent: "flex-start",
  },
  microserviceEvidenceToggle: {
    border: "1px solid #cbd5e1",
    background: "#ffffff",
    color: "#1d4ed8",
    borderRadius: 999,
    padding: "6px 12px",
    fontSize: 12,
    fontWeight: 700,
    cursor: "pointer",
  },
  microserviceScoreBreakdownList: {
    display: "grid",
    gap: 12,
  },
  microserviceScoreCard: {
    background: "#ffffff",
    border: "1px solid #dbeafe",
    borderRadius: 16,
    padding: 16,
    boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
  },
  microserviceScoreHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 12,
    marginBottom: 10,
  },
  microserviceScoreName: {
    fontSize: 14,
    fontWeight: 700,
    color: "#1e293b",
  },
  microserviceScoreTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  microserviceScoreInfoButton: {
    width: 20,
    height: 20,
    borderRadius: "50%",
    border: "1px solid #93c5fd",
    background: "#eff6ff",
    color: "#1d4ed8",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 800,
    cursor: "pointer",
    padding: 0,
    lineHeight: 1,
  },
  microserviceScoreWeight: {
    fontSize: 11,
    color: "#64748b",
    marginTop: 2,
  },
  microserviceScoreValue: {
    fontSize: 16,
    fontWeight: 800,
    color: "#0f172a",
  },
  microserviceScoreTrack: {
    width: "100%",
    height: 8,
    borderRadius: 999,
    background: "#e2e8f0",
    overflow: "hidden",
    marginBottom: 8,
  },
  microserviceScoreFill: {
    height: "100%",
    borderRadius: 999,
  },
  microserviceScoreText: {
    fontSize: 12,
    color: "#475569",
    lineHeight: 1.6,
  },
  microserviceScoreEvidenceBox: {
    marginTop: 12,
    padding: "12px 14px",
    borderRadius: 14,
    background: "#f8fafc",
    border: "1px solid #e2e8f0",
    display: "grid",
    gap: 6,
  },
  microserviceScoreEvidenceTitle: {
    fontSize: 12,
    fontWeight: 800,
    color: "#334155",
  },
  microserviceScoreEvidenceItem: {
    fontSize: 12,
    color: "#475569",
    lineHeight: 1.6,
  },
  microserviceScoreTooltip: {
    marginBottom: 10,
    padding: "12px 14px",
    borderRadius: 14,
    background: "#eff6ff",
    border: "1px solid #bfdbfe",
    display: "grid",
    gap: 6,
  },
  microserviceScoreTooltipTitle: {
    fontSize: 12,
    fontWeight: 800,
    color: "#1e3a8a",
    lineHeight: 1.5,
  },
  microserviceScoreTooltipText: {
    fontSize: 12,
    color: "#334155",
    lineHeight: 1.6,
  },
  microserviceServiceGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12,
  },
  microserviceServiceCard: {
    background: "#ffffff",
    border: "1px solid #dbeafe",
    borderRadius: 16,
    padding: 16,
    boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  microserviceServiceHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 10,
  },
  microserviceServiceTitle: {
    fontSize: 15,
    fontWeight: 800,
    color: "#1d4ed8",
    lineHeight: 1.3,
  },
  microserviceTransactionalBadge: {
    flexShrink: 0,
    fontSize: 10,
    fontWeight: 800,
    color: "#92400e",
    background: "#fef3c7",
    border: "1px solid #fcd34d",
    borderRadius: 999,
    padding: "4px 8px",
  },
  microserviceServicePackages: {
    fontSize: 12,
    color: "#475569",
    lineHeight: 1.55,
  },
  microserviceServiceEvidence: {
    display: "grid",
    gap: 6,
  },
  microserviceServiceSignalsLabel: {
    fontSize: 11,
    fontWeight: 800,
    color: "#64748b",
    letterSpacing: "0.03em",
    textTransform: "uppercase",
  },
  microserviceTagRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 6,
  },
  microserviceTagButton: {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    background: "#ccfbf1",
    border: "1px solid #99f6e4",
    color: "#0f766e",
    fontSize: 10,
    fontWeight: 700,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  microserviceTag: {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    background: "#ccfbf1",
    border: "1px solid #99f6e4",
    color: "#0f766e",
    fontSize: 10,
    fontWeight: 700,
  },
  microserviceTagMutedButton: {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    background: "#f1f5f9",
    border: "1px solid #cbd5e1",
    color: "#475569",
    fontSize: 10,
    fontWeight: 700,
    cursor: "pointer",
    fontFamily: "inherit",
  },
  microserviceTagMuted: {
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    background: "#f1f5f9",
    border: "1px solid #cbd5e1",
    color: "#475569",
    fontSize: 10,
    fontWeight: 700,
  },
  microserviceServiceTagTooltip: {
    marginTop: 10,
    padding: "12px 14px",
    borderRadius: 14,
    background: "#f8fafc",
    border: "1px solid #dbeafe",
    display: "grid",
    gap: 6,
  },
  microserviceServiceTagTooltipTitle: {
    fontSize: 12,
    fontWeight: 800,
    color: "#1e3a8a",
    lineHeight: 1.5,
  },
  microserviceServiceTagTooltipText: {
    fontSize: 12,
    color: "#334155",
    lineHeight: 1.6,
  },
  microserviceDecisionGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
    gap: 12,
  },
  microserviceDecisionCard: {
    border: "1px solid #e2e8f0",
    borderRadius: 16,
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 10,
    boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
  },
  microserviceDecisionHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 10,
  },
  microserviceDecisionTitle: {
    fontSize: 15,
    fontWeight: 800,
    color: "#1e293b",
    lineHeight: 1.35,
  },
  microserviceDecisionBadge: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    padding: "4px 8px",
    borderRadius: 999,
    background: "#ffffff",
    border: "1px solid #cbd5e1",
    color: "#0f172a",
    fontSize: 10,
    fontWeight: 800,
    letterSpacing: "0.03em",
  },
  microserviceDecisionLead: {
    fontSize: 13,
    color: "#475569",
    lineHeight: 1.65,
  },
  microserviceDecisionList: {
    display: "grid",
    gap: 6,
  },
  microserviceDecisionItem: {
    fontSize: 13,
    color: "#166534",
    lineHeight: 1.6,
  },
  microserviceDetailedGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12,
  },
  microserviceDetailedCard: {
    background: "#ffffff",
    border: "1px solid #e2e8f0",
    borderRadius: 16,
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 8,
    boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)",
  },
  microserviceDetailedTitle: {
    fontSize: 13,
    fontWeight: 800,
    color: "#1e293b",
  },
  microserviceDetailedItem: {
    fontSize: 12,
    color: "#475569",
    lineHeight: 1.6,
  },
  microserviceDetailedEmpty: {
    fontSize: 12,
    color: "#94a3b8",
    fontStyle: "italic",
  },
  microserviceEmptyState: {
    border: "1px dashed #cbd5e1",
    borderRadius: 14,
    padding: 18,
    textAlign: "center",
    background: "#ffffff",
    color: "#64748b",
    fontSize: 13,
    lineHeight: 1.6,
  },
  radioGroup: { display: "flex", flexDirection: "column", gap: 10 },
  radioLabel: { display: "flex", alignItems: "flex-start", gap: 12, padding: 16, border: "1px solid #e2e8f0", borderRadius: 10, cursor: "pointer", transition: "all 0.2s ease", backgroundColor: "#fff" },
  radio: { marginTop: 4, accentColor: "#2563eb" },
  checkbox: { width: 18, height: 18, accentColor: "#2563eb", cursor: "pointer" },
  frameworkGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14 },
  frameworkItem: { display: "flex", alignItems: "center", gap: 12, padding: 16, border: "1px solid #e2e8f0", borderRadius: 10, cursor: "pointer", background: "#fff", transition: "all 0.2s ease" },
  detectedBadge: { marginLeft: "auto", fontSize: 11, padding: "4px 10px", background: "#059669", color: "#fff", borderRadius: 12, fontWeight: 600 },
  conversionGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 },
  conversionItem: { display: "flex", alignItems: "flex-start", gap: 14, padding: 18, border: "1px solid #e2e8f0", borderRadius: 10, cursor: "pointer", position: "relative", transition: "all 0.2s ease", background: "#fff" },
  conversionIcon: { fontSize: 24 },
  checkMark: { position: "absolute", top: 10, right: 10, color: "#059669", fontWeight: 700, fontSize: 18 },
  optionsGrid: { display: "flex", flexDirection: "column", gap: 14 },
  optionItem: { display: "flex", alignItems: "flex-start", gap: 14, padding: 18, border: "1px solid #e2e8f0", borderRadius: 10, cursor: "pointer", background: "#fff", transition: "all 0.2s ease" },
  progressSection: { marginBottom: 24 },
  progressHeader: { display: "flex", justifyContent: "space-between", marginBottom: 10, fontSize: 14, fontWeight: 600, color: "#1e293b" },
  progressBar: { width: "100%", height: 10, background: "#e5e7eb", borderRadius: 6, overflow: "hidden" },
  progressFill: { height: "100%", background: "#2563eb", borderRadius: 6, transition: "width 0.4s ease" },
  statsGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 24 },
  statBox: { background: "#fff", padding: 20, borderRadius: 10, textAlign: "center", border: "1px solid #e2e8f0" },
  statValue: { fontSize: 28, fontWeight: 700, color: "#2563eb" },
  statLabel: { fontSize: 12, color: "#64748b", marginTop: 8, fontWeight: 600, textTransform: "uppercase" },
  successBox: { background: "#dcfce7", border: "1px solid #86efac", borderRadius: 12, padding: 28, textAlign: "center", marginBottom: 24 },
  successTitle: { fontSize: 20, fontWeight: 700, color: "#166534", marginBottom: 12 },
  repoLink: { display: "inline-block", color: "#2563eb", fontWeight: 600, textDecoration: "none", fontSize: 14, padding: "10px 20px", background: "#eff6ff", borderRadius: 8 },
  connectionModes: { display: "flex", gap: 14, marginBottom: 20 },
  modeButton: { flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 8, padding: 20, border: "1px solid #e2e8f0", borderRadius: 10, background: "#fff", cursor: "pointer", transition: "all 0.2s ease", fontWeight: 500 },
  modeButtonActive: { border: "1px solid #2563eb", background: "#eff6ff" },
  modeIcon: { fontSize: 28 },
  modeTitle: { fontWeight: 600, fontSize: 14 },
  modeDesc: { fontSize: 12, color: "#64748b", textAlign: "center", lineHeight: 1.4 },
  fileList: { display: "flex", flexDirection: "column", gap: 8, maxHeight: 380, overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: 10, padding: 14, background: "#f8fafc" },
  breadcrumb: { display: "flex", alignItems: "center", gap: 12, marginBottom: 14, padding: "10px 14px", background: "#eff6ff", borderRadius: 8, border: "1px solid #bfdbfe" },
  backBtn: { background: "none", border: "none", color: "#2563eb", cursor: "pointer", fontSize: 14, fontWeight: 600 },
  fileItem: { display: "flex", alignItems: "center", gap: 12, padding: "14px 16px", border: "1px solid #e2e8f0", borderRadius: 8, cursor: "pointer", transition: "all 0.2s ease", backgroundColor: "#fff" },
  fileIcon: { fontSize: 20 },
  fileInfo: { flex: 1 },
  fileName: { fontWeight: 600, fontSize: 14, color: "#1e293b" },
  filePath: { fontSize: 12, color: "#64748b", marginTop: 2 },
  fileSize: { fontSize: 11, color: "#94a3b8", fontWeight: 500, padding: "3px 8px", backgroundColor: "#f1f5f9", borderRadius: 6 },
  discoveryContent: { display: "flex", flexDirection: "column", gap: 14 },
  discoveryItem: { display: "flex", alignItems: "center", gap: 14, padding: 18, background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0" },
  discoveryIcon: { fontSize: 26 },
  discoveryTitle: { fontSize: 15, fontWeight: 600, color: "#1e293b", marginBottom: 2 },
  discoveryDesc: { fontSize: 13, color: "#64748b" },
  documentCard: { background: "#ffffff", border: "1px solid #dbe5f3", borderRadius: 14, padding: 20, marginBottom: 24, boxShadow: "0 8px 24px rgba(15, 23, 42, 0.04)" },
  documentCardHeader: { display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 },
  documentCardTitleRow: { display: "flex", alignItems: "center", gap: 10 },
  documentCardIcon: { fontSize: 16, lineHeight: 1 },
  documentCardTitle: { fontSize: 17, fontWeight: 700, color: "#1e293b" },
  documentCardSubtitle: { fontSize: 14, color: "#64748b", lineHeight: 1.6, maxWidth: 880 },
  documentActionRow: { display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 },
  documentHelperText: { fontSize: 12, color: "#94a3b8", lineHeight: 1.5 },
  detectedConfigCard: { background: "linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%)", border: "1px solid #bfdbfe", borderRadius: 12, padding: 20, marginTop: 18, marginBottom: 20 },
  detectedConfigHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 14 },
  detectedConfigTitle: { fontSize: 16, fontWeight: 700, color: "#1e3a8a", marginBottom: 4 },
  detectedConfigSubtitle: { fontSize: 13, color: "#475569", lineHeight: 1.5 },
  detectedConfigActions: { display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12 },
  detectedConfigChip: { padding: "10px 14px", borderRadius: 999, border: "1px solid #93c5fd", background: "#fff", color: "#1e3a8a", fontSize: 13, fontWeight: 600, cursor: "default" },
  detectedConfigActionBtn: { padding: "10px 16px", borderRadius: 999, border: "1px solid #2563eb", background: "#2563eb", color: "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer", transition: "all 0.2s ease" },
  detectedConfigActionBtnActive: { background: "#1d4ed8", borderColor: "#1d4ed8", boxShadow: "0 0 0 3px rgba(37, 99, 235, 0.15)" },
  detectedConfigNote: { fontSize: 12, color: "#475569", lineHeight: 1.5 },
  reportContainer: { display: "flex", flexDirection: "column", gap: 22 },
  reportHeroShell: {
    borderRadius: 28,
    padding: 28,
    background: "linear-gradient(180deg, #ffffff 0%, #fcfdff 58%, #f8fbff 100%)",
    border: "1px solid #dbeafe",
    boxShadow: "0 24px 52px rgba(37, 99, 235, 0.10)",
  },
  reportHeroHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20, flexWrap: "wrap", marginBottom: 22 },
  reportHeroContent: { display: "flex", flexDirection: "column", gap: 12, flex: 1, minWidth: 280 },
  reportHeroBadgeRow: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  reportHeroEyebrow: { fontSize: 11, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "#2563eb" },
  reportHeroFeatureBadge: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 999,
    padding: "7px 12px",
    background: "linear-gradient(180deg, #faf5ff 0%, #f3e8ff 100%)",
    border: "1px solid #e9d5ff",
    color: "#7c3aed",
    fontSize: 11,
    fontWeight: 800,
    letterSpacing: "0.02em",
    boxShadow: "0 10px 22px rgba(124, 58, 237, 0.10)",
  },
  reportHeroTitleRow: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" },
  reportHeroTitle: { margin: 0, fontSize: 30, lineHeight: 1.08, fontWeight: 800, color: "#0f172a" },
  reportHeroSubtitle: { margin: 0, fontSize: 14, lineHeight: 1.7, color: "#475569", maxWidth: 720 },
  reportHeroStatusPill: { display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: 999, borderWidth: 1, borderStyle: "solid", padding: "8px 13px", fontSize: 12, fontWeight: 800, whiteSpace: "nowrap", boxShadow: "0 10px 22px rgba(15, 23, 42, 0.05)" },
  reportHeroAside: { display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 12, minWidth: 240, flexShrink: 0 },
  reportHeroElapsed: { display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 999, background: "#ffffff", border: "1px solid #e2e8f0", color: "#0f172a", fontSize: 13, fontWeight: 800, boxShadow: "0 8px 18px rgba(15, 23, 42, 0.04)" },
  reportHeroElapsedLabel: { fontSize: 11, color: "#64748b", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", marginRight: 8 },
  reportHeroElapsedValue: { display: "inline-flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 800, color: "#0f172a" },
  reportHeroMiniMeta: { display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "flex-end" },
  reportHeroMetaPill: { display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: 999, padding: "9px 13px", background: "#ffffff", border: "1px solid #dbeafe", color: "#334155", fontSize: 12, fontWeight: 700, boxShadow: "0 10px 22px rgba(15, 23, 42, 0.05)" },
  reportHeroStatsGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 16 },
  reportHeroStatCard: { background: "rgba(255,255,255,0.92)", border: "1px solid #e2e8f0", borderRadius: 22, padding: "22px 20px 20px", minHeight: 144, display: "flex", flexDirection: "column", justifyContent: "center", boxShadow: "0 16px 30px rgba(15, 23, 42, 0.05)" },
  reportHeroStatValue: { fontSize: 40, lineHeight: 1, fontWeight: 800, marginBottom: 12 },
  reportHeroStatLabel: { fontSize: 11, color: "#64748b", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.10em" },
  reportHeroStatMeta: { fontSize: 12, color: "#64748b", marginTop: 10, lineHeight: 1.5, fontWeight: 600 },
  reportSection: { background: "linear-gradient(180deg, #ffffff 0%, #fbfdff 100%)", borderRadius: 20, padding: 24, border: "1px solid #e2e8f0", boxShadow: "0 16px 36px rgba(15, 23, 42, 0.05)" },
  reportAccordionToggle: {
    width: "100%",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    background: "transparent",
    border: "none",
    padding: 0,
    marginBottom: 18,
    textAlign: "left",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  reportAccordionIcon: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 36,
    height: 36,
    borderRadius: 12,
    background: "#eff6ff",
    color: "#1d4ed8",
    fontSize: 18,
    fontWeight: 800,
    flexShrink: 0,
  },
  reportAccordionSubtitle: { fontSize: 13, color: "#64748b", lineHeight: 1.6 },
  reportTitle: { fontSize: 18, fontWeight: 800, color: "#0f172a", marginBottom: 18, paddingBottom: 14, borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 10 },
  reportGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 },
  reportItem: { display: "flex", flexDirection: "column", gap: 8, padding: 16, borderRadius: 16, background: "rgba(255,255,255,0.9)", border: "1px solid #e2e8f0" },
  reportLabel: { fontSize: 11, color: "#64748b", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" },
  reportValue: { fontSize: 14, color: "#0f172a", fontWeight: 700, lineHeight: 1.6, wordBreak: "break-word" },
  testResults: { display: "flex", flexDirection: "column", gap: 10 },
  testItem: { display: "flex", justifyContent: "space-between", padding: "14px 18px", background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0" },
  sonarqubeResults: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 },
  qualityItem: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 18px", background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0" },
  logsContainer: { background: "linear-gradient(180deg, #1e293b 0%, #172033 100%)", color: "#86efac", fontFamily: "'JetBrains Mono', 'Fira Code', monospace", padding: 20, borderRadius: 16, maxHeight: 340, overflowY: "auto", fontSize: 12, lineHeight: 1.75, border: "1px solid #334155", boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)" },
  logEntry: { marginBottom: 8, padding: "6px 0", borderBottom: "1px solid rgba(148,163,184,0.14)" },
  issuesContainer: { display: "flex", flexDirection: "column", gap: 14 },
  issueItem: { padding: 18, background: "linear-gradient(180deg, #ffffff 0%, #fafcff 100%)", borderRadius: 16, border: "1px solid #dbe5f3", boxShadow: "0 10px 24px rgba(15, 23, 42, 0.04)" },
  issueHeader: { display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" },
  issueSeverity: { padding: "6px 12px", borderRadius: 999, fontSize: 10, fontWeight: 800, color: "#fff", textTransform: "uppercase", letterSpacing: "0.08em" },
  issueCategory: { fontSize: 11, color: "#64748b", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.08em" },
  issueStatus: { fontSize: 11, color: "#059669", fontWeight: 800, marginLeft: "auto", textTransform: "uppercase", letterSpacing: "0.08em" },
  issueMessage: { fontSize: 14, color: "#0f172a", marginBottom: 10, fontWeight: 600, lineHeight: 1.55 },
  issueFile: { fontSize: 12, color: "#2563eb", fontFamily: "'JetBrains Mono', monospace", backgroundColor: "#eff6ff", padding: "8px 12px", borderRadius: 10, display: "inline-block", border: "1px solid #dbeafe" },
  noIssues: { textAlign: "center", color: "#64748b", padding: 28, fontStyle: "italic", fontSize: 14 },
  noFilesMsg: { textAlign: "center", color: "#64748b", padding: 28, fontStyle: "italic", background: "#f8fafc", borderRadius: 10, border: "1px dashed #e2e8f0" },
  noLogs: { textAlign: "center", color: "#64748b", padding: 28, fontStyle: "italic" },

  // Animation styles
  animationContainer: {
    padding: 28,
    background: "linear-gradient(180deg, #fbfdff 0%, #f6f9ff 55%, #f8fafc 100%)",
    borderRadius: 28,
    marginTop: 20,
    border: "1px solid #dbe5f3",
    boxShadow: "0 24px 60px rgba(37, 99, 235, 0.06)",
  },
  migrationAnimation: { maxWidth: 760, margin: "0 auto" },
  animationHeader: { textAlign: "center", marginBottom: 34 },
  migratingText: { fontSize: 34, fontWeight: 800, color: "#0f172a", marginBottom: 14, letterSpacing: "-0.03em", lineHeight: 1.08 },
  versionTransition: {
    fontSize: 14,
    color: "#eff6ff",
    padding: "12px 20px",
    background: "linear-gradient(135deg, #2563eb 0%, #4f46e5 55%, #7c3aed 100%)",
    borderRadius: 999,
    display: "inline-block",
    fontWeight: 700,
    boxShadow: "0 16px 34px rgba(79, 70, 229, 0.18)",
  },
  animationSteps: { display: "flex", flexDirection: "column", gap: 16, marginBottom: 30 },
  animationStep: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    padding: "18px 20px",
    background: "rgba(255,255,255,0.86)",
    borderRadius: 18,
    border: "1px solid rgba(219, 229, 243, 0.95)",
    boxShadow: "0 12px 28px rgba(15, 23, 42, 0.04)",
    backdropFilter: "blur(8px)",
  },
  stepIconAnimated: { fontSize: 22, minWidth: 22 },
  stepText: { flex: 1, fontSize: 14, fontWeight: 600, color: "#1e293b" },
  checkMarkAnimated: { fontSize: 18, color: "#059669" },
  progressExperienceSection: {
    marginTop: 6,
    display: "flex",
    flexDirection: "column",
    gap: 22,
    padding: "8px 0 4px",
  },
  animatedProgressSection: {
    marginBottom: 0,
    padding: 0,
    borderRadius: 0,
    background: "transparent",
    border: "none",
  },
  animatedProgressHeader: { display: "flex", justifyContent: "space-between", marginBottom: 12, fontSize: 13, fontWeight: 800, color: "#0f172a", textTransform: "uppercase", letterSpacing: "0.04em" },
  animatedProgressBar: { width: "100%", height: 8, background: "#dbe4f0", borderRadius: 999, overflow: "hidden", boxShadow: "inset 0 1px 2px rgba(15, 23, 42, 0.08)" },
  animatedProgressFill: { height: "100%", borderRadius: 999, transition: "width 0.4s ease", background: "#2563eb" },
  progressInsightRow: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 14,
    width: "min(100%, 560px)",
    margin: "0 auto",
  },
  statusHeroBlock: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 0,
    minHeight: 0,
    maxWidth: "100%",
    textAlign: "center",
  },
  currentStatusHeadline: {
    fontSize: 22,
    fontWeight: 800,
    color: "#0f172a",
    lineHeight: 1.25,
  },
  recentLog: {
    fontSize: 13,
    color: "#64748b",
    fontFamily: "'JetBrains Mono', monospace",
    background: "rgba(255,255,255,0.78)",
    padding: "12px 16px",
    borderRadius: 14,
    border: "1px solid #dbe5f3",
    boxShadow: "0 10px 22px rgba(15, 23, 42, 0.04)",
  },

  // Report styles
  changesGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 },
  changeItem: { display: "flex", alignItems: "center", gap: 16, padding: 20, background: "linear-gradient(180deg, #ffffff 0%, #f8fbff 100%)", borderRadius: 18, border: "1px solid #dbeafe", boxShadow: "0 14px 28px rgba(37, 99, 235, 0.06)" },
  changeIcon: { fontSize: 28, width: 48, height: 48, borderRadius: 14, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "#eff6ff" },
  changeTitle: { fontSize: 15, fontWeight: 700, color: "#0f172a", marginBottom: 6 },
  changeValue: { fontSize: 13, color: "#475569", lineHeight: 1.6 },
  reportPagerBar: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 16, padding: "12px 14px", borderRadius: 14, background: "#f8fafc", border: "1px solid #e2e8f0" },
  reportPagerHint: { fontSize: 13, color: "#475569", fontWeight: 600 },
  reportPagerActions: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  reportPagerPage: { fontSize: 12, color: "#64748b", fontWeight: 700, minWidth: 90, textAlign: "center" },
  dependenciesReport: { display: "flex", flexDirection: "column", gap: 10 },
  dependencyReportItem: { display: "grid", gridTemplateColumns: "1fr 220px 150px", gap: 16, alignItems: "center", padding: "16px 18px", background: "rgba(255,255,255,0.92)", borderRadius: 16, border: "1px solid #e2e8f0", boxShadow: "0 8px 18px rgba(15, 23, 42, 0.03)" },
  dependencyName: { fontSize: 14, fontWeight: 700, color: "#0f172a", fontFamily: "'JetBrains Mono', monospace", wordBreak: "break-word", lineHeight: 1.55 },
  dependencyChange: { fontSize: 13, color: "#64748b", textAlign: "center", fontWeight: 600 },
  dependencyStatus: { padding: "7px 12px", borderRadius: 999, fontSize: 10, fontWeight: 800, textTransform: "uppercase", textAlign: "center", letterSpacing: "0.08em" },
  noData: { textAlign: "center", color: "#64748b", padding: 28, fontStyle: "italic" },
  errorsSummary: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14 },
  errorStat: { textAlign: "center", padding: 18, background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0" },
  errorCount: { display: "block", fontSize: 26, fontWeight: 700, color: "#1e293b", marginBottom: 6 },
  errorLabel: { fontSize: 12, color: "#64748b", fontWeight: 600, textTransform: "uppercase" },
  businessLogicGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 },
  businessItem: { display: "flex", alignItems: "flex-start", gap: 14, padding: 20, background: "linear-gradient(180deg, #ffffff 0%, #fffaf5 100%)", borderRadius: 18, border: "1px solid #fde7cf", boxShadow: "0 14px 28px rgba(249, 115, 22, 0.05)" },
  businessIcon: { fontSize: 24, marginTop: 2, width: 40, height: 40, borderRadius: 12, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "#fff7ed" },
  businessTitle: { fontSize: 15, fontWeight: 700, color: "#0f172a", marginBottom: 6 },
  businessDesc: { fontSize: 13, color: "#475569", lineHeight: 1.6 },
  sonarSectionShell: { background: "linear-gradient(180deg, #ffffff 0%, #fbfdff 100%)", borderRadius: 18, boxShadow: "0 12px 40px rgba(15, 23, 42, 0.05)" },
  sonarSectionHeader: { display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 14 },
  sonarSectionSubtitle: { fontSize: 13, color: "#64748b", lineHeight: 1.6, marginTop: -4 },
  sonarActionRow: { display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 18 },
  sonarHeroPanel: { border: "1px solid #e0ecff", background: "linear-gradient(135deg, #f8fbff 0%, #ffffff 58%)", borderRadius: 18, padding: 18, marginBottom: 18 },
  sonarHeroHeader: { display: "flex", justifyContent: "space-between", alignItems: "stretch", gap: 18, flexWrap: "wrap" },
  sonarHeroEyebrow: { fontSize: 11, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: "#2563eb", marginBottom: 8 },
  sonarHeroTitle: { fontSize: 24, fontWeight: 800, color: "#0f172a", lineHeight: 1.3, marginBottom: 10 },
  sonarHeroSubtitle: { fontSize: 13, color: "#475569", lineHeight: 1.7, maxWidth: 720 },
  sonarHeroMetaGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14, minWidth: "min(100%, 360px)", flex: "0 0 360px" },
  sonarHeroMiniCard: { background: "#fff", border: "1px solid #dbeafe", borderRadius: 16, padding: 16, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, boxShadow: "0 12px 28px rgba(37, 99, 235, 0.08)" },
  sonarHeroMiniLabel: { fontSize: 11, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase", color: "#64748b" },
  sonarqubeGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 20, marginBottom: 20 },
  sonarqubeItem: { textAlign: "center" },
  qualityGate: { marginBottom: 18 },
  gateStatus: { display: "inline-block", padding: "12px 24px", borderRadius: 20, color: "#fff", fontSize: 14, fontWeight: 700, textTransform: "uppercase" },
  gateLabel: { display: "block", fontSize: 12, color: "#64748b", marginTop: 10, fontWeight: 600 },
  coverageMeter: { position: "relative" },
  coverageCircle: { width: 110, height: 110, borderRadius: "50%", background: "#eff6ff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", margin: "0 auto", border: "3px solid #2563eb" },
  coveragePercent: { fontSize: 26, fontWeight: 700, color: "#2563eb" },
  coverageLabel: { fontSize: 11, color: "#64748b", fontWeight: 600, marginTop: 2 },
  qualityMetrics: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14 },
  metricItem: { textAlign: "center", padding: 16, background: "#fff", borderRadius: 16, borderWidth: 1, borderStyle: "solid", borderColor: "#e2e8f0", cursor: "pointer", transition: "all 0.2s ease", minHeight: 126, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6, width: "100%", appearance: "none", fontFamily: "inherit" },
  metricItemActive: { boxShadow: "0 0 0 2px rgba(37, 99, 235, 0.18)", borderColor: "#93c5fd", background: "#eff6ff" },
  metricValue: { display: "block", fontSize: 22, fontWeight: 700, marginBottom: 6, color: "#1e293b" },
  metricLabel: { fontSize: 11, color: "#64748b", fontWeight: 600, textTransform: "uppercase" },
  metricHelper: { fontSize: 12, color: "#64748b", lineHeight: 1.5 },
  sonarRiskSummaryGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, marginBottom: 18 },
  sonarRiskSummaryCard: { borderWidth: 1.5, borderStyle: "solid", borderRadius: 16, padding: "16px 18px", minHeight: 108, display: "flex", flexDirection: "column", justifyContent: "center", boxShadow: "0 10px 26px rgba(15, 23, 42, 0.04)" },
  sonarRiskSummaryLabel: { fontSize: 11, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase", color: "#64748b", marginBottom: 10 },
  sonarRiskSummaryValue: { fontSize: 30, fontWeight: 800, lineHeight: 1.1, color: "#0f172a" },
  sonarRecommendationPanel: { border: "1px solid #bfdbfe", background: "#eff6ff", borderRadius: 16, padding: "16px 18px", marginBottom: 18 },
  sonarRecommendationTitle: { fontSize: 14, fontWeight: 800, color: "#1d4ed8", marginBottom: 10 },
  sonarRecommendationList: { display: "flex", flexDirection: "column", gap: 8 },
  sonarRecommendationItem: { fontSize: 13, color: "#1e3a8a", lineHeight: 1.6 },
  sonarCategoryHeader: { marginBottom: 14 },
  sonarFindingsPanel: { marginTop: 6, display: "flex", flexDirection: "column", gap: 16, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 18, padding: 18 },
  sonarFindingsPanelIntro: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 14, flexWrap: "wrap", padding: "4px 2px 2px" },
  sonarFindingsPanelEyebrow: { fontSize: 11, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: "#2563eb", marginBottom: 6 },
  sonarFindingsPanelSummaryBadge: { display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "10px 14px", borderRadius: 999, background: "linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)", color: "#1d4ed8", fontSize: 12, fontWeight: 800, border: "1px solid #bfdbfe", whiteSpace: "nowrap" },
  sonarFindingsPanelHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" },
  sonarFindingsPanelTitle: { fontSize: 16, fontWeight: 700, color: "#1e293b", marginBottom: 4 },
  sonarFindingsPanelSubtitle: { fontSize: 13, color: "#64748b", lineHeight: 1.5 },
  sonarFilterBar: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "10px 14px", borderRadius: 14, background: "#f8fafc", border: "1px solid #e2e8f0" },
  sonarFilterLabel: { fontSize: 13, color: "#334155", fontWeight: 700 },
  sonarFilterClearButton: { border: "1px solid #cbd5e1", background: "#fff", color: "#334155", borderRadius: 999, padding: "7px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer", boxShadow: "0 4px 14px rgba(15, 23, 42, 0.06)" },
  sonarSeverityFilterRow: { display: "flex", flexWrap: "wrap", gap: 10, paddingTop: 2 },
  sonarSeverityFilterButton: { borderWidth: 1, borderStyle: "solid", borderColor: "#dbe5f3", background: "#fff", color: "#334155", borderRadius: 999, padding: "7px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer" },
  sonarSeverityFilterButtonActive: { background: "#eff6ff", color: "#1d4ed8", borderColor: "#93c5fd" },
  sonarCategoryCardGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 },
  sonarCategoryCard: { width: "100%", appearance: "none", fontFamily: "inherit", textAlign: "left", borderWidth: 1, borderStyle: "solid", borderRadius: 18, padding: 18, minHeight: 150, cursor: "pointer", transition: "all 0.2s ease", display: "flex", flexDirection: "column", justifyContent: "space-between" },
  sonarCategoryCardTopRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 },
  sonarCategoryIconBadge: { width: 40, height: 40, borderRadius: 12, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 20, fontWeight: 800, borderWidth: 1, borderStyle: "solid" },
  sonarCategoryStatusBadge: { display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: 999, padding: "6px 10px", fontSize: 10, fontWeight: 800, letterSpacing: "0.08em" },
  sonarCategoryCardValue: { fontSize: 40, lineHeight: 1, fontWeight: 800, marginTop: 18 },
  sonarCategoryCardLabel: { fontSize: 12, fontWeight: 800, color: "#475569", letterSpacing: "0.08em", textTransform: "uppercase", marginTop: 8 },
  sonarCategoryCardNote: { fontSize: 13, color: "#64748b", lineHeight: 1.5, marginTop: 8 },
  sonarFindingSection: { background: "#fff", borderWidth: 1, borderStyle: "solid", borderColor: "#e2e8f0", borderRadius: 16, padding: 16, boxShadow: "0 10px 24px rgba(15, 23, 42, 0.04)" },
  sonarFindingSectionHeader: { marginBottom: 12 },
  sonarFindingSectionTitleRow: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" },
  sonarFindingSectionTitle: { margin: 0, fontSize: 15, fontWeight: 700, color: "#1e293b" },
  sonarFindingSectionDescription: { fontSize: 12, color: "#64748b", lineHeight: 1.6, marginTop: 6 },
  sonarFindingCountBadge: { display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 40, padding: "6px 10px", borderRadius: 999, borderWidth: 1, borderStyle: "solid", fontSize: 12, fontWeight: 800 },
  sonarFindingsList: { display: "flex", flexDirection: "column", gap: 12, maxHeight: 540, overflowY: "auto", paddingRight: 4 },
  sonarFindingCard: { borderWidth: 1, borderStyle: "solid", borderColor: "#e2e8f0", borderRadius: 14, padding: 14, background: "rgba(255,255,255,0.92)" },
  sonarFindingHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 10, flexWrap: "wrap" },
  sonarFindingTitle: { fontSize: 14, fontWeight: 700, color: "#1e293b", lineHeight: 1.5, flex: 1, minWidth: 240 },
  sonarFindingBadgeRow: { display: "flex", gap: 8, flexWrap: "wrap" },
  sonarFindingBadge: { display: "inline-flex", alignItems: "center", borderRadius: 999, padding: "5px 9px", fontSize: 11, fontWeight: 800 },
  sonarFindingMeta: { display: "flex", flexWrap: "wrap", gap: 8, fontSize: 12, color: "#475569", lineHeight: 1.5 },
  sonarFindingMetaPill: { display: "inline-flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 999, background: "#eff6ff", color: "#1d4ed8", fontWeight: 700 },
  sonarFindingLoadMoreRow: { display: "flex", justifyContent: "center", paddingTop: 12 },
  sonarFindingLoadMoreButton: { border: "1px solid #cbd5e1", background: "#fff", color: "#1d4ed8", borderRadius: 999, padding: "8px 14px", fontSize: 12, fontWeight: 700, cursor: "pointer" },
  sonarFindingNote: { fontSize: 12, color: "#64748b", paddingTop: 4 },
  sonarFindingEmpty: { border: "1px dashed #cbd5e1", borderRadius: 12, padding: 16, textAlign: "center", fontSize: 13, color: "#64748b", background: "#f8fafc" },
  testStatus: { display: "flex", alignItems: "center", gap: 12, padding: 16, background: "#dcfce7", borderRadius: 16, border: "1px solid #86efac", boxShadow: "0 10px 24px rgba(34, 197, 94, 0.08)" },
  testStatusIcon: { fontSize: 18 },
  testSummaryReport: { borderRadius: 18, overflow: "hidden", border: "1px solid #e2e8f0", background: "#fff", marginBottom: 18, boxShadow: "0 10px 24px rgba(15, 23, 42, 0.05)" },
  testSummaryReportHeader: { background: "linear-gradient(135deg, #6d5efc 0%, #7c3aed 100%)", padding: "16px 18px", color: "#fff", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" },
  testSummaryReportTitle: { fontSize: 12, fontWeight: 800, letterSpacing: "0.16em", textTransform: "uppercase" },
  testSummaryReportSubtitle: { marginTop: 6, fontSize: 12, opacity: 0.9, fontWeight: 600 },
  testSummaryReportGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, padding: 16, background: "#f8fafc" },
  testSummaryReportCard: { background: "#fff", border: "1px solid #e2e8f0", borderRadius: 14, padding: 14, textAlign: "center" },
  testSummaryReportValue: { fontSize: 22, fontWeight: 900, color: "#0f172a", lineHeight: 1.1 },
  testSummaryReportLabel: { marginTop: 8, fontSize: 11, fontWeight: 800, letterSpacing: "0.08em", textTransform: "uppercase", color: "#64748b" },
  jmeterGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 },
  jmeterItem: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 20px", background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)", borderRadius: 16, border: "1px solid #e2e8f0", boxShadow: "0 10px 22px rgba(15, 23, 42, 0.04)" },
  jmeterLabel: { fontSize: 13, color: "#64748b", fontWeight: 600 },
  jmeterValue: { fontSize: 18, fontWeight: 800, color: "#0f172a" },
};
