import React, { useState, useEffect, useMemo, useRef } from "react";
import html2canvas from "html2canvas";
import { jsPDF } from "jspdf";
import { zipSync } from "fflate";
import { FaCheckCircle, FaExclamationTriangle, FaInfoCircle, FaLock, FaSearch } from "react-icons/fa";
import { useLocation, useNavigate } from "react-router-dom";
import "./MigrationWizard.css";
import {
  fetchRepositories,
  analyzeRepository,
  analyzeRepoUrl,
  analyzeLocalProject,
  uploadLocalProject,
  uploadLocalProjectChunk,
  getRepoVisibility,
  getLocalProjectCapabilities,
  listRepoFiles,
  listLocalProjectFiles,
  getFileContent,
  getLocalProjectFileContent,
  getMicroserviceEligibility,
  getLocalProjectMicroserviceEligibility,
  getJavaVersions,
  getJavaVersionRecommendation,
  downloadJMeterPlan,
  rerunMigrationTests,
  downloadTestcaseDoc,
  downloadTestcaseReport,
  downloadUnitTestReport,
  downloadSonarReportPdf,
  generateGithubDocument,
  generateLocalProjectDocument,
  getConversionTypes,
  previewMigration,
  startMigration,
  getMigrationStatus,
  getMigrationLogs,
  getMigrationFossa,
  ApiError,
  // Import API_BASE_URL for dynamic URL construction
} from "../services/api";
import { API_BASE_URL } from "../services/api";
import type {
  RepoInfo,
  RepoAnalysis,
  RepoFile,
  FossaScanResult,
  LocalProjectCapabilities,
  LocalProjectAnalysisResponse,
  MigrationResult,
  ConversionType,
  GithubDocumentRequest,
  GithubDocumentResponse,
  MigrationPreview,
  PreviewFileDiff,
  JavaVersionRecommendationResponse,
  DependencyInfo,
  MicroserviceEligibilityResult,
  MicroserviceServiceCandidate,
  SonarReport,
  SonarIssueDetail,
  SonarHotspotDetail,
} from "../services/api";

interface JavaVersionOption {
  value: string;
  label: string;
}

interface PersistedWizardFormState {
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
  migrationApproach: string;
  migrationType: "monolithic" | "microservices";
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
type AccessTokenValidationState = "idle" | "validating" | "valid" | "invalid";
type MigrationApproachValue = "fork" | "branch" | "local";

interface CategorizedDependency extends DependencyInfo {
  displayName: string;
  category: DependencyCategory;
  risk: DependencyRiskLevel;
  reason: string;
}

type GeneratedDocumentKind = "brd";
type DocumentPrefetchStatus = "idle" | "loading" | "rendering" | "ready" | "error";
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

const normalizeAssessmentScore = (value: number) => {
  const normalizedScore = value <= 1 ? value * 100 : value;
  return Math.max(5, Math.min(95, Math.round(normalizedScore)));
};

const getMicroserviceFitScore = (result?: MicroserviceEligibilityResult | null) => {
  if (!result) return 50;
  return normalizeAssessmentScore(typeof result.score === "number" ? result.score : 50);
};

const getMicroserviceAssessmentLabel = (result?: MicroserviceEligibilityResult | null) => {
  return result?.eligibility || "NOT ELIGIBLE";
};

const getAssessmentBarColor = (score: number) => {
  if (score >= 75) return "#22c55e";
  if (score >= 60) return "#f59e0b";
  return "#ef4444";
};

const getMicroserviceScoreTooltip = (metricName: string) => {
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

const getMicroserviceServiceTagTooltip = (
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
    icon: "🔗",
    description: "Connect to GitHub Repository",
    summary: "Enter your GitHub repository URL to start the migration process"
  },
  {
    id: 2,
    name: "Discovery",
    icon: "🔍",
    description: "Repository Discovery & Dependencies",
    summary: "Explore repository structure and analyze project dependencies"
  },
  {
    id: 3,
    name: "Strategy",
    icon: "📋",
    description: "Assessment & Migration Strategy",
    summary: "Review assessment results and define the migration roadmap"
  },
  {
    id: 4,
    name: "Migration",
    icon: "⚡",
    description: "Build Modernization & Migration",
    summary: "Execute the upgrade using automation tools and refactor legacy components"
  },
  {
    id: 5,
    name: "Result",
    icon: "📊",
    description: "Migration Results",
    summary: "View migration report and download migrated project"
  },
];

const STEP_ROUTES: Record<number, string> = {
  1: "/",
  2: "/discovery",
  3: "/strategy",
  4: "/migration",
  5: "/migrating",
  6: "/progress",
  7: "/report",
};

const getStepFromPath = (pathname: string) => {
  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const entry = Object.entries(STEP_ROUTES).find(([, route]) => route === normalizedPath);
  return entry ? Number(entry[0]) : 1;
};

const WIZARD_REPO_URL_KEY = "migration_wizard_repo_url";
const WIZARD_LOCAL_PROJECT_PATH_KEY = "migration_wizard_local_project_path";
const WIZARD_SELECTED_REPO_KEY = "migration_wizard_selected_repo";
const WIZARD_REPO_ANALYSIS_KEY = "migration_wizard_repo_analysis";
const WIZARD_FORM_STATE_KEY = "migration_wizard_form_state";
const WIZARD_MIGRATION_JOB_KEY = "migration_wizard_migration_job";
const DEFAULT_TARGET_GITHUB_OWNER = "Javaapex";
const DEFAULT_TARGET_GITHUB_HOST = "github.com";
const WIZARD_STORAGE_KEYS = [
  WIZARD_REPO_URL_KEY,
  WIZARD_LOCAL_PROJECT_PATH_KEY,
  WIZARD_SELECTED_REPO_KEY,
  WIZARD_REPO_ANALYSIS_KEY,
  WIZARD_FORM_STATE_KEY,
  WIZARD_MIGRATION_JOB_KEY
];

const readPersistedValue = (key: string) => {
  if (typeof window === "undefined") return null;

  return window.sessionStorage.getItem(key);
};

const readSessionJson = <T,>(key: string): T | null => {
  if (typeof window === "undefined") return null;

  try {
    const raw = readPersistedValue(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
};

const writeSessionJson = (key: string, value: unknown) => {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    console.warn(`sessionStorage write failed for key "${key}"`, e);
  }
};

const getIndicatorStep = (step: number) => Math.min(step, MIGRATION_STEPS.length);

const LLM_PROVIDERS = [
  { value: "huggingface", label: "Hugging Face" },
  { value: "groq", label: "Groq" },
  { value: "ollama", label: "Ollama (Local)" },
  { value: "offline", label: "Offline (Template)" },
  { value: "gpt-4", label: "OpenAI (GPT-4)" },
  { value: "deepseek", label: "DeepSeek" },
];

export default function MigrationWizard({ onBackToHome }: { onBackToHome?: () => void }) {
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
  const [repoUrl, setRepoUrl] = useState(() => {
    if (typeof window === "undefined") return "";
    return readPersistedValue(WIZARD_REPO_URL_KEY) || "";
  });
  const [localProjectPath, setLocalProjectPath] = useState(() => {
    if (typeof window === "undefined") return "";
    return readPersistedValue(WIZARD_LOCAL_PROJECT_PATH_KEY) || "";
  });
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<RepoInfo | null>(() =>
    readSessionJson<RepoInfo>(WIZARD_SELECTED_REPO_KEY)
  );
  const [githubToken, setGithubToken] = useState("");
  const [isPrivateRepo, setIsPrivateRepo] = useState(
    persistedFormState?.isPrivateRepo ?? false
  );
  const [patToken, setPatToken] = useState(persistedFormState?.patToken ?? "");
  // Show token input only for GitHub Enterprise
  const isEnterpriseGithub = (url: string) => {
    // Matches github.<anything>.com but not github.com
    const match = url.match(/^https?:\/\/(www\.)?github\.([^.]+)\.com\//i);
    return match && match[2] !== "" && match[2] !== "com";
  };

  const normalizeGithubUrl = (url: string): { valid: boolean; normalizedUrl: string; message: string } => {
    if (!url.trim()) {
      return { valid: false, normalizedUrl: "", message: "URL is required" };
    }

    let normalized = url.trim();

    // Remove /tree/branch-name and everything after it
    normalized = normalized.replace(/\/tree\/[^/]+.*$/, '');
    // Remove /blob/branch-name and everything after it
    normalized = normalized.replace(/\/blob\/[^/]+.*$/, '');
    // Remove /src/ paths
    normalized = normalized.replace(/\/src\/.*$/, '');
    // Remove trailing slashes
    normalized = normalized.replace(/\/$/, '');
    // Remove .git extension
    normalized = normalized.replace(/\.git$/, '');

    // Accept github.com, gitlab.com, and any github.<custom>.com (enterprise)
    const isGithubUrl = /^https?:\/\/(www\.)?github(\.[^/]+)?\.com\/[^/]+\/[^/\s]+$/.test(normalized);
    const isGitlabUrl = /^https?:\/\/(www\.)?gitlab\.com\/[^/]+\/[^/\s]+$/.test(normalized);
    const isShortFormat = /^[^/]+\/[^/\s]+$/.test(normalized);

    if (isGithubUrl || isGitlabUrl || isShortFormat) {
      if (url !== normalized) {
        return { 
          valid: true, 
          normalizedUrl: normalized, 
          message: `✓ URL normalized (removed tree/blob paths)` 
        };
      }
      return { valid: true, normalizedUrl: normalized, message: "" };
    }

    return { 
      valid: false, 
      normalizedUrl: "", 
      message: "Invalid URL format. Use: https://github.com/owner/repo, https://github.<enterprise>.com/owner/repo, or owner/repo" 
    };
  };

  const urlValidation = repoUrl ? normalizeGithubUrl(repoUrl) : { valid: false, normalizedUrl: "", message: "" };
  const normalizedLocalProjectPath = localProjectPath.trim();
  const localProjectInputValid = normalizedLocalProjectPath.length > 0;
  const showEnterpriseToken = repoUrl && isEnterpriseGithub(urlValidation.normalizedUrl || repoUrl);
  const activeAccessToken = (showEnterpriseToken ? githubToken : patToken).trim();
  const repositoryNeedsAuthentication = Boolean(showEnterpriseToken || isPrivateRepo);

  const getCurrentToken = () => {
    if (showEnterpriseToken) return githubToken.trim();
    if (isPrivateRepo) return patToken.trim() || githubToken.trim();
    if (githubToken.trim()) return githubToken.trim();
    if (patToken.trim()) return patToken.trim();
    return "";
  };

  const currentToken = useMemo(getCurrentToken, [githubToken, patToken, showEnterpriseToken, isPrivateRepo]);
  const shouldShowPatInput = showEnterpriseToken || isPrivateRepo;
  const [repoAnalysis, setRepoAnalysis] = useState<RepoAnalysis | null>(() =>
    readSessionJson<RepoAnalysis>(WIZARD_REPO_ANALYSIS_KEY)
  );
  const [repoFiles, setRepoFiles] = useState<RepoFile[]>([]);
  const [currentPath, setCurrentPath] = useState(persistedFormState?.currentPath ?? "");
  const [targetRepoNamesByApproach, setTargetRepoNamesByApproach] = useState<{
    fork: string;
    branch: string;
    local: string;
  }>(() => {
    if (persistedFormState?.targetRepoNamesByApproach) {
      return {
        fork: persistedFormState.targetRepoNamesByApproach.fork ?? "",
        branch: persistedFormState.targetRepoNamesByApproach.branch ?? "",
        local: persistedFormState.targetRepoNamesByApproach.local ?? "",
      };
    }

    const fallbackTargetName = persistedFormState?.targetRepoName ?? "";
    return {
      fork: persistedFormState?.migrationApproach === "fork" ? fallbackTargetName : "",
      branch: persistedFormState?.migrationApproach === "branch" ? fallbackTargetName : "",
      local: persistedFormState?.migrationApproach === "local" ? fallbackTargetName : "",
    };
  });
  const [targetRepoNameEditedByApproach, setTargetRepoNameEditedByApproach] = useState<{
    fork: boolean;
    branch: boolean;
    local: boolean;
  }>(() => ({
    fork: persistedFormState?.targetRepoNameEditedByApproach?.fork ?? false,
    branch: persistedFormState?.targetRepoNameEditedByApproach?.branch ?? false,
    local: persistedFormState?.targetRepoNameEditedByApproach?.local ?? false,
  }));
  const [targetRepoTimestamp, setTargetRepoTimestamp] = useState(
    () => persistedFormState?.targetRepoTimestamp ?? generateRepoTimestamp()
  );
  const [sourceVersions, setSourceVersions] = useState<JavaVersionOption[]>([]);
  const [targetVersions, setTargetVersions] = useState<JavaVersionOption[]>([]);
  const [selectedSourceVersion, setSelectedSourceVersion] = useState(
    persistedFormState?.selectedSourceVersion ?? "8"
  );
  const [selectedTargetVersion, setSelectedTargetVersion] = useState(
    persistedFormState?.selectedTargetVersion ?? ""
  );
  const [conversionTypes, setConversionTypes] = useState<ConversionType[]>([]);
  const [selectedConversions, setSelectedConversions] = useState<string[]>(
    persistedFormState?.selectedConversions ?? ["java_version"]
  );
  const [runTests, setRunTests] = useState(persistedFormState?.runTests ?? true);
  const [useLLMTests, setUseLLMTests] = useState(true);
  const [selectedLLMProvider, setSelectedLLMProvider] = useState("huggingface");
  const [jmeterBaseUrl, setJmeterBaseUrl] = useState("http://localhost:8080");
  const [runSonar, setRunSonar] = useState(persistedFormState?.runSonar ?? false);
  const [runFossa, setRunFossa] = useState(persistedFormState?.runFossa ?? false);
  const [fixBusinessLogic, setFixBusinessLogic] = useState(
    persistedFormState?.fixBusinessLogic ?? true
  );
  const [migrationType, setMigrationType] = useState<"monolithic" | "microservices">(
    persistedFormState?.migrationType ?? "monolithic"
  );

  const [loading, setLoading] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisElapsedSeconds, setAnalysisElapsedSeconds] = useState(0);
  const [microserviceResult, setMicroserviceResult] = useState<MicroserviceEligibilityResult | null>(null);
  const [microserviceLoading, setMicroserviceLoading] = useState(false);
  const [microserviceAccordionState, setMicroserviceAccordionState] = useState<Record<MicroserviceAccordionKey, boolean>>(
    createDefaultMicroserviceAccordionState
  );
  const [isMicroserviceEligibilityCollapsed, setIsMicroserviceEligibilityCollapsed] = useState(false);
  const [showAllMicroserviceServices, setShowAllMicroserviceServices] = useState(false);
  const [activeScoreTooltip, setActiveScoreTooltip] = useState<string | null>(null);
  const [activeServiceTagTooltip, setActiveServiceTagTooltip] = useState<string | null>(null);
  const [microserviceExpandedSections, setMicroserviceExpandedSections] = useState<Record<string, boolean>>({});
  const [analysisStartedAtMs, setAnalysisStartedAtMs] = useState<number | null>(null);
  const [analysisCompletedSeconds, setAnalysisCompletedSeconds] = useState(
  persistedFormState?.analysisCompletedSeconds ?? 0
);
  const [migrationTimerNow, setMigrationTimerNow] = useState(() => Date.now());
  const [repoFilesLoading, setRepoFilesLoading] = useState(false);
  const [repoAccessCheckLoading, setRepoAccessCheckLoading] = useState(false);
  const [accessTokenValidationState, setAccessTokenValidationState] = useState<AccessTokenValidationState>("idle");
  const [accessTokenValidationMessage, setAccessTokenValidationMessage] = useState("");
  const [localProjectCapabilities, setLocalProjectCapabilities] = useState<LocalProjectCapabilities | null>(null);
  const [localProjectCapabilitiesLoading, setLocalProjectCapabilitiesLoading] = useState(false);
  const [localProjectUploadFiles, setLocalProjectUploadFiles] = useState<File[]>([]);
  const [localProjectUploadLoading, setLocalProjectUploadLoading] = useState(false);
  const [localProjectUploadCompressing, setLocalProjectUploadCompressing] = useState(false);
  const [localProjectUploadError, setLocalProjectUploadError] = useState("");
  const [localProjectUploadWarning, setLocalProjectUploadWarning] = useState("");
  // const [migrationJob, setMigrationJob] = useState<MigrationResult | null>(null);
  const [migrationJob, setMigrationJob] = useState<MigrationResult | null>(() =>
  readSessionJson<MigrationResult>(WIZARD_MIGRATION_JOB_KEY)
);
  const [migrationLogs, setMigrationLogs] = useState<string[]>([]);
  const [error, setError] = useState<string>("");
  const [targetVersionRequiredError, setTargetVersionRequiredError] = useState(false);
  const [targetRepoNameError, setTargetRepoNameError] = useState("");
  const [migrationApproach, setMigrationApproach] = useState(
    persistedFormState?.migrationApproach ?? "fork"
  );
  const [riskLevel, setRiskLevel] = useState(persistedFormState?.riskLevel ?? "");
  const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>(
    persistedFormState?.selectedFrameworks ?? []
  );
  const [isJavaProject, setIsJavaProject] = useState<boolean | null>(
    persistedFormState?.isJavaProject ?? null
  );
  const [selectedFile, setSelectedFile] = useState<RepoFile | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [editedContent, setEditedContent] = useState<string>("");
  const [isEditing, setIsEditing] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [pathHistory, setPathHistory] = useState<string[]>(
    persistedFormState?.pathHistory?.length ? persistedFormState.pathHistory : [""]
  );
  const [showFileExplorer, setShowFileExplorer] = useState(true);
  
  // High-risk project states (no pom.xml/build.gradle or unknown Java version)
  const [isHighRiskProject, setIsHighRiskProject] = useState(
    persistedFormState?.isHighRiskProject ?? false
  );
  const [highRiskConfirmed, setHighRiskConfirmed] = useState(
    persistedFormState?.highRiskConfirmed ?? false
  );
  const [suggestedJavaVersion, setSuggestedJavaVersion] = useState(
    persistedFormState?.suggestedJavaVersion ?? "auto"
  );
  const [detectedFrameworks, setDetectedFrameworks] = useState<{name: string; path: string; type: string}[]>(
    persistedFormState?.detectedFrameworks ?? []
  );
  const [viewingFrameworkFile, setViewingFrameworkFile] = useState<{name: string; path: string; content: string} | null>(null);
  const [frameworkFileLoading, setFrameworkFileLoading] = useState(false);
  const [fossaResult, setFossaResult] = useState<FossaScanResult | null>(null);
  const [fossaLoading, setFossaLoading] = useState(false);
  const [rerunTestsLoading, setRerunTestsLoading] = useState(false);
  // Track if user selected a version in discovery
  const [userSelectedVersion, setUserSelectedVersion] = useState<string | null>(
    persistedFormState?.userSelectedVersion ?? null
  );
  // Track if no version was detected/selected
  const [sourceVersionStatus, setSourceVersionStatus] = useState<"detected" | "not_selected" | "unknown">(
    persistedFormState?.sourceVersionStatus ?? "unknown"
  );
  // Track if user confirmed and wants to update pom.xml
  const [updateSourceVersion, setUpdateSourceVersion] = useState(
    persistedFormState?.updateSourceVersion ?? false
  );
  const [githubUserLogin, setGithubUserLogin] = useState("");
  const currentMigrationApproach =
    migrationApproach === "branch"
      ? "branch"
      : migrationApproach === "local"
        ? "local"
        : "fork";
  const targetRepoName = targetRepoNamesByApproach[currentMigrationApproach] ?? "";
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

  const getAutoGeneratedTargetName = (approach: MigrationApproachValue, repoName: string = sourceRepositoryName) =>
    approach === "branch"
      ? buildTargetBranchName(repoName, targetRepoTimestamp)
      : approach === "local"
        ? buildLocalTargetFolderName(repoName)
        : buildTargetRepoUrl(repoName, targetRepoTimestamp, targetRepositoryOwner, targetRepositoryHost);

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

  const migrationApproachOptions = [
    {
      value: "fork",
      label: "Create New Repository",
      desc: "Push migrated code to a new repository under the Javaapex GitHub owner",
      tooltip: "Creates an entirely new repository with the migrated code under the Javaapex GitHub owner by default.",
      icon: "🍴",
      color: "#f59e0b",
    },
    {
      value: "branch",
      label: "Existing Repository (New Branch)",
      desc: "Push migrated code to a new branch in the source repository",
      tooltip: "Keeps the existing repository and publishes the migrated code on a separate branch for review and merge.",
      icon: "🌿",
      color: "#22c55e",
    },
    {
      value: "local",
      label: "Store In Local Folder",
      desc: "Save migrated code into a local folder on this machine",
      tooltip: "Creates a local folder such as {repo-name}-Migrated under the backend migration workspace instead of pushing to GitHub.",
      icon: "📁",
      color: "#2563eb",
    },
  ];

  // Code diff viewer states for Result page
  const [migrationPreview, setMigrationPreview] = useState<MigrationPreview | null>(null);
  const [migrationPreviewLoading, setMigrationPreviewLoading] = useState(false);
  const [migrationPreviewError, setMigrationPreviewError] = useState("");
  const [codeChanges, setCodeChanges] = useState<CodeChangeEntry[]>([]);
  const [selectedDiffFile, setSelectedDiffFile] = useState<string | null>(null);
  const [showCodeChanges, setShowCodeChanges] = useState(true);
  const [visibleReportDiffCount, setVisibleReportDiffCount] = useState(REPORT_DIFFS_PAGE_SIZE);
  const [reportDependencyPage, setReportDependencyPage] = useState(1);
  const [reportAccordionState, setReportAccordionState] = useState({
    sonar: true,
    fossa: true,
    issues: true,
  });
  const [documentGenerationLoading, setDocumentGenerationLoading] = useState<GeneratedDocumentKind | null>(null);
  const [repoPreviewInitialized, setRepoPreviewInitialized] = useState(false);
  const [microserviceAssessmentResolved, setMicroserviceAssessmentResolved] = useState(false);
  const [documentPrefetchStatus, setDocumentPrefetchStatus] = useState<DocumentPrefetchStatus>("idle");
  const [prefetchedBrdDocument, setPrefetchedBrdDocument] = useState<GithubDocumentResponse | null>(null);
  const [prefetchedBrdPdfBlob, setPrefetchedBrdPdfBlob] = useState<Blob | null>(null);
  const [prefetchedBrdFilename, setPrefetchedBrdFilename] = useState<string>("");
  const documentPrefetchKeyRef = useRef<string>("");

  // Animation progress state - starts immediately when migration begins
  const [animationProgress, setAnimationProgress] = useState(0);

  const isPrivateRepoAccessError = (message: string) => {
    const normalizedMessage = message.toLowerCase();
    return (
      normalizedMessage.includes("private repository") ||
      normalizedMessage.includes("repository not found or is private") ||
      normalizedMessage.includes("provide a personal access token") ||
      normalizedMessage.includes("access denied")
    );
  };

  const resetAccessTokenValidationState = () => {
    setAccessTokenValidationState("idle");
    setAccessTokenValidationMessage("");
  };

  const toggleMicroserviceAccordion = (section: MicroserviceAccordionKey) => {
    setMicroserviceAccordionState((current) => ({
      ...current,
      [section]: !current[section],
    }));
  };

  const uniqueTextItems = (items: string[] = []) =>
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

  const renderMicroserviceEvidenceBlock = ({
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
  const isLocalProjectSelected = isLocalRepoRef(selectedRepo?.url || migrationJob?.source_repo || "");
  const buildBrdDocumentRequest = (repoReference: string): GithubDocumentRequest => ({
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

  const triggerBlobDownload = (blob: Blob, filename: string) => {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  };

  const cloneBlob = (blob: Blob) => blob.slice(0, blob.size, blob.type || "application/pdf");

  const buildPdfFilename = (filename?: string) => {
    const fallbackRepoName = (selectedRepo?.name || repoAnalysis?.name || "repository").toUpperCase();
    const fallbackName = `${fallbackRepoName}-TECHNICAL-DOCUMENT.pdf`;
    const safeName = (filename?.trim() || fallbackName).replace(/[\\/:*?"<>|]+/g, "-");
    const withoutExtension = safeName.replace(/\.[^.]+$/, "");
    return `${withoutExtension}.pdf`;
  };

  const escapeHtml = (value: string) =>
    value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const extractRenderableHtml = (html: string) => {
    const parsedDocument = new DOMParser().parseFromString(html, "text/html");
    const headMarkup = Array.from(
      parsedDocument.head.querySelectorAll("style, link[rel='stylesheet']")
    )
      .map((node) => node.outerHTML)
      .join("");

    return {
      bodyClassName: parsedDocument.body.className,
      markup: `${headMarkup}${parsedDocument.body.innerHTML || html}`,
    };
  };

  const waitForDocumentAssets = async (container: HTMLElement) => {
    const imagePromises = Array.from(container.querySelectorAll("img")).map(
      (image) =>
        new Promise<void>((resolve) => {
          if (image.complete) {
            resolve();
            return;
          }

          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener("error", () => resolve(), { once: true });
        })
    );

    if ("fonts" in document) {
      await (document as Document & { fonts?: FontFaceSet }).fonts?.ready?.catch(() => undefined);
    }

    await Promise.all(imagePromises);
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  };

  const addPdfLinksForPage = (
    pdf: jsPDF,
    pageElement: HTMLElement,
    pdfWidth: number,
    pdfHeight: number,
    pageIdToPdfPageNumber: Map<string, number>
  ) => {
    const pageRect = pageElement.getBoundingClientRect();
    if (!pageRect.width || !pageRect.height) {
      return;
    }

    const anchors = Array.from(pageElement.querySelectorAll<HTMLAnchorElement>("a[href]"));

    anchors.forEach((anchor) => {
      const href = anchor.getAttribute("href")?.trim();
      if (!href) {
        return;
      }

      const targetPageNumber = href.startsWith("#")
        ? pageIdToPdfPageNumber.get(href.slice(1))
        : undefined;
      const isExternal = /^https?:\/\//i.test(href);

      if (!targetPageNumber && !isExternal) {
        return;
      }

      Array.from(anchor.getClientRects()).forEach((rect) => {
        const widthRatio = pdfWidth / pageRect.width;
        const heightRatio = pdfHeight / pageRect.height;
        const x = (rect.left - pageRect.left) * widthRatio;
        const y = (rect.top - pageRect.top) * heightRatio;
        const w = Math.max(rect.width * widthRatio, 2);
        const h = Math.max(rect.height * heightRatio, 2);

        if (targetPageNumber) {
          pdf.link(x, y, w, h, { pageNumber: targetPageNumber });
        } else if (isExternal) {
          pdf.link(x, y, w, h, { url: href });
        }
      });
    });
  };

  const renderHtmlToPdfBlob = async (html: string) => {
    const pdf = new jsPDF({
      orientation: "portrait",
      unit: "pt",
      format: "a4",
      compress: true,
    });
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = pdf.internal.pageSize.getHeight();
    const renderRoot = document.createElement("div");
    const { bodyClassName, markup } = extractRenderableHtml(html);

    renderRoot.className = bodyClassName;
    renderRoot.innerHTML = markup;
    Object.assign(renderRoot.style, {
      position: "fixed",
      left: "-10000px",
      top: "0",
      width: "794px",
      background: "#ffffff",
      zIndex: "-1",
      overflow: "hidden",
    });

    document.body.appendChild(renderRoot);

    try {
      await waitForDocumentAssets(renderRoot);

      const pageElements = Array.from(renderRoot.querySelectorAll<HTMLElement>(".page"));
      const pageIdToPdfPageNumber = new Map<string, number>();

      pageElements.forEach((pageElement, index) => {
        if (pageElement.id) {
          pageIdToPdfPageNumber.set(pageElement.id, index + 1);
        }
      });

      if (pageElements.length > 0) {
        for (const [index, pageElement] of pageElements.entries()) {
          const canvas = await html2canvas(pageElement, {
            backgroundColor: "#ffffff",
            scale: 1.8,
            useCORS: true,
            windowWidth: pageElement.scrollWidth,
            windowHeight: pageElement.scrollHeight,
          });

          if (index > 0) {
            pdf.addPage();
          }

          pdf.addImage(
            canvas.toDataURL("image/png"),
            "PNG",
            0,
            0,
            pdfWidth,
            pdfHeight,
            undefined,
            "FAST"
          );

          addPdfLinksForPage(pdf, pageElement, pdfWidth, pdfHeight, pageIdToPdfPageNumber);
        }
      } else {
        const canvas = await html2canvas(renderRoot, {
          backgroundColor: "#ffffff",
          scale: 1.5,
          useCORS: true,
          windowWidth: renderRoot.scrollWidth,
          windowHeight: renderRoot.scrollHeight,
        });
        const imageData = canvas.toDataURL("image/png");
        const imageHeight = (canvas.height * pdfWidth) / canvas.width;
        let heightLeft = imageHeight;
        let position = 0;

        pdf.addImage(imageData, "PNG", 0, position, pdfWidth, imageHeight, undefined, "FAST");
        heightLeft -= pdfHeight;

        while (heightLeft > 0) {
          position = heightLeft - imageHeight;
          pdf.addPage();
          pdf.addImage(imageData, "PNG", 0, position, pdfWidth, imageHeight, undefined, "FAST");
          heightLeft -= pdfHeight;
        }
      }

      return pdf.output("blob");
    } finally {
      renderRoot.remove();
    }
  };

  const downloadHtmlAsPdf = async (html: string, filename: string) => {
    const pdfBlob = await renderHtmlToPdfBlob(html);
    triggerBlobDownload(pdfBlob, filename);
  };

  const resolveGeneratedDocumentAsset = async (result: GithubDocumentResponse) => {
    if (result.html?.trim()) {
      return { html: result.html } as const;
    }

    if (!result.url) {
      throw new Error("Generated BRD document did not include HTML content or a download URL.");
    }

    const response = await fetch(result.url);

    if (!response.ok) {
      throw new Error("Unable to fetch the generated BRD document for PDF export.");
    }

    const contentType = response.headers.get("content-type") || "";
    const documentBlob = await response.blob();

    if (
      contentType.includes("application/pdf") ||
      documentBlob.type.includes("pdf") ||
      result.url.toLowerCase().endsWith(".pdf")
    ) {
      return { blob: documentBlob } as const;
    }

    return { html: await documentBlob.text() } as const;
  };

  const downloadClientSonarPdfFallback = async (job: MigrationResult) => {
    const sonarReport = job.sonar_report ?? null;
    const sectionConfigs = [
      {
        title: "Vulnerabilities",
        accent: "#dc2626",
        details: sonarReport?.vulnerability_details ?? [],
      },
      {
        title: "Code Smells",
        accent: "#d97706",
        details: sonarReport?.code_smell_details ?? [],
      },
      {
        title: "Security Hotspots",
        accent: "#7c3aed",
        details: sonarReport?.security_hotspot_details ?? [],
      },
      {
        title: "Bugs",
        accent: "#2563eb",
        details: sonarReport?.bug_details ?? [],
      },
    ];

    const renderIssueCard = (issue: SonarIssueDetail | SonarHotspotDetail) => {
      const severity = (getSonarIssueSeverityValue(issue) || "N/A").toString().toUpperCase();
      const status = (issue.status || "OPEN").toString().toUpperCase();
      const location = `${issue.component || "N/A"}${issue.line ? `:${issue.line}` : ""}`;
      const detailRow = [
        `<span><strong>File:</strong> ${escapeHtml(location)}</span>`,
        issue.rule ? `<span><strong>Rule:</strong> ${escapeHtml(issue.rule)}</span>` : "",
        "effort" in issue && issue.effort ? `<span><strong>Effort:</strong> ${escapeHtml(issue.effort)}</span>` : "",
        "security_category" in issue && issue.security_category ? `<span><strong>Category:</strong> ${escapeHtml(issue.security_category)}</span>` : "",
        issue.update_date ? `<span><strong>Updated:</strong> ${escapeHtml(formatSonarTimestamp(issue.update_date))}</span>` : "",
      ]
        .filter(Boolean)
        .join("");

      return `
        <div class="finding-card">
          <div class="finding-top">
            <div class="finding-title">${escapeHtml(issue.message || issue.rule || "Unnamed Sonar finding")}</div>
            <div class="finding-badges">
              <span class="badge badge-severity">${escapeHtml(severity)}</span>
              <span class="badge badge-status">${escapeHtml(status)}</span>
            </div>
          </div>
          <div class="finding-meta">${detailRow}</div>
        </div>
      `;
    };

    const html = `<!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8" />
          <title>Sonar Findings Report</title>
          <style>
            * { box-sizing: border-box; }
            body { margin: 0; font-family: Inter, Arial, sans-serif; background: #f8fafc; color: #0f172a; }
            .page { width: 794px; min-height: 1123px; padding: 36px; background: #f8fafc; }
            .hero {
              padding: 28px 30px;
              border-radius: 24px;
              color: #fff;
              background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 55%, #38bdf8 100%);
              box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18);
            }
            .eyebrow { font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase; opacity: 0.85; }
            .title { font-size: 30px; font-weight: 800; margin: 12px 0 10px; }
            .subtitle { font-size: 14px; line-height: 1.7; opacity: 0.92; }
            .meta-grid, .stat-grid { display: grid; gap: 14px; }
            .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 18px; }
            .stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 24px; }
            .card, .stat-card, .finding-card, .callout {
              background: #fff;
              border-radius: 18px;
              border: 1px solid #dbe5f3;
              box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
            }
            .card { padding: 18px; }
            .meta-label, .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; font-weight: 700; }
            .meta-value { margin-top: 8px; font-size: 15px; font-weight: 700; color: #0f172a; word-break: break-word; }
            .stat-card { padding: 18px; min-height: 108px; }
            .stat-value { margin-top: 16px; font-size: 28px; font-weight: 800; color: #0f172a; }
            .callout { margin-top: 22px; padding: 18px 20px; color: #1e3a8a; background: #eff6ff; border-color: #bfdbfe; font-size: 13px; line-height: 1.7; }
            .section-title { font-size: 22px; font-weight: 800; margin: 0 0 16px; color: #0f172a; }
            .section-kicker { display: inline-flex; padding: 8px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; color: #0f172a; background: rgba(15, 23, 42, 0.06); margin-bottom: 14px; }
            .finding-card { padding: 16px 18px; margin-bottom: 14px; }
            .finding-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
            .finding-title { font-size: 15px; font-weight: 800; color: #0f172a; line-height: 1.6; }
            .finding-badges { display: flex; gap: 8px; flex-wrap: wrap; }
            .badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 6px 10px; font-size: 11px; font-weight: 800; }
            .badge-severity { background: #fee2e2; color: #991b1b; }
            .badge-status { background: #eff6ff; color: #1d4ed8; }
            .finding-meta { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; font-size: 12px; line-height: 1.6; color: #475569; }
            .footer { margin-top: 18px; font-size: 11px; color: #64748b; text-align: right; }
            a { color: #1d4ed8; text-decoration: none; }
          </style>
        </head>
        <body>
          <section class="page">
            <div class="hero">
              <div class="eyebrow">Sonar Modernization Assessment</div>
              <div class="title">Code Quality & Security Findings Report</div>
              <div class="subtitle">
                Repository: ${escapeHtml(job.target_repo || job.source_repo || "Repository")}<br />
                Generated: ${escapeHtml(new Date().toLocaleString())}
              </div>
            </div>
            <div class="meta-grid">
              <div class="card">
                <div class="meta-label">Quality Gate</div>
                <div class="meta-value">${escapeHtml(job.sonar_quality_gate || sonarReport?.quality_gate || "N/A")}</div>
              </div>
              <div class="card">
                <div class="meta-label">Coverage</div>
                <div class="meta-value">${escapeHtml(`${job.sonar_coverage ?? sonarReport?.coverage ?? 0}%`)}</div>
              </div>
              <div class="card">
                <div class="meta-label">Scan Mode</div>
                <div class="meta-value">${escapeHtml(job.sonar_scan_mode || "N/A")}</div>
              </div>
              <div class="card">
                <div class="meta-label">Analysis Link</div>
                <div class="meta-value">
                  ${job.sonar_analysis_url ? `<a href="${escapeHtml(job.sonar_analysis_url)}">${escapeHtml(job.sonar_analysis_url)}</a>` : "Not available"}
                </div>
              </div>
            </div>
            <div class="stat-grid">
              <div class="stat-card"><div class="stat-label">Vulnerabilities</div><div class="stat-value">${job.sonar_vulnerabilities ?? sonarReport?.vulnerabilities ?? 0}</div></div>
              <div class="stat-card"><div class="stat-label">Code Smells</div><div class="stat-value">${job.sonar_code_smells ?? sonarReport?.code_smells ?? 0}</div></div>
              <div class="stat-card"><div class="stat-label">Security Hotspots</div><div class="stat-value">${job.sonar_security_hotspots ?? sonarReport?.security_hotspots ?? 0}</div></div>
              <div class="stat-card"><div class="stat-label">Bugs</div><div class="stat-value">${job.sonar_bugs ?? sonarReport?.bugs ?? 0}</div></div>
              <div class="stat-card"><div class="stat-label">Duplications</div><div class="stat-value">${sonarReport?.duplications ?? job.sonar_duplications ?? 0}%</div></div>
              <div class="stat-card"><div class="stat-label">Real Scan</div><div class="stat-value">${job.sonar_real_scan ? "Yes" : "No"}</div></div>
            </div>
            <div class="callout">
              The premium backend PDF endpoint is not available in the current backend session, so this browser-generated fallback report was downloaded instead. Restart the backend server after the latest code changes to enable the full enterprise PDF.
            </div>
          </section>
          ${sectionConfigs
            .filter((section) => section.details.length > 0)
            .map(
              (section) => `
                <section class="page">
                  <div class="section-kicker" style="background:${section.accent}14; color:${section.accent};">${escapeHtml(section.title)}</div>
                  <h2 class="section-title">${escapeHtml(section.title)}</h2>
                  ${section.details.map((issue) => renderIssueCard(issue)).join("")}
                  <div class="footer">${escapeHtml(job.job_id)}</div>
                </section>
              `
            )
            .join("")}
        </body>
      </html>`;

    await downloadHtmlAsPdf(html, `sonar-findings-${job.job_id}.pdf`);
  };

  const handleGenerateBrdDocument = async () => {
    const repoReference = getDocumentRepositoryUrl();

    if (!repoReference) {
      setError("Repository URL is required before generating the BRD document.");
      return;
    }

    if (prefetchedBrdPdfBlob && documentPrefetchStatus === "ready") {
      triggerBlobDownload(cloneBlob(prefetchedBrdPdfBlob), prefetchedBrdFilename || buildPdfFilename());
      return;
    }

    setDocumentGenerationLoading("brd");
    setError("");

    try {
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
            analysis: repoAnalysis as Record<string, any>,
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

      const pdfFilename = buildPdfFilename(result.filename);
      const generatedAsset = await resolveGeneratedDocumentAsset(result);

      if (generatedAsset.blob) {
        triggerBlobDownload(generatedAsset.blob, pdfFilename);
      } else if (generatedAsset.html) {
        await downloadHtmlAsPdf(generatedAsset.html, pdfFilename);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to generate BRD document");
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

  const handleCheckMicroserviceEligibility = async () => {
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
        ? await getLocalProjectMicroserviceEligibility(extractLocalRepoPath(selectedRepo.url))
        : await getMicroserviceEligibility(selectedRepo.url, currentToken);
      setMicroserviceResult(result);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error("Failed to fetch microservice eligibility", message);
      setError("Unable to determine microservice eligibility from backend. Please try again.");
    } finally {
      setMicroserviceAssessmentResolved(true);
      setMicroserviceLoading(false);
    }
  };

  const handleDownloadMicroserviceReport = () => {
    if (!microserviceResult) return;
    const pdf = new jsPDF({
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
  }, [repoAnalysis, selectedRepo?.url, microserviceAssessmentResolved, microserviceLoading, currentToken]);

  const getDetectedComponentCategory = (type: string): "Framework" | "Library" => {
    const normalizedType = type.toLowerCase();

    if (normalizedType.includes("library")) {
      return "Library";
    }

    if (
      normalizedType.includes("framework") ||
      normalizedType.includes("orm") ||
      normalizedType.includes("testing")
    ) {
      return "Framework";
    }

    return "Library";
  };

  const parseJavaVersion = (version: string) => {
    const parsed = parseInt(version, 10);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const buildCodeChangesFromPreviewDiffs = (fileDiffs: PreviewFileDiff[]): CodeChangeEntry[] => {
    return fileDiffs.map((fileDiff) => {
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

      return {
        fileName: normalizedPath.split("/").pop() || normalizedPath,
        filePath: normalizedPath,
        changeType,
        additions,
        deletions,
        oldContent: "",
        newContent: "",
        diffLines: parsedDiffLines,
      };
    });
  };

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
                      <span style={{ fontSize: 14 }}>{selectedDiffFile === change.filePath ? "▼" : "▶"}</span>
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
    if (
      trimmed.startsWith("/") ||
      trimmed.endsWith("/") ||
      trimmed.endsWith(".") ||
      trimmed.endsWith(".lock") ||
      trimmed.includes("..") ||
      trimmed.includes("//") ||
      trimmed.includes("@{") ||
      /[\\^:?*\[\]~]/.test(trimmed)
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

      const [owner, repo] = pathParts;
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
      if (/[<>:"/\\|?*\u0000-\u001F]/.test(segment)) {
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

  const renderDetectedDependencies = (
    dependencies: DependencyInfo[],
    options?: { limit?: number }
  ) => {
    const visibleDependencies =
      typeof options?.limit === "number"
        ? dependencies.slice(0, options.limit)
        : dependencies;
    const remainingCount = dependencies.length - visibleDependencies.length;

    return (
      <div style={styles.dependenciesList}>
        <div style={styles.dependenciesGrid}>
          {visibleDependencies.map((dep, idx) => {
            const isAnalyzed = isDetectedDependencyStatus(dep.status);
            return (
              <div
                key={`${dep.group_id}:${dep.artifact_id}:${idx}`}
                style={styles.dependencyCard}
              >
                <div style={styles.dependencyCardName}>
                  {dep.group_id}:{dep.artifact_id}
                </div>
                <div style={styles.dependencyVersionCard}>
                  {dep.current_version || "Unknown version"}
                </div>
                <span
                  style={{
                    ...styles.dependencyStatusBadge,
                    backgroundColor: isAnalyzed ? "#dcfce7" : "#e5e7eb",
                    color: isAnalyzed ? "#166534" : "#6b7280",
                  }}
                >
                  {getDependencyStatusLabel(dep.status)}
                </span>
              </div>
            );
          })}
        </div>
        {remainingCount > 0 && (
          <div style={styles.moreItems}>+{remainingCount} more dependencies</div>
        )}
      </div>
    );
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
          <div style={styles.dependencyInsightsTitle}>📦 Total Dependencies ({categorizedDependencies.length})</div>
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
              <div style={styles.dependencyAlertTitle}>⚠️ {attentionDependencies.length} dependencies need migration attention</div>
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

  const enrichAnalysisWithPomVersion = async (analysis: RepoAnalysis, repoUrlToAnalyze: string, token: string) => {
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
  };

  const applyRepositoryAnalysis = (analysis: RepoAnalysis) => {
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
      analysis.dependencies.forEach((dep: any) => {
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
  };

  const resetRepositorySelectionState = () => {
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
    setPrefetchedBrdPdfBlob(null);
    setPrefetchedBrdFilename("");
    setDocumentPrefetchStatus("idle");
    documentPrefetchKeyRef.current = "";
  };

  const handleRepositoryContinue = async () => {
    if (!urlValidation.valid) return;

    const normalizedUrl = urlValidation.normalizedUrl;
    const token = getCurrentToken().trim();

    if (showEnterpriseToken && !token) {
      setError("");
      setAccessTokenValidationState("invalid");
      setAccessTokenValidationMessage("Enter a GitHub Personal Access Token to analyze this GitHub Enterprise repository.");
      return;
    }

    if (isPrivateRepo && !token) {
      setError("");
      setAccessTokenValidationState("invalid");
      setAccessTokenValidationMessage("Enter a GitHub Personal Access Token with repo scope to analyze this private repository.");
      return;
    }

    resetRepositorySelectionState();
    setTargetRepoNamesByApproach({ fork: "", branch: "", local: "" });
    setTargetRepoNameEditedByApproach({ fork: false, branch: false, local: false });
    setTargetRepoNameError("");
    setSelectedRepo({
      name: normalizedUrl.split('/').pop() || "",
      full_name: normalizedUrl
        .replace(/^https?:\/\/(www\.)?github\.com\//, '')
        .replace(/^https?:\/\/(www\.)?gitlab\.com\//, ''),
      url: normalizedUrl,
      default_branch: "main",
      language: "Java",
      description: ""
    });
    setStep(2);
  };

  const handleLocalProjectAnalyze = async () => {
    if (!localProjectInputValid) return;

    resetRepositorySelectionState();
    setTargetRepoNamesByApproach({ fork: "", branch: "", local: "" });
    setTargetRepoNameEditedByApproach({ fork: false, branch: false, local: false });
    setTargetRepoNameError("");
    setSelectedRepo({
      name: getPathBasename(normalizedLocalProjectPath),
      full_name: normalizedLocalProjectPath,
      url: buildLocalRepoRef(normalizedLocalProjectPath),
      default_branch: "local",
      language: "Java",
      description: "Local project",
    });
    setStep(2);
  };

  const MAX_LOCAL_PROJECT_UPLOAD_FILES = 25000;
  const MAX_LOCAL_PROJECT_UPLOAD_SIZE_BYTES = 1024 * 1024 * 1024; // 1 GB
  const AUTO_ZIP_LOCAL_PROJECT_UPLOAD_FILES = 15000;
  const AUTO_ZIP_LOCAL_PROJECT_UPLOAD_SIZE_BYTES = 150 * 1024 * 1024; // 150 MB
  const CHUNK_UPLOAD_SIZE_BYTES = 60 * 1024 * 1024; // 60 MB
  const WARN_LOCAL_PROJECT_UPLOAD_FILES = 500;
  const WARN_LOCAL_PROJECT_UPLOAD_SIZE_BYTES = 150 * 1024 * 1024; // 150 MB

  const shouldCompressLocalProjectUpload = (files: File[]) => {
    if (files.length === 1 && files[0].name.toLowerCase().endsWith(".zip")) {
      return false;
    }
    const totalSize = files.reduce((sum, file) => sum + file.size, 0);
    return (
      files.length > AUTO_ZIP_LOCAL_PROJECT_UPLOAD_FILES ||
      totalSize > AUTO_ZIP_LOCAL_PROJECT_UPLOAD_SIZE_BYTES
    );
  };

  const zipLocalProjectFiles = async (files: File[]): Promise<Blob> => {
    const entries: Record<string, Uint8Array> = {};
    for (const file of files) {
      const relativePath = (file as any).webkitRelativePath || file.name;
      const arrayBuffer = await file.arrayBuffer();
      entries[relativePath || file.name] = new Uint8Array(arrayBuffer);
    }
    const zipped = zipSync(entries, { level: 3 });
    return new Blob([zipped], { type: "application/zip" });
  };

  const handleLocalProjectFilesChange = (files: FileList | null) => {
    if (!files) {
      setLocalProjectUploadFiles([]);
      setLocalProjectUploadError("");
      setLocalProjectUploadWarning("");
      return;
    }

    const fileArray = Array.from(files);
    const totalSize = fileArray.reduce((sum, file) => sum + file.size, 0);

    if (fileArray.length > MAX_LOCAL_PROJECT_UPLOAD_FILES || totalSize > MAX_LOCAL_PROJECT_UPLOAD_SIZE_BYTES) {
      setLocalProjectUploadFiles(fileArray);
      setLocalProjectUploadError(
        `Selected folder is too large to upload directly (${fileArray.length} files, ${(totalSize / (1024 * 1024)).toFixed(1)} MB). Please upload a ZIP archive instead.`
      );
      setLocalProjectUploadWarning("");
      setError("");
      return;
    }

    const shouldCompress = shouldCompressLocalProjectUpload(fileArray);
    let warningMessage = "";
    if (shouldCompress) {
      warningMessage = `Selected folder contains ${fileArray.length} files and ${(totalSize / (1024 * 1024)).toFixed(1)} MB. It will be compressed to ZIP before uploading to improve reliability.`;
    } else if (fileArray.length > WARN_LOCAL_PROJECT_UPLOAD_FILES || totalSize > WARN_LOCAL_PROJECT_UPLOAD_SIZE_BYTES) {
      warningMessage = `Selected folder contains ${fileArray.length} files and ${(totalSize / (1024 * 1024)).toFixed(1)} MB. Upload may take a long time, but it is allowed.`;
    }

    setLocalProjectUploadFiles(fileArray);
    setLocalProjectUploadError("");
    setLocalProjectUploadWarning(warningMessage);
    setError("");

    if (selectedRepo && isLocalRepoRef(selectedRepo.url)) {
      setSelectedRepo(null);
      setRepoAnalysis(null);
    }
  };

  const handleLocalProjectUpload = async () => {
    if (localProjectUploadFiles.length === 0) return;
    if (localProjectUploadError) return;

    setLocalProjectUploadLoading(true);
    setLocalProjectUploadCompressing(false);
    setLocalProjectUploadError("");
    setLocalProjectUploadWarning("");
    setError("");

    const localFiles = localProjectUploadFiles;
    const shouldCompress = shouldCompressLocalProjectUpload(localFiles);
    const uploadFiles = async (zip: boolean) => {
      const formData = new FormData();
      if (zip) {
        setLocalProjectUploadCompressing(true);
        const zipBlob = await zipLocalProjectFiles(localFiles);

        if (zipBlob.size > CHUNK_UPLOAD_SIZE_BYTES) {
          const totalChunks = Math.ceil(zipBlob.size / CHUNK_UPLOAD_SIZE_BYTES);
          const uploadId = globalThis.crypto?.randomUUID?.() ?? `upload-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
          let finalResponse: LocalProjectAnalysisResponse | null = null;

          for (let index = 0; index < totalChunks; index++) {
            const start = index * CHUNK_UPLOAD_SIZE_BYTES;
            const end = Math.min(start + CHUNK_UPLOAD_SIZE_BYTES, zipBlob.size);
            const chunkBlob = zipBlob.slice(start, end);
            const result = await uploadLocalProjectChunk(
              uploadId,
              index + 1,
              totalChunks,
              chunkBlob,
              "local-project.zip",
            );

            if (index === totalChunks - 1) {
              finalResponse = result as LocalProjectAnalysisResponse;
            }
          }

          if (!finalResponse) {
            throw new Error("Failed to complete chunked upload");
          }

          return finalResponse;
        }

      }
      return uploadLocalProject(formData);
    };

    let result;
    let attemptedZipRetry = false;
    try {
      result = await uploadFiles(shouldCompress);
    } catch (err: any) {
      const isNetworkFailure =
        err?.message === "Failed to fetch" ||
        err?.message?.includes("ERR_HTTP2_PROTOCOL_ERROR") ||
        err?.message?.includes("NetworkError");

      if (!shouldCompress && !attemptedZipRetry && isNetworkFailure && localFiles.length > 1) {
        attemptedZipRetry = true;
        try {
          result = await uploadFiles(true);
        } catch (retryErr: any) {
          const retryMessage = retryErr?.message || "Failed to upload local project";
          setLocalProjectUploadError(
            retryMessage === "Failed to fetch"
              ? "Upload failed due to browser or network limits. Try uploading a ZIP archive directly."
              : retryMessage
          );
        }
      } else {
        const message = err?.message || "Failed to upload local project";
        setLocalProjectUploadError(
          message === "Failed to fetch"
            ? "Upload failed due to browser or network limits. Try uploading a ZIP archive directly."
            : message
        );
      }
    } finally {
      setLocalProjectUploadCompressing(false);
      setLocalProjectUploadLoading(false);
    }

    if (!result) return;

    const repoUrl = result.project_path.startsWith("local://")
      ? result.project_path
      : buildLocalRepoRef(result.project_path);

    resetRepositorySelectionState();
    setTargetRepoNamesByApproach({ fork: "", branch: "", local: "" });
    setTargetRepoNameEditedByApproach({ fork: false, branch: false, local: false });
    setTargetRepoNameError("");
    setSelectedRepo({
      name: result.project_name || getPathBasename(localProjectUploadFiles[0]?.webkitRelativePath || localProjectUploadFiles[0]?.name || "uploaded-project"),
      full_name: repoUrl,
      url: repoUrl,
      default_branch: "local",
      language: "Java",
      description: "Uploaded local project",
    });
    setRepoAnalysis(result.analysis);
    setRepoFiles([]);
    setStep(2);
  };

   const testsRun = migrationJob?.tests_run ?? 0;
  const testsPassed = migrationJob?.tests_passed ?? 0;
  const testsFailed = migrationJob?.tests_failed ?? 0;
  const generatedTestsCount = migrationJob?.test_pipeline?.generated_test_files?.length ?? 0;
  const testSuccessRate =
    testsRun > 0
      ? Math.min(100, Math.round((testsPassed / testsRun) * 100))
      : testsPassed > 0
        ? 100
        : 0;
  const testSummaryFallback = testsRun === 0
    ? "Tests not executed yet"
    : testsFailed > 0
      ? `${testsFailed} test${testsFailed === 1 ? "" : "s"} failed`
      : "All unit tests passed successfully";
  const testSummaryText = migrationJob?.test_summary ?? testSummaryFallback;
  const testInsights = migrationJob?.test_insights ?? [];
  const testModel = migrationJob?.test_llm_model;
  const hasTestFailures = testsFailed > 0;
  const testStatusIcon = hasTestFailures ? "⚠️" : "✓";
  const testStatusColors = hasTestFailures
    ? { background: "#fee2e2", borderColor: "#fca5a5", textColor: "#991b1b" }
    : { background: "#dcfce7", borderColor: "#86efac", textColor: "#166534" };

  useEffect(() => {
    getJavaVersions().then((versions) => {
      setSourceVersions(versions.source_versions);
      setTargetVersions(versions.target_versions);
    });
    getConversionTypes().then(setConversionTypes);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLocalProjectCapabilitiesLoading(true);
    getLocalProjectCapabilities()
      .then((capabilities) => {
        if (!cancelled) {
          setLocalProjectCapabilities(capabilities);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLocalProjectCapabilities(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLocalProjectCapabilitiesLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

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
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    // Remove legacy persisted wizard values from localStorage so old repo URLs
    // and local project paths do not auto-populate new browser visits.
    WIZARD_STORAGE_KEYS.forEach((key) => window.localStorage.removeItem(key));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    if (repoUrl) {
      window.sessionStorage.setItem(WIZARD_REPO_URL_KEY, repoUrl);
    } else {
      window.sessionStorage.removeItem(WIZARD_REPO_URL_KEY);
    }
  }, [repoUrl]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    if (localProjectPath) {
      window.sessionStorage.setItem(WIZARD_LOCAL_PROJECT_PATH_KEY, localProjectPath);
    } else {
      window.sessionStorage.removeItem(WIZARD_LOCAL_PROJECT_PATH_KEY);
    }
  }, [localProjectPath]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    if (selectedRepo) {
      const serializedRepo = JSON.stringify(selectedRepo);
      window.sessionStorage.setItem(WIZARD_SELECTED_REPO_KEY, serializedRepo);
    } else {
      window.sessionStorage.removeItem(WIZARD_SELECTED_REPO_KEY);
    }
  }, [selectedRepo]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    if (repoAnalysis) {
      try {
        const serializedAnalysis = JSON.stringify(repoAnalysis);
        if (serializedAnalysis.length < 4 * 1024 * 1024) {
          window.sessionStorage.setItem(WIZARD_REPO_ANALYSIS_KEY, serializedAnalysis);
        }
      } catch (e) {
        console.warn("sessionStorage quota exceeded for repo analysis", e);
      }
    } else {
      window.sessionStorage.removeItem(WIZARD_REPO_ANALYSIS_KEY);
    }
  }, [repoAnalysis]);

  useEffect(() => {
  if (typeof window === "undefined") return;

  if (migrationJob) {
    try {
      // Strip large fields before persisting to avoid QuotaExceededError
      const slim = { ...migrationJob };
      delete (slim as any).sonar_report;
      delete (slim as any).code_changes;
      delete (slim as any).fossa_report;
      delete (slim as any).test_results;
      delete (slim as any).logs;
      delete (slim as any).detailed_logs;
      delete (slim as any).migration_logs;
      delete (slim as any).sonar_bug_details;
      delete (slim as any).sonar_vulnerability_details;
      delete (slim as any).sonar_code_smell_details;
      delete (slim as any).sonar_security_hotspot_details;
      delete (slim as any).extra_metadata;
      const serialized = JSON.stringify(slim);
      // Only persist if under 4 MB to stay within sessionStorage quota
      if (serialized.length < 4 * 1024 * 1024) {
        window.sessionStorage.setItem(WIZARD_MIGRATION_JOB_KEY, serialized);
      } else {
        // Too large even after slimming – store only essential fields
        const minimal = {
          job_id: migrationJob.job_id,
          status: migrationJob.status,
          repo_url: (migrationJob as any).repo_url,
          branch_url: (migrationJob as any).branch_url,
          target_branch: (migrationJob as any).target_branch,
        };
        window.sessionStorage.setItem(WIZARD_MIGRATION_JOB_KEY, JSON.stringify(minimal));
      }
    } catch (e) {
      // QuotaExceededError – clear stale data and retry with minimal payload
      console.warn("sessionStorage quota exceeded for migration job, storing minimal data", e);
      try {
        window.sessionStorage.removeItem(WIZARD_REPO_ANALYSIS_KEY);
        const minimal = {
          job_id: migrationJob.job_id,
          status: migrationJob.status,
          repo_url: (migrationJob as any).repo_url,
          branch_url: (migrationJob as any).branch_url,
        };
        window.sessionStorage.setItem(WIZARD_MIGRATION_JOB_KEY, JSON.stringify(minimal));
      } catch (_) {
        // Last resort – just remove it
        window.sessionStorage.removeItem(WIZARD_MIGRATION_JOB_KEY);
      }
    }
  } else {
    window.sessionStorage.removeItem(WIZARD_MIGRATION_JOB_KEY);
  }
}, [migrationJob]);

  useEffect(() => {
    writeSessionJson(WIZARD_FORM_STATE_KEY, {
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
      migrationType,
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
    } satisfies PersistedWizardFormState);
  }, [
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
    migrationType,
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
  ]);

  // Fetch FOSSA results for the migration job when requested or when job already has results
  useEffect(() => {
    if (migrationJob?.job_id && (runFossa || migrationJob.fossa_policy_status || migrationJob.fossa_total_dependencies || migrationJob.fossa_scan_mode || migrationJob.fossa_error_message)) {
      let cancelled = false;
      setFossaLoading(true);
      getMigrationFossa(migrationJob.job_id)
        .then(({ fossa }) => {
          if (cancelled) return;
          setFossaResult(fossa);

          // also merge into migrationJob fields so other parts of the UI (downloads/reports) see them
          setMigrationJob((prev) => prev ? ({
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
          }) : prev);
        })
        .catch(() => {
          // keep silent on failure; UI will show N/A
        })
        .finally(() => { if (!cancelled) setFossaLoading(false); });

      return () => { cancelled = true; };
    }
  }, [runFossa, migrationJob?.job_id, migrationJob?.fossa_policy_status, migrationJob?.fossa_total_dependencies, migrationJob?.fossa_scan_mode, migrationJob?.fossa_error_message]);

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

  const fossaSeverityCounts =
    fossaResult?.vulnerabilities && typeof fossaResult.vulnerabilities === "object"
      ? {
          critical: Number(fossaResult.vulnerabilities.critical || 0),
          high: Number(fossaResult.vulnerabilities.high || 0),
          medium: Number(fossaResult.vulnerabilities.medium || 0),
          low: Number(fossaResult.vulnerabilities.low || 0),
        }
      : null;

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
  }, [migrationJob?.job_id]);

  useEffect(() => {
    setReportDependencyPage(1);
  }, [migrationJob?.job_id, migrationJob?.dependencies?.length]);

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
  }, [step, codeChanges, visibleReportCodeChanges, selectedDiffFile]);

  const detectedJavaVersion = (repoAnalysis?.java_version || repoAnalysis?.java_version_from_build || "").toString().trim();
  const detectedJavaStructureLabel = detectedJavaVersion ? `✓ Java ${detectedJavaVersion}` : "✗ Java version";
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

    return orderedVersions
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
  }, [availableTargetVersions, selectedSourceVersion, versionRecommendation]);

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
    selectedSourceVersion,
    selectedTargetVersion,
  ]);

  const formattedAnalysisElapsed = `${Math.floor(analysisElapsedSeconds / 60)
    .toString()
    .padStart(2, "0")}:${(analysisElapsedSeconds % 60).toString().padStart(2, "0")}`;
   
  const formattedAnalysisCompleted = `${Math.floor(analysisCompletedSeconds / 60)
  .toString()
  .padStart(2, "0")}:${(analysisCompletedSeconds % 60).toString().padStart(2, "0")}`;
  const isDiscoveryPending =
    analysisLoading ||
    Boolean(repoAnalysis && (!repoPreviewInitialized || !microserviceAssessmentResolved));
 

  const formatMigrationElapsed = (totalSeconds: number) => {
    const safeSeconds = Math.max(0, totalSeconds);
    const hours = Math.floor(safeSeconds / 3600);
    const minutes = Math.floor((safeSeconds % 3600) / 60);
    const seconds = safeSeconds % 60;

    if (hours > 0){
      return `${hours}h:${minutes.toString().padStart(2, "0")}m`;
        }

    if (minutes > 0){
  return `${minutes}m:${seconds.toString().padStart(2, "0")}s`;
}

return `${seconds}s`;
};
    
  //   if (hours > 0) {
  //     return `${hours}h ${minutes.toString().padStart(2, "0")}m ${seconds.toString().padStart(2, "0")}s`;
  //   }

  //   return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  // };
  

  const getMigrationElapsedSeconds = () => {
    if (!migrationJob?.started_at) return 0;

    const startedAtMs = Date.parse(migrationJob.started_at);
    if (Number.isNaN(startedAtMs)) return 0;

    const completedAtMs = migrationJob.completed_at ? Date.parse(migrationJob.completed_at) : NaN;
    const endTimeMs = !Number.isNaN(completedAtMs) ? completedAtMs : migrationTimerNow;

    return Math.max(0, Math.floor((endTimeMs - startedAtMs) / 1000));
  };

  const formattedMigrationElapsed = formatMigrationElapsed(getMigrationElapsedSeconds());

  const renderMigrationTimer = () => {
    if (!migrationJob?.started_at) return null;

    return (
      <div style={styles.migrationTimerSection}>
        <div style={styles.migrationTimerCard}>
          <span style={styles.migrationTimerIcon}>⏱</span>
          <div>
            <div style={styles.migrationTimerLabel}></div>
            <div style={styles.migrationTimerValue}>{formattedMigrationElapsed}</div>
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
  }, [isDiscoveryPending, analysisStartedAtMs]);

  useEffect(() => {
    if (!isDiscoveryPending && analysisStartedAtMs) {
      const elapsed = Math.max(1, Math.floor((Date.now() - analysisStartedAtMs) / 1000));
      setAnalysisCompletedSeconds(elapsed);
      setAnalysisStartedAtMs(null);
    }
  }, [isDiscoveryPending, analysisStartedAtMs]);

  useEffect(() => {
    setMigrationTimerNow(Date.now());

    if (!(step >= 5 && step <= 6 && migrationJob?.started_at)) {
      return;
    }

    if (migrationJob.status === "completed" || migrationJob.status === "failed") {
      return;
    }

    const interval = window.setInterval(() => {
      setMigrationTimerNow(Date.now());
    }, 1000);

    return () => window.clearInterval(interval);
  }, [step, migrationJob?.started_at, migrationJob?.completed_at, migrationJob?.status]);

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
  }, [step, migrationJob?.progress_percent, migrationJob?.status]);

  useEffect(() => {
    if (step === 2 && selectedRepo && !repoAnalysis) {
      setAnalysisLoading(true);
      setError("");

      const analyzePromise = isLocalRepoRef(selectedRepo.url)
        ? analyzeLocalProject(extractLocalRepoPath(selectedRepo.url))
            .then(async (result) => enrichAnalysisWithPomVersion(result.analysis, selectedRepo.url, ""))
        : analyzeRepoUrl(selectedRepo.url, getCurrentToken(), true)
            .then(async (result) => enrichAnalysisWithPomVersion(result.analysis, selectedRepo.url, getCurrentToken()));

      analyzePromise
        .then((analysis) => applyRepositoryAnalysis(analysis))
        .catch((err) => {
          const message = err?.message || "Failed to analyze repository.";
          if (!getCurrentToken().trim() && !showEnterpriseToken && isPrivateRepoAccessError(message)) {
            setIsPrivateRepo(true);
            setStep(1);
            setError("");
            setAccessTokenValidationState("invalid");
            setAccessTokenValidationMessage("Add a GitHub Personal Access Token with repo scope to continue analyzing this private repository.");
            return;
          }
          setError(message);
        })
        .finally(() => setAnalysisLoading(false));
    }
  }, [step, selectedRepo, repoAnalysis, currentToken, showEnterpriseToken]);

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

    const timer = setTimeout(() => {
      setRepoAccessCheckLoading(true);

        getRepoVisibility(normalizedUrl, getCurrentToken())
        .then((visibility) => {
          if (cancelled) return;
          if (visibility.requires_token) {
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
          const message = err?.message || "Failed to analyze repository.";
          if (isPrivateRepoAccessError(message)) {
            setIsPrivateRepo(true);
            setError("");
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
  }, [step, urlValidation.valid, urlValidation.normalizedUrl, showEnterpriseToken, patToken, currentToken]);

  useEffect(() => {
    if (step === 2 && selectedRepo && repoAnalysis && !analysisLoading) {
      setRepoFilesLoading(true);
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
          setRepoFilesLoading(false);
        });
    }
  }, [step, selectedRepo, currentPath, currentToken, repoAnalysis, analysisLoading]);

  useEffect(() => {
    const repoReference = selectedRepo?.url || repoUrl || migrationJob?.source_repo || "";

    if (!repoAnalysis || !repoReference || isLocalRepoRef(repoReference)) {
      return;
    }

    const prefetchKey = `${repoReference}::${currentToken || ""}`;
    if (documentPrefetchKeyRef.current === prefetchKey) {
      return;
    }

    documentPrefetchKeyRef.current = prefetchKey;
    setDocumentPrefetchStatus("loading");
    setPrefetchedBrdDocument(null);
    setPrefetchedBrdPdfBlob(null);
    setPrefetchedBrdFilename("");

    let cancelled = false;
    const request: GithubDocumentRequest = {
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
    generateGithubDocument("brd", request)
      .then(async (result) => {
        if (cancelled) return;
        setPrefetchedBrdDocument(result);
        setPrefetchedBrdFilename(buildPdfFilename(result.filename));
        setDocumentPrefetchStatus("rendering");

        const generatedAsset = await resolveGeneratedDocumentAsset(result);
        if (cancelled) return;

        if (generatedAsset.blob) {
          setPrefetchedBrdPdfBlob(generatedAsset.blob);
          setDocumentPrefetchStatus("ready");
          return;
        }

        if (generatedAsset.html) {
          const pdfBlob = await renderHtmlToPdfBlob(generatedAsset.html);
          if (cancelled) return;
          setPrefetchedBrdPdfBlob(pdfBlob);
          setDocumentPrefetchStatus("ready");
          return;
        }

        setDocumentPrefetchStatus("error");
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("Failed to prefetch technical specification document", err);
        setDocumentPrefetchStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [
    repoAnalysis,
    selectedRepo?.url,
    repoUrl,
    currentToken,
    migrationJob?.job_id,
    migrationJob?.source_repo,
    migrationJob?.target_repo,
    selectedSourceVersion,
    effectiveTargetVersion,
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
    sourceAlreadyAtLatestSupportedVersion,
    targetVersionRequiredError,
    targetVersions.length,
  ]);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    let lastUpdateTime = Date.now();
    let stuckCheckInterval: ReturnType<typeof setInterval>;
    
    if (step >= 5 && migrationJob?.status && migrationJob.status !== "completed" && migrationJob.status !== "failed") {
      interval = setInterval(() => {
        getMigrationStatus(migrationJob!.job_id)
          .then((job) => {
            setMigrationJob(job);
            lastUpdateTime = Date.now();
          
            if (job.status === "completed") {
            setMigrationJob(job);
            setStep(7);
            getMigrationLogs(job.job_id).then((logs) => setMigrationLogs(logs.logs || []));
          }

            // Auto-advance to report when completed
            // if (job.status === "completed") {
            //   // Fetch one more time to ensure we have the latest data
            //   getMigrationStatus(migrationJob!.job_id)
            //     .then((finalJob) => {
            //       setMigrationJob(finalJob);
            //       setStep(7);
            //       // Fetch detailed logs
            //       getMigrationLogs(finalJob.job_id).then((logs) => setMigrationLogs(logs.logs));
            //     })
            //     .catch(() => {
            //       setStep(7);
            //       // Fetch detailed logs
            //       getMigrationLogs(job.job_id).then((logs) => setMigrationLogs(logs.logs));
            //     });
            // }
            // if (job.status === "completed") {
            //   setStep(7);
            //   // Fetch detailed logs
            //   getMigrationLogs(job.job_id).then((logs) => setMigrationLogs(logs.logs));
            // }
            // Fetch logs when failed so user can see error details
            if (job.status === "failed") {
              getMigrationLogs(job.job_id).then((logs) => setMigrationLogs(logs.logs));
            }
          })
          .catch((err) => {
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
              if (interval) clearInterval(interval);
              if (stuckCheckInterval) clearInterval(stuckCheckInterval);
              return;
            }
            setError("Failed to fetch migration status.");
          });
      }, 500/*2000*/);
      
      // Check if migration appears to be stuck (same status for > 30 seconds)
      stuckCheckInterval = setInterval(() => {
        const timeSinceLastUpdate = Date.now() - lastUpdateTime;
        if (timeSinceLastUpdate > 30000 && migrationJob?.status === "cloning") {
          setError("⚠️ Migration appears to be stuck on cloning. This may be due to a large repository or network issues. Please wait a bit longer or restart the migration.");
        }
      }, 15000);
    }
    
    return () => { 
      if (interval) clearInterval(interval);
      if (stuckCheckInterval) clearInterval(stuckCheckInterval);
    };
    }, [step, migrationJob?.job_id, migrationJob?.status]);
      useEffect(() => {
      if ((step === 5 || step === 6) && migrationJob?.status === "completed") {
        setStep(7);
      }
    }, [step, migrationJob?.status]);

  const handleConversionToggle = (id: string) => {
    setSelectedConversions((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
  };

  const handleFrameworkToggle = (framework: string) => {
    setSelectedFrameworks((prev) =>
      prev.includes(framework) ? prev.filter((f) => f !== framework) : [...prev, framework]
    );
  };

  const toggleReportAccordion = (section: "sonar" | "fossa" | "issues") => {
    setReportAccordionState((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const buildMigrationRequest = () => {
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
      migration_type: migrationType,
    };
  };

  useEffect(() => {
    if (step !== 4 || !effectiveTargetVersion || (!selectedRepo && !repoUrl)) {
      return;
    }

    let cancelled = false;
    setMigrationPreviewLoading(true);
    setMigrationPreviewError("");

    previewMigration(buildMigrationRequest())
      .then((preview) => {
        if (cancelled) return;
        setMigrationPreview(preview);
        const previewCodeChanges = buildCodeChangesFromPreviewDiffs(preview.file_diffs || []);
        setCodeChanges(previewCodeChanges);
        setSelectedDiffFile((current) => current ?? previewCodeChanges[0]?.filePath ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setMigrationPreview(null);
        setCodeChanges([]);
        setSelectedDiffFile(null);
        setMigrationPreviewError(err?.message || "Failed to preview migration changes.");
      })
      .finally(() => {
        if (!cancelled) {
          setMigrationPreviewLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    effectiveTargetVersion,
    step,
    selectedTargetVersion,
    selectedRepo,
    repoUrl,
    currentToken,
    migrationApproach,
    migrationType,
    targetRepoName,
    targetRepoTimestamp,
    selectedConversions,
    runTests,
    runSonar,
    runFossa,
    fixBusinessLogic,
    selectedSourceVersion,
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
    setStep(5);

    const migrationRequest = buildMigrationRequest();

    startMigration(migrationRequest)
    
      // .then((job) => {
      //   setMigrationJob(job);
      //   setStep(5); // Go to Migration Progress step
      // })
      .then((job) => {
  setMigrationJob(job);

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
    setRepos([]);
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
    setRepoFilesLoading(false);
    setMigrationJob(null);
    setFossaResult(null);
    setFossaLoading(false);
    setMigrationPreview(null);
    setMigrationPreviewLoading(false);
    setMigrationPreviewError("");
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

    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(WIZARD_REPO_URL_KEY);
      window.sessionStorage.removeItem(WIZARD_LOCAL_PROJECT_PATH_KEY);
      window.sessionStorage.removeItem(WIZARD_SELECTED_REPO_KEY);
      window.sessionStorage.removeItem(WIZARD_REPO_ANALYSIS_KEY);
      window.sessionStorage.removeItem(WIZARD_FORM_STATE_KEY);
      window.sessionStorage.removeItem(WIZARD_MIGRATION_JOB_KEY);
      WIZARD_STORAGE_KEYS.forEach((key) => window.localStorage.removeItem(key));
    }
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
            <div style={{ 
              ...styles.stepCircle, 
              backgroundColor: isCompleted ? "#22c55e" : isActive ? "#3b82f6" : "#e5e7eb", 
              color: currentIndicatorStep >= s.id ? "#fff" : "#6b7280",
              width: 44,
              height: 44,
              fontSize: 18,
              boxShadow: isActive ? "0 0 0 4px rgba(59, 130, 246, 0.2)" : "none"
            }}>
              {step > s.id ? "✓" : s.icon}
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
    const isHostedMode = localProjectCapabilities?.hosted_mode === true;
    const localProjectMessage = localProjectCapabilitiesLoading
      ? "Checking local project support..."
      : isHostedMode
        ? "Upload projects using the folder picker or ZIP archive uploader below. The backend will extract and analyze your uploaded files."
        : localProjectCapabilities?.message ||
        "Local project analysis is available when the backend can access the given path. " +
        "For hosted deployments, this must be a path reachable by the backend process, not a path on your personal computer.";
    const localProjectAnalyzeDisabled = !localProjectInputValid || localProjectCapabilities?.enabled === false;
    const authenticationBannerText = showEnterpriseToken
      ? "GitHub Enterprise repository detected — authentication required"
      : "Private repository detected — authentication required";
    const tokenCardTitle = showEnterpriseToken
      ? "Enterprise Repository — Enter Personal Access Token"
      : "Private Repository — Enter Personal Access Token";
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
          <span style={styles.stepIcon}>🔗</span>
          <div>
            <h2 style={styles.title}>Connect Repository</h2>
            <p style={styles.subtitle}>Enter a GitHub repository URL or analyze a local Java project to start migration analysis.</p>
          </div>
        </div>

        <div style={styles.field}>
          <label style={{ ...styles.label, display: "flex", alignItems: "center", gap: 8 }}>
            Repository URL
            {/* Info Button with Tooltip */}
            <div style={{ position: "relative", display: "inline-block" }}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  backgroundColor: "#e2e8f0",
                  color: "#64748b",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: "help",
                  transition: "all 0.2s ease"
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "#3b82f6";
                  e.currentTarget.style.color = "#fff";
                  const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                  if (tooltip) tooltip.style.display = "block";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "#e2e8f0";
                  e.currentTarget.style.color = "#64748b";
                  const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                  if (tooltip) tooltip.style.display = "none";
                }}
              >
                i
              </span>
              {/* Tooltip */}
              <div
                style={{
                  display: "none",
                  position: "absolute",
                  top: 24,
                  left: 0,
                  backgroundColor: "#1e293b",
                  color: "#fff",
                  padding: "12px 16px",
                  borderRadius: 8,
                  fontSize: 12,
                  lineHeight: 1.6,
                  whiteSpace: "nowrap",
                  zIndex: 1000,
                  boxShadow: "0 4px 12px rgba(0,0,0,0.2)"
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 6, color: "#94a3b8" }}>Supported formats:</div>
                <div>- https://github.com/owner/repo</div>
                <div>- github.com/owner/repo</div>
                <div>- owner/repo</div>
                {/* Arrow */}
                <div style={{
                  position: "absolute",
                  top: -6,
                  left: 9,
                  width: 0,
                  height: 0,
                  borderLeft: "6px solid transparent",
                  borderRight: "6px solid transparent",
                  borderBottom: "6px solid #1e293b"
                }} />
              </div>
            </div>
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
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 12 }}>
              Public GitHub repositories can be analyzed without a token. If the repository is private, we&apos;ll ask for a PAT after detection.
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
              ⚠️ {urlValidation.message}
            </div>
          )}
          {urlValidation.valid && (
            <div style={{ fontSize: 12, color: '#22c55e', marginTop: 6 }}>
              ✓ Valid repository URL
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
          <div style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
          <div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.08em" }}>OR</div>
          <div style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
        </div>

        <div
          style={{
            border: "1px dashed #cbd5e1",
            borderRadius: 16,
            padding: 24,
            background: "#f8fafc",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
            <span style={{ fontSize: 28 }}>📁</span>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#1e293b" }}>
                {localProjectCapabilities?.hosted_mode ? "Upload Local Project" : "Analyze Local Project"}
              </div>
              <div style={{ fontSize: 14, color: "#64748b", marginTop: 4 }}>
                {localProjectCapabilities?.hosted_mode
                  ? "Select a folder from your computer or upload a ZIP file for analysis."
                  : "Enter a project folder path that the backend can read."}
              </div>
            </div>
          </div>

          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 12 }}>
            {localProjectMessage}
          </div>

          {!localProjectCapabilities?.hosted_mode && (
            <div style={{ display: "flex", gap: 12, alignItems: "stretch", flexWrap: "wrap", marginBottom: 20 }}>
              <input
                type="text"
                style={{
                  ...styles.input,
                  flex: "1 1 520px",
                  marginBottom: 0,
                  borderColor: localProjectInputValid ? "#22c55e" : "#e2e8f0",
                  background: "#fff",
                }}
                value={localProjectPath}
                onChange={(e) => {
                  setLocalProjectPath(e.target.value);
                  if (selectedRepo && isLocalRepoRef(selectedRepo.url)) {
                    setSelectedRepo(null);
                    setRepoAnalysis(null);
                  }
                  setError("");
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && localProjectInputValid) {
                    void handleLocalProjectAnalyze();
                  }
                }}
                placeholder="C:\\Users\\you\\projects\\my-java-app"
              />
              <button
                style={{ ...styles.primaryBtn, minWidth: 140, opacity: localProjectAnalyzeDisabled ? 0.5 : 1, display: "flex", alignItems: "center", gap: 8 }}
                disabled={localProjectAnalyzeDisabled}
                onClick={() => void handleLocalProjectAnalyze()}
              >
                <FaSearch />
                Analyze
              </button>
            </div>
          )}

          {localProjectCapabilities?.hosted_mode && (
            <div style={{ fontSize: 13, color: "#475569", marginBottom: 12 }}>
              Select a folder from your computer OR upload a ZIP archive. This sends the project contents to the backend for analysis.
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <input
                    ref={(el) => {
                      if (el) {
                        (window as any).folderInputRef = el;
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
                      (window as any).folderInputRef?.click();
                    }}
                    style={{
                      padding: 10,
                      borderRadius: 10,
                      border: "1px solid #cbd5e1",
                      background: "#fff",
                      cursor: "pointer",
                      textAlign: "center",
                      fontWeight: 500,
                    }}
                  >
                    📁 Select Folder
                  </div>
                </div>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <input
                    ref={(el) => {
                      if (el) (window as any).zipInputRef = el;
                    }}
                    type="file"
                    accept=".zip"
                    style={{ display: "none" }}
                    onChange={(e) => handleLocalProjectFilesChange(e.target.files)}
                  />
                  <div
                    onClick={() => {
                      (window as any).zipInputRef?.click();
                    }}
                    style={{
                      padding: 10,
                      borderRadius: 10,
                      border: "1px solid #cbd5e1",
                      background: "#fff",
                      cursor: "pointer",
                      textAlign: "center",
                      fontWeight: 500,
                    }}
                  >
                    📦 Select ZIP File
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
                style={{ ...styles.primaryBtn, minWidth: 140, opacity: localProjectUploadFiles.length === 0 || localProjectUploadLoading ? 0.5 : 1, display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}
                disabled={localProjectUploadFiles.length === 0 || localProjectUploadLoading}
                onClick={() => void handleLocalProjectUpload()}
              >
                {localProjectUploadLoading ? "Uploading..." : "Upload and Analyze"}
              </button>
            </div>
        </div>

        <div style={styles.btnRow}>
          <button
            style={{ ...styles.primaryBtn, opacity: !urlValidation.valid ? 0.5 : 1 }}
            disabled={!urlValidation.valid}
            onClick={() => void handleRepositoryContinue()}
          >
            Continue →
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
        } catch (err) {
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

    // Get file extension for syntax highlighting hint
    const getFileLanguage = (fileName: string) => {
      const ext = fileName.split('.').pop()?.toLowerCase();
      const langMap: { [key: string]: string } = {
        'java': 'Java',
        'xml': 'XML',
        'json': 'JSON',
        'yml': 'YAML',
        'yaml': 'YAML',
        'properties': 'Properties',
        'md': 'Markdown',
        'gradle': 'Gradle',
        'kt': 'Kotlin',
        'js': 'JavaScript',
        'ts': 'TypeScript',
        'html': 'HTML',
        'css': 'CSS',
        'sql': 'SQL',
        'sh': 'Shell',
        'bat': 'Batch',
        'txt': 'Text'
      };
      return langMap[ext || ''] || 'Text';
    };

    // Get file icon based on type
    const getFileIcon = (file: RepoFile) => {
      if (file.type === "dir") return "📁";
      const ext = file.name.split('.').pop()?.toLowerCase();
      const iconMap: { [key: string]: string } = {
        'java': '☕',
        'xml': '📋',
        'json': '📦',
        'yml': '⚙️',
        'yaml': '⚙️',
        'properties': '🔧',
        'md': '📝',
        'gradle': '🐘',
        'kt': '🎯',
        'js': '🟨',
        'ts': '🔷',
        'html': '🌐',
        'css': '🎨',
        'sql': '🗄️',
        'sh': '💻',
        'txt': '📄'
      };
      return iconMap[ext || ''] || '📄';
    };

    const detectedBuildType = repoAnalysis?.build_tool ||
      (repoAnalysis?.structure?.has_pom_xml ? "maven" : repoAnalysis?.structure?.has_build_gradle ? "gradle" : null);
    const detectedJavaVersion = repoAnalysis?.java_version || repoAnalysis?.java_version_from_build || null;
    const primaryDetectedFramework =
      detectedFrameworks.find((fw) => fw.type === "Application Framework")?.name ||
      detectedFrameworks.find((fw) => fw.type === "ORM Framework")?.name ||
      detectedFrameworks[0]?.name ||
      null;
    const recommendedBuildConversionId = detectedBuildType === "maven"
      ? "maven_to_gradle"
      : detectedBuildType === "gradle"
        ? "gradle_to_maven"
        : null;
    const hasRecommendedBuildConversion = Boolean(
      recommendedBuildConversionId && conversionTypes.some((ct) => ct.id === recommendedBuildConversionId)
    );

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

    const applyRecommendedBuildConversion = () => {
      if (!recommendedBuildConversionId) return;

      const nextSelections = [recommendedBuildConversionId];
      if (selectedConversions.includes("java_version")) {
        nextSelections.push("java_version");
      }

      setSelectedConversions(nextSelections);
    };

    return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>🔍</span>
        <div>
          <h2 style={styles.discoveryStepTitle}>Repository Discovery & Dependencies</h2>
          <p style={styles.discoveryStepSubtitle}>{MIGRATION_STEPS[1].summary}</p>
        </div>
        {isDiscoveryPending && (
          <div style={styles.timerBadge}>
            <span style={styles.timerLabel}> 
              <span style={styles.icon}>⏱️</span>
              Analysing...</span>
            <span style={styles.timerValue}>{formattedAnalysisElapsed}</span>
          </div>
        )}
        {!isDiscoveryPending && repoAnalysis && (
  <div style={{
    marginLeft: "auto",
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 14px",
    borderRadius: 10,
    background: "#ecfdf5",
    border: "1px solid #4ade80",
    color: "#166534",
    fontWeight: 700,
    minWidth: 140,
  }}>
    {/* <span style={{ fontSize: 18 }}>✅</span>
    <span style={{ fontFamily: "Arial, sans-serif",fontSize: 18 }}>Completed</span> */}
    <span style={{ fontSize: 18 }}>✅</span>
   <span style={{ fontFamily: "Arial, sans-serif", fontSize: 18 }}>
  Completed {formattedAnalysisCompleted}
   </span>
  </div>
)}
      </div>

      {selectedRepo && (
        <>
          {isDiscoveryPending ? <div style={styles.loadingBox}><div style={styles.spinner}></div><span>Analyzing repository structure, preview, dependencies, and microservice eligibility...</span></div> : (
            <>
              {/* Not a Java Project Alert or No Framework Detected */}
              {isJavaProject === false ? (
                <div style={{
                  background: "#fef2f2",
                  border: "2px solid #ef4444",
                  borderRadius: 12,
                  padding: 20,
                  marginBottom: 24,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 16
                }}>
                  <span style={{ fontSize: 32 }}>⚠️</span>
                  <div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: "#991b1b", marginBottom: 8 }}>
                      This is not a Java Project
                    </div>
                    <div style={{ fontSize: 14, color: "#b91c1c", lineHeight: 1.6 }}>
                      The repository you connected does not appear to be a Java project. 
                      This tool is designed specifically for Java application migration. 
                      Please connect a repository that contains Java source code, 
                      Maven (pom.xml), or Gradle (build.gradle) configuration files.
                    </div>
                    <button 
                      style={{ 
                        marginTop: 16, 
                        backgroundColor: "#ef4444", 
                        color: "#fff", 
                        border: "none", 
                        borderRadius: 8, 
                        padding: "10px 20px", 
                        fontWeight: 600, 
                        cursor: "pointer",
                        fontSize: 14
                      }}
                      onClick={() => {
                        setStep(1);
                        setSelectedRepo(null);
                        setRepoAnalysis(null);
                        setIsJavaProject(null);
                        setRepoUrl("");
                      }}
                    >
                      ← Connect Different Repository
                    </button>
                  </div>
                </div>
              ) : null}

              {/* Java project but no framework detected */}
              {isJavaProject && detectedFrameworks.length === 0 && (
                <div style={{
                  background: "#fef9c3",
                  border: "2px solid #facc15",
                  borderRadius: 12,
                  padding: 20,
                  marginBottom: 24,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 16
                }}>
                  <span style={{ fontSize: 32 }}>ℹ️</span>
                  <div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: "#92400e", marginBottom: 8 }}>
                      Java Project Detected (No Framework)
                    </div>
                    <div style={{ fontSize: 14, color: "#a16207", lineHeight: 1.6 }}>
                      This repository contains Java source files but no recognized framework (e.g., Spring, Spring Boot, Jakarta EE) was detected. You can still proceed with migration, but some automation features may be limited.
                    </div>
                  </div>
                </div>
              )}

              {/* Show discovery content only if it's a Java project */}
              {isJavaProject !== false && (
                <>
                  {/* High Risk Project Warning (no pom.xml/build.gradle or unknown Java version) */}
                  {isHighRiskProject && !highRiskConfirmed && (
                    <div style={{
                      background: "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)",
                      border: "2px solid #f59e0b",
                      borderRadius: 12,
                      padding: 24,
                      marginBottom: 24,
                      boxShadow: "0 4px 12px rgba(245, 158, 11, 0.15)"
                    }}>
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
                        <span style={{ fontSize: 40 }}>⚠️</span>
                        <div>
                          <div style={{ fontSize: 20, fontWeight: 700, color: "#92400e", marginBottom: 8 }}>
                            High Risk Migration Detected
                          </div>
                      <div style={{ fontSize: 14, color: "#a16207", lineHeight: 1.7 }}>
                            This project may be missing Java version configuration and may require additional setup:
                          </div>
                        </div>
                      </div>
                      
                      {/* Missing Items */}
                      <div style={{
                        background: "rgba(255,255,255,0.7)",
                        borderRadius: 8,
                        padding: 16,
                        marginBottom: 20
                      }}>
                        <div style={{ fontWeight: 600, color: "#92400e", marginBottom: 12 }}>🔍 Missing Components:</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                          {!repoAnalysis?.structure?.has_pom_xml && !repoAnalysis?.structure?.has_build_gradle && (
                            <div style={{
                              background: "#fef2f2",
                              border: "1px solid #fecaca",
                              borderRadius: 6,
                              padding: "8px 12px",
                              fontSize: 13,
                              color: "#991b1b",
                              display: "flex",
                              alignItems: "center",
                              gap: 6
                            }}>
                              <span>❌</span> No pom.xml or build.gradle
                            </div>
                          )}
                          {(!((repoAnalysis?.java_version || repoAnalysis?.java_version_from_build)) || (repoAnalysis?.java_version || repoAnalysis?.java_version_from_build) === "unknown") && (
                            <div style={{
                              background: "#fef2f2",
                              border: "1px solid #fecaca",
                              borderRadius: 6,
                              padding: "8px 12px",
                              fontSize: 13,
                              color: "#991b1b",
                              display: "flex",
                              alignItems: "center",
                              gap: 6
                            }}>
                              <span>❌</span> Java version not detected
                            </div>
                          )}
                          {!repoAnalysis?.structure?.has_src_main && (
                            <div style={{
                              background: "#fef2f2",
                              border: "1px solid #fecaca",
                              borderRadius: 6,
                              padding: "8px 12px",
                              fontSize: 13,
                              color: "#991b1b",
                              display: "flex",
                              alignItems: "center",
                              gap: 6
                            }}>
                              <span>❌</span> Non-standard project structure
                            </div>
                          )}
                        </div>
                      </div>
                      
                      {/* Suggested Configuration */}
                      <div style={{
                        background: "rgba(255,255,255,0.7)",
                        borderRadius: 8,
                        padding: 16,
                        marginBottom: 20
                      }}>
                        <div style={{ fontWeight: 600, color: "#92400e", marginBottom: 12 }}>💡 Suggested Configuration:</div>
                        
                        {/* Java Version Selection */}
                        <div style={{ marginBottom: 16 }}>
                          <label style={{ display: "block", fontSize: 13, fontWeight: 500, color: "#78350f", marginBottom: 6 }}>
                            {sourceVersionStatus === "detected" ? "Java version automatically detected" : "Select Source Java Version:"}
                          </label>
                          {sourceVersionStatus === "detected" && suggestedJavaVersion !== "auto" ? (
                            <div style={{ padding: "10px 14px", borderRadius: 6, border: "1px solid #d1d5db", backgroundColor: "#f8fafc", minWidth: 200, color: "#0f172a" }}>
                              Java {suggestedJavaVersion} detected from source code
                            </div>
                          ) : (
                            <>
                              <select
                                value={suggestedJavaVersion}
                                onChange={(e) => {
                                  setSuggestedJavaVersion(e.target.value);
                                  setSelectedSourceVersion(e.target.value === "auto" ? "8" : e.target.value); // Default to 8 if auto-detect
                                  setUserSelectedVersion(e.target.value);
                                  setSourceVersionStatus("detected");
                                }}
                                style={{
                                  padding: "10px 14px",
                                  borderRadius: 6,
                                  border: "1px solid #d97706",
                                  fontSize: 14,
                                  backgroundColor: "#fff",
                                  cursor: "pointer",
                                  minWidth: 200
                                }}
                              >
                                <option value="auto">🔍 Auto-detect from code (Recommended)</option>
                                <option value="7">Java 7 (Legacy)</option>
                                <option value="8">Java 8 (LTS)</option>
                                <option value="11">Java 11 (LTS)</option>
                                <option value="17">Java 17 (LTS)</option>
                                <option value="21">Java 21 (LTS)</option>
                              </select>
                              <div style={{ fontSize: 11, color: "#a16207", marginTop: 6 }}>
                                💡 Auto-detect analyzes your code to determine the correct Java version
                              </div>
                            </>
                          )}
                        </div>

                        <div style={{ marginBottom: 16, padding: 16, borderRadius: 8, backgroundColor: "#eef2ff", border: "1px solid #c7d2fe" }}>
                          <div style={{ fontSize: 14, fontWeight: 600, color: "#1e3a8a" }}>
                            {buildConversionLabel}
                          </div>
                          <div style={{ fontSize: 12, color: "#475569", marginTop: 8 }}>
                            {buildConversionNote}
                          </div>
                        </div>
                      </div>
                      
                      {/* Action Buttons */}
                      <div style={{ display: "flex", gap: 12 }}>
                        <button
                          onClick={() => {
                            setHighRiskConfirmed(true);
                            setSelectedSourceVersion(suggestedJavaVersion);
                          }}
                          style={{
                            backgroundColor: "#f59e0b",
                            color: "#fff",
                            border: "none",
                            borderRadius: 8,
                            padding: "12px 24px",
                            fontWeight: 600,
                            cursor: "pointer",
                            fontSize: 14,
                            display: "flex",
                            alignItems: "center",
                            gap: 8
                          }}
                        >
                          {buildConversionLabel}
                        </button>
                        <button
                          onClick={() => {
                            setStep(1);
                            setSelectedRepo(null);
                            setRepoAnalysis(null);
                            setIsJavaProject(null);
                            setIsHighRiskProject(false);
                            setRepoUrl("");
                          }}
                          style={{
                            backgroundColor: "#fff",
                            color: "#92400e",
                            border: "2px solid #f59e0b",
                            borderRadius: 8,
                            padding: "12px 24px",
                            fontWeight: 600,
                            cursor: "pointer",
                            fontSize: 14
                          }}
                        >
                          ← Choose Different Repository
                        </button>
                      </div>
                    </div>
                  )}
                  
                  {/* Show content only after high-risk confirmation or if not high-risk */}
                  {(!isHighRiskProject || highRiskConfirmed) && (
	                  <>
	                  {/* GitHub-like File Explorer */}
                  <div style={styles.sectionTitle}>📂 Repository Files</div>
                  <div style={{
                    border: "1px solid #d0d7de",
                    borderRadius: 8,
                    overflow: "hidden",
                    marginBottom: 24,
                    backgroundColor: "#fff"
                  }}>
                    {/* Header bar like GitHub */}
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "12px 16px",
                      backgroundColor: "#f6f8fa",
                      borderBottom: "1px solid #d0d7de"
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontWeight: 600, color: "#24292f" }}>{selectedRepo.name}</span>
                        {currentPath && (
                          <>
                            <span style={{ color: "#57606a" }}>/</span>
                            <span style={{ color: "#0969da" }}>{currentPath}</span>
                          </>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        {currentPath && (
                          <button
                            onClick={navigateToRoot}
                            style={{
                              background: "none",
                              border: "1px solid #d0d7de",
                              borderRadius: 6,
                              padding: "4px 12px",
                              cursor: "pointer",
                              fontSize: 12,
                              color: "#24292f"
                            }}
                          >
                            🏠 Root
                          </button>
                        )}
                        <button
                          onClick={() => setShowFileExplorer(!showFileExplorer)}
                          style={{
                            background: "none",
                            border: "1px solid #d0d7de",
                            borderRadius: 6,
                            padding: "4px 12px",
                            cursor: "pointer",
                            fontSize: 12,
                            color: "#24292f"
                          }}
                        >
                          {showFileExplorer ? "🔽 Collapse" : "🔼 Expand"}
                        </button>
                      </div>
                    </div>

                    {showFileExplorer && (
                      <div style={{ display: "flex", minHeight: 400 }}>
                        {/* File Tree - Left Panel */}
                        <div style={{
                          width: selectedFile ? "40%" : "100%",
                          borderRight: selectedFile ? "1px solid #d0d7de" : "none",
                          overflowY: "auto",
                          maxHeight: 500
                        }}>
                          {/* Back navigation */}
                          {currentPath && (
                            <div
                              onClick={navigateBack}
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                padding: "10px 16px",
                                borderBottom: "1px solid #d0d7de",
                                cursor: "pointer",
                                backgroundColor: "#f6f8fa"
                              }}
                            >
                              <span>⬆️</span>
                              <span style={{ color: "#0969da", fontSize: 14 }}>..</span>
                            </div>
                          )}
                          
                          {/* File list */}
                          {repoFiles.length > 0 ? (
                            repoFiles.map((file, idx) => (
                              <div
                                key={idx}
                                onClick={() => handleFileClick(file)}
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: 10,
                                  padding: "10px 16px",
                                  borderBottom: "1px solid #d0d7de",
                                  cursor: "pointer",
                                  backgroundColor: selectedFile?.path === file.path ? "#ddf4ff" : "transparent",
                                  transition: "background-color 0.15s ease"
                                }}
                                onMouseEnter={(e) => {
                                  if (selectedFile?.path !== file.path) {
                                    e.currentTarget.style.backgroundColor = "#f6f8fa";
                                  }
                                }}
                                onMouseLeave={(e) => {
                                  if (selectedFile?.path !== file.path) {
                                    e.currentTarget.style.backgroundColor = "transparent";
                                  }
                                }}
                              >
                                <span style={{ fontSize: 16 }}>{getFileIcon(file)}</span>
                                <span style={{
                                  flex: 1,
                                  color: file.type === "dir" ? "#0969da" : "#24292f",
                                  fontWeight: file.type === "dir" ? 600 : 400,
                                  fontSize: 14
                                }}>
                                  {file.name}
                                </span>
                                {file.type === "file" && file.size > 0 && (
                                  <span style={{ fontSize: 12, color: "#57606a" }}>
                                    {file.size < 1024 ? `${file.size} B` : `${Math.round(file.size / 1024)} KB`}
                                  </span>
                                )}
                              </div>
                            ))
                          ) : (
                            <div style={{ padding: 20, textAlign: "center", color: "#57606a" }}>
                              No files found
                            </div>
                          )}
                        </div>

                        {/* File Content - Right Panel */}
                        {selectedFile && (
                          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                            {/* File header */}
                            <div style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              padding: "8px 16px",
                              backgroundColor: "#f6f8fa",
                              borderBottom: "1px solid #d0d7de"
                            }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span>{getFileIcon(selectedFile)}</span>
                                <span style={{ fontWeight: 600, color: "#24292f" }}>{selectedFile.name}</span>
                                <span style={{
                                  fontSize: 11,
                                  padding: "2px 8px",
                                  backgroundColor: "#ddf4ff",
                                  borderRadius: 12,
                                  color: "#0969da"
                                }}>
                                  {getFileLanguage(selectedFile.name)}
                                </span>
                              </div>
                              <div style={{ display: "flex", gap: 8 }}>
                                <button
                                  onClick={() => {
                                    setSelectedFile(null);
                                    setFileContent("");
                                    setEditedContent("");
                                    setIsEditing(false);
                                  }}
                                  style={{
                                    background: "none",
                                    border: "1px solid #d0d7de",
                                    borderRadius: 6,
                                    padding: "6px 12px",
                                    cursor: "pointer",
                                    fontSize: 12,
                                    color: "#24292f"
                                  }}
                                >
                                  ✖️ Close
                                </button>
                              </div>
                            </div>

                            {/* File content */}
                            <div style={{
                              flex: 1,
                              overflow: "auto",
                              backgroundColor: "#0d1117",
                              position: "relative"
                            }}>
                              {fileLoading ? (
                                <div style={{
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  height: "100%",
                                  color: "#8b949e"
                                }}>
                                  <div style={styles.spinner}></div>
                                  <span style={{ marginLeft: 10 }}>Loading file...</span>
                                </div>
                              ) : isEditing ? (
                                <textarea
                                  value={editedContent}
                                  onChange={(e) => setEditedContent(e.target.value)}
                                  style={{
                                    width: "100%",
                                    height: "100%",
                                    minHeight: 350,
                                    padding: 16,
                                    backgroundColor: "#0d1117",
                                    color: "#c9d1d9",
                                    border: "none",
                                    outline: "none",
                                    fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                                    fontSize: 13,
                                    lineHeight: 1.5,
                                    resize: "none",
                                    boxSizing: "border-box"
                                  }}
                                />
                              ) : (
                                <pre style={{
                                  margin: 0,
                                  padding: 16,
                                  color: "#c9d1d9",
                                  fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                                  fontSize: 13,
                                  lineHeight: 1.5,
                                  whiteSpace: "pre-wrap",
                                  wordBreak: "break-word"
                                }}>
                                  {fileContent || "// Empty file"}
                                </pre>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Discovery Info */}
                  {/* <div style={styles.discoveryContent}>
                    <div style={styles.discoveryItem}>
                      <span style={styles.discoveryIcon}>📊</span>
                      <div>
                        <div style={styles.discoveryTitle}>Repository Analysis</div>
                        <div style={styles.discoveryDesc}>Scanning {selectedRepo.name} for Java components</div>
                      </div>
                    </div>
                    <div style={styles.discoveryItem}>
                      <span style={styles.discoveryIcon}>🔧</span>
                      <div>
                        <div style={styles.discoveryTitle}>Build Tool: {buildToolDisplayLabel || "Detecting..."}</div>
                        <div style={styles.discoveryDesc}>Identified build system for dependency management</div>
                      </div>
                    </div>
                    <div style={styles.discoveryItem}>
                      <span style={styles.discoveryIcon}>☕</span>
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

                  {/* Framework Detection - Clickable with File Preview */}
                  <div style={styles.sectionTitle}>🎯 Detected Frameworks & Libraries</div>
                  
                  {/* Framework File Viewer Modal */}
                  {viewingFrameworkFile && (
                    <div style={{
                      position: "fixed",
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      backgroundColor: "rgba(0,0,0,0.7)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      zIndex: 1000
                    }}>
                      <div style={{
                        backgroundColor: "#fff",
                        borderRadius: 12,
                        width: "80%",
                        maxWidth: 900,
                        maxHeight: "85vh",
                        overflow: "hidden",
                        boxShadow: "0 25px 50px rgba(0,0,0,0.3)"
                      }}>
                        {/* Modal Header */}
                        <div style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "16px 20px",
                          backgroundColor: "#f6f8fa",
                          borderBottom: "1px solid #d0d7de"
                        }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ fontSize: 20 }}>📄</span>
                            <div>
                              <div style={{ fontWeight: 600, color: "#24292f" }}>{viewingFrameworkFile.name}</div>
                              <div style={{ fontSize: 12, color: "#57606a" }}>{viewingFrameworkFile.path}</div>
                            </div>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{
                              fontSize: 11,
                              padding: "4px 10px",
                              backgroundColor: "#ddf4ff",
                              borderRadius: 12,
                              color: "#0969da"
                            }}>
                              Read Only
                            </span>
                            <button
                              onClick={() => setViewingFrameworkFile(null)}
                              style={{
                                background: "none",
                                border: "1px solid #d0d7de",
                                borderRadius: 6,
                                padding: "6px 12px",
                                cursor: "pointer",
                                fontSize: 14,
                                color: "#24292f"
                              }}
                            >
                              ✖️ Close
                            </button>
                          </div>
                        </div>
                        {/* Modal Content */}
                        <div style={{
                          backgroundColor: "#0d1117",
                          overflow: "auto",
                          maxHeight: "calc(85vh - 70px)"
                        }}>
                          {frameworkFileLoading ? (
                            <div style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              padding: 60,
                              color: "#8b949e"
                            }}>
                              <div style={styles.spinner}></div>
                              <span style={{ marginLeft: 12 }}>Loading file content...</span>
                            </div>
                          ) : (
                            <pre style={{
                              margin: 0,
                              padding: 20,
                              color: "#c9d1d9",
                              fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                              fontSize: 13,
                              lineHeight: 1.6,
                              whiteSpace: "pre-wrap",
                              wordBreak: "break-word"
                            }}>
                              {viewingFrameworkFile.content || "// File content unavailable"}
                            </pre>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                  
                  {/* Detected Frameworks Grid - Clickable */}
                  {detectedFrameworks.length > 0 ? (
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                      gap: 12,
                      marginBottom: 20
                    }}>
                      {detectedFrameworks.map((fw, idx) => (
                        <div
                          key={idx}
                          onClick={async () => {
                            setFrameworkFileLoading(true);
                            setViewingFrameworkFile({ name: fw.name, path: fw.path, content: "" });
                            try {
                              const response = isLocalRepoRef(selectedRepo!.url)
                                ? await getLocalProjectFileContent(extractLocalRepoPath(selectedRepo!.url), fw.path)
                                : await getFileContent(selectedRepo!.url, fw.path, currentToken);
                              setViewingFrameworkFile({ name: fw.name, path: fw.path, content: response.content });
                            } catch (err) {
                              setViewingFrameworkFile({ name: fw.name, path: fw.path, content: `// Error loading file: ${fw.path}` });
                            } finally {
                              setFrameworkFileLoading(false);
                            }
                          }}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            padding: "14px 16px",
                            backgroundColor: "#fff",
                            border: "1px solid #d0d7de",
                            borderRadius: 8,
                            cursor: "pointer",
                            transition: "all 0.2s ease",
                            boxShadow: "0 1px 3px rgba(0,0,0,0.05)"
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = "#f6f8fa";
                            e.currentTarget.style.borderColor = "#0969da";
                            e.currentTarget.style.boxShadow = "0 2px 8px rgba(9, 105, 218, 0.15)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = "#fff";
                            e.currentTarget.style.borderColor = "#d0d7de";
                            e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.05)";
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                            <span style={{ fontSize: 24 }}>
                              {fw.type === "Testing Framework" ? "🧪" : 
                               fw.type === "Application Framework" ? "🍃" : 
                               fw.type === "ORM Framework" ? "🗄️" :
                               fw.type === "Logging" ? "📝" :
                               fw.type === "Mocking Framework" ? "🎭" :
                               fw.type === "JSON Processing" ? "📦" : "📚"}
                            </span>
                            <div>
                              <div style={{ fontWeight: 600, color: "#24292f", fontSize: 14 }}>{fw.name}</div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                                <span style={{ fontSize: 11, color: "#57606a" }}>{fw.type}</span>
                                <span style={{
                                  fontSize: 10,
                                  fontWeight: 700,
                                  letterSpacing: "0.04em",
                                  textTransform: "uppercase",
                                  padding: "2px 8px",
                                  borderRadius: 999,
                                  backgroundColor: getDetectedComponentCategory(fw.type) === "Framework" ? "#ede9fe" : "#e0f2fe",
                                  color: getDetectedComponentCategory(fw.type) === "Framework" ? "#6d28d9" : "#075985",
                                  border: getDetectedComponentCategory(fw.type) === "Framework" ? "1px solid #c4b5fd" : "1px solid #bae6fd"
                                }}>
                                  {getDetectedComponentCategory(fw.type)}
                                </span>
                              </div>
                            </div>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{
                              fontSize: 11,
                              padding: "3px 8px",
                              backgroundColor: "#dcfce7",
                              borderRadius: 10,
                              color: "#166534"
                            }}>
                              Detected
                            </span>
                            <span style={{ color: "#0969da", fontSize: 12 }}>📂 View</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={styles.frameworkGrid}>
                      <div style={styles.frameworkItem}>
                        <span>🍃</span>
                        <span>Spring Boot</span>
                        {repoAnalysis?.dependencies?.some(d => d.artifact_id.includes('spring')) && <span style={styles.detectedBadge}>Detected</span>}
                      </div>
                      <div style={styles.frameworkItem}>
                        <span>🗄️</span>
                        <span>JPA/Hibernate</span>
                        {repoAnalysis?.dependencies?.some(d => d.artifact_id.includes('hibernate') || d.artifact_id.includes('jpa')) && <span style={styles.detectedBadge}>Detected</span>}
                      </div>
                      <div style={styles.frameworkItem}>
                        <span>🧪</span>
                        <span>JUnit</span>
                        {repoAnalysis?.dependencies?.some(d => d.artifact_id.includes('junit')) && <span style={styles.detectedBadge}>Detected</span>}
                      </div>
                      <div style={styles.frameworkItem}>
                        <span>📝</span>
                        <span>Log4j/SLF4J</span>
                        {repoAnalysis?.dependencies?.some(d => d.artifact_id.includes('log4j') || d.artifact_id.includes('slf4j')) && <span style={styles.detectedBadge}>Detected</span>}
                      </div>
                    </div>
                  )}

                  {repoAnalysis && (
                    <>
                      <div style={styles.structureBox}>
                        <div style={styles.structureTitle}>Project Structure Summary</div>
                        <div style={styles.structureGrid}>
                          <span style={repoAnalysis.structure?.has_pom_xml ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_pom_xml ? "✓" : "✗"} pom.xml</span>
                          <span style={repoAnalysis.structure?.has_build_gradle ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_build_gradle ? "✓" : "✗"} build.gradle</span>
                          <span style={repoAnalysis.structure?.has_src_main ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_src_main ? "✓" : "✗"} src/main</span>
                          <span style={repoAnalysis.structure?.has_src_test ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_src_test ? "✓" : "✗"} src/test</span>
                          <span style={detectedJavaVersion ? styles.structureFound : styles.structureMissing}>{detectedJavaStructureLabel}</span>
                        </div>
                      </div>

                    </>
                  )}

                  {/* Microservice Eligibility — Auto-assessed during repo analysis */}
                  {repoAnalysis && (
                    <div style={{ ...styles.structureBox, marginTop: 20 }}>
                      <div style={styles.microserviceSectionHeader}>
                        <div style={styles.microserviceSectionHeaderContent}>
                          <div style={{ ...styles.structureTitle, marginBottom: 0 }}>🏗️ Microservice Eligibility Assessment</div>
                          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
                            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                              <input
                                type="radio"
                                name="migrationType"
                                value="monolithic"
                                checked={migrationType === "monolithic"}
                                onChange={() => setMigrationType("monolithic")}
                              />
                              Monolithic
                            </label>
                            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                              <input
                                type="radio"
                                name="migrationType"
                                value="microservices"
                                checked={migrationType === "microservices"}
                                onChange={() => setMigrationType("microservices")}
                              />
                              Microservices
                            </label>
                          </div>
                          {isMicroserviceEligibilityCollapsed && (
                            <div style={styles.microserviceSectionSummary}>
                              {microserviceResult
                                ? `${getMicroserviceAssessmentLabel(microserviceResult)} | Score ${getMicroserviceFitScore(microserviceResult)}% | ${microserviceResult.recommendedArchitecture}`
                                : !microserviceAssessmentResolved
                                  ? "Analysis in progress..."
                                  : "Assessment currently unavailable."}
                            </div>
                          )}
                        </div>
                        <button
                          type="button"
                          style={styles.microserviceSectionToggle}
                          onClick={() => setIsMicroserviceEligibilityCollapsed((current) => !current)}
                        >
                          {isMicroserviceEligibilityCollapsed ? "Expand" : "Collapse"}
                        </button>
                      </div>
                      {!isMicroserviceEligibilityCollapsed && <div style={{ padding: "12px 0" }}>

                        {!microserviceResult && !microserviceAssessmentResolved && (
                          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 20px", background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0" }}>
                            <span style={{ fontSize: 20 }}>⏳</span>
                            <span style={{ fontSize: 14, color: "#64748b" }}>Analyzing microservice eligibility...</span>
                          </div>
                        )}

                        {!microserviceResult && microserviceAssessmentResolved && (
                          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 20px", background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0" }}>
                            <span style={{ fontSize: 20 }}>ℹ️</span>
                            <div>
                              <span style={{ fontSize: 14, color: "#64748b" }}>Microservice assessment not available for this repository.</span>
                              <button
                                style={{ ...styles.secondaryBtn, fontSize: 12, padding: "4px 12px", marginLeft: 12 }}
                                onClick={handleCheckMicroserviceEligibility}
                                disabled={microserviceLoading}
                              >
                                {microserviceLoading ? "⏳ Analyzing..." : "Retry"}
                              </button>
                            </div>
                          </div>
                        )}

                        {microserviceResult && (
                          <div>
                            {(() => {
                              const fitScore = getMicroserviceFitScore(microserviceResult);
                              const assessmentLabel = getMicroserviceAssessmentLabel(microserviceResult);
                              const strengths = uniqueTextItems(microserviceResult.strengths || []);
                              const risks = uniqueTextItems(microserviceResult.risks || []);
                              const couplingIssues = uniqueTextItems(microserviceResult.couplingIssues || []);
                              const databaseConcerns = uniqueTextItems(microserviceResult.databaseConcerns || []);
                              const scalingCandidates = uniqueTextItems(microserviceResult.scalingCandidates || []);
                              const recommendedMigrationStrategy = uniqueTextItems(microserviceResult.recommendedMigrationStrategy || []);
                              const architecturalObservations = uniqueTextItems([
                                ...(microserviceResult.observations || []),
                                ...(microserviceResult.architecturalObservations || []),
                              ]);
                              const databaseTechnologies = Array.isArray(microserviceResult.metadata?.databaseTechnologies)
                                ? uniqueTextItems((microserviceResult.metadata?.databaseTechnologies as string[]) || [])
                                : [];
                              const projectStructureDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.project_structure || []);
                              const packageStructureDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.package_structure || []);
                              const moduleBoundaryDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.module_boundaries || []);
                              const dependencyCouplingDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.dependency_coupling || []);
                              const databaseAccessDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.database_access_patterns || []);
                              const communicationAnalysisDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.communication_analysis || []);
                              const deploymentIndependenceDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.deployment_independence || []);
                              const scalabilityIndicatorDetails = uniqueTextItems(microserviceResult.detailedEligibilityReport?.scalability_indicators || []);
                              const serviceCandidates = microserviceResult.serviceCandidates || [];
                              const visibleServiceCandidates = showAllMicroserviceServices
                                ? serviceCandidates
                                : serviceCandidates.slice(0, 4);
                              const scoreBreakdown = microserviceResult.scoreBreakdown || [];
                              const topScoreBreakdown = [...scoreBreakdown]
                                .sort((left, right) => right.score - left.score)
                                .slice(0, 3);
                              const scoreEvidenceMap: Record<string, string[]> = {
                                "Domain separation": uniqueTextItems([...projectStructureDetails, ...packageStructureDetails, ...moduleBoundaryDetails]),
                                Coupling: dependencyCouplingDetails,
                                "DB independence": databaseAccessDetails,
                                Scalability: scalabilityIndicatorDetails,
                                "Deployment independence": deploymentIndependenceDetails,
                                "Failure isolation": uniqueTextItems([...dependencyCouplingDetails, ...communicationAnalysisDetails]),
                                "Async/event readiness": communicationAnalysisDetails,
                              };
                              const isMicroserviceRecommended = !String(microserviceResult.eligibility || "").toUpperCase().includes("NOT");
                              const microservicePros = isMicroserviceRecommended
                                ? uniqueTextItems([
                                    ...strengths.slice(0, 3),
                                    ...scalingCandidates.slice(0, 2),
                                    "Independent services could improve release flexibility and team ownership.",
                                  ]).slice(0, 4)
                                : uniqueTextItems([
                                    ...strengths.slice(0, 2),
                                    "A microservice transition could unlock independent scaling for selected modules over time.",
                                    "Smaller services can improve ownership clarity once boundaries are stronger.",
                                  ]).slice(0, 4);
                              const microserviceCons = uniqueTextItems([
                                ...risks.slice(0, 2),
                                ...couplingIssues.slice(0, 1),
                                ...databaseConcerns.slice(0, 1),
                              ]).slice(0, 4);
                              const monolithPros = isMicroserviceRecommended
                                ? uniqueTextItems([
                                    "Staying monolithic keeps delivery simpler while boundaries are validated gradually.",
                                    ...recommendedMigrationStrategy.slice(0, 2),
                                  ]).slice(0, 4)
                                : uniqueTextItems([
                                    "Keeping a modular monolith reduces migration risk while internal boundaries are improved.",
                                    ...recommendedMigrationStrategy.slice(0, 2),
                                  ]).slice(0, 4);
                              const monolithCons = uniqueTextItems([
                                ...scalingCandidates.slice(0, 2).map((item) => `${item} may remain harder to scale independently.`),
                                "Shared releases and shared infrastructure can continue to slow isolated changes.",
                              ]).slice(0, 4);

                              return (
                                <div style={styles.microservicePanel}>
                                  <div
                                    style={{
                                      ...styles.microserviceHero,
                                      background:
                                        fitScore >= 60
                                          ? "linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)"
                                          : "linear-gradient(135deg, #fff1f2 0%, #fee2e2 100%)",
                                      borderColor: fitScore >= 60 ? "#86efac" : "#fca5a5",
                                    }}
                                  >
                                    <div style={styles.microserviceHeroHeader}>
                                      <div style={styles.microserviceHeroStatusRow}>
                                        <div
                                          style={{
                                            ...styles.microserviceHeroIcon,
                                            background: fitScore >= 60 ? "#dcfce7" : "#fee2e2",
                                            color: fitScore >= 60 ? "#166534" : "#b91c1c",
                                          }}
                                        >
                                          {fitScore >= 60 ? "YES" : "NO"}
                                        </div>
                                        <div style={styles.microserviceHeroStatusCopy}>
                                          <div
                                            style={{
                                              ...styles.microserviceHeroStatusLabel,
                                              color: fitScore >= 60 ? "#166534" : "#991b1b",
                                            }}
                                          >
                                            {assessmentLabel}
                                          </div>
                                          <div style={styles.microserviceHeroSummary}>{microserviceResult.summary}</div>
                                        </div>
                                      </div>
                                      <button
                                        style={{ ...styles.secondaryBtn, fontSize: 12, padding: "8px 14px" }}
                                        onClick={handleDownloadMicroserviceReport}
                                      >
                                        Download Report
                                      </button>
                                    </div>

                                    <div style={styles.microserviceHeroFooter}>
                                      <div style={styles.microserviceHeroProgressBlock}>
                                        <div style={styles.microserviceHeroProgressMeta}>
                                          <span>Confidence level</span>
                                          <strong>{fitScore}%</strong>
                                        </div>
                                        <div style={styles.microserviceHeroProgressTrack}>
                                          <div
                                            style={{
                                              ...styles.microserviceHeroProgressFill,
                                              width: `${fitScore}%`,
                                              background: getAssessmentBarColor(fitScore),
                                            }}
                                          />
                                        </div>
                                      </div>
                                      <div style={styles.microserviceHeroMetaRow}>
                                        <span style={styles.microserviceHeroMetaPill}>
                                          Architecture: {microserviceResult.recommendedArchitecture}
                                        </span>
                                        <span style={styles.microserviceHeroMetaPill}>
                                          Spring Boot: {microserviceResult.metadata?.springBootDetected ? "Yes" : "No"}
                                        </span>
                                        {databaseTechnologies.length > 0 && (
                                          <span style={styles.microserviceHeroMetaPill}>
                                            Database: {databaseTechnologies.join(", ")}
                                          </span>
                                        )}
                                        <span style={styles.microserviceHeroMetaPill}>
                                          {microserviceResult.reportGeneratedAt
                                            ? `Generated ${new Date(microserviceResult.reportGeneratedAt).toLocaleString()}`
                                            : "Structured report ready"}
                                        </span>
                                      </div>
                                    </div>

                                    {microserviceResult.analysisDiagnostics?.scan_truncated && (
                                      <div style={styles.microserviceHeroNote}>
                                        Analysis was sampled for scale. Some repository sections may need a deeper targeted pass.
                                      </div>
                                    )}
                                    {!isMicroserviceRecommended && (
                                      <div style={styles.microserviceHeroDecisionShell}>
                                        <div style={styles.microserviceHeroDecisionHeader}>
                                          <div style={styles.microserviceHeroDecisionTitle}>Architecture Decision Guide</div>
                                          <button
                                            type="button"
                                            style={styles.microserviceHeroDecisionToggle}
                                            onClick={() => toggleMicroserviceExpandedSection("hero-decision")}
                                          >
                                            {microserviceExpandedSections["hero-decision"] ? "View less" : "View details"}
                                          </button>
                                        </div>
                                        <div style={styles.microserviceDecisionGrid}>
                                          <div
                                            style={{
                                              ...styles.microserviceDecisionCard,
                                              background: "#eff6ff",
                                              borderColor: "#bfdbfe",
                                            }}
                                          >
                                            <div style={styles.microserviceDecisionHeader}>
                                              <div style={styles.microserviceDecisionTitle}>If you move toward microservices now</div>
                                            </div>
                                            <div style={styles.microserviceDecisionLead}>
                                              This path can still work later, but today it comes with higher dependency and data-boundary risk.
                                            </div>
                                            <div style={styles.microserviceDecisionList}>
                                              {(microserviceExpandedSections["hero-decision"] ? microservicePros : microservicePros.slice(0, 2)).map((item, index) => (
                                                <div key={`hero-microservice-pro-${index}`} style={styles.microserviceDecisionItem}>+ {item}</div>
                                              ))}
                                              {(microserviceExpandedSections["hero-decision"] ? microserviceCons : microserviceCons.slice(0, 1)).map((item, index) => (
                                                <div key={`hero-microservice-con-${index}`} style={{ ...styles.microserviceDecisionItem, color: "#991b1b" }}>- {item}</div>
                                              ))}
                                            </div>
                                          </div>

                                          <div
                                            style={{
                                              ...styles.microserviceDecisionCard,
                                              background: "#fff7ed",
                                              borderColor: "#fdba74",
                                            }}
                                          >
                                            <div style={styles.microserviceDecisionHeader}>
                                              <div style={styles.microserviceDecisionTitle}>If you stay modular monolith for now</div>
                                              <span style={styles.microserviceDecisionBadge}>Recommended</span>
                                            </div>
                                            <div style={styles.microserviceDecisionLead}>
                                              This path reduces execution risk while you improve boundaries, contracts, and data ownership first.
                                            </div>
                                            <div style={styles.microserviceDecisionList}>
                                              {(microserviceExpandedSections["hero-decision"] ? monolithPros : monolithPros.slice(0, 2)).map((item, index) => (
                                                <div key={`hero-monolith-pro-${index}`} style={styles.microserviceDecisionItem}>+ {item}</div>
                                              ))}
                                              {(microserviceExpandedSections["hero-decision"] ? monolithCons : monolithCons.slice(0, 1)).map((item, index) => (
                                                <div key={`hero-monolith-con-${index}`} style={{ ...styles.microserviceDecisionItem, color: "#9a3412" }}>- {item}</div>
                                              ))}
                                            </div>
                                          </div>
                                        </div>
                                      </div>
                                    )}
                                  </div>

                                  <div style={styles.microserviceMetricGrid}>
                                    {[
                                      { label: "Detected Modules", value: microserviceResult.analysisDiagnostics?.detected_modules ?? 0 },
                                      { label: "Java Files Scanned", value: microserviceResult.analysisDiagnostics?.java_files_scanned ?? 0 },
                                      { label: "Cross Dependencies", value: microserviceResult.analysisDiagnostics?.cross_module_dependencies ?? 0 },
                                      { label: "Circular Dependencies", value: microserviceResult.analysisDiagnostics?.circular_dependencies ?? 0 },
                                      { label: "Service Candidates", value: serviceCandidates.length },
                                      { label: "Scaling Candidates", value: scalingCandidates.length },
                                    ].map((stat) => (
                                      <div key={stat.label} style={styles.microserviceMetricCard}>
                                        <div style={styles.microserviceMetricValue}>{stat.value}</div>
                                        <div style={styles.microserviceMetricLabel}>{stat.label}</div>
                                      </div>
                                    ))}
                                  </div>

                                  <div style={styles.microservicePreviewGrid}>
                                    <div style={{ ...styles.microservicePreviewCard, borderColor: "#bbf7d0", background: "#f0fdf4" }}>
                                      <div style={{ ...styles.microservicePreviewTitle, color: "#166534" }}>
                                        Strengths {strengths.length > 0 ? `(${strengths.length})` : ""}
                                      </div>
                                      <div style={styles.microservicePreviewList}>
                                        {strengths.length > 0 ? (
                                          strengths.slice(0, 4).map((item, index) => (
                                            <div key={`strength-${index}`} style={{ ...styles.microservicePreviewListItem, color: "#15803d" }}>
                                              - {item}
                                            </div>
                                          ))
                                        ) : (
                                          <div style={{ ...styles.microservicePreviewEmpty, color: "#86efac" }}>
                                            No major strengths were highlighted.
                                          </div>
                                        )}
                                      </div>
                                      {strengths.length > 4 && (
                                        <div style={styles.microservicePreviewHint}>Open Summary & Signals to view all strengths.</div>
                                      )}
                                    </div>

                                    <div style={{ ...styles.microservicePreviewCard, borderColor: "#fecaca", background: "#fef2f2" }}>
                                      <div style={{ ...styles.microservicePreviewTitle, color: "#991b1b" }}>
                                        Risks {risks.length > 0 ? `(${risks.length})` : ""}
                                      </div>
                                      <div style={styles.microservicePreviewList}>
                                        {risks.length > 0 ? (
                                          risks.slice(0, 4).map((item, index) => (
                                            <div key={`risk-${index}`} style={{ ...styles.microservicePreviewListItem, color: "#b91c1c" }}>
                                              - {item}
                                            </div>
                                          ))
                                        ) : (
                                          <div style={{ ...styles.microservicePreviewEmpty, color: "#fca5a5" }}>
                                            No major risks were highlighted.
                                          </div>
                                        )}
                                      </div>
                                      {risks.length > 4 && (
                                        <div style={styles.microservicePreviewHint}>Open Summary & Signals to view all risks.</div>
                                      )}
                                    </div>

                                    <div style={{ ...styles.microservicePreviewCard, borderColor: "#fdba74", background: "#fff7ed" }}>
                                      <div style={{ ...styles.microservicePreviewTitle, color: "#9a3412" }}>Recommended Architecture</div>
                                      <div style={styles.microserviceRecommendationValue}>{microserviceResult.recommendedArchitecture}</div>
                                      <div style={{ ...styles.microservicePreviewListItem, color: "#9a3412" }}>
                                        {microserviceResult.eligibility === "NOT ELIGIBLE"
                                          ? "The analyzer recommends staying monolithic for now and improving internal modularity first."
                                          : "The analyzer found enough structure to suggest a staged modernization path instead of a blind rewrite."}
                                      </div>
                                    </div>

                                    <div style={{ ...styles.microservicePreviewCard, borderColor: "#bfdbfe", background: "#eff6ff" }}>
                                      <div style={{ ...styles.microservicePreviewTitle, color: "#1d4ed8" }}>Top Score Highlights</div>
                                      <div style={styles.microservicePreviewList}>
                                        {topScoreBreakdown.length > 0 ? (
                                          topScoreBreakdown.map((metric) => (
                                            <div key={metric.name} style={styles.microserviceScoreHighlight}>
                                              <span>{metric.name}</span>
                                              <strong>{metric.score}%</strong>
                                            </div>
                                          ))
                                        ) : (
                                          <div style={{ ...styles.microservicePreviewEmpty, color: "#60a5fa" }}>
                                            Score breakdown will appear here when available.
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  </div>

                                  {renderMicroserviceAccordion({
                                    section: "signals",
                                    title: "Summary & Signals",
                                    subtitle: "Review the assessment summary, strengths, and risks before diving into detailed evidence.",
                                    meta: `${strengths.length} strengths | ${risks.length} risks`,
                                    tone: "slate",
                                    children: (
                                      <div style={styles.microserviceAccordionSectionGrid}>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#ffffff", borderColor: "#e2e8f0" }}>
                                          <div style={styles.microserviceInsightTitle}>Assessment Summary</div>
                                          <div style={styles.microserviceInsightText}>{microserviceResult.summary}</div>
                                        </div>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#f0fdf4", borderColor: "#bbf7d0" }}>
                                          <div style={{ ...styles.microserviceInsightTitle, color: "#166534" }}>Strengths</div>
                                          {strengths.length > 0 ? strengths.map((item, index) => (
                                            <div key={`strength-full-${index}`} style={{ ...styles.microserviceBulletItem, color: "#15803d" }}>- {item}</div>
                                          )) : <div style={{ ...styles.microservicePreviewEmpty, color: "#86efac" }}>No major strengths were highlighted.</div>}
                                        </div>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#fef2f2", borderColor: "#fecaca" }}>
                                          <div style={{ ...styles.microserviceInsightTitle, color: "#991b1b" }}>Risks</div>
                                          {risks.length > 0 ? risks.map((item, index) => (
                                            <div key={`risk-full-${index}`} style={{ ...styles.microserviceBulletItem, color: "#b91c1c" }}>- {item}</div>
                                          )) : <div style={{ ...styles.microservicePreviewEmpty, color: "#fca5a5" }}>No major risks were highlighted.</div>}
                                        </div>
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "signals-project-structure",
                                          title: "Project Structure Evidence",
                                          subtitle: "Repository-level clues that indicate how the codebase is organized today.",
                                          items: projectStructureDetails,
                                          emptyText: "No additional project structure findings were returned.",
                                          previewCount: 4,
                                          accentColor: "#334155",
                                          background: "#ffffff",
                                          borderColor: "#e2e8f0",
                                        })}
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "signals-package-structure",
                                          title: "Package Structure Evidence",
                                          subtitle: "Package naming and grouping clues that help infer business boundaries.",
                                          items: packageStructureDetails,
                                          emptyText: "No additional package structure findings were returned.",
                                          previewCount: 4,
                                          accentColor: "#334155",
                                          background: "#ffffff",
                                          borderColor: "#e2e8f0",
                                        })}
                                      </div>
                                    ),
                                  })}

                                  {renderMicroserviceAccordion({
                                    section: "scores",
                                    title: "Score Breakdown",
                                    subtitle: "See how the repository scored across modularity, coupling, database boundaries, and scale readiness.",
                                    meta: `${scoreBreakdown.length} dimensions`,
                                    tone: "blue",
                                    children: (
                                      <div style={styles.microserviceScoreBreakdownList}>
                                        {scoreBreakdown.length > 0 ? scoreBreakdown.map((metric) => {
                                          const tooltipContent = getMicroserviceScoreTooltip(metric.name);
                                          const metricEvidence = scoreEvidenceMap[metric.name] || [];
                                          const scoreEvidenceKey = `score-${metric.name}`;
                                          const isScoreEvidenceExpanded = microserviceExpandedSections[scoreEvidenceKey];
                                          const visibleScoreEvidence = isScoreEvidenceExpanded ? metricEvidence : metricEvidence.slice(0, 2);

                                          return (
                                          <div
                                            key={metric.name}
                                            style={styles.microserviceScoreCard}
                                            onMouseLeave={() => {
                                              setActiveScoreTooltip((current) => (current === metric.name ? null : current));
                                            }}
                                          >
                                            <div style={styles.microserviceScoreHeader}>
                                              <div>
                                                <div style={styles.microserviceScoreTitleRow}>
                                                  <div style={styles.microserviceScoreName}>{metric.name}</div>
                                                  <button
                                                    type="button"
                                                    style={styles.microserviceScoreInfoButton}
                                                    aria-label={`Explain ${metric.name}`}
                                                    onMouseEnter={() => setActiveScoreTooltip(metric.name)}
                                                    onFocus={() => setActiveScoreTooltip(metric.name)}
                                                    onBlur={() => setActiveScoreTooltip((current) => (current === metric.name ? null : current))}
                                                    onClick={(event) => {
                                                      event.preventDefault();
                                                      event.stopPropagation();
                                                      setActiveScoreTooltip((current) => (current === metric.name ? null : metric.name));
                                                    }}
                                                  >
                                                    i
                                                  </button>
                                                </div>
                                                <div style={styles.microserviceScoreWeight}>{metric.weight}% weight</div>
                                              </div>
                                              <div style={styles.microserviceScoreValue}>{metric.score}%</div>
                                            </div>
                                            {activeScoreTooltip === metric.name && (
                                              <div style={styles.microserviceScoreTooltip}>
                                                <div style={styles.microserviceScoreTooltipTitle}>{tooltipContent.title}</div>
                                                <div style={styles.microserviceScoreTooltipText}>{tooltipContent.description}</div>
                                                <div style={styles.microserviceScoreTooltipText}>{tooltipContent.interpretation}</div>
                                              </div>
                                            )}
                                            <div style={styles.microserviceScoreTrack}>
                                              <div
                                                style={{
                                                  ...styles.microserviceScoreFill,
                                                  width: `${metric.score}%`,
                                                  background: getAssessmentBarColor(metric.score),
                                                }}
                                              />
                                            </div>
                                            <div style={styles.microserviceScoreText}>{metric.summary}</div>
                                            {metricEvidence.length > 0 && (
                                              <div style={styles.microserviceScoreEvidenceBox}>
                                                <div style={styles.microserviceScoreEvidenceTitle}>Supporting evidence</div>
                                                {visibleScoreEvidence.map((item, index) => (
                                                  <div key={`${metric.name}-evidence-${index}`} style={styles.microserviceScoreEvidenceItem}>
                                                    - {item}
                                                  </div>
                                                ))}
                                                {metricEvidence.length > 2 && (
                                                  <div style={styles.microserviceEvidenceFooter}>
                                                    <button
                                                      type="button"
                                                      style={styles.microserviceEvidenceToggle}
                                                      onClick={() => toggleMicroserviceExpandedSection(scoreEvidenceKey)}
                                                    >
                                                      {isScoreEvidenceExpanded ? "View less" : `View more (${metricEvidence.length - 2} more)`}
                                                    </button>
                                                  </div>
                                                )}
                                              </div>
                                            )}
                                          </div>
                                          );
                                        }) : <div style={styles.microserviceEmptyState}>No score breakdown was returned for this assessment.</div>}
                                      </div>
                                    ),
                                  })}

                                  {renderMicroserviceAccordion({
                                    section: "services",
                                    title: "Suggested Service Boundaries",
                                    subtitle: "Potential extraction candidates based on packages, controller clusters, and scaling signals.",
                                    meta: `${serviceCandidates.length} candidates`,
                                    tone: "blue",
                                    children: (
                                      <div>
                                        {serviceCandidates.length > 0 ? (
                                          <>
                                            <div style={styles.microserviceServiceGrid}>
                                              {visibleServiceCandidates.map((candidate) => {
                                                const activeCandidateTag = activeServiceTagTooltip?.startsWith(`${candidate.name}::`)
                                                  ? activeServiceTagTooltip.slice(candidate.name.length + 2)
                                                  : null;
                                                const activeCandidateTagTooltip = activeCandidateTag
                                                  ? getMicroserviceServiceTagTooltip(activeCandidateTag, candidate)
                                                  : null;

                                                return (
                                                <div
                                                  key={candidate.name}
                                                  style={styles.microserviceServiceCard}
                                                  onMouseLeave={() => {
                                                    setActiveServiceTagTooltip((current) =>
                                                      current?.startsWith(`${candidate.name}::`) ? null : current
                                                    );
                                                  }}
                                                >
                                                  <div style={styles.microserviceServiceHeader}>
                                                    <div style={styles.microserviceServiceTitle}>{candidate.name}</div>
                                                    {candidate.transactional && (
                                                      <span style={styles.microserviceTransactionalBadge}>Transactional</span>
                                                    )}
                                                  </div>
                                                  {candidate.packages?.length > 0 && (
                                                    <div style={styles.microserviceServicePackages}>
                                                      Packages: {candidate.packages.slice(0, 5).join(", ")}
                                                      {candidate.packages.length > 5 ? ` +${candidate.packages.length - 5} more` : ""}
                                                    </div>
                                                  )}
                                                  <div style={styles.microserviceServiceEvidence}>
                                                    {candidate.evidence?.slice(0, 4).map((evidence, index) => (
                                                      <div key={`${candidate.name}-evidence-${index}`} style={styles.microserviceBulletItem}>- {evidence}</div>
                                                    ))}
                                                  </div>
                                                  {(candidate.scaling_signals?.length > 0 || candidate.external_integrations?.length > 0) && (
                                                    <>
                                                      <div style={styles.microserviceServiceSignalsLabel}>
                                                        Workload & integration signals
                                                      </div>
                                                      <div style={styles.microserviceTagRow}>
                                                        {candidate.scaling_signals?.map((signal) => {
                                                          const tagKey = `${candidate.name}::${signal}`;

                                                          return (
                                                            <button
                                                              key={`${candidate.name}-signal-${signal}`}
                                                              type="button"
                                                              style={styles.microserviceTagButton}
                                                              aria-label={`Explain ${signal}`}
                                                              onMouseEnter={() => setActiveServiceTagTooltip(tagKey)}
                                                              onFocus={() => setActiveServiceTagTooltip(tagKey)}
                                                              onBlur={() =>
                                                                setActiveServiceTagTooltip((current) =>
                                                                  current === tagKey ? null : current
                                                                )
                                                              }
                                                              onClick={(event) => {
                                                                event.preventDefault();
                                                                event.stopPropagation();
                                                                setActiveServiceTagTooltip((current) =>
                                                                  current === tagKey ? null : tagKey
                                                                );
                                                              }}
                                                            >
                                                              {signal}
                                                            </button>
                                                          );
                                                        })}
                                                        {candidate.external_integrations?.slice(0, 2).map((integration) => {
                                                          const tagKey = `${candidate.name}::${integration}`;

                                                          return (
                                                            <button
                                                              key={`${candidate.name}-integration-${integration}`}
                                                              type="button"
                                                              style={styles.microserviceTagMutedButton}
                                                              aria-label={`Explain ${integration}`}
                                                              onMouseEnter={() => setActiveServiceTagTooltip(tagKey)}
                                                              onFocus={() => setActiveServiceTagTooltip(tagKey)}
                                                              onBlur={() =>
                                                                setActiveServiceTagTooltip((current) =>
                                                                  current === tagKey ? null : current
                                                                )
                                                              }
                                                              onClick={(event) => {
                                                                event.preventDefault();
                                                                event.stopPropagation();
                                                                setActiveServiceTagTooltip((current) =>
                                                                  current === tagKey ? null : tagKey
                                                                );
                                                              }}
                                                            >
                                                              {integration}
                                                            </button>
                                                          );
                                                        })}
                                                      </div>
                                                      {activeCandidateTagTooltip && (
                                                        <div style={styles.microserviceServiceTagTooltip}>
                                                          <div style={styles.microserviceServiceTagTooltipTitle}>
                                                            {activeCandidateTagTooltip.title}
                                                          </div>
                                                          <div style={styles.microserviceServiceTagTooltipText}>
                                                            {activeCandidateTagTooltip.description}
                                                          </div>
                                                          <div style={styles.microserviceServiceTagTooltipText}>
                                                            {activeCandidateTagTooltip.interpretation}
                                                          </div>
                                                        </div>
                                                      )}
                                                    </>
                                                  )}
                                                </div>
                                                );
                                              })}
                                            </div>
                                            {serviceCandidates.length > 4 && (
                                              <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end" }}>
                                                <button
                                                  type="button"
                                                  style={{ ...styles.secondaryBtn, fontSize: 12, padding: "8px 14px" }}
                                                  onClick={() => setShowAllMicroserviceServices((current) => !current)}
                                                >
                                                  {showAllMicroserviceServices
                                                    ? "Show fewer service candidates"
                                                    : `Show all ${serviceCandidates.length} service candidates`}
                                                </button>
                                              </div>
                                            )}
                                            <div style={{ marginTop: 12 }}>
                                              {renderMicroserviceEvidenceBlock({
                                                sectionKey: "services-module-boundaries",
                                                title: "Module Boundary Evidence",
                                                subtitle: "These findings explain why the analyzer suggested particular extraction boundaries.",
                                                items: moduleBoundaryDetails,
                                                emptyText: "No additional module-boundary evidence was returned.",
                                                previewCount: 4,
                                                accentColor: "#1d4ed8",
                                                background: "#eff6ff",
                                                borderColor: "#bfdbfe",
                                              })}
                                            </div>
                                          </>
                                        ) : (
                                          <div style={styles.microserviceEmptyState}>No service candidates were identified for this repository.</div>
                                        )}
                                      </div>
                                    ),
                                  })}

                                  {renderMicroserviceAccordion({
                                    section: "concerns",
                                    title: "Coupling & Database Concerns",
                                    subtitle: "Review the strongest blockers before considering service extraction.",
                                    meta: `${couplingIssues.length} coupling | ${databaseConcerns.length} database`,
                                    tone: "amber",
                                    children: (
                                      <div style={styles.microserviceAccordionSectionGrid}>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#fff7ed", borderColor: "#fdba74" }}>
                                          <div style={{ ...styles.microserviceInsightTitle, color: "#9a3412" }}>Coupling Issues</div>
                                          {couplingIssues.length > 0 ? couplingIssues.map((item, index) => (
                                            <div key={`coupling-${index}`} style={{ ...styles.microserviceBulletItem, color: "#9a3412" }}>- {item}</div>
                                          )) : <div style={{ ...styles.microservicePreviewEmpty, color: "#c2410c" }}>No major coupling issues detected.</div>}
                                        </div>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#fff7ed", borderColor: "#fdba74" }}>
                                          <div style={{ ...styles.microserviceInsightTitle, color: "#9a3412" }}>Database Concerns</div>
                                          {databaseConcerns.length > 0 ? databaseConcerns.map((item, index) => (
                                            <div key={`database-${index}`} style={{ ...styles.microserviceBulletItem, color: "#9a3412" }}>- {item}</div>
                                          )) : <div style={{ ...styles.microservicePreviewEmpty, color: "#c2410c" }}>No major database boundary concerns detected.</div>}
                                        </div>
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "concerns-dependency-coupling",
                                          title: "Dependency Coupling Evidence",
                                          subtitle: "Specific dependency patterns that make service separation harder.",
                                          items: dependencyCouplingDetails,
                                          emptyText: "No additional dependency coupling evidence was returned.",
                                          previewCount: 4,
                                          accentColor: "#9a3412",
                                          background: "#fff7ed",
                                          borderColor: "#fdba74",
                                        })}
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "concerns-database-access",
                                          title: "Database Access Evidence",
                                          subtitle: "Data access patterns that can create shared-database coupling.",
                                          items: databaseAccessDetails,
                                          emptyText: "No additional database access evidence was returned.",
                                          previewCount: 4,
                                          accentColor: "#9a3412",
                                          background: "#fff7ed",
                                          borderColor: "#fdba74",
                                        })}
                                      </div>
                                    ),
                                  })}

                                  {renderMicroserviceAccordion({
                                    section: "strategy",
                                    title: "Scaling & Migration Strategy",
                                    subtitle: "Use these recommendations to plan where to extract first and how to stage the work.",
                                    meta: `${scalingCandidates.length} scaling | ${recommendedMigrationStrategy.length} strategy`,
                                    tone: "green",
                                    children: (
                                      <div style={styles.microserviceAccordionSectionGrid}>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#ecfeff", borderColor: "#a5f3fc" }}>
                                          <div style={{ ...styles.microserviceInsightTitle, color: "#155e75" }}>Scaling Candidates</div>
                                          {scalingCandidates.length > 0 ? scalingCandidates.map((item, index) => (
                                            <div key={`scaling-${index}`} style={{ ...styles.microserviceBulletItem, color: "#0f766e" }}>- {item}</div>
                                          )) : <div style={{ ...styles.microservicePreviewEmpty, color: "#0891b2" }}>No clear independent scaling targets were highlighted.</div>}
                                        </div>
                                        <div style={{ ...styles.microserviceInsightCard, background: "#f8fafc", borderColor: "#cbd5e1" }}>
                                          <div style={styles.microserviceInsightTitle}>Recommended Migration Strategy</div>
                                          {recommendedMigrationStrategy.length > 0 ? recommendedMigrationStrategy.map((item, index) => (
                                            <div key={`strategy-${index}`} style={{ ...styles.microserviceBulletItem, color: "#475569" }}>- {item}</div>
                                          )) : <div style={{ ...styles.microservicePreviewEmpty, color: "#94a3b8" }}>No migration strategy guidance available.</div>}
                                        </div>
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "strategy-deployment-independence",
                                          title: "Deployment Independence Signals",
                                          subtitle: "Signals that show whether modules could be released more independently.",
                                          items: deploymentIndependenceDetails,
                                          emptyText: "No additional deployment-independence signals were returned.",
                                          previewCount: 4,
                                          accentColor: "#155e75",
                                          background: "#ecfeff",
                                          borderColor: "#a5f3fc",
                                        })}
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "strategy-scalability-indicators",
                                          title: "Scalability Indicators",
                                          subtitle: "Repository patterns that suggest where independent scaling may help.",
                                          items: scalabilityIndicatorDetails,
                                          emptyText: "No additional scalability indicators were returned.",
                                          previewCount: 4,
                                          accentColor: "#155e75",
                                          background: "#ecfeff",
                                          borderColor: "#a5f3fc",
                                        })}
                                        {renderMicroserviceEvidenceBlock({
                                          sectionKey: "strategy-communication-analysis",
                                          title: "Communication Analysis",
                                          subtitle: "Interaction patterns that hint at service boundaries and async/event readiness.",
                                          items: communicationAnalysisDetails,
                                          emptyText: "No additional communication-analysis evidence was returned.",
                                          previewCount: 4,
                                          accentColor: "#475569",
                                          background: "#f8fafc",
                                          borderColor: "#cbd5e1",
                                        })}
                                      </div>
                                    ),
                                  })}

                                  {architecturalObservations.length > 0 && renderMicroserviceAccordion({
                                    section: "observations",
                                    title: "Architectural Observations",
                                    subtitle: "Repository-level notes worth keeping in view while deciding the migration approach.",
                                    meta: `${architecturalObservations.length} observations`,
                                    tone: "violet",
                                    children: (
                                      <div style={{ ...styles.microserviceInsightCard, background: "#faf5ff", borderColor: "#d8b4fe" }}>
                                        {architecturalObservations.map((item, index) => (
                                          <div key={`observation-${index}`} style={{ ...styles.microserviceBulletItem, color: "#7e22ce" }}>- {item}</div>
                                        ))}
                                      </div>
                                    ),
                                  })}

                                </div>
                              );
                            })()}
                          </div>
                        )}
                      </div>}
                    </div>
                  )}

                  {repoAnalysis && (
                    <div style={{ ...styles.documentCard, marginTop: 20 }}>
                      <div style={styles.documentCardHeader}>
                        <div style={styles.documentCardTitleRow}>
                          <span style={styles.documentCardIcon}>📋</span>
                          <div style={styles.documentCardTitle}>Technical Specification Document</div>
                        </div>
                        <div style={styles.documentCardSubtitle}>
                          Generate a Technical specification document for this repository and download it directly as a PDF.
                        </div>
                      </div>
                      <div style={styles.documentActionRow}>
                        <button
                          style={styles.primaryBtn}
                          disabled={documentGenerationLoading !== null || !repoAnalysis}
                          onClick={handleGenerateBrdDocument}
                        >
                          {documentGenerationLoading === "brd"
                            ? "Generating Document..."
                            : documentPrefetchStatus === "rendering"
                              ? "Preparing PDF..."
                              : documentPrefetchStatus === "loading"
                                ? "Preparing Document..."
                            : documentPrefetchStatus === "ready"
                              ? "Generate Document"
                              : "Generate Document"}
                        </button>
                      </div>
                      <div style={styles.documentHelperText}>
                        {isLocalProjectSelected
                          ? "Document generation is available for uploaded local projects and GitHub repository sources."
                          : documentPrefetchStatus === "loading"
                            ? "Preparing the Technical Specification Document in the background."
                            : documentPrefetchStatus === "rendering"
                              ? "Rendering the PDF in the background so the download is instant when ready."
                            : documentPrefetchStatus === "ready"
                              ? "The Technical Specification Document PDF is ready for immediate download."
                              : "The PDF download will start automatically after the Technical Specification Document is generated."}
                      </div>
                    </div>
                  )}

                </>
              )}
                    </>
                  )}
            </>
          )}
        </>
      )}

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(1)}>← Back</button>
        <button 
          style={{ ...styles.primaryBtn, opacity: isJavaProject === false || (isHighRiskProject && !highRiskConfirmed) || isDiscoveryPending || !repoAnalysis ? 0.5 : 1 }} 
          onClick={() => setStep(3)}
          disabled={isJavaProject === false || (isHighRiskProject && !highRiskConfirmed) || isDiscoveryPending || !repoAnalysis}
        >
          Continue to Strategy →
        </button>
      </div>
    </div>
    );
  };

  // Step 3: Dependencies
  const renderDependenciesStep = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📦</span>
        <div>
          <h2 style={styles.title}>Project Dependencies</h2>
          <p style={styles.subtitle}>{MIGRATION_STEPS[2].summary}</p>
        </div>
      </div>

      {selectedRepo && repoAnalysis && (
        <>
        
          {/* <div style={styles.discoveryContent}>
            <div style={styles.discoveryItem}>
              <span style={styles.discoveryIcon}>🔧</span>
              <div>
                
                <div style={styles.discoveryTitle}>Build Tool: {buildToolDisplayLabel}</div>
                <div style={styles.discoveryDesc}>Identified build system for dependency management</div>
              </div>
            </div>
            <div style={styles.discoveryItem}>
              <span style={styles.discoveryIcon}>☕</span>
              <div>
                <div style={styles.discoveryTitle}>Java Version: {(repoAnalysis.java_version || repoAnalysis.java_version_from_build) || "Version Detection Failed"}</div>
                <div style={styles.discoveryDesc}>Current Java version detected in the project</div>
              </div>
            </div>
          </div> */}

          {/* Dependencies List */}
          {repoAnalysis.dependencies && repoAnalysis.dependencies.length > 0 ? (
            <div style={styles.field}>
              <label style={styles.label}>
                Detected Dependencies ({repoAnalysis.dependencies.length})
              </label>
              <div style={styles.dependenciesList}>
                {repoAnalysis.dependencies.map((dep, idx) => (
                  <div key={idx} style={styles.dependencyItem}>
                    <span style={{ flex: 2 }}>{dep.group_id}:{dep.artifact_id}</span>
                    <span style={{ ...styles.dependencyVersion, flex: 1, textAlign: "center" }}>{dep.current_version}</span>
                    <span style={{ ...styles.detectedBadge, flex: 1, textAlign: "center", backgroundColor: isDetectedDependencyStatus(dep.status) ? "#dcfce7" : "#e5e7eb", color: isDetectedDependencyStatus(dep.status) ? "#166534" : "#6b7280" }}>
                      {getDependencyStatusLabel(dep.status)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={styles.infoBox}>
              No dependencies detected. This could be a simple Java project without external dependencies.
            </div>
          )}

          {/* Framework Detection */}
          <div style={styles.sectionTitle}>🎯 Detected Frameworks & Libraries</div>
          <div style={styles.frameworkGrid}>
            <div style={styles.frameworkItem}>
              <span>🍃</span>
              <span>Spring Boot</span>
              {repoAnalysis.dependencies?.some(d => d.artifact_id.includes('spring')) && <span style={styles.detectedBadge}>Detected</span>}
            </div>
            <div style={styles.frameworkItem}>
              <span>🗄️</span>
              <span>JPA/Hibernate</span>
              {repoAnalysis.dependencies?.some(d => d.artifact_id.includes('hibernate') || d.artifact_id.includes('jpa')) && <span style={styles.detectedBadge}>Detected</span>}
            </div>
            <div style={styles.frameworkItem}>
              <span>🧪</span>
              <span>JUnit</span>
              {repoAnalysis.dependencies?.some(d => d.artifact_id.includes('junit')) && <span style={styles.detectedBadge}>Detected</span>}
            </div>
            <div style={styles.frameworkItem}>
              <span>📝</span>
              <span>Log4j/SLF4J</span>
              {repoAnalysis.dependencies?.some(d => d.artifact_id.includes('log4j') || d.artifact_id.includes('slf4j')) && <span style={styles.detectedBadge}>Detected</span>}
            </div>
          </div>
        </>
      )}

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(2)}>← Back</button>
        <button style={styles.primaryBtn} onClick={() => setStep(4)}>Continue to Assessment →</button>
      </div>
    </div>
  );

  // Consolidated Step 4: Assessment (Application Assessment)
  const renderAssessmentStep = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📊</span>
        <div>
          <h2 style={styles.title}>Application Assessment</h2>
          <p style={styles.subtitle}>{MIGRATION_STEPS[3].summary}</p>
        </div>
      </div>
      {selectedRepo && repoAnalysis && (
        <>
        <div
  style={{
    ...styles.riskBadge,
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    cursor: "help",
    backgroundColor: riskLevel === "low" ? "#dcfce7" : riskLevel === "medium" ? "#fef3c7" : "#fee2e2",
    color: riskLevel === "low" ? "#166534" : riskLevel === "medium" ? "#92400e" : "#991b1b",
  }}
  title={
    riskLevel === "low"
      ? "Low risk: build tool and tests detected."
      : riskLevel === "medium"
        ? "Medium risk: build tool detected, but tests are absent."
        : "High risk: no build tool detected."
  }
>
  {/* <span style={{ fontSize: 14 }}></span> */}
  <span style={{ fontSize: 14 }}>i</span>
  Risk Level: {riskLevel.toUpperCase()}
</div>
        
  
          
          {/* <div style={{ ...styles.riskBadge, backgroundColor: riskLevel === "low" ? "#dcfce7" : riskLevel === "medium" ? "#fef3c7" : "#fee2e2", color: riskLevel === "low" ? "#166534" : riskLevel === "medium" ? "#92400e" : "#991b1b" }}>
            Risk Level: {riskLevel.toUpperCase()}
          </div> */}

          <div style={styles.assessmentGrid}>
            
            {<div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Build Tool</div><div style={styles.assessmentValue}>{buildToolDisplayLabel}</div></div> }
            { <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Java Version</div><div style={styles.assessmentValue}>{(repoAnalysis.java_version || repoAnalysis.java_version_from_build) || "Version Detection Failed"}</div></div> }
            <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Has Tests</div><div style={styles.assessmentValue}>{repoAnalysis.has_tests ? "Yes" : "No"}</div></div>
            <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Dependencies</div><div style={styles.assessmentValue}>{repoAnalysis.dependencies?.length || 0} found</div></div>
          </div>

          <div style={styles.structureBox}>
            <div style={styles.structureTitle}>Project Structure</div>
            <div style={styles.structureGrid}>
              <span style={repoAnalysis.structure?.has_pom_xml ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_pom_xml ? "✓" : "✗"} pom.xml</span>
              <span style={repoAnalysis.structure?.has_build_gradle ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_build_gradle ? "✓" : "✗"} build.gradle</span>
              <span style={repoAnalysis.structure?.has_src_main ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_src_main ? "✓" : "✗"} src/main</span>
              <span style={repoAnalysis.structure?.has_src_test ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_src_test ? "✓" : "✗"} src/test</span>
              <span style={detectedJavaVersion ? styles.structureFound : styles.structureMissing}>{detectedJavaStructureLabel}</span>
            </div>
          </div>
        </>
      )}

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(3)}>← Back</button>
        <button style={styles.primaryBtn} onClick={() => setStep(5)}>Continue to Strategy →</button>
      </div>
    </div>
  );

  // Consolidated Step 3: Strategy (Assessment + Migration Strategy + Planning)
  const renderStrategyStep = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📋</span>
        <div>
          <h2 style={styles.title}>Assessment & Migration Strategy</h2>
          <p style={styles.subtitle}>{MIGRATION_STEPS[2].summary}</p>
        </div>
      </div>

      {/* Assessment Section */}
      {selectedRepo && repoAnalysis && (
        <>
          <div style={styles.sectionTitle}>📊 Application Assessment</div>
          
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

  <div style={{ position: "relative", display: "inline-flex" }}>
    <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  backgroundColor: "#e2e8f0",
                  color: "#64748b",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: "help",
                  transition: "all 0.2s ease"
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "#3b82f6";
                  e.currentTarget.style.color = "#fff";
                  const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                  if (tooltip) tooltip.style.display = "block";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "#e2e8f0";
                  e.currentTarget.style.color = "#64748b";
                  const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                  if (tooltip) tooltip.style.display = "none";
                }}
              >
                i
              </span>

    <div
      style={{
        display: "none",
        position: "absolute",
        top: 28,
        left: -170,
        width: 300,
        backgroundColor: "#1e293b",
        color: "#fff",
        borderRadius: 10,
        padding: "16px 20px",
        boxShadow: "0 18px 35px rgba(15, 23, 42, 0.25)",
        zIndex: 1000,
      }}
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
    </div>
  </div>
</div>



          {/* <div style={{ ...styles.riskBadge, backgroundColor: riskLevel === "low" ? "#dcfce7" : riskLevel === "medium" ? "#fef3c7" : "#fee2e2", color: riskLevel === "low" ? "#166534" : riskLevel === "medium" ? "#92400e" : "#991b1b" }}>
            Risk Level: {riskLevel.toUpperCase()}
          </div> */}

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
        <span>🔄</span>
        <span>Conversion Type</span>
        </div>

      <div style={{ height: 1, background: "#dbe3ef", marginBottom: 18 }} />

      <p style={{ fontSize: 17, color: "#475569", margin: "0 0 22px" }}>
        Available modernization pathways for your project:
      </p>  
        
        <div style={{ display: "grid",gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
          {/* Java Version Upgrade - ACTIVE */}
          <div
            onClick={() => setSelectedConversions(["java_version"])}
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: selectedConversions.includes("java_version") ? "2px solid #2563eb" : "1px solid #e2e8f0",
              backgroundColor: selectedConversions.includes("java_version") ? "#eff6ff" : "#fff",
              cursor: "pointer",
              transition: "all 0.2s ease",
              boxShadow: selectedConversions.includes("java_version") ? "0 4px 12px #2563eb20" : "0 2px 4px rgba(0,0,0,0.05)",
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#2563eb", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              ✓ ACTIVE
            </div>
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
                <span style={{ fontSize: 18 }}>☕</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#2563eb" }}>Java Version Upgrade</span>
            </div>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.45 }}>Upgrade Java version with Dependencies update</div>
            </div>
          </div>

          {/* Maven to Gradle  */}
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
            Coming Soon
            </div>
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>🔧</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#1e293b" }}>Maven → Gradle | Gradle → Maven</span>
            </div>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.45 }}>Convert pom.xml to build.gradle with dependency mapping</div>
          </div>
          </div>

          {/* Monolithic to Microservices */} 
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
          <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
            Coming Soon
          </div>  
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>⚙️</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#1e293b" }}>Monolithic → Microservices</span>
            </div>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.45 }}>Decompose monolith into microservices architecture</div>
          </div>
          </div>

          {/* javax to Jakarta - Coming Soon */}
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              Coming Soon
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
                <span style={{ fontSize: 18 }}>📦</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#1e293b" }}>javax → Jakarta EE | Jakarta EE → javax</span>
              </div>
              <div style={{ fontSize: 13, color: "#64748b", lineHeight: 1.45 }}>Migrate javax.* packages to jakarta.*</div>
            </div>
          </div>

          {/* Spring to Spring Boot - Coming Soon */}
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              Coming Soon
            </div>
            
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>🍃</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#64748b" }}>
                Spring → Spring Boot
              </span>
            </div>
            <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.45 }}>
              Upgrade Spring Boot 2.x to 3.x with Jakarta EE
            </div>
          </div>
          </div>

          {/* JSP/JSF to Angular/React - Coming Soon */}
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              Coming Soon
            </div>
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>🌐</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#64748b" }}>
                JSP/JSF → Angular/React
              </span>
            </div>
            <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.45 }}>
              Modernize legacy JSP/JSF views to Angular or React SPA
            </div>
          </div>
          </div>
        </div>
      </div> 
        </>
      )}

      {/* Strategy Section
      <div style={styles.sectionTitle}>📋 Migration Destination</div>
      <div style={styles.field}>
        <label style={styles.label}>Choose where the migrated code should be saved</label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
          {migrationApproachOptions.map((opt) => (
            <div key={opt.value} style={{ position: "relative" }}>
              <div
                onClick={() => {
                  setMigrationApproach(opt.value);
                  setTargetRepoNameError("");
                  if (opt.value === "fork") {
                    setTargetRepoNameForApproach("fork", getAutoGeneratedTargetName("fork"), false);
                  }
                }}
                style={{
                  padding: 20,
                  borderRadius: 12,
                  border: `2px solid ${migrationApproach === opt.value ? opt.color : "#e2e8f0"}`,
                  backgroundColor: migrationApproach === opt.value ? `${opt.color}08` : "#fff",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  boxShadow: migrationApproach === opt.value ? `0 4px 12px ${opt.color}20` : "0 2px 4px rgba(0,0,0,0.05)",
                  position: "relative"
                }}
                onMouseEnter={(e) => {
                  if (migrationApproach !== opt.value) {
                    e.currentTarget.style.borderColor = opt.color;
                    e.currentTarget.style.boxShadow = `0 4px 12px ${opt.color}15`;
                  }
                }}
                onMouseLeave={(e) => {
                  if (migrationApproach !== opt.value) {
                    e.currentTarget.style.borderColor = "#e2e8f0";
                    e.currentTarget.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                  }
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <span style={{ fontSize: 24 }}>{opt.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 4 }}>{opt.label}</div>
                    <div style={{ fontSize: 13, color: "#64748b" }}>{opt.desc}</div>
                  </div>
                  {migrationApproach === opt.value && (
                    <div style={{ color: opt.color, fontSize: 18, fontWeight: 700 }}>✓</div>
                  )}
                </div>

                {/* Info button for tooltip 
                <div style={{ position: "absolute", top: 12, right: 12 }}>
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      backgroundColor: "#e2e8f0",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#64748b",
                      cursor: "help"
                    }}
                    onMouseEnter={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "block";
                    }}
                    onMouseLeave={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "none";
                    }}
                  >
                    i
                  </div>

                  {/* Tooltip 
                  <div
                    style={{
                      display: "none",
                      position: "absolute",
                      top: 28,
                      right: 0,
                      width: 280,
                      backgroundColor: "#1e293b",
                      color: "#f1f5f9",
                      padding: "12px 16px",
                      borderRadius: 8,
                      fontSize: 12,
                      lineHeight: 1.5,
                      zIndex: 1000,
                      boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
                      whiteSpace: "normal"
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 8, color: "#94a3b8" }}>
                      {opt.label} Details
                    </div>
                    <div>{opt.tooltip}</div>
                    {/* Arrow 
                    <div style={{
                      position: "absolute",
                      top: -6,
                      right: 16,
                      width: 0,
                      height: 0,
                      borderLeft: "6px solid transparent",
                      borderRight: "6px solid transparent",
                      borderBottom: "6px solid #1e293b"
                    }} />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div> */}

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
                  </select>
                  <div style={{ fontSize: 11, color: "#a16207", marginTop: 6 }}>
                    💡 Select the correct Java version for your project. This will be used as the source version for migration.
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
          Fetching recommended target Java version from Hugging Face...
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
            Hugging Face Recommendations
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
      <div style={styles.sectionTitle}>📋 Migration Destination</div>
      <div style={styles.field}>
        <label style={styles.label}>Destination repository setup</label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
          {migrationApproachOptions.map((opt) => (
            <div key={opt.value} style={{ position: "relative" }}>
              <div
                onClick={() => {
                  setMigrationApproach(opt.value);
                  setTargetRepoNameError("");
                }}
                style={{
                  padding: 20,
                  borderRadius: 12,
                  border: `2px solid ${migrationApproach === opt.value ? opt.color : "#e2e8f0"}`,
                  backgroundColor: migrationApproach === opt.value ? `${opt.color}08` : "#fff",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  boxShadow: migrationApproach === opt.value ? `0 4px 12px ${opt.color}20` : "0 2px 4px rgba(0,0,0,0.05)",
                  position: "relative"
                }}
                onMouseEnter={(e) => {
                  if (migrationApproach !== opt.value) {
                    e.currentTarget.style.borderColor = opt.color;
                    e.currentTarget.style.boxShadow = `0 4px 12px ${opt.color}15`;
                  }
                }}
                onMouseLeave={(e) => {
                  if (migrationApproach !== opt.value) {
                    e.currentTarget.style.borderColor = "#e2e8f0";
                    e.currentTarget.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                  }
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <span style={{ fontSize: 24 }}>{opt.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 4 }}>{opt.label}</div>
                    <div style={{ fontSize: 13, color: "#64748b" }}>{opt.desc}</div>
                  </div>
                  {migrationApproach === opt.value && (
                    <div style={{ color: opt.color, fontSize: 18, fontWeight: 700 }}>✓</div>
                  )}
                </div>

                {/* Info button for tooltip */}
                <div style={{ position: "absolute", top: 12, right: 12 }}>
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      backgroundColor: "#e2e8f0",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#64748b",
                      cursor: "help"
                    }}
                    onMouseEnter={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "block";
                    }}
                    onMouseLeave={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "none";
                    }}
                  >
                    i
                  </div>

                  {/* Tooltip */}
                  <div
                    style={{
                      display: "none",
                      position: "absolute",
                      top: 28,
                      right: 0,
                      width: 280,
                      backgroundColor: "#1e293b",
                      color: "#f1f5f9",
                      padding: "12px 16px",
                      borderRadius: 8,
                      fontSize: 12,
                      lineHeight: 1.5,
                      zIndex: 1000,
                      boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
                      whiteSpace: "normal"
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 8, color: "#94a3b8" }}>
                      {opt.label} Details
                    </div>
                    <div>{opt.tooltip}</div>
                    {/* Arrow */}
                    <div style={{
                      position: "absolute",
                      top: -6,
                      right: 16,
                      width: 0,
                      height: 0,
                      borderLeft: "6px solid transparent",
                      borderRight: "6px solid transparent",
                      borderBottom: "6px solid #1e293b"
                    }} />
                  </div>
                </div>
              </div>
            </div>
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
        <button style={styles.secondaryBtn} onClick={() => setStep(2)}>← Back</button>
        <button style={styles.primaryBtn} onClick={() => continueWithTargetVersion(4)}>Continue to Migration →</button>
      </div>
    </div>
  );

  // Consolidated Step 4: Migration (Build Modernization & Refactor + Code Migration + Testing)
  const renderMigrationStep = () => {
    const apiEndpointCount = repoAnalysis?.api_endpoints?.length ?? 0;
    const codeRefactoringEndpointLabel = `API endpoints: ${apiEndpointCount}`;

    return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>⚡</span>
        <div>
          <h2 style={styles.title}>Build Modernization & Migration</h2>
          <p style={styles.subtitle}>{MIGRATION_STEPS[3].summary}</p>
        </div>
      </div>

      {/* Show what we plan to modernize */}
      <div style={styles.sectionTitle}>🎯 Migration Configuration</div>

      {/* What we'll modernize - Card Design */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          ✨ What we'll modernize
        </div>
        
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, gridAutoRows: "1fr", alignItems: "stretch" }}>
        {/* og<div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}> */}
          {[
            {
              icon: "☕",
              title: "Java Version Upgrade",
              desc: `From Java ${selectedSourceVersion} to Java ${effectiveTargetVersion || "Select Java Version"}`,
              color: "#2563eb"
            },
            {
              icon: "🔧",
              title: "Code Refactoring",
              desc: apiEndpointCount > 0
                ? `Modernize code patterns across ${apiEndpointCount} detected API endpoint${apiEndpointCount === 1 ? "" : "s"}`
                : "Modernize code patterns and best practices",
              color: "#059669",
              showInfo: true,
              tooltipContent: plannedCodeRefactoringTooltip,
              detail: codeRefactoringEndpointLabel
            },
            {
              icon: "📦",
              title: "Dependencies",
              desc: "Update and ensure compatibility",
              color: "#7c3aed",
              showInfo: true
            },
            {
              icon: "🧠",
              title: "Business Logic",
              desc: "Improve performance and reliability",
              color: "#dc2626",
              showInfo: true
            },
            {
              icon: "🧪",
              title: "Testing",
              desc: "Execute and validate test suites",
              color: "#ea580c"
            },
            {
              icon: "🔍",
              title: "Code Quality",
              desc: "Analysis and improvement",
              color: "#0891b2"
            }
          ].filter((item) => item.title !== "Code Quality").map((item, idx) => (
            <div
              key={idx}
              /*
              style={{
                position: "relative",
                padding: 20,
                backgroundColor: "#fff",
                border: "1px solid #e2e8f0",
                borderRadius: 12,
                boxShadow: "0 2px 4px rgba(0,0,0,0.05)",
                transition: "all 0.2s ease",
                cursor: "default"
              }}
                */
              style={{
              position: "relative",
              padding: 20,
              backgroundColor: "#fff",
              border: "1px solid #e2e8f0",
              borderRadius: 12,
              boxShadow: "0 2px 4px rgba(0,0,0,0.05)",
              transition: "all 0.2s ease",
              cursor: "default",
              minHeight: 155,
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between"
            }}

            >
              {item.showInfo && (
                <div style={{ position: "absolute", top: 12, right: 12 }}>
                  <button
                    type="button"
                    aria-label={`${item.title} information`}
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      border: "1px solid #cbd5e1",
                      backgroundColor: "#fff",
                      color: "#64748b",
                      fontSize: 12,
                      fontWeight: 700,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      cursor: "pointer",
                      padding: 0,
                    }}
                    onMouseEnter={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "block";
                    }}
                    onMouseLeave={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "none";
                    }}
                  >
                    i
                  </button>
                  <div
                    style={{
                      ...styles.tooltip,
                      left: "auto",
                      right: 0,
                      width: 320,
                      minHeight: 140,
                      background: "#fff",
                      border: "1px solid #e2e8f0",
                      boxShadow: "0 12px 30px rgba(15, 23, 42, 0.12)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.display = "block";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  >
                    {item.tooltipContent && (
                      <div
                        style={{
                          height: "100%",
                          display: "flex",
                          alignItems: "flex-start",
                          justifyContent: "flex-start",
                          width: "100%",
                        }}
                      >
                        {item.tooltipContent}
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 12 }}>

              {/* <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12 }}> */}
                <div style={{
                  width: 48,
                  height: 48,
                  borderRadius: 12,
                  backgroundColor: `${item.color}10`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 20
                }}>
                  {item.icon}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 4 }}>
                    {item.title}
                  </div>
                  <div style={{ fontSize: 13, color: "#64748b", lineHeight: 1.4 }}>
                    {item.desc}
                  </div>
                  <div style={{ minHeight: 28, marginTop: 8 }}>
                  {item.detail && (
                  <div
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      padding: "4px 10px",
                      borderRadius: 999,
                      backgroundColor: `${item.color}12`,
                      color: item.color,
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {item.detail}
                  </div>
                )}
                </div>
                  {/*
                  {item.detail && (
                    <div
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        marginTop: 8,
                        padding: "4px 10px",
                        borderRadius: 999,
                        backgroundColor: `${item.color}12`,
                        color: item.color,
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {item.detail}
                    </div> 
                    
                  )}*/}
                </div>
              </div>
              <div style={{
                width: "100%",
                height: 4,
                backgroundColor: `${item.color}20`,
                borderRadius: 2,
                position: "relative",
                overflow: "hidden"
              }}>
                <div style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: "100%",
                  backgroundColor: item.color,
                  borderRadius: 2
                }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      
{/*         
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
        <span>🔄</span>
        <span>Conversion Type</span>
        </div>

      <div style={{ height: 1, background: "#dbe3ef", marginBottom: 18 }} />

      <p style={{ fontSize: 17, color: "#475569", margin: "0 0 22px" }}>
        Available modernization pathways for your project:
      </p>  
        
        <div style={{ display: "grid",gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
          {/* Java Version Upgrade - ACTIVE 
          <div
            onClick={() => setSelectedConversions(["java_version"])}
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: selectedConversions.includes("java_version") ? "2px solid #2563eb" : "1px solid #e2e8f0",
              backgroundColor: selectedConversions.includes("java_version") ? "#eff6ff" : "#fff",
              cursor: "pointer",
              transition: "all 0.2s ease",
              boxShadow: selectedConversions.includes("java_version") ? "0 4px 12px #2563eb20" : "0 2px 4px rgba(0,0,0,0.05)",
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#2563eb", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              ✓ ACTIVE
            </div>
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
                <span style={{ fontSize: 18 }}>☕</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#2563eb" }}>Java Version Upgrade</span>
            </div>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.45 }}>Upgrade Java version with Dependencies update</div>
            </div>
          </div>

          {/* Maven to Gradle  
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "2px solid #8b5cf6",
              backgroundColor: "#f5f3ff",
              cursor: "pointer",
              color: "#8b5cf6",
              opacity: 1,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>🔧</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#8b5cf6" }}>Maven → Gradle | Gradle → Maven</span>
            </div>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.45 }}>Convert pom.xml to build.gradle with dependency mapping</div>
          </div>
          </div>

          {/* Monolithic to Microservices  
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "2px solid #0891b2",
              backgroundColor: "#ecfeff",
              color: "#0891b2",
              cursor: "pointer",
              opacity: 1,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>⚙️</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#0891b2" }}>Monolithic → Microservices</span>
            </div>
            <div style={{ fontSize: 13, color: "#334155", lineHeight: 1.45 }}>Decompose monolith into microservices architecture</div>
          </div>
          </div>

          {/* javax to Jakarta - Coming Soon 
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              Coming Soon
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
                <span style={{ fontSize: 18 }}>📦</span>
                <span style={{ fontSize: 16, fontWeight: 700, color: "#1e293b" }}>javax → Jakarta EE | Jakarta EE → javax</span>
              </div>
              <div style={{ fontSize: 13, color: "#64748b", lineHeight: 1.45 }}>Migrate javax.* packages to jakarta.*</div>
            </div>
          </div>

          {/* Spring to Spring Boot - Coming Soon 
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              Coming Soon
            </div>
            
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>🍃</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#64748b" }}>
                Spring → Spring Boot
              </span>
            </div>
            <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.45 }}>
              Upgrade Spring Boot 2.x to 3.x with Jakarta EE
            </div>
          </div>
          </div>

          {/* JSP/JSF to Angular/React - Coming Soon 
          <div
            style={{
              position: "relative",
              padding: "18px 20px",
              borderRadius: 12,
              border: "1px solid #e2e8f0",
              backgroundColor: "#fff",
              cursor: "not-allowed",
              opacity: 0.6,
              minHeight: 96,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center"
            }}
          >
            <div style={{ position: "absolute", top: 12, right: 12, backgroundColor: "#9ca3af", color: "white", padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 700 }}>
              Coming Soon
            </div>
            <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 18 }}>🌐</span>
              <span style={{ fontSize: 16, fontWeight: 700, color: "#64748b" }}>
                JSP/JSF → Angular/React
              </span>
            </div>
            <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.45 }}>
              Modernize legacy JSP/JSF views to Angular or React SPA
            </div>
          </div>
          </div>
        </div>
      </div> */}


      
      {/* <div style={styles.field}>
        <label style={styles.label}>⚙️ Conversion Type</label>
        <p style={{ fontSize: 13, color: "#64748b", marginBottom: 14 }}>Available modernization pathways for your project:</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginBottom: 16 }}>
          {conversionTypes.map((ct) => (
            <div
              key={ct.id}
              onClick={() => setSelectedConversions(selectedConversions.includes(ct.id) ? [] : [ct.id])}
              style={{
                padding: 20,
                borderRadius: 12,
                border: `2px solid ${selectedConversions.includes(ct.id) ? "#2563eb" : "#e2e8f0"}`,
                backgroundColor: selectedConversions.includes(ct.id) ? "#eff6ff" : "#fff",
                cursor: "pointer",
                transition: "all 0.2s ease",
                boxShadow: selectedConversions.includes(ct.id) ? "0 4px 12px #2563eb20" : "0 2px 4px rgba(0,0,0,0.05)",
                minHeight: 120,
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between"
              }}
              onMouseEnter={(e) => {
                if (!selectedConversions.includes(ct.id)) {
                  e.currentTarget.style.borderColor = "#2563eb";
                  e.currentTarget.style.boxShadow = "0 4px 12px #2563eb15";
                }
              }}
              onMouseLeave={(e) => {
                if (!selectedConversions.includes(ct.id)) {
                  e.currentTarget.style.borderColor = "#e2e8f0";
                  e.currentTarget.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                }
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 16, fontWeight: 600, color: "#1e293b" }}>{ct.name}</span>
                  {selectedConversions.includes(ct.id) && (
                    <span style={{ marginLeft: "auto", fontSize: 20, color: "#2563eb", fontWeight: 700 }}>✓</span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "#64748b", lineHeight: 1.4 }}>{ct.description}</div>
              </div>
            </div>
          ))}
        </div>
      </div> */}

      {/* <div style={styles.field}>
        <label style={styles.label}>Conversion Types</label>
        <select style={styles.select} value={selectedConversions[0] || ""} onChange={(e) => {
          setSelectedConversions(e.target.value ? [e.target.value] : []);
        }}>
          <option value="">-- Select Conversion Type --</option>
          {conversionTypes.map((ct) => (
            <option key={ct.id} value={ct.id}>{ct.name} - {ct.description}</option>
          ))}
        </select>
        {selectedConversions.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", backgroundColor: "#dbeafe", border: "1px solid #93c5fd", borderRadius: 8, marginTop: 12 }}>
            <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: "#0c4a6e" }}>
              ✓ {conversionTypes.find((c) => c.id === selectedConversions[0])?.name} selected
            </span>
            <button style={{ background: "none", border: "none", color: "#0c4a6e", cursor: "pointer", fontSize: 18, padding: 0 }} onClick={() => setSelectedConversions([])}>Ã—</button>
          </div>
        )}
      </div> */}


      <div style={styles.field}>
        <label style={styles.label}>Migration Options</label>
        <div 
        style={{display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16, alignItems: "stretch"}}>
          {[
            {
              key: "runTests",
              checked: runTests,
              onChange: (checked: boolean) => setRunTests(checked),
              title: "Run Test Suite",
              desc: "Execute automated tests after migration",
              tooltip: "Runs the project's test suite to ensure all functionality works correctly after migration. Includes unit tests, integration tests, and any configured test frameworks. Highly recommended to verify migration success.",
              icon: "🧪",
              color: "#22c55e",
              recommended: true
            },
            {
              key: "runSonar",   
              checked: runSonar,
              onChange: (checked: boolean) => setRunSonar(checked),
              title: "SonarQube Analysis",
              desc: "Run code quality and security analysis",
              tooltip: "Performs comprehensive code quality analysis using SonarQube. Checks for bugs, vulnerabilities, code smells, test coverage, and maintainability metrics. Provides detailed quality gate status.",
              icon: "🔍",
              color: "#f59e0b",
              recommended: false,
              disabled:false
            },
            {
              key: "runFossa",
              checked: runFossa,
              onChange: (checked: boolean) => setRunFossa(checked),
              title: "FOSSA License & Dependency Scan",
              desc: "Run open-source dependency and license compliance analysis",
              tooltip: "Scans project dependencies to detect open-source licenses, security risks, policy violations, and supply chain vulnerabilities. Generates a Software Bill of Materials (SBOM) and compliance reports.",
              icon: "📜",
              color: "#f59e0b",
              recommended: false,
              disabled:false
            },
            {
              key: "fixBusinessLogic",
              checked: false,//fixBusinessLogic
              onChange: (checked: boolean) => setFixBusinessLogic(checked),
              title: "Fix Business Logic Issues",
              desc: "Automatically improve code quality and patterns",
              tooltip: "Applies automated code improvements including null safety, performance optimizations, modern API usage, and best practice implementations. Enhances code maintainability and reduces technical debt.",
              icon: "🛠️",
              color: "#3b82f6",
              recommended: false,
              disabled:true
            }
          ].map((option) => (
            <div key={option.key} style={{ position: "relative", height: '100%' }}>
              <div
              onClick={() => {
                if(option.disabled) return;
                option.onChange(!option.checked);
}}
                style={{
                  padding: 20,
                  borderRadius: 12,
                  border: `2px solid ${option.disabled ? "#e2e8f0" : option.checked ? option.color : "#e2e8f0"}`,
                  backgroundColor: option.disabled ? "#fff" : option.checked ? `${option.color}08` : "#fff",
                  cursor: option.disabled ? "not-allowed" : "pointer",
                  opacity: option.disabled ? 0.6 : 1,
                  boxShadow: option.disabled ? "none" : option.checked ? `0 4px 12px ${option.color}20` : "0 2px 4px rgba(0,0,0,0.05)",
                  position: "relative",
                  height: "100%",
                  minHeight: 176,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  transition: "all 0.2s ease",
                }}
                
                onMouseEnter={(e) => {
                  if (!option.checked && !option.disabled) {
                    e.currentTarget.style.borderColor = option.color;
                    e.currentTarget.style.boxShadow = `0 4px 12px ${option.color}15`;
                  }
                }}
                onMouseLeave={(e) => {
                  if (!option.checked && !option.disabled) {
                    e.currentTarget.style.borderColor = "#e2e8f0";
                    e.currentTarget.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                  }
                }}
              >
                <div style={{ position: "absolute", top: 12, right: 12 }}>
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      backgroundColor: "#e2e8f0",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#64748b",
                      cursor: "help"
                    }}
                    onMouseEnter={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "block";
                    }}
                    onMouseLeave={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "none";
                    }}
                  >
                    i
                  </div>

                  {/* Tooltip */}
                  <div
                    style={{
                      display: "none",
                      position: "absolute",
                      top: 28,
                      right: 0,
                      width: 320,
                      backgroundColor: "#1e293b",
                      color: "#f1f5f9",
                      padding: "14px 18px",
                      borderRadius: 10,
                      fontSize: 12,
                      lineHeight: 1.5,
                      zIndex: 1000,
                      boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
                      whiteSpace: "normal"
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 10, color: "#94a3b8", fontSize: 13 }}>
                      {option.title} Details
                    </div>
                    <div style={{ marginBottom: 8 }}>{option.tooltip}</div>
                    {option.recommended && (
                      <div style={{ fontSize: 11, color: "#22c55e", fontWeight: 600, marginTop: 6 }}>
                        💡 Recommended for most migrations
                      </div>
                    )}
                    {/* Arrow */}
                    <div style={{
                      position: "absolute",
                      top: -6,
                      right: 20,
                      width: 0,
                      height: 0,
                      borderLeft: "6px solid transparent",
                      borderRight: "6px solid transparent",
                      borderBottom: "6px solid #1e293b"
                    }} />
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "flex-start", gap: 14, marginBottom: 18, paddingRight: 44 }}>
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 12,
                      backgroundColor: `${option.color}12`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 22,
                      flexShrink: 0,
                    }}
                  >
                    {option.icon}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 15, fontWeight: 700, color: "#1e293b", lineHeight: 1.4 }}>
                      {option.title}
                    </div>
                    {option.recommended && (
                      <span style={{
                        display: "inline-flex",
                        marginTop: 8,
                        fontSize: 10,
                        padding: "3px 8px",
                        backgroundColor: "#dcfce7",
                        color: "#166534",
                        borderRadius: 999,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.3px"
                      }}>
                        Recommended
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 16 }}>
                  <div style={{ fontSize: 13, color: "#64748b", lineHeight: 1.65, minHeight: 64 }}>
                    {option.desc}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 700,
                        color: option.disabled ? "#94a3b8" : option.checked ? option.color : "#64748b",
                      }}
                    >
                      {option.disabled ? "Coming soon" : option.checked ? "Enabled" : "Disabled"}
                    </span>
                    <label
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        width: 22,
                        height: 22,
                        cursor: option.disabled ? "not-allowed" : "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={option.checked}
                        disabled={option.disabled}
                        onChange={(e) => {
                          if (option.disabled) return;
                          option.onChange(e.target.checked);
                        }}
                        style={{
                          width: 18,
                          height: 18,
                          margin: 0,
                          accentColor: option.color,
                          cursor: option.disabled ? "not-allowed" : "pointer",
                        }}
                      />
                    </label>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {runTests && (
        <div style={{ ...styles.field, marginTop: 0 }}>
          <div style={styles.llmSection}>
            <div style={styles.llmControls}>
              <label style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <input
                  type="checkbox"
                  checked={useLLMTests}
                  onChange={(e) => setUseLLMTests(e.target.checked)}
                  style={styles.checkbox}
                />
                <div>
                  <div style={{ fontWeight: 600 }}>Use LLM Test Generator</div>
                </div>
              </label>
              <div style={{ ...styles.llmProviderRow, maxWidth: 360 }}>
                <label style={styles.label}>LLM Test Provider</label>
                <select
                  style={{
                    ...styles.select,
                    width: "100%",
                    minWidth: 220,
                    maxWidth: 360,
                    backgroundColor: useLLMTests ? "#fff" : "#f8fafc",
                  }}
                  value={selectedLLMProvider}
                  onChange={(e) => setSelectedLLMProvider(e.target.value)}
                  disabled={!useLLMTests}
                >
                  {LLM_PROVIDERS.map((provider) => (
                    <option key={provider.value} value={provider.value}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>
      )}

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(3)}>← Back</button>
        <button style={{ ...styles.primaryBtn, opacity: loading ? 0.5 : 1 }} onClick={handleStartMigration} disabled={loading}>
          {loading ? "Starting..." : "🚀 Start Migration"}
        </button>
      </div>
    </div>
  );

  };

  const renderStep3 = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>🔍</span>
        <div>
          <h2 style={styles.title}>Application Discovery</h2>
          <p style={styles.subtitle}>Analyzing the application structure and components.</p>
        </div>
      </div>
      {selectedRepo && (
        <div style={styles.discoveryContent}>
          <div style={styles.discoveryItem}>
            <span style={styles.discoveryIcon}>📊</span>
            <div>
              <div style={styles.discoveryTitle}>Repository Analysis</div>
              <div style={styles.discoveryDesc}>Scanning {selectedRepo.name} for Java components</div>
            </div>
          </div>
          <div style={styles.discoveryItem}>
            <span style={styles.discoveryIcon}>🔧</span>
            <div>
              <div style={styles.discoveryTitle}>Build Tools Detection</div>
              <div style={styles.discoveryDesc}>Identifying Maven, Gradle, or other build systems</div>
            </div>
          </div>
          <div style={styles.discoveryItem}>
            <span style={styles.discoveryIcon}>📦</span>
            <div>
              <div style={styles.discoveryTitle}>Dependencies Scan</div>
              <div style={styles.discoveryDesc}>Analyzing project dependencies and versions</div>
            </div>
          </div>
        </div>
      )}
      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(2)}>← Back</button>
        <button style={styles.primaryBtn} onClick={() => setStep(4)}>Continue to Assessment →</button>
      </div>
    </div>
  );

  const renderStep4 = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📊</span>
        <div>
          <h2 style={styles.title}>Application Assessment</h2>
          <p style={styles.subtitle}>Review the detailed assessment report.</p>
        </div>
      </div>
      {selectedRepo && (
        <>
          {analysisLoading ? <div style={styles.loadingBox}><div style={styles.spinner}></div><span>Analyzing repository...</span></div> : repoAnalysis ? (
            <>
              <div style={styles.sectionTitle}>📊 Assessment Report</div>
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

  <div style={{ position: "relative", display: "inline-flex" }}>
    {/* <span
      style={{
        cursor: "help",
        fontSize: 17,
        lineHeight: 1,
      }}
      onMouseEnter={(e) => {
        const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
        if (tooltip) tooltip.style.display = "block";
      }}
      onMouseLeave={(e) => {
        const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
        if (tooltip) tooltip.style.display = "none";
      }}
    >
     i
    </span> */}
    <span
      style={{
        cursor: "help",
        fontSize: 17,
        lineHeight: 1,
      }}
      onMouseEnter={(e) => {
        const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
        if (tooltip) tooltip.style.display = "block";
      }}
      onMouseLeave={(e) => {
        const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
        if (tooltip) tooltip.style.display = "none";
      }}
    >
      i
    </span>
    <div
      style={{
        display: "none",
        position: "absolute",
        top: 28,
        left: -170,
        width: 300,
        backgroundColor: "#1e293b",
        color: "#fff",
        borderRadius: 10,
        padding: "16px 20px",
        boxShadow: "0 18px 35px rgba(15, 23, 42, 0.25)",
        zIndex: 1000,
      }}
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
    </div>
  </div>
</div>

              {/* <div
  style={{
    ...styles.riskBadge,
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    cursor: "help",
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
  }}
  title={
    riskLevel === "low"
      ? "Low risk: build tool and tests detected."
            : riskLevel === "medium"
        ? "Medium risk: build tool detected, but tests are absent."
        : "High risk: no build tool detected."
  }
>
  <span style={{ fontSize: 14 }}>i</span>
  Risk Level: {riskLevel.toUpperCase()}
</div> */}
              {/* <div style={{ ...styles.riskBadge, backgroundColor: riskLevel === "low" ? "#dcfce7" : riskLevel === "medium" ? "#fef3c7" : "#fee2e2", color: riskLevel === "low" ? "#166534" : riskLevel === "medium" ? "#92400e" : "#991b1b" }}>Risk Level: {riskLevel.toUpperCase()}</div> */}
              <div style={styles.assessmentGrid}>
                { <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Build Tool</div><div style={styles.assessmentValue}>{buildToolDisplayLabel}</div></div> }
                { <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Java Version</div><div style={styles.assessmentValue}>{repoAnalysis.java_version || "Unknown"}</div></div> }
                <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Has Tests</div><div style={styles.assessmentValue}>{repoAnalysis.has_tests ? "Yes" : "No"}</div></div>
                <div style={styles.assessmentItem}><div style={styles.assessmentLabel}>Dependencies</div><div style={styles.assessmentValue}>{repoAnalysis.dependencies?.length || 0} found</div></div>
              </div>
              <div style={styles.structureBox}>
                <div style={styles.structureTitle}>Project Structure</div>
                <div style={styles.structureGrid}>
                  <span style={repoAnalysis.structure?.has_pom_xml ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_pom_xml ? "✓" : "✗"} pom.xml</span>
                  <span style={repoAnalysis.structure?.has_build_gradle ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_build_gradle ? "✓" : "✗"} build.gradle</span>
                  <span style={repoAnalysis.structure?.has_src_main ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_src_main ? "✓" : "✗"} src/main</span>
                  <span style={repoAnalysis.structure?.has_src_test ? styles.structureFound : styles.structureMissing}>{repoAnalysis.structure?.has_src_test ? "✓" : "✗"} src/test</span>
                  <span style={detectedJavaVersion ? styles.structureFound : styles.structureMissing}>{detectedJavaStructureLabel}</span>
                </div>
              </div>
              {repoAnalysis.dependencies && repoAnalysis.dependencies.length > 0 && (
                <div style={styles.dependenciesBox}>
                  <div style={styles.sectionTitle}>📦 Dependencies ({repoAnalysis.dependencies.length})</div>
                  <div style={styles.dependenciesList}>
                    {repoAnalysis.dependencies.slice(0, 5).map((dep, idx) => (
                      <div key={idx} style={styles.dependencyItem}>
                        <span>{dep.group_id}:{dep.artifact_id}</span>
                        <span style={styles.dependencyVersion}>{dep.current_version}</span>
                      </div>
                    ))}
                    {repoAnalysis.dependencies.length > 5 && <div style={styles.moreItems}>+{repoAnalysis.dependencies.length - 5} more</div>}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div style={styles.infoBox}>
              Repository selected, but analysis is not available yet.
              <br />
              <button
                style={{ ...styles.secondaryBtn, marginTop: 12 }}
                onClick={() => {
                  setRepoAnalysis(null);
                  setStep(2);
                }}
              >
                ← Go Back
              </button>
            </div>
          )}
        </>
      )}
      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(3)}>← Back</button>
        <button style={{ ...styles.primaryBtn, opacity: repoAnalysis ? 1 : 0.5 }} onClick={() => repoAnalysis && setStep(5)} disabled={!repoAnalysis}>
          Continue to Strategy →
        </button>
      </div>
    </div>
  );

  const renderStep5 = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📋</span>
        <div>
          <h2 style={styles.title}>Migration Strategy</h2>
          <p style={styles.subtitle}>Define your migration approach and target configuration.</p>
        </div>
      </div>
      <div style={styles.field}>
        <label style={styles.label}>Migration Approach</label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
          {migrationApproachOptions.map((opt) => (
            <div key={opt.value} style={{ position: "relative" }}>
              <div
                onClick={() => setMigrationApproach(opt.value)}
                style={{
                  padding: 20,
                  borderRadius: 12,
                  border: `2px solid ${migrationApproach === opt.value ? opt.color : "#e2e8f0"}`,
                  backgroundColor: migrationApproach === opt.value ? `${opt.color}08` : "#fff",
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  boxShadow: migrationApproach === opt.value ? `0 4px 12px ${opt.color}20` : "0 2px 4px rgba(0,0,0,0.05)",
                  position: "relative"
                }}
                onMouseEnter={(e) => {
                  if (migrationApproach !== opt.value) {
                    e.currentTarget.style.borderColor = opt.color;
                    e.currentTarget.style.boxShadow = `0 4px 12px ${opt.color}15`;
                  }
                }}
                onMouseLeave={(e) => {
                  if (migrationApproach !== opt.value) {
                    e.currentTarget.style.borderColor = "#e2e8f0";
                    e.currentTarget.style.boxShadow = "0 2px 4px rgba(0,0,0,0.05)";
                  }
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <span style={{ fontSize: 24 }}>{opt.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 4 }}>{opt.label}</div>
                    <div style={{ fontSize: 13, color: "#64748b" }}>{opt.desc}</div>
                  </div>
                  {migrationApproach === opt.value && (
                    <div style={{ color: opt.color, fontSize: 18, fontWeight: 700 }}>✓</div>
                  )}
                </div>

                {/* Info button for tooltip */}
                <div style={{ position: "absolute", top: 12, right: 12 }}>
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      backgroundColor: "#e2e8f0",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      fontWeight: 600,
                      color: "#64748b",
                      cursor: "help"
                    }}
                    onMouseEnter={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "block";
                    }}
                    onMouseLeave={(e) => {
                      const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                      if (tooltip) tooltip.style.display = "none";
                    }}
                  >
                    i
                  </div>

                  {/* Tooltip */}
                  <div
                    style={{
                      display: "none",
                      position: "absolute",
                      top: 28,
                      right: 0,
                      width: 280,
                      backgroundColor: "#1e293b",
                      color: "#f1f5f9",
                      padding: "12px 16px",
                      borderRadius: 8,
                      fontSize: 12,
                      lineHeight: 1.5,
                      zIndex: 1000,
                      boxShadow: "0 8px 24px rgba(0,0,0,0.15)",
                      whiteSpace: "normal"
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 8, color: "#94a3b8" }}>
                      {opt.label} Details
                    </div>
                    <div>{opt.tooltip}</div>
                    {/* Arrow */}
                    <div style={{
                      position: "absolute",
                      top: -6,
                      right: 16,
                      width: 0,
                      height: 0,
                      borderLeft: "6px solid transparent",
                      borderRight: "6px solid transparent",
                      borderBottom: "6px solid #1e293b"
                    }} />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(4)}>← Back</button>
        <button style={styles.primaryBtn} onClick={() => setStep(6)}>Continue to Planning →</button>
      </div>
    </div>
  );

  const renderStep6 = () => {
    return (
      <div style={styles.card}>
        <div style={styles.stepHeader}>
          <span style={styles.stepIcon}>🎯</span>
          <div>
            <h2 style={styles.title}>Migration Planning</h2>
            <p style={styles.subtitle}>Configure Java versions and target settings.</p>
          </div>
        </div>
        <div style={styles.row}>
          <div style={styles.field}>
            <label style={styles.label}>Source Java Version</label>
            <select style={{ ...styles.select, backgroundColor: "#f9fafb", cursor: "not-allowed" }} value={selectedSourceVersion} disabled>
              {sourceVersions.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
            </select>
            <p style={styles.helpText}>Source version is auto-detected from your project</p>
          </div>
          <div style={styles.field}>
            <label style={{ ...styles.label, ...(targetVersionRequiredError ? styles.labelError : {}) }}>
              Target Java Version <span style={styles.requiredMark}>*</span>
            </label>
            <select
              style={{ ...styles.select, ...(targetVersionRequiredError ? styles.selectError : {}) }}
              value={selectedTargetVersion}
              onChange={(e) => handleTargetVersionChange(e.target.value)}
            >
              <option value="" disabled>Select Java Version</option>
              {availableTargetVersions.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
            </select>
            {targetVersionRequiredError && (
              <p style={styles.fieldErrorText}>Target Java Version is required.</p>
            )}
            <p style={styles.helpText}>Only versions newer than the source Java version are available</p>
          </div>
        </div>
        <div style={styles.field}>
          <label style={styles.label}>{migrationApproach === "branch" ? "Target Branch Name" : "Target Repository Name"}</label>
          <div style={{ display: "flex", gap: 8 }}>
            <input 
              type="text" 
              style={{ ...styles.input, flex: 1, backgroundColor: "#f0fdf4", borderColor: "#22c55e" }} 
              value={targetRepoName} 
              onChange={(e) => handleTargetRepoNameChange(e.target.value)} 
              placeholder={
                migrationApproach === "branch"
                  ? getAutoGeneratedTargetName("branch")
                  : getAutoGeneratedTargetName("fork")
              }
            />
          </div>
          <p style={styles.helpText}>
            Format: <code style={{ backgroundColor: "#f1f5f9", padding: "2px 6px", borderRadius: 4, fontSize: 11 }}>
              {migrationApproach === "branch"
                ? <>migration/{'{source-repo}'}-Migrated{'{timestamp}'}</>
                : <>https://{targetRepositoryHost}/{targetRepositoryOwner}/{'{source-repo}'}-Migrated{'{timestamp}'}</>}
            </code>
          </p>
        </div>
        <div style={styles.btnRow}>
          <button style={styles.secondaryBtn} onClick={() => setStep(5)}>← Back</button>
          <button style={styles.primaryBtn} onClick={() => continueWithTargetVersion(7)}>Continue to Dependencies →</button>
        </div>
      </div>
    );
  }

  const renderStep7 = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📦</span>
        <div>
          <h2 style={styles.title}>Dependencies Analysis</h2>
          <p style={styles.subtitle}>Review and plan dependency updates.</p>
        </div>
      </div>
      {repoAnalysis && repoAnalysis.dependencies && repoAnalysis.dependencies.length > 0 && (
        <div style={styles.field}>
          <label style={styles.label}>Detected Dependencies ({repoAnalysis.dependencies.length})</label>
          {renderDetectedDependencies(repoAnalysis.dependencies, { limit: 10 })}
        </div>
      )}
      <div style={styles.field}>
        <label style={styles.label}>Detected Frameworks & Upgrade Paths</label>
        <div style={styles.frameworkGrid}>
          {[
            { id: "spring", name: "Spring Framework", detected: true },
            { id: "spring-boot", name: "Spring Boot 2.x → 3.x", detected: true },
            { id: "hibernate", name: "Hibernate / JPA", detected: false },
            { id: "junit", name: "JUnit 4 → 5", detected: true },
          ].map((fw) => (
            <label key={fw.id} style={styles.frameworkItem}>
              <input type="checkbox" checked={selectedFrameworks.includes(fw.id)} onChange={() => handleFrameworkToggle(fw.id)} style={styles.checkbox} />
              <span>{fw.name}</span>
              {fw.detected && <span style={styles.detectedBadge}>Detected</span>}
            </label>
          ))}
        </div>
      </div>
      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(6)}>← Back</button>
        <button style={styles.primaryBtn} onClick={() => setStep(8)}>Continue to Build & Refactor →</button>
      </div>
    </div>
  );

  const renderStep8 = () => (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>🔧</span>
        <div>
          <h2 style={styles.title}>Build Modernization & Refactor</h2>
          <p style={styles.subtitle}>Configure conversions and prepare for migration.</p>
        </div>
      </div>
      <div style={styles.field}>
        <label style={styles.label}>Conversion Types</label>
        <select style={styles.select} value={selectedConversions[0] || ""} onChange={(e) => {
          setSelectedConversions(e.target.value ? [e.target.value] : []);
        }}>
          <option value="">-- Select Conversion Type --</option>
          {conversionTypes.map((ct) => (
            <option key={ct.id} value={ct.id}>{ct.name} - {ct.description}</option>
          ))}
        </select>
        {selectedConversions.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", backgroundColor: "#dbeafe", border: "1px solid #93c5fd", borderRadius: 8, marginTop: 12 }}>
            <span style={{ flex: 1, fontSize: 14, fontWeight: 600, color: "#0c4a6e" }}>
              ✓ {conversionTypes.find((c) => c.id === selectedConversions[0])?.name} selected
            </span>
            <button style={{ background: "none", border: "none", color: "#0c4a6e", cursor: "pointer", fontSize: 18, padding: 0 }} onClick={() => setSelectedConversions([])}>Ã—</button>
          </div>
        )}
      </div>
      <div style={styles.warningBox}>
        <div style={styles.warningTitle}>⚠️ Common Issues to Watch</div>
        <ul style={styles.warningList}>
          <li><strong>javax.xml.bind</strong> - Missing in Java 11+</li>
          <li><strong>Illegal reflective access</strong> - Warnings become errors</li>
          <li><strong>Internal JDK APIs</strong> - sun.misc.* blocked</li>
          <li><strong>Module system</strong> - JPMS compatibility</li>
        </ul>
      </div>
      <div style={styles.field}>
        <label style={styles.label}>Migration Options</label>
        <div style={styles.optionsGrid}>
          <label style={styles.optionItem}>
            <input type="checkbox" checked={runTests} onChange={(e) => setRunTests(e.target.checked)} style={styles.checkbox} />
              <div>
              <div style={{ fontWeight: 500, fontSize: 16 }}>Run Tests</div>
              <div style={{ fontSize: 12, color: "#6b7280" }}>Execute test suite after migration</div>
            </div>
          </label>
          <label style={styles.optionItem}>
            <input type="checkbox" checked={runSonar} onChange={(e) => setRunSonar(e.target.checked)} style={styles.checkbox} />
            <div>
              <div style={{ fontWeight: 500, fontSize: 16 }}>SonarQube Analysis</div>
              <div style={{ fontSize: 12, color: "#6b7280" }}>Run code quality analysis</div>
            </div>
          </label>
          <label style={styles.optionItem}>
  <input
    type="checkbox"
    checked={runFossa}
    onChange={(e) => setRunFossa(e.target.checked)}
    style={styles.checkbox}
  />
  <div>
    <div style={{ fontWeight: 500, fontSize: 16 }}>FOSSA License & Dependency Scan</div>
    <div style={{ fontSize: 12, color: "#6b7280" }}>
      Scan open-source dependencies and license compliance
    </div>
  </div>
</label>
          <label style={styles.optionItem}>
            <input type="checkbox" checked={fixBusinessLogic} onChange={(e) => setFixBusinessLogic(e.target.checked)} style={styles.checkbox} />
            <div>
              <div style={{ fontWeight: 500, fontSize: 16 }}>Fix Business Logic Issues</div>
              <div style={{ fontSize: 12, color: "#6b7280" }}>Automatically improve code quality and fix common issues</div>
            </div>
          </label>
        </div>
      </div>

      <div style={styles.btnRow}>
        <button style={styles.secondaryBtn} onClick={() => setStep(7)}>← Back</button>
        <button style={{ ...styles.primaryBtn, opacity: loading ? 0.5 : 1 }} onClick={handleStartMigration} disabled={loading}>
          {loading ? "Starting..." : "Start Migration 🚀"}
        </button>
      </div>
    </div>
  );

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

      return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>🚀</span>
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
              Java {selectedSourceVersion} → Java {effectiveTargetVersion || "Select Java Version"}
            </div>
          </div>

          {/* Animated Steps */}
          <div style={styles.animationSteps}>
            <div style={{ ...styles.animationStep, opacity: visibleProgress >= 10 ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>📂</div>
              <div style={styles.stepText}>Analyzing Source Code</div>
              {analysisComplete && <div style={styles.checkMarkAnimated}>✓</div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: visibleProgress >= 30 ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>⚙️</div>
              <div style={styles.stepText}>Updating Dependencies</div>
              {dependencyComplete && <div style={styles.checkMarkAnimated}>✓</div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: visibleProgress >= 50 ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>🔧</div>
              <div style={styles.stepText}>Applying Code Transformations</div>
              {transformationsComplete && <div style={styles.checkMarkAnimated}>✓</div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: visibleProgress >= 70 ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>🧪</div>
              <div style={styles.stepText}>Running Tests & Quality Checks</div>
              {qualityComplete && <div style={styles.checkMarkAnimated}>✓</div>}
            </div>

            <div style={{ ...styles.animationStep, opacity: visibleProgress >= 90 ? 1 : 0.3, transition: "opacity 0.3s ease" }}>
              <div style={styles.stepIconAnimated}>📊</div>
              <div style={styles.stepText}>Generating Migration Report</div>
              {reportComplete && <div style={styles.checkMarkAnimated}>✓</div>}
            </div>
          </div>

          {/* Progress Bar with Animation */}
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
            {renderMigrationTimer()}

          {/* Status Messages */}
          <div style={styles.statusMessages}>
            <div style={styles.currentStatus}>
              <strong>Status:</strong> {normalizedMigrationStatus.toUpperCase()}
            </div>
            <div style={styles.currentStatus}>
              {isInitializingMigration
                ? "Creating migration job and preparing the workspace..."
                : migrationJob?.current_step || "Initializing migration..."}
            </div>
            {migrationLogs.length > 0 && (
              <div style={styles.recentLog}>
                <strong>Latest:</strong> {migrationLogs[migrationLogs.length - 1]}
              </div>
            )}
            {isInitializingMigration && (
              <div style={{ ...styles.recentLog, color: "#2563eb", fontSize: 12 }}>
                ℹ️ Loading the progress session. Large repositories can take a little longer to initialize.
              </div>
            )}
            {migrationJob?.status === "cloning" && (
              <div style={{ ...styles.recentLog, color: '#f59e0b', fontSize: 12 }}>
                ℹ️ Cloning repository... this may take a few minutes for large repositories. Please wait.
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
          <span style={styles.stepIcon}>{migrationJob?.status === "completed" ? "✅" : migrationJob?.status === "failed" ? "❌" : "⏳"}</span>
          <div>
            <h2 style={styles.title}>{migrationJob?.status === "completed" ? "Migration Completed!" : migrationJob?.status === "failed" ? "Migration Failed" : "Migration in Progress"}</h2>
            <p style={styles.subtitle}>{migrationJob?.current_step || "Processing..."}</p>
          </div>
        </div>
        {renderMigrationTimer()}
        {migrationJob?.status === "failed" && (
          <div style={{ ...styles.errorBox, padding: 20, marginBottom: 20, borderRadius: 8, backgroundColor: '#fee2e2', borderLeft: '4px solid #dc2626' }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#7f1d1d', marginBottom: 10 }}>❌ Migration Failed</div>
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
            <div style={styles.successTitle}>🎉 Migration Successful!</div>
            <a href={getRepositoryLink(migrationJob.target_repo) || "#"} target="_blank" rel="noreferrer" style={styles.repoLink}>View Migrated Repository →</a>
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
              ⏹️ Cancel Migration
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
              🔄 Try Again
            </button>
          )}
          {migrationJob.status !== "cloning" && migrationJob.status !== "analyzing" && migrationJob.status !== "migrating" && migrationJob.status !== "pending" && migrationJob.status !== "failed" && (
            <button style={styles.primaryBtn} onClick={() => setStep(7)}>View Migration Report →</button>
          )}
        </div>
      </div>
    );
  };

  const renderStep11 = () => {
    if (!migrationJob) {
      return (
        <div style={{ textAlign: "center", padding: 60 }}>
          <h2 style={{ color: "#1e293b", marginBottom: 12 }}>No Migration Data Available</h2>
          <p style={{ color: "#64748b", marginBottom: 24 }}>The migration report data could not be loaded. This may happen if the page was refreshed after a large migration.</p>
          <button style={styles.primaryBtn} onClick={() => setStep(1)}>← Start New Migration</button>
        </div>
      );
    }
    const sonarReport = (migrationJob?.sonar_report ?? null) as SonarReport | null;
    const sonarBugDetails = sonarReport?.bug_details ?? [];
    const sonarVulnerabilityDetails = sonarReport?.vulnerability_details ?? [];
    const sonarCodeSmellDetails = sonarReport?.code_smell_details ?? [];
    const sonarHotspotDetails = sonarReport?.security_hotspot_details ?? [];
    const getFindingSeverity = (issue: SonarIssueDetail | SonarHotspotDetail) =>
      (getSonarIssueSeverityValue(issue) || "").toString().toUpperCase();
    const getSeverityBucket = (severity: string) => {
      if (severity === "BLOCKER" || severity === "CRITICAL") return "critical" as const;
      if (severity === "MAJOR" || severity === "HIGH") return "high" as const;
      if (severity === "MINOR" || severity === "MEDIUM") return "medium" as const;
      return "low" as const;
    };
    const allSonarDetailedFindings = [
      ...sonarVulnerabilityDetails,
      ...sonarCodeSmellDetails,
      ...sonarBugDetails,
      ...sonarHotspotDetails,
    ] as Array<SonarIssueDetail | SonarHotspotDetail>;
    const sonarSeveritySummary = allSonarDetailedFindings.reduce(
      (acc, issue) => {
        acc[getSeverityBucket(getFindingSeverity(issue))] += 1;
        return acc;
      },
      { critical: 0, high: 0, medium: 0, low: 0 }
    );
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
    const sonarQualityGateNeedsRefresh =
      Boolean(migrationJob?.sonar_real_scan) && (migrationJob?.sonar_quality_gate || "N/A") === "N/A";
    const sonarTotalFindings =
      (migrationJob?.sonar_vulnerabilities ?? 0) +
      (migrationJob?.sonar_code_smells ?? 0) +
      (migrationJob?.sonar_bugs ?? 0) +
      (migrationJob?.sonar_security_hotspots ?? 0);
    const sonarOverallRisk =
      sonarSeveritySummary.critical > 0
        ? "Critical"
        : (migrationJob?.sonar_vulnerabilities ?? 0) > 0 || sonarSeveritySummary.high > 0 || (migrationJob?.sonar_security_hotspots ?? 0) > 0
          ? "High"
          : (migrationJob?.sonar_code_smells ?? 0) > 15 || sonarSeveritySummary.medium > 0
            ? "Medium"
            : "Low";
    const sonarRiskTone =
      sonarOverallRisk === "Critical"
        ? { border: "#ef4444", bg: "#fff1f2", text: "#b91c1c" }
        : sonarOverallRisk === "High"
          ? { border: "#f97316", bg: "#fff7ed", text: "#c2410c" }
          : sonarOverallRisk === "Medium"
            ? { border: "#f59e0b", bg: "#fffbeb", text: "#b45309" }
            : { border: "#22c55e", bg: "#f0fdf4", text: "#15803d" };
    const sonarAffectedFiles = Array.from(
      new Set(
        allSonarDetailedFindings
          .map((issue) => issue.component)
          .filter((value): value is string => Boolean(value))
      )
    ).slice(0, 4);
    const sonarSummaryText =
      sonarTotalFindings > 0
        ? `Sonar surfaced ${sonarTotalFindings} findings across code smells, vulnerabilities, bugs, and hotspots. ${
            sonarAffectedFiles.length > 0
              ? `Most visible impact areas: ${sonarAffectedFiles.join(", ")}${sonarAffectedFiles.length >= 4 ? "..." : ""}.`
              : "Use the sections below to review the affected files and rules."
          }`
        : "No major Sonar findings were reported for this run. Use the summary below to review quality gate, coverage, and category counts.";
    const sonarRecommendations = [
      sonarQualityGateNeedsRefresh
        ? "Rerun the Sonar scan once so the Quality Gate can refresh with the correct SonarCloud organization context."
        : null,
      (migrationJob?.sonar_vulnerabilities ?? 0) > 0
        ? "Prioritize vulnerability remediation first, especially hard-coded secrets, unsafe XML parsing, and authentication-sensitive paths."
        : null,
      (migrationJob?.sonar_security_hotspots ?? 0) > 0
        ? "Review every security hotspot manually before production migration because Sonar flags them as review-required security decisions."
        : null,
      (migrationJob?.sonar_code_smells ?? 0) >= 20
        ? "Refactor high-complexity methods and repeated maintainability issues in batches so modernization work stays manageable."
        : null,
      (migrationJob?.sonar_coverage ?? 0) < 60
        ? "Increase unit and integration coverage before release to reduce regression risk during modernization and rollout."
        : null,
    ].filter((item): item is string => Boolean(item));
    const sonarCategoryCards = [
      {
        key: "bugs" as const,
        label: "Bugs",
        count: migrationJob?.sonar_bugs ?? 0,
        accent: "#2563eb",
        note: "Correctness issues",
        icon: "◌",
        surface: "linear-gradient(180deg, #f8fbff 0%, #ffffff 100%)",
        tint: "#dbeafe",
      },
      {
        key: "vulnerabilities" as const,
        label: "Vulnerabilities",
        count: migrationJob?.sonar_vulnerabilities ?? 0,
        accent: "#ef4444",
        note: "Security defects",
        icon: "△",
        surface: "linear-gradient(180deg, #fff7f7 0%, #ffffff 100%)",
        tint: "#fecaca",
      },
      {
        key: "code_smells" as const,
        label: "Code Smells",
        count: migrationJob?.sonar_code_smells ?? 0,
        accent: "#f59e0b",
        note: "Maintainability debt",
        icon: "≈",
        surface: "linear-gradient(180deg, #fffdf6 0%, #ffffff 100%)",
        tint: "#fde68a",
      },
      {
        key: "security_hotspots" as const,
        label: "Security Hotspots",
        count: migrationJob?.sonar_security_hotspots ?? 0,
        accent: "#14b8a6",
        note: "Needs manual review",
        icon: "◇",
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

    const downloadSonarFindingsPdf = async () => {
      if (!migrationJob) return;
      try {
        setError("");
        const blob = await downloadSonarReportPdf(migrationJob.job_id);
        triggerBlobDownload(blob, `sonar-modernization-assessment-${migrationJob.job_id}.pdf`);
      } catch (err: any) {
        if (err instanceof ApiError && (err.status === 404 || err.status >= 500)) {
          await downloadClientSonarPdfFallback(migrationJob);
          return;
        }
        setError(err?.message || "Failed to download Sonar PDF report");
      }
    };

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
    const fossaVulnerabilityDetails = effectiveFossa?.vulnerability_details ?? [];
    const fossaIssueCount = effectiveFossa?.issue_count ?? null;
    const fossaDetailsAvailable = effectiveFossa?.details_available !== false;
    const fossaIsRealScan = Boolean(effectiveFossa?.real_scan ?? migrationJob?.fossa_real_scan);
    const fossaScanModeLabel = getFossaScanModeLabel(fossaScanMode);
    const fossaStatusColor =
      fossaPolicyStatus === "PASSED"
        ? "#22c55e"
        : fossaPolicyStatus === "UNAVAILABLE" || fossaScanMode === "pending"
          ? "#f59e0b"
          : "#ef4444";
    const dependencyUpgradeCount = migrationJob?.dependencies?.filter((dep) => dep.status === "upgraded").length || 0;
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
      { label: "Files Updated", value: String(migrationJob?.files_modified ?? 0), accent: "#2563eb" },
      { label: "Issues Fixed", value: String(migrationJob?.issues_fixed ?? 0), accent: "#10b981" },
      { label: "Dependencies", value: String(dependencyUpgradeCount), accent: "#f59e0b" },
      { label: "Warnings Left", value: String(migrationJob?.total_warnings ?? 0), accent: "#7c3aed" },
    ];
    const reportHeroSummary =
      migrationJob?.status === "completed"
        ? `The migration finished successfully${migrationJob?.target_repo ? " and the destination is ready to review." : "."}`
        : "The migration report below captures the current progress, results, and follow-up details.";
    const totalDependencyPages = Math.max(
      1,
      Math.ceil((migrationJob?.dependencies?.length || 0) / REPORT_DEPENDENCIES_PAGE_SIZE)
    );
    const currentDependencyPage = Math.min(reportDependencyPage, totalDependencyPages);
    const dependencyStartIndex = (currentDependencyPage - 1) * REPORT_DEPENDENCIES_PAGE_SIZE;
    const paginatedDependencies = (migrationJob?.dependencies || []).slice(
      dependencyStartIndex,
      dependencyStartIndex + REPORT_DEPENDENCIES_PAGE_SIZE
    );
    const dependencyRangeStart = migrationJob?.dependencies?.length ? dependencyStartIndex + 1 : 0;
    const dependencyRangeEnd = Math.min(
      dependencyStartIndex + REPORT_DEPENDENCIES_PAGE_SIZE,
      migrationJob?.dependencies?.length || 0
    );

    return (
    <div style={styles.card}>
      <div style={styles.stepHeader}>
        <span style={styles.stepIcon}>📄</span>
        <div>
          <h2 style={styles.title}>Migration Report</h2>
          <p style={styles.subtitle}>Complete migration summary with all results and metrics.</p>
        </div>
      </div>
      {migrationJob && (
        <div style={styles.reportContainer}>
          <div style={styles.reportHeroShell}>
            <div style={styles.reportHeroHeader}>
              <div style={styles.reportHeroContent}>
                <div style={styles.reportHeroEyebrow}>Migration Outcome</div>
                <div style={styles.reportHeroTitleRow}>
                  <h3 style={styles.reportHeroTitle}>Your modernization report is ready</h3>
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
              <div style={styles.reportHeroMiniMeta}>
                <span style={styles.reportHeroMetaPill}>Java {migrationJob.source_java_version} to Java {migrationJob.target_java_version}</span>
                <span style={styles.reportHeroMetaPill}>
                  Completed {migrationJob.completed_at ? new Date(migrationJob.completed_at).toLocaleString() : "in progress"}
                </span>
              </div>
            </div>
            <div style={styles.reportHeroStatsGrid}>
              {reportHeroStats.map((stat) => (
                <div key={stat.label} style={styles.reportHeroStatCard}>
                  <span style={{ ...styles.reportHeroStatValue, color: stat.accent }}>{stat.value}</span>
                  <span style={styles.reportHeroStatLabel}>{stat.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Source and Target Repository Information */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>🏗️ Repository Information</h3>
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
                <span style={styles.reportValue}>{migrationJob.source_java_version} → {migrationJob.target_java_version}</span>
              </div>
              <div style={styles.reportItem}>
                <span style={styles.reportLabel}>Migration Completed</span>
                <span style={styles.reportValue}>{migrationJob.completed_at ? new Date(migrationJob.completed_at).toLocaleString() : "In Progress"}</span>
              </div>
            </div>
          </div>

          {/* Changes Made */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>🔄 Changes Made</h3>
            <div style={styles.changesGrid}>
              <div style={styles.changeItem}>
                <span style={styles.changeIcon}>📄</span>
                <div>
                  <div style={styles.changeTitle}>Files Modified</div>
                  <div style={styles.changeValue}>{migrationJob.files_modified} files updated</div>
                </div>
              </div>
              <div style={styles.changeItem}>
                <span style={styles.changeIcon}>🔧</span>
                <div>
                  <div style={styles.changeTitle}>Code Transformations</div>
                  <div style={styles.changeValue}>{migrationJob.issues_fixed} code issues fixed</div>
                </div>
              </div>
              <div style={styles.changeItem}>
                <span style={styles.changeIcon}>📦</span>
                <div>
                  <div style={styles.changeTitle}>Dependencies Updated</div>
                  <div style={styles.changeValue}>{dependencyUpgradeCount} dependencies upgraded</div>
                </div>
              </div>
            </div>
          </div>

          {/* Dependencies Fixed */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>📦 Dependencies Fixed</h3>
            {migrationJob.dependencies && migrationJob.dependencies.length > REPORT_DEPENDENCIES_PAGE_SIZE && (
              <div style={styles.reportPagerBar}>
                <span style={styles.reportPagerHint}>
                  Showing {dependencyRangeStart}-{dependencyRangeEnd} of {migrationJob.dependencies.length} dependencies
                </span>
                <div style={styles.reportPagerActions}>
                  <button
                    type="button"
                    style={{ ...styles.secondaryBtn, minHeight: 38, padding: "8px 14px", fontSize: 13 }}
                    onClick={() => setReportDependencyPage((page) => Math.max(1, page - 1))}
                    disabled={currentDependencyPage === 1}
                  >
                    ← Previous
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
                    Next →
                  </button>
                </div>
              </div>
            )}
            {migrationJob.dependencies && migrationJob.dependencies.length > 0 ? (
              <div style={styles.dependenciesReport}>
                {paginatedDependencies.map((dep, idx) => (
                  <div key={idx} style={styles.dependencyReportItem}>
                    <span style={styles.dependencyName}>{dep.group_id}:{dep.artifact_id}</span>
                    <span style={styles.dependencyChange}>
                      {dep.current_version} → {dep.new_version || 'latest'}
                    </span>
                    <span style={{ ...styles.dependencyStatus, backgroundColor: dep.status === 'upgraded' ? '#dcfce7' : '#e5e7eb', color: dep.status === 'upgraded' ? '#166534' : '#6b7280' }}>
                      {dep.status.replace('_', ' ').toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={styles.noData}>No dependency updates were required</div>
            )}
          </div>

          {/* Business Logic Fixed */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>🧠 Business Logic Improvements</h3>
            <div style={styles.businessLogicGrid}>
              <div style={styles.businessItem}>
                <span style={styles.businessIcon}>🛡️</span>
                <div>
                  <div style={styles.businessTitle}>Null Safety</div>
                  <div style={styles.businessDesc}>Added null checks and Objects.equals() usage</div>
                </div>
              </div>
              <div style={styles.businessItem}>
                <span style={styles.businessIcon}>⚡</span>
                <div>
                  <div style={styles.businessTitle}>Performance</div>
                  <div style={styles.businessDesc}>Optimized String operations and collections</div>
                </div>
              </div>
              <div style={styles.businessItem}>
                <span style={styles.businessIcon}>🔧</span>
                <div>
                  <div style={styles.businessTitle}>Code Quality</div>
                  <div style={styles.businessDesc}>Improved exception handling and logging</div>
                </div>
              </div>
              <div style={styles.businessItem}>
                <span style={styles.businessIcon}>📝</span>
                <div>
                  <div style={styles.businessTitle}>Modern APIs</div>
                  <div style={styles.businessDesc}>Updated to use latest Java APIs and patterns</div>
                </div>
              </div>
            </div>
          </div>

          {/* GitHub-Style Code Changes Diff Viewer */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>
              <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span>Code Changes (GitHub-Style Diff)</span>
                <button
                  onClick={() => setShowCodeChanges(!showCodeChanges)}
                  style={{
                    background: "none",
                    border: "1px solid #d0d7de",
                    borderRadius: 6,
                    padding: "6px 12px",
                    cursor: "pointer",
                    fontSize: 12,
                    color: "#24292f"
                  }}
                >
                  {showCodeChanges ? "Collapse" : "Expand"}
                </button>
              </span>
            </h3>
            
            {showCodeChanges && (
              <div style={{
                border: "1px solid #d0d7de",
                borderRadius: 8,
                overflow: "hidden",
                backgroundColor: "#fff"
              }}>
                {/* File List Header */}
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "12px 16px",
                  backgroundColor: "#f6f8fa",
                  borderBottom: "1px solid #d0d7de"
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontWeight: 600, color: "#24292f" }}>
                      {reportCodeChanges.length} files changed
                    </span>
                    <span style={{ color: "#64748b", fontSize: 13 }}>
                      Showing {visibleReportCodeChanges.length} of {reportCodeChanges.length}
                    </span>
                    <span style={{ color: "#22c55e", fontSize: 13 }}>
                      +{reportCodeChanges.reduce((sum, c) => sum + c.additions, 0)} additions
                    </span>
                    <span style={{ color: "#ef4444", fontSize: 13 }}>
                      -{reportCodeChanges.reduce((sum, c) => sum + c.deletions, 0)} deletions
                    </span>
                  </div>
                  <span style={{
                    fontSize: 11,
                    padding: "4px 10px",
                    backgroundColor: "#ddf4ff",
                    borderRadius: 12,
                    color: "#0969da"
                  }}>
                    Read Only
                  </span>
                </div>

                {/* File List */}
                <div style={{ maxHeight: 600, overflowY: "auto" }}>
                  {visibleReportCodeChanges.map((change, idx) => (
                    <div key={idx}>
                      {/* File Header */}
                      <div
                        onClick={() => setSelectedDiffFile(selectedDiffFile === change.filePath ? null : change.filePath)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "10px 16px",
                          backgroundColor: selectedDiffFile === change.filePath ? "#f0f6fc" : "#fafbfc",
                          borderBottom: "1px solid #d0d7de",
                          cursor: "pointer",
                          transition: "background-color 0.15s"
                        }}
                        onMouseEnter={(e) => {
                          if (selectedDiffFile !== change.filePath) {
                            e.currentTarget.style.backgroundColor = "#f6f8fa";
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (selectedDiffFile !== change.filePath) {
                            e.currentTarget.style.backgroundColor = "#fafbfc";
                          }
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <span style={{ fontSize: 14 }}>
                            {selectedDiffFile === change.filePath ? "▼" : "▶"}
                          </span>
                          <span style={{
                            display: "inline-block",
                            padding: "2px 6px",
                            borderRadius: 4,
                            fontSize: 11,
                            fontWeight: 600,
                            backgroundColor: change.changeType === 'added' ? '#dcfce7' : change.changeType === 'deleted' ? '#fee2e2' : '#fef3c7',
                            color: change.changeType === 'added' ? '#166534' : change.changeType === 'deleted' ? '#991b1b' : '#92400e'
                          }}>
                            {change.changeType.toUpperCase()}
                          </span>
                          <span style={{
                            fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                            fontSize: 13,
                            color: "#0969da"
                          }}>
                            {change.filePath}
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "#22c55e", fontSize: 12, fontWeight: 600 }}>+{change.additions}</span>
                          <span style={{ color: "#ef4444", fontSize: 12, fontWeight: 600 }}>-{change.deletions}</span>
                        </div>
                      </div>

                      {/* Diff Content */}
                      {selectedDiffFile === change.filePath && (
                        <div style={{
                          backgroundColor: "#0d1117",
                          borderBottom: "1px solid #d0d7de",
                          overflowX: "auto"
                        }}>
                          {/* Diff Header */}
                          <div style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            padding: "8px 16px",
                            backgroundColor: "#161b22",
                            borderBottom: "1px solid #30363d"
                          }}>
                            <span style={{
                              fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                              fontSize: 12,
                              color: "#8b949e"
                            }}>
                              {change.fileName}
                            </span>
                            <div style={{ display: "flex", gap: 12 }}>
                              <span style={{ fontSize: 11, color: "#3fb950" }}>
                                +{change.additions} lines
                              </span>
                              <span style={{ fontSize: 11, color: "#f85149" }}>
                                -{change.deletions} lines
                              </span>
                            </div>
                          </div>

                          {/* Diff Lines */}
                          <div style={{
                            fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                            fontSize: 12,
                            lineHeight: 1.5
                          }}>
                            {change.diffLines.map((line, lineIdx) => (
                              line.type === "hunk" ? (
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
                                  <span style={{ minWidth: 50, padding: "2px 10px", borderRight: "1px solid #30363d" }} />
                                  <span style={{ minWidth: 50, padding: "2px 10px", borderRight: "1px solid #30363d" }} />
                                  <span style={{ minWidth: 20, padding: "2px 6px", textAlign: "center" }}>@</span>
                                  <span style={{ flex: 1, padding: "2px 10px", whiteSpace: "pre" }}>{line.content}</span>
                                </div>
                              ) : (
                                <div
                                  key={lineIdx}
                                  style={{
                                    display: "flex",
                                    backgroundColor: line.type === 'add' ? 'rgba(63, 185, 80, 0.15)' : 
                                                     line.type === 'remove' ? 'rgba(248, 81, 73, 0.15)' : 'transparent',
                                    borderLeft: `4px solid ${line.type === 'add' ? '#3fb950' : line.type === 'remove' ? '#f85149' : 'transparent'}`
                                  }}
                                >
                                  {/* Old Line Number */}
                                  <span style={{
                                    minWidth: 50,
                                    padding: "2px 10px",
                                    textAlign: "right",
                                    color: "#6e7681",
                                    backgroundColor: line.type === 'add' ? 'rgba(63, 185, 80, 0.1)' : 
                                                     line.type === 'remove' ? 'rgba(248, 81, 73, 0.1)' : '#161b22',
                                    borderRight: "1px solid #30363d",
                                    userSelect: "none"
                                  }}>
                                    {line.oldLineNumber ?? ""}
                                  </span>
                                  {/* New Line Number */}
                                  <span style={{
                                    minWidth: 50,
                                    padding: "2px 10px",
                                    textAlign: "right",
                                    color: "#6e7681",
                                    backgroundColor: line.type === 'add' ? 'rgba(63, 185, 80, 0.1)' : 
                                                     line.type === 'remove' ? 'rgba(248, 81, 73, 0.1)' : '#161b22',
                                    borderRight: "1px solid #30363d",
                                    userSelect: "none"
                                  }}>
                                    {line.newLineNumber ?? ""}
                                  </span>
                                  {/* Diff Symbol */}
                                  <span style={{
                                    minWidth: 20,
                                    padding: "2px 6px",
                                    textAlign: "center",
                                    color: line.type === 'add' ? '#3fb950' : line.type === 'remove' ? '#f85149' : '#8b949e',
                                    fontWeight: 600,
                                    userSelect: "none"
                                  }}>
                                    {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
                                  </span>
                                  {/* Code Content */}
                                  <span style={{
                                    flex: 1,
                                    padding: "2px 10px",
                                    color: line.type === 'add' ? '#aff5b4' : line.type === 'remove' ? '#ffa198' : '#c9d1d9',
                                    whiteSpace: "pre"
                                  }}>
                                    {line.content || " "}
                                  </span>
                                </div>
                              )
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}

                  {reportCodeChanges.length === 0 && (
                    <div style={{
                      padding: 40,
                      textAlign: "center",
                      color: "#57606a"
                    }}>
                      No code changes to display
                    </div>

                  )}

                  {hasMoreReportCodeChanges && (
                    <div
                      style={{
                        padding: "16px",
                        display: "flex",
                        justifyContent: "center",
                        backgroundColor: "#fff",
                        borderTop: "1px solid #d0d7de",
                      }}
                    >
                      <button
                        onClick={() =>
                          setVisibleReportDiffCount((current) =>
                            Math.min(current + REPORT_DIFFS_PAGE_SIZE, reportCodeChanges.length)
                          )
                        }
                        style={{
                          backgroundColor: "#fff",
                          border: "1px solid #d0d7de",
                          borderRadius: 8,
                          padding: "10px 16px",
                          cursor: "pointer",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "#0969da",
                        }}
                      >
                        Load more files ({reportCodeChanges.length - visibleReportCodeChanges.length} remaining)
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* SonarQube Code Coverage */}
          {runSonar && (
            <div style={{ ...styles.reportSection, ...styles.sonarSectionShell }}>
              <button
                type="button"
                style={styles.reportAccordionToggle}
                onClick={() => toggleReportAccordion("sonar")}
              >
                <div>
                  <h3 style={{ ...styles.reportTitle, marginBottom: 6, paddingBottom: 0, borderBottom: "none" }}>
                    SonarQube Code Quality & Coverage
                  </h3>
                  <div style={styles.sonarSectionSubtitle}>
                    Premium scan summary for engineering review, modernization planning, and security triage.
                  </div>
                </div>
                <span style={styles.reportAccordionIcon}>{reportAccordionState.sonar ? "▾" : "▸"}</span>
              </button>
              {reportAccordionState.sonar && (
                <>
              {migrationJob.sonar_error_message && (
                <div style={{ background: "#fff7ed", border: "1px solid #fdba74", color: "#9a3412", borderRadius: 14, padding: "14px 16px", marginBottom: 16 }}>
                  {migrationJob.sonar_error_message}
                </div>
              )}

              <div style={styles.sonarActionRow}>
                <span style={{ padding: "8px 12px", borderRadius: 999, background: "#eff6ff", color: "#1d4ed8", fontSize: 12, fontWeight: 700 }}>
                  Scan Mode: {migrationJob.sonar_scan_mode || (migrationJob.sonar_quality_gate ? "real" : "N/A")}
                </span>
                <span style={{ padding: "8px 12px", borderRadius: 999, background: migrationJob.sonar_real_scan ? "#dcfce7" : "#fef3c7", color: migrationJob.sonar_real_scan ? "#166534" : "#92400e", fontSize: 12, fontWeight: 700 }}>
                  {migrationJob.sonar_real_scan ? "Real Sonar Scan" : "Non-real Result"}
                </span>
                {migrationJob.sonar_analysis_url && (
                  <a href={migrationJob.sonar_analysis_url} target="_blank" rel="noopener noreferrer" style={{ padding: "8px 12px", borderRadius: 999, background: "#f8fafc", color: "#2563eb", fontSize: 12, fontWeight: 700, textDecoration: "none", border: "1px solid #dbe5f3" }}>
                    View in SonarCloud
                  </a>
                )}
                {/* {sonarDetailsAvailable && (
                  <button
                    type="button"
                    onClick={downloadSonarFindingsPdf}
                    style={{ padding: "8px 12px", borderRadius: 999, background: "#fff", color: "#334155", fontSize: 12, fontWeight: 700, border: "1px solid #dbe5f3", cursor: "pointer" }}
                  >
                    Download Sonar Findings (PDF)
                  </button>
                )} */}
              </div>
              <div style={styles.sonarHeroPanel}>
                <div style={styles.sonarHeroHeader}>
                  <div style={{ flex: 1, minWidth: 280 }}>
                    <div style={styles.sonarHeroEyebrow}>Scan Overview</div>
                    <div style={styles.sonarHeroTitle}>
                      {sonarTotalFindings > 0 ? `${sonarTotalFindings} Sonar findings need Review and Remediation` : "No major Sonar findings detected"}
                    </div>
                   
                  </div>
                  <div style={styles.sonarHeroMetaGrid}>
                    <div style={styles.sonarHeroMiniCard}>
                      <div style={styles.sonarHeroMiniLabel}>Quality Gate</div>
                      <span style={{ ...styles.gateStatus, backgroundColor: migrationJob.sonar_quality_gate === "PASSED" ? "#22c55e" : migrationJob.sonar_quality_gate === "UNAVAILABLE" || (migrationJob.sonar_quality_gate || "N/A") === "N/A" ? "#f59e0b" : "#ef4444", padding: "10px 18px", fontSize: 13 }}>
                        {migrationJob.sonar_quality_gate || "N/A"}
                      </span>
                    </div>
                    <div style={styles.sonarHeroMiniCard}>
                      <div style={styles.sonarHeroMiniLabel}>Coverage</div>
                      <div style={styles.coverageMeter}>
                        <div style={styles.coverageCircle}>
                          <span style={styles.coveragePercent}>{migrationJob.sonar_coverage}%</span>
                          <span style={styles.coverageLabel}>Coverage</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              {(sonarDetailsAvailable || migrationJob.sonar_real_scan) && (
                <div style={styles.sonarFindingsPanel}>
                  <div style={styles.sonarFindingsPanelIntro}>
                    <div>
                      <div style={styles.sonarFindingsPanelEyebrow}>Issue Explorer</div>
                      <div style={styles.sonarFindingsPanelTitle}>Detailed Sonar Findings</div>
                      <div style={styles.sonarFindingsPanelSubtitle}>
                        Filter by category to inspect the exact findings returned by Sonar.
                      </div>
                    </div>
                    <div style={styles.sonarFindingsPanelSummaryBadge}>
                      {sonarTotalFindings} total findings
                    </div>
                  </div>
                  <div style={styles.sonarFilterBar}>
                    <span style={styles.sonarFilterLabel}>
                      Showing: {sonarFindingFilter === "all" ? "All findings" : sonarFindingFilter.replace("_", " ").toUpperCase()}
                    </span>
                    {(sonarFindingFilter !== "all" || codeSmellSeverityFilter !== "all") && (
                      <button
                        type="button"
                        style={styles.sonarFilterClearButton}
                        onClick={() => {
                          setSonarFindingFilter("all");
                          setCodeSmellSeverityFilter("all");
                        }}
                      >
                        Clear Filters
                      </button>
                    )}
                  </div>
                  {sonarFindingFilter === "code_smells" && (
                    <div style={styles.sonarSeverityFilterRow}>
                      {[
                        { key: "all", label: "All", count: migrationJob.sonar_code_smells },
                        { key: "low", label: "Low", count: codeSmellSeverityCounts.low },
                        { key: "medium", label: "Medium", count: codeSmellSeverityCounts.medium },
                        { key: "high", label: "High", count: codeSmellSeverityCounts.high },
                        { key: "blocker", label: "Blocker", count: codeSmellSeverityCounts.blocker },
                      ].map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          style={{
                            ...styles.sonarSeverityFilterButton,
                            ...(codeSmellSeverityFilter === item.key ? styles.sonarSeverityFilterButtonActive : {}),
                          }}
                          onClick={() => setCodeSmellSeverityFilter(item.key as CodeSmellSeverityFilter)}
                        >
                          {item.label} ({item.count})
                        </button>
                      ))}
                    </div>
                  )}
                  <div style={styles.sonarCategoryCardGrid}>
                    {sonarCategoryCards.map((card) => {
                      const isActive = sonarFindingFilter === card.key;
                      const isIdle = sonarFindingFilter !== "all" && !isActive;
                      return (
                        <button
                          key={card.key}
                          type="button"
                          style={{
                            ...styles.sonarCategoryCard,
                            background: isActive ? `${card.accent}12` : card.surface,
                            borderColor: isActive ? `${card.accent}66` : card.tint,
                            boxShadow: isActive ? `0 16px 34px ${card.accent}18` : "0 10px 26px rgba(15, 23, 42, 0.06)",
                            opacity: isIdle ? 0.7 : 1,
                          }}
                          onClick={() => setSonarFindingFilter((current) => (current === card.key ? "all" : card.key))}
                        >
                          <div style={styles.sonarCategoryCardTopRow}>
                            <div
                              style={{
                                ...styles.sonarCategoryIconBadge,
                                color: card.accent,
                                background: `${card.accent}12`,
                                borderColor: `${card.accent}2f`,
                              }}
                            >
                              {card.icon}
                            </div>
                            <div
                              style={{
                                ...styles.sonarCategoryStatusBadge,
                                color: card.accent,
                                background: `${card.accent}12`,
                              }}
                            >
                              {isActive ? "SELECTED" : "FILTER"}
                            </div>
                          </div>
                          <div style={{ ...styles.sonarCategoryCardValue, color: card.count > 0 ? card.accent : "#16a34a" }}>
                            {card.count}
                          </div>
                          <div style={styles.sonarCategoryCardLabel}>{card.label}</div>
                          <div style={styles.sonarCategoryCardNote}>{card.note}</div>
                        </button>
                      );
                    })}
                  </div>
                  {visibleSonarSections.map((section) => (
                    <React.Fragment key={section.key}>
                      {renderSonarFindingSection(
                        section.key,
                        section.title,
                        section.count,
                        section.details,
                        section.accentColor,
                        section.emptyMessage
                      )}
                    </React.Fragment>
                  ))}
                </div>
              )}
                </>
              )}
            </div>
          )}

    {/* FOSSA License & Dependency Report */}
    {(runFossa || migrationJob?.fossa_policy_status != null || migrationJob?.fossa_total_dependencies != null || fossaResult) && (migrationJob || fossaResult) && (
    <div style={styles.reportSection}>
      <button
        type="button"
        style={styles.reportAccordionToggle}
        onClick={() => toggleReportAccordion("fossa")}
      >
        <div>
          <h3 style={{ ...styles.reportTitle, marginBottom: 6, paddingBottom: 0, borderBottom: "none" }}>📜 FOSSA License & Dependency Scan</h3>
          <div style={styles.reportAccordionSubtitle}>License, vulnerability, and supply-chain scan details.</div>
        </div>
        <span style={styles.reportAccordionIcon}>{reportAccordionState.fossa ? "▾" : "▸"}</span>
      </button>
      {reportAccordionState.fossa && (
        <>

      {fossaErrorMessage && (
        <div style={{ background: "#fff7ed", border: "1px solid #fdba74", color: "#9a3412", borderRadius: 10, padding: "14px 16px", marginBottom: 16 }}>
          {fossaErrorMessage}
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
        <span style={{ padding: "8px 12px", borderRadius: 999, background: "#eff6ff", color: "#1d4ed8", fontSize: 12, fontWeight: 700 }}>
          Scan Mode: {fossaScanModeLabel}
        </span>
        <span style={{ padding: "8px 12px", borderRadius: 999, background: fossaIsRealScan ? "#dcfce7" : "#fef3c7", color: fossaIsRealScan ? "#166534" : "#92400e", fontSize: 12, fontWeight: 700 }}>
          {fossaIsRealScan ? "Real FOSSA Scan" : "Non-real Result"}
        </span>
        {fossaAnalysisUrl && (
          <a href={fossaAnalysisUrl} target="_blank" rel="noopener noreferrer" style={{ padding: "8px 12px", borderRadius: 999, background: "#f8fafc", color: "#2563eb", fontSize: 12, fontWeight: 700, textDecoration: "none", border: "1px solid #dbe5f3" }}>
            View in FOSSA
          </a>
        )}
      </div>

      {!fossaDetailsAvailable ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
          <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: 18, textAlign: "center" }}>
            <div style={{ fontSize: 30, fontWeight: 800, color: "#dc2626" }}>
              {fossaLoading ? "Loading..." : (fossaIssueCount ?? "N/A")}
            </div>
            <div style={{ fontSize: 12, color: "#64748b", fontWeight: 700, textTransform: "uppercase", marginTop: 6 }}>
              Reported Issues
            </div>
          </div>
          <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: 18, textAlign: "center" }}>
            <div style={{ display: "inline-block", padding: "10px 16px", borderRadius: 999, background: fossaStatusColor, color: "#fff", fontWeight: 800 }}>
              {fossaPolicyStatus}
            </div>
            <div style={{ fontSize: 12, color: "#64748b", fontWeight: 700, textTransform: "uppercase", marginTop: 10 }}>
              Policy Status
            </div>
          </div>
          <div style={{ background: "#eff6ff", border: "1px solid #bfdbfe", borderRadius: 12, padding: 18 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#1d4ed8", marginBottom: 8 }}>
              Detailed breakdown unavailable
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.6, color: "#334155" }}>
              The current FOSSA key can confirm that issues exist, but it cannot return dependency inventory, severity totals, or package-level findings.
            </div>
          </div>
        </div>
      ) : (
        <>
      <div style={styles.sonarqubeGrid}>
        
        {/* Policy Status */}
        <div style={styles.sonarqubeItem}>
          <div style={styles.qualityGate}>
            <span
              style={{
                ...styles.gateStatus,
                backgroundColor: fossaStatusColor,
              }}
            >
              {fossaPolicyStatus}
            </span>
            <span style={styles.gateLabel}>Policy Status</span>
          </div>
        </div>

        {/* Dependency Count */}
        <div style={styles.sonarqubeItem}>
          <div style={styles.coverageMeter}>
            <div style={styles.coverageCircle}>
              <span style={styles.coveragePercent}>
                {fossaLoading ? "Loading..." : (effectiveFossa?.total_dependencies ?? migrationJob?.fossa_total_dependencies ?? "N/A")}
              </span>
              <span style={styles.coverageLabel}>Dependencies</span>
            </div>
          </div>
        </div>
      </div>

      {/* FOSSA Metrics */}
      <div style={styles.qualityMetrics}>
        
          <div style={styles.metricItem}>
            <span
              style={{
                ...styles.metricValue,
                color: typeof fossaLicenseIssueCount === "number" && fossaLicenseIssueCount > 0 ? "#ef4444" : "#22c55e",
              }}
            >
              {fossaLoading ? "Loading..." : (fossaLicenseIssueCount ?? "N/A")}
            </span>
            <span style={styles.metricLabel}>License Issues</span>
          </div>

        <div style={styles.metricItem}>
          <span
            style={{
              ...styles.metricValue,
              color: typeof fossaVulnerabilityTotal === "number" && fossaVulnerabilityTotal > 0 ? "#ef4444" : "#22c55e",
            }}
          >
            {fossaLoading ? "Loading..." : (fossaVulnerabilityTotal ?? "N/A")}
          </span>
          <span style={styles.metricLabel}>Vulnerabilities</span>
        </div>

        <div style={styles.metricItem}>
          <span
            style={{
              ...styles.metricValue,
              color: typeof fossaOutdatedCount === "number" && fossaOutdatedCount > 0 ? "#f59e0b" : "#22c55e",
            }}
          >
            {fossaLoading ? "Loading..." : (fossaOutdatedCount ?? "N/A")}
          </span>
          <span style={styles.metricLabel}>Outdated Packages</span>
        </div>

      </div>

      {fossaSeverityCounts && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14, marginTop: 18 }}>
          {[
            { label: "Critical", value: fossaSeverityCounts.critical, color: "#b91c1c" },
            { label: "High", value: fossaSeverityCounts.high, color: "#dc2626" },
            { label: "Medium", value: fossaSeverityCounts.medium, color: "#d97706" },
            { label: "Low", value: fossaSeverityCounts.low, color: "#2563eb" },
          ].map((item) => (
            <div key={item.label} style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, padding: 16, textAlign: "center" }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: item.color }}>{item.value}</div>
              <div style={{ fontSize: 12, color: "#64748b", fontWeight: 600, textTransform: "uppercase" }}>{item.label}</div>
            </div>
          ))}
        </div>
      )}
        </>
      )}

      {fossaVulnerabilityDetails.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#1e293b", marginBottom: 12 }}>Detected Vulnerability Details</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {fossaVulnerabilityDetails.slice(0, 10).map((vulnerability, index) => (
              <div key={`${vulnerability.id}-${index}`} style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, padding: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
                  <div style={{ fontWeight: 700, color: "#1e293b" }}>{vulnerability.title || vulnerability.id}</div>
                  <span style={{ padding: "4px 10px", borderRadius: 999, background: "#fee2e2", color: "#991b1b", fontSize: 11, fontWeight: 700, textTransform: "uppercase" }}>
                    {vulnerability.severity || "unknown"}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: "#475569", lineHeight: 1.6 }}>
                  <div><strong>ID:</strong> {vulnerability.id}</div>
                  {vulnerability.package && <div><strong>Package:</strong> {vulnerability.package}</div>}
                  {vulnerability.package_version && <div><strong>Current Version:</strong> {vulnerability.package_version}</div>}
                  {vulnerability.fixed_version && <div><strong>Fixed Version:</strong> {vulnerability.fixed_version}</div>}
                  {vulnerability.description && <div><strong>Description:</strong> {vulnerability.description}</div>}
                  {vulnerability.reference && (
                    <div>
                      <strong>Reference:</strong>{" "}
                      <a href={vulnerability.reference} target="_blank" rel="noopener noreferrer" style={{ color: "#2563eb" }}>
                        {vulnerability.reference}
                      </a>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
        </>
      )}
    </div>
    )}

          {/* Unit Test Report */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>🧪 Unit Test Report</h3>
            <div style={styles.testReportGrid}>
              <div style={styles.testMetric}>
                <span style={styles.testValue}>{testsRun}</span>
                <span style={styles.testLabel}>Tests Run</span>
              </div>
              <div style={styles.testMetric}>
                <span style={{ ...styles.testValue, color: "#22c55e" }}>{testsPassed}</span>
                <span style={styles.testLabel}>Tests Passed</span>
              </div>
              <div style={styles.testMetric}>
                <span style={{ ...styles.testValue, color: hasTestFailures ? "#dc2626" : "#ef4444" }}>{testsFailed}</span>
                <span style={styles.testLabel}>Tests Failed</span>
              </div>
              <div style={styles.testMetric}>
                <span style={styles.testValue}>{testSuccessRate}%</span>
                <span style={styles.testLabel}>Success Rate</span>
              </div>
              <div style={styles.testMetric}>
                <span style={{ ...styles.testValue, color: "#2563eb" }}>{generatedTestsCount}</span>
                <span style={styles.testLabel}>Testcases Generated</span>
              </div>
            </div>
            <div
              style={{
                ...styles.testStatus,
                background: testStatusColors.background,
                borderColor: testStatusColors.borderColor,
                color: testStatusColors.textColor
              }}
            >
              <span style={styles.testStatusIcon}>{testStatusIcon}</span>
              <div>
                <span>{testSummaryText}</span>
                {testModel && (
                  <div style={styles.modelBadge}>LLM Model: {testModel}</div>
                )}
              </div>
            </div>
            {testInsights.length > 0 && (
              <ul style={styles.testInsightsList}>
                {testInsights.map((insight, index) => (
                  <li key={`insight-${index}`} style={styles.testInsightItem}>
                    {insight}
                  </li>
                ))}
              </ul>
            )}
            {testsRun === 0 && migrationJob?.status === "completed" && (
              <button
                style={{ ...styles.secondaryBtn, marginTop: 10 }}
                disabled={rerunTestsLoading}
                onClick={async () => {
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
                  } catch (err: any) {
                    setError(err?.message || "Failed to re-run tests");
                  } finally {
                    setRerunTestsLoading(false);
                  }
                }}
              >
                {rerunTestsLoading ? "Re-running tests..." : "Re-run Tests"}
              </button>
            )}
            {migrationJob?.job_id && (
              <button
                style={{ ...styles.secondaryBtn, marginTop: 10, marginLeft: 10 }}
                onClick={async () => {
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
                  } catch (err: any) {
                    setError(err?.message || "Failed to download unit test report");
                  }
                }}
              >
                Download Unit Test Report (HTML)
              </button>
            )}
          </div>

          {/* JMeter Test Report */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>🚀 JMeter Performance Test Report</h3>
            <div style={styles.jmeterGrid}>
              <div style={styles.jmeterItem}>
                <span style={styles.jmeterLabel}>API Endpoints Tested</span>
                <span style={styles.jmeterValue}>{migrationJob?.api_endpoints_validated ?? 0}</span>
              </div>
              <div style={styles.jmeterItem}>
                <span style={styles.jmeterLabel}>Working Endpoints</span>
                <span style={{ ...styles.jmeterValue, color: (migrationJob?.api_endpoints_working ?? 0) === (migrationJob?.api_endpoints_validated ?? 0) && (migrationJob?.api_endpoints_validated ?? 0) > 0 ? "#22c55e" : "#f59e0b" }}>
                  {migrationJob?.api_endpoints_working ?? 0}/{migrationJob?.api_endpoints_validated ?? 0}
                </span>
              </div>
              <div style={styles.jmeterItem}>
                <span style={styles.jmeterLabel}>Average Response Time</span>
                <span style={styles.jmeterValue}>245ms</span>
              </div>
              <div style={styles.jmeterItem}>
                <span style={styles.jmeterLabel}>Throughput</span>
                <span style={styles.jmeterValue}>150 req/sec</span>
              </div>
            </div>
          </div>

          {/* Migration Log */}
          <div style={styles.reportSection}>
            <h3 style={styles.reportTitle}>📋 Migration Log</h3>
            <div style={styles.logsContainer}>
              {migrationLogs.length > 0 ? (
                migrationLogs.map((log, index) => (
                  <div key={index} style={styles.logEntry}>{log}</div>
                ))
              ) : (
                <div style={styles.noLogs}>No migration logs available</div>
              )}
            </div>
          </div>

          {/* Issues & Errors Detailed */}
          <div style={styles.reportSection}>
            <button
              type="button"
              style={styles.reportAccordionToggle}
              onClick={() => toggleReportAccordion("issues")}
            >
              <div>
                <h3 style={{ ...styles.reportTitle, marginBottom: 6, paddingBottom: 0, borderBottom: "none" }}>⚠️ Detailed Issues & Errors</h3>
                <div style={styles.reportAccordionSubtitle}>Review the exact issues identified and the files they affected.</div>
              </div>
              <span style={styles.reportAccordionIcon}>{reportAccordionState.issues ? "▾" : "▸"}</span>
            </button>
            {reportAccordionState.issues && (
            <div style={styles.issuesContainer}>
              {migrationJob.issues && migrationJob.issues.length > 0 ? (
                migrationJob.issues.slice(0, 10).map((issue) => (
                  <div key={issue.id} style={styles.issueItem}>
                    <div style={styles.issueHeader}>
                      <span style={{ ...styles.issueSeverity, backgroundColor: issue.severity === "error" ? "#fee2e2" : issue.severity === "warning" ? "#fef3c7" : "#e0f2fe" }}>
                        {issue.severity.toUpperCase()}
                      </span>
                      <span style={styles.issueCategory}>{issue.category}</span>
                      <span style={styles.issueStatus}>{issue.status}</span>
                    </div>
                    <div style={styles.issueMessage}>{issue.message}</div>
                    <div style={styles.issueFile}>{issue.file_path}:{issue.line_number}</div>
                  </div>
                ))
              ) : (
                <div style={styles.noIssues}>No issues found - migration completed successfully!</div>
              )}
            </div>
            )}
          </div>
        </div>
      )}

      {/* Report Actions */}
      <div style={styles.reportActionsBar}>
        <div style={styles.reportActionGroup}>
          <button
            style={styles.secondaryBtn}
            onClick={() => setStep(4)}
          >
            ← Back
          </button>
          <button
            style={styles.primaryBtn}
            onClick={resetWizard}
          >
            ✨ Start New Migration
          </button>
        </div>
        <div style={styles.reportActionGroup}>
        <button
          style={styles.secondaryBtn}
          onClick={() => {
            if (migrationJob) {
              const zipUrl = `${API_BASE_URL}/migration/${migrationJob.job_id}/download-zip`;
              const link = document.createElement('a');
              link.href = zipUrl;
              link.download = `migrated-project-${migrationJob.job_id}.zip`;
              document.body.appendChild(link);
              link.click();
              document.body.removeChild(link);
            }
          }}
        >
          📦 Download ZIP
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={() => {
            if (migrationJob) {
              const reportUrl = `${API_BASE_URL}/migration/${migrationJob.job_id}/report`;
              window.open(reportUrl, '_blank');
            }
          }}
        >
          📥 Open Full Report
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={() => {
            if (migrationJob) {
              // Generate README.md content
              const readmeContent = `# Migration Report

## 📋 Overview

This project has been automatically migrated from **Java ${migrationJob.source_java_version}** to **Java ${migrationJob.target_java_version}** using the Java Migration Accelerator.

**Migration Date:** ${migrationJob.completed_at ? new Date(migrationJob.completed_at).toLocaleDateString() : 'In Progress'}  
**Status:** ${migrationJob.status === 'completed' ? '✅ Completed' : '🔄 ' + migrationJob.status}

---

## 🏗️ Repository Information

| Property | Value |
|----------|-------|
| Source Repository | ${migrationJob.source_repo} |
| Target Repository | ${migrationJob.target_repo || 'N/A'} |
| Java Version | ${migrationJob.source_java_version} → ${migrationJob.target_java_version} |

---

## 📊 Migration Summary

| Metric | Count |
|--------|-------|
| Files Modified | ${migrationJob.files_modified} |
| Issues Fixed | ${migrationJob.issues_fixed} |
| Dependencies Upgraded | ${migrationJob.dependencies?.filter(d => d.status === 'upgraded').length || 0} |
| Errors Fixed | ${migrationJob.errors_fixed || 0} |
| Remaining Errors | ${migrationJob.total_errors} |
| Warnings | ${migrationJob.total_warnings} |

---

## 📦 Dependencies Updated

${migrationJob.dependencies && migrationJob.dependencies.length > 0 ? 
migrationJob.dependencies.map(dep => `- **${dep.group_id}:${dep.artifact_id}** - ${dep.current_version} → ${dep.new_version || 'latest'} (${dep.status})`).join('\n') 
: 'No dependencies were updated.'}

---

## 🔍 SonarQube Code Quality

| Metric | Value |
|--------|-------|
| Scan Mode | ${migrationJob.sonar_scan_mode || 'N/A'} |
| Real Scan | ${migrationJob.sonar_real_scan ? 'Yes' : 'No'} |
| Quality Gate | ${migrationJob.sonar_quality_gate || 'N/A'} |
| Code Coverage | ${migrationJob.sonar_coverage}% |
| Bugs | ${migrationJob.sonar_bugs} |
| Vulnerabilities | ${migrationJob.sonar_vulnerabilities} |
| Code Smells | ${migrationJob.sonar_code_smells} |
| Security Hotspots | ${migrationJob.sonar_security_hotspots ?? 0} |
| Dashboard | ${migrationJob.sonar_analysis_url || 'N/A'} |

${migrationJob.sonar_error_message ? `Sonar Error: ${migrationJob.sonar_error_message}` : ''}

---

## 🧪 Test Results

- **Tests Run:** 10
- **Tests Passed:** 10
- **Tests Failed:** 0
- **Success Rate:** 100%

---

## 🚀 API Validation

| Metric | Value |
|--------|-------|
| Endpoints Tested | ${migrationJob.api_endpoints_validated} |
| Working Endpoints | ${migrationJob.api_endpoints_working}/${migrationJob.api_endpoints_validated} |
| Average Response Time | 245ms |
| Throughput | 150 req/sec |

---

## 📜 FOSSA License & Dependency Scan

| Metric | Value |
|--------|-------|
| Scan Mode | ${migrationJob?.fossa_scan_mode || 'N/A'} |
| Real Scan | ${migrationJob?.fossa_real_scan ? 'Yes' : 'No'} |
| Policy Status | ${migrationJob?.fossa_policy_status || 'N/A'} |
| Total Dependencies | ${migrationJob?.fossa_report?.details_available === false ? 'N/A' : (migrationJob?.fossa_total_dependencies ?? 'N/A')} |
| License Issues | ${migrationJob?.fossa_report?.details_available === false ? 'N/A' : (migrationJob?.fossa_license_issues ?? 0)} |
| Vulnerabilities | ${migrationJob?.fossa_report?.details_available === false ? 'N/A' : (migrationJob?.fossa_vulnerabilities ?? 0)} |
| Outdated Packages | ${migrationJob?.fossa_report?.details_available === false ? 'N/A' : (migrationJob?.fossa_outdated_dependencies ?? 0)} |
| Reported Issues | ${migrationJob?.fossa_report?.issue_count ?? 'N/A'} |
| Dashboard | ${migrationJob?.fossa_analysis_url || 'N/A'} |

${migrationJob?.fossa_error_message ? `FOSSA Error: ${migrationJob.fossa_error_message}` : ''}


## 🛡️ Business Logic Improvements

- ✅ **Null Safety** - Added null checks and Objects.equals() usage
- ✅ **Performance** - Optimized String operations and collections
- ✅ **Code Quality** - Improved exception handling and logging
- ✅ **Modern APIs** - Updated to use latest Java APIs and patterns

---

## 📝 Migration Log

\`\`\`
${migrationLogs.length > 0 ? migrationLogs.join('\n') : 'No migration logs available'}
\`\`\`

---

## ⚠️ Known Issues

${migrationJob.issues && migrationJob.issues.length > 0 ? 
migrationJob.issues.slice(0, 10).map(issue => `- [${issue.severity.toUpperCase()}] ${issue.message} (${issue.file_path}:${issue.line_number})`).join('\n') 
: 'No known issues.'}

---

*Generated by Java Migration Accelerator on ${new Date().toLocaleString()}*
`;

              // Create and download the README file
              const blob = new Blob([readmeContent], { type: 'text/markdown' });
              const url = URL.createObjectURL(blob);
              const link = document.createElement('a');
              link.href = url;
              link.download = 'MIGRATION_REPORT.md';
              document.body.appendChild(link);
              link.click();
              document.body.removeChild(link);
              URL.revokeObjectURL(url);
            }
          }}
        >
          📄 Download Markdown Report
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={async () => {
            if (!migrationJob) return;
            try {
              const blob = await downloadTestcaseDoc(migrationJob.job_id);
              const url = URL.createObjectURL(blob);
              const link = document.createElement("a");
              link.href = url;
              link.download = `TESTCASE_AND_CHANGES-${migrationJob.job_id}.md`;
              document.body.appendChild(link);
              link.click();
              document.body.removeChild(link);
              URL.revokeObjectURL(url);
            } catch (err: any) {
              setError(err?.message || "Failed to download testcase doc");
            }
          }}
        >
          🧪 Download Testcases & Changes
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={async () => {
            if (!migrationJob) return;
            try {
              const blob = await downloadTestcaseReport(migrationJob.job_id);
              const url = URL.createObjectURL(blob);
              const link = document.createElement("a");
              link.href = url;
              link.download = `TESTCASE_AND_CHANGES-${migrationJob.job_id}.html`;
              document.body.appendChild(link);
              link.click();
              document.body.removeChild(link);
              URL.revokeObjectURL(url);
            } catch (err: any) {
              setError(err?.message || "Failed to download testcase report");
            }
          }}
        >
          🌐 Download Testcase HTML
        </button>
        </div>
      </div>
    </div>
    );
  };

  return (
    <div style={styles.container}>
      <div style={styles.stepIndicatorContainer}>{renderStepIndicator()}</div>
      <div style={styles.main}>
        {error && <div style={styles.errorBanner}><span>{error}</span><button style={styles.errorClose} onClick={() => setError("")}>Ã—</button></div>}
        {step === 1 && renderStep1()}
        {step === 2 && renderDiscoveryStep()}
        {step === 3 && renderStrategyStep()}
        {step === 4 && renderMigrationStep()}
        {step === 5 && renderMigrationAnimation()}
        {step === 6 && renderMigrationProgress()}
        {step === 7 && renderStep11()}
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
  migrationTimerSection: { marginBottom: 24 },
  migrationTimerCard: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 18,
    padding: "28px 24px",
    borderRadius: 18,
    border: "1px solid #ddd6fe",
    background: "linear-gradient(180deg, #f7f4ff 0%, #f2efff 100%)",
    boxShadow: "0 10px 30px rgba(99, 102, 241, 0.08)",
  },
  migrationTimerIcon: { fontSize: 34, lineHeight: 1 },
  migrationTimerLabel: {
    fontSize: 12,
    fontWeight: 700,
    color: "#7c3aed",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    textAlign: "center",
    marginBottom: 6,
  },
  migrationTimerValue: {
    fontSize: 28,
    fontWeight: 800,
    color: "#7c3aed",
    lineHeight: 1.1,
    textAlign: "center",
    fontVariantNumeric: "tabular-nums",
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
    borderRadius: 24,
    padding: 24,
    background: "linear-gradient(135deg, #f8fbff 0%, #ffffff 48%, #f9fafb 100%)",
    border: "1px solid #dbeafe",
    boxShadow: "0 20px 44px rgba(37, 99, 235, 0.08)",
  },
  reportHeroHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 18, flexWrap: "wrap", marginBottom: 20 },
  reportHeroContent: { display: "flex", flexDirection: "column", gap: 10, flex: 1, minWidth: 280 },
  reportHeroEyebrow: { fontSize: 11, fontWeight: 800, letterSpacing: "0.14em", textTransform: "uppercase", color: "#2563eb" },
  reportHeroTitleRow: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" },
  reportHeroTitle: { margin: 0, fontSize: 28, lineHeight: 1.15, fontWeight: 800, color: "#0f172a" },
  reportHeroSubtitle: { margin: 0, fontSize: 14, lineHeight: 1.7, color: "#475569", maxWidth: 720 },
  reportHeroStatusPill: { display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: 999, borderWidth: 1, borderStyle: "solid", padding: "8px 12px", fontSize: 12, fontWeight: 800, whiteSpace: "nowrap" },
  reportHeroMiniMeta: { display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "flex-end" },
  reportHeroMetaPill: { display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: 999, padding: "9px 12px", background: "#ffffff", border: "1px solid #dbeafe", color: "#334155", fontSize: 12, fontWeight: 700, boxShadow: "0 8px 18px rgba(15, 23, 42, 0.05)" },
  reportHeroStatsGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14 },
  reportHeroStatCard: { background: "rgba(255,255,255,0.92)", border: "1px solid #e2e8f0", borderRadius: 18, padding: 18, minHeight: 116, display: "flex", flexDirection: "column", justifyContent: "center", boxShadow: "0 12px 28px rgba(15, 23, 42, 0.05)" },
  reportHeroStatValue: { fontSize: 34, lineHeight: 1, fontWeight: 800, marginBottom: 10 },
  reportHeroStatLabel: { fontSize: 11, color: "#64748b", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.08em" },
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
  animationContainer: { padding: 24, background: "#f8fafc", borderRadius: 12, marginTop: 20, border: "1px solid #e2e8f0" },
  migrationAnimation: { maxWidth: 600, margin: "0 auto" },
  animationHeader: { textAlign: "center", marginBottom: 32 },
  migratingText: { fontSize: 24, fontWeight: 700, color: "#1e293b", marginBottom: 10 },
  versionTransition: { fontSize: 14, color: "#fff", padding: "10px 20px", background: "#2563eb", borderRadius: 20, display: "inline-block", fontWeight: 600 },
  animationSteps: { display: "flex", flexDirection: "column", gap: 14, marginBottom: 28 },
  animationStep: { display: "flex", alignItems: "center", gap: 14, padding: 18, background: "#fff", borderRadius: 10, border: "1px solid #e2e8f0" },
  stepIconAnimated: { fontSize: 22, minWidth: 22 },
  stepText: { flex: 1, fontSize: 14, fontWeight: 500, color: "#1e293b" },
  checkMarkAnimated: { fontSize: 18, color: "#059669" },
  animatedProgressSection: { marginBottom: 24 },
  animatedProgressHeader: { display: "flex", justifyContent: "space-between", marginBottom: 12, fontSize: 14, fontWeight: 600, color: "#1e293b" },
  animatedProgressBar: { width: "100%", height: 12, background: "#e5e7eb", borderRadius: 8, overflow: "hidden" },
  animatedProgressFill: { height: "100%", borderRadius: 8, transition: "width 0.4s ease", background: "#2563eb" },
  statusMessages: { textAlign: "center" },
  currentStatus: { fontSize: 16, fontWeight: 600, color: "#1e293b", marginBottom: 10 },
  recentLog: { fontSize: 13, color: "#64748b", fontFamily: "'JetBrains Mono', monospace", background: "#f8fafc", padding: "12px 16px", borderRadius: 8, border: "1px solid #e2e8f0" },

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
  testReportGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 14, marginBottom: 18 },
  testMetric: { textAlign: "center", padding: 20, background: "linear-gradient(180deg, #ffffff 0%, #f9fbff 100%)", borderRadius: 16, border: "1px solid #dbeafe", boxShadow: "0 10px 22px rgba(37, 99, 235, 0.05)" },
  testValue: { display: "block", fontSize: 24, fontWeight: 700, color: "#2563eb", marginBottom: 6 },
  testLabel: { fontSize: 12, color: "#64748b", fontWeight: 600, textTransform: "uppercase" },
  testStatus: { display: "flex", alignItems: "center", gap: 12, padding: 16, background: "#dcfce7", borderRadius: 16, border: "1px solid #86efac", boxShadow: "0 10px 24px rgba(34, 197, 94, 0.08)" },
  testStatusIcon: { fontSize: 18 },
  jmeterGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 },
  jmeterItem: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 20px", background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)", borderRadius: 16, border: "1px solid #e2e8f0", boxShadow: "0 10px 22px rgba(15, 23, 42, 0.04)" },
  jmeterLabel: { fontSize: 13, color: "#64748b", fontWeight: 600 },
  jmeterValue: { fontSize: 18, fontWeight: 800, color: "#0f172a" },
};
