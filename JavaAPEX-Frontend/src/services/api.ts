/**
 * API Service for Java Migration Backend
 */
const configuredApiUrl = import.meta.env?.VITE_API_URL?.trim();
const isLocalFrontend =
  typeof window !== "undefined" &&
  ["localhost", "127.0.0.1"].includes(window.location.hostname) &&
  window.location.port !== "8000";
const runtimeOrigin =
  isLocalFrontend
    ? "http://localhost:8000"
    : typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
    : "http://localhost:8000";

export const APP_BASE_URL = (configuredApiUrl || runtimeOrigin).replace(/\/+$/, "");
export const API_BASE_URL = `${APP_BASE_URL}/api`;
export const GITHUB_AUTH_LOGIN_URL = `${API_BASE_URL}/auth/github/login`;

export class ApiError extends Error {
  status: number;
  code?: string;
  detail?: unknown;

  constructor(message: string, status: number, code?: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function getErrorMessage(detail: unknown, fallbackMessage = "Request failed"): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item: any) => item?.msg || item?.message || JSON.stringify(item))
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const typedDetail = detail as Record<string, unknown>;
    return (
      (typeof typedDetail.message === "string" && typedDetail.message) ||
      (typeof typedDetail.msg === "string" && typedDetail.msg) ||
      fallbackMessage
    );
  }
  return fallbackMessage;
}

async function parseJsonResponse<T>(response: Response, fallbackMessage: string): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  const bodyText = await response.text();

  if (!contentType.includes("application/json")) {
    if (bodyText.trim().startsWith("<!doctype") || bodyText.trim().startsWith("<html")) {
      throw new Error(`API routing error: expected JSON from ${response.url} but received HTML. Check VITE_API_URL or backend routing.`);
    }
    throw new Error(fallbackMessage);
  }

  const data = JSON.parse(bodyText);
  if (!response.ok) {
    const detail = data?.detail;
    const errorMessage = typeof data?.error === "string" && data.error.trim()
      ? data.error
      : getErrorMessage(detail, fallbackMessage);
    const errorCode =
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as Record<string, unknown>).code
        : undefined;
    throw new ApiError(
      errorMessage,
      response.status,
      typeof errorCode === "string" ? errorCode : undefined,
      detail,
    );
  }

  return data as T;
}

async function readErrorDetail(response: Response): Promise<string | undefined> {
  const text = await response
    .clone()
    .text()
    .catch(() => "");

  if (!text) return undefined;

  try {
    const json = JSON.parse(text);
    if (typeof json === "string") return json;
    return getErrorMessage(json?.detail ?? json?.message ?? json?.error);
  } catch {
    return text;
  }
}

export interface RepoInfo {
  name: string;
  full_name: string;
  url: string;
  default_branch: string;
  language: string | null;
  description: string | null;
}

export interface RepoFile {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size: number;
  url: string;
}

export interface RepoUrlAnalysis {
  repo_url: string;
  owner: string;
  repo: string;
  analysis: RepoAnalysis;
}

export interface LocalProjectCapabilities {
  enabled: boolean;
  hosted_mode: boolean;
  allow_any_path: boolean;
  allowed_roots: string[];
  supports_upload?: boolean;
  message: string;
}

export interface LocalProjectAnalysisResponse {
  project_path: string;
  project_name: string;
  repo_url: string;
  owner: string;
  repo: string;
  analysis: RepoAnalysis;
}

export interface RepoVisibilityInfo {
  owner: string;
  repo: string;
  visibility: "public" | "private" | "private_or_inaccessible";
  requires_token: boolean;
  message: string;
}

export interface RepoFilesResponse {
  repo_url: string;
  owner: string;
  repo: string;
  path: string;
  files: RepoFile[];
}

export interface FileContentResponse {
  repo_url: string;
  owner: string;
  repo: string;
  file_path: string;
  content: string;
}

export interface DependencyInfo {
  group_id: string;
  artifact_id: string;
  current_version: string;
  new_version: string | null;
  status: string;
}

export interface ConversionType {
  id: string; 
  name: string;
  description: string;
  category: string;
  icon: string;
}

export interface MigrationIssue {
  id: string;
  severity: 'error' | 'warning' | 'info';
  status: 'detected' | 'fixed' | 'manual_review' | 'ignored';
  category: string;
  message: string;
  file_path: string;
  line_number: number | null;
  column: number | null;
  code_snippet: string | null;
  suggested_fix: string | null;
  fixed_at: string | null;
  conversion_type: string;
}

export interface SonarIssueDetail {
  key?: string | null;
  type?: string | null;
  severity?: string | null;
  component?: string | null;
  line?: number | null;
  message?: string | null;
  rule?: string | null;
  status?: string | null;
  resolution?: string | null;
  effort?: string | null;
  debt?: string | null;
  author?: string | null;
  tags?: string[];
  creation_date?: string | null;
  update_date?: string | null;
}

export interface SonarHotspotDetail {
  key?: string | null;
  component?: string | null;
  line?: number | null;
  message?: string | null;
  rule?: string | null;
  status?: string | null;
  security_category?: string | null;
  vulnerability_probability?: string | null;
  author?: string | null;
  creation_date?: string | null;
  update_date?: string | null;
}

export interface SonarReport {
  quality_gate?: string | null;
  bugs?: number;
  vulnerabilities?: number;
  code_smells?: number;
  coverage?: number;
  duplications?: number;
  security_hotspots?: number;
  analysis_url?: string | null;
  bug_details?: SonarIssueDetail[];
  vulnerability_details?: SonarIssueDetail[];
  code_smell_details?: SonarIssueDetail[];
  security_hotspot_details?: SonarHotspotDetail[];
  [key: string]: any;
}

export interface PreviewFileChange {
  type: string;
  pattern?: string;
  replacement?: string;
  description: string;
  occurrences?: number;
}

export interface PreviewFileDiff {
  file_path: string;
  diff: string;
  change_count: number;
}

export interface MigrationPreview {
  repository: string;
  platform: string;
  source_version: string;
  target_version: string;
  conversions: string[];
  business_logic_fixes: boolean;
  summary: {
    files_to_modify: number;
    files_to_create: number;
    files_to_remove: number;
    total_changes: number;
  };
  changes: {
    files_to_modify: string[];
    files_to_create: string[];
    files_to_remove: string[];
    file_changes: Record<string, PreviewFileChange[]>;
    dependencies_to_update: Array<{
      dependency: string;
      current_version: string;
      new_version: string;
      status?: string;
    }>;
    issues_to_fix: Array<{
      type: string;
      severity: string;
      description: string;
      file: string;
    }>;
  };
  file_diffs: PreviewFileDiff[];
}

export interface FossaVulnerabilityDetail {
  id: string;
  title: string;
  severity: string;
  package?: string | null;
  package_version?: string | null;
  fixed_version?: string | null;
  description?: string | null;
  reference?: string | null;
}

export interface FossaScanResult {
  scan_mode?: string | null;
  real_scan?: boolean;
  simulated?: boolean;
  ready?: boolean;
  details_available?: boolean;
  permission_limited?: boolean;
  compliance_status?: string | null;
  total_dependencies?: number | null;
  issue_count?: number | null;
  license_issues?: number | null;
  licenses?: Record<string, number>;
  vulnerabilities?: Record<string, number> | number | null;
  vulnerability_details?: FossaVulnerabilityDetail[];
  dependencies?: Array<Record<string, any>>;
  outdated_dependencies?: number | null;
  analysis_url?: string | null;
  error_message?: string | null;
  raw_summary?: string | null;
}

export interface MigrationRequest {
  source_repo_url: string;
  target_repo_name: string;
  migration_approach?: string;
  platform?: string;
  source_java_version: string;
  target_java_version: string;
  token?: string;
  github_token?: string;
  build_tool?: string | null;
  conversion_types: string[];
  email?: string;
  run_tests: boolean;
  use_llm_tests?: boolean;
  llm_test_provider?: string;
  run_sonar: boolean;
  run_fossa?: boolean;
  fix_business_logic: boolean;
  migration_type?: "monolithic" | "microservices";
}

export interface MigrationResult {
  job_id: string;
  status: string;
  source_repo: string;
  target_repo: string | null;
  migration_type?: string;
  microservice_output_path?: string | null;
  source_java_version: string;
  target_java_version: string;
  conversion_types: string[];
  started_at: string;
  completed_at: string | null;
  progress_percent: number;
  current_step: string;
  dependencies: DependencyInfo[];
  files_modified: number;
  issues_fixed: number;
  api_endpoints_validated: number;
  api_endpoints_working: number;
  sonar_quality_gate: string | null;
  sonar_bugs: number;
  sonar_vulnerabilities: number;
  sonar_code_smells: number;
  sonar_coverage: number;
  sonar_duplications?: number;
  sonar_security_hotspots?: number;
  sonar_scan_mode?: string | null;
  sonar_real_scan?: boolean;
  sonar_analysis_url?: string | null;
  sonar_error_message?: string | null;
  sonar_report?: SonarReport | null;
  tests_run: number;
  tests_passed: number;
  tests_failed: number;
  test_summary?: string | null;
  test_insights?: string[];
  test_llm_model?: string | null;
  test_pipeline?: {
    provider: string;
    project_kind: string;
    generated_tests_relative: string;
    test_strategy?: string | null;
    existing_tests_detected?: number;
    existing_test_files?: string[];
    migrated_test_files?: string[];
    generated_test_files: string[];
    runner: Record<string, any>;
    manual_test_plan_path?: string | null;
    migration_patch_path?: string | null;
    deepeval_result?: Record<string, any> | null;
    garak_result?: Record<string, any> | null;
    coverage_result?: Record<string, any> | null;
  } | null;
  // FOSSA scan results (optional)
  fossa_policy_status?: string | null;
  fossa_total_dependencies?: number;
  fossa_license_issues?: number;
  fossa_vulnerabilities?: number;
  fossa_outdated_dependencies?: number;
  fossa_scan_mode?: string | null;
  fossa_real_scan?: boolean;
  fossa_analysis_url?: string | null;
  fossa_error_message?: string | null;
  fossa_report?: FossaScanResult | null;
  error_message: string | null;
  migration_log: string[];
  file_diffs?: PreviewFileDiff[];
  issues: MigrationIssue[];
  total_errors: number;
  total_warnings: number;
  errors_fixed: number;
  warnings_fixed: number;
}

export interface RepoAnalysis {
  name: string;
  full_name: string;
  default_branch: string;
  language: string | null;
  build_tool: string | null;
  java_version: string | null;
  java_version_from_build?: string | null;
  // List of discovered Java source file paths
  java_files?: string[];
  has_tests: boolean;
  dependencies: DependencyInfo[];
  api_endpoints: { path: string; method: string; file: string }[];
  structure: {
    has_pom_xml: boolean;
    has_build_gradle: boolean;
    has_src_main: boolean;
    has_src_test: boolean;
    has_build_gradle_kts:boolean;
  };
  // backend-provided microservice eligibility assessment
  microservice_eligibility?: MicroserviceEligibilityResult;
}

export interface MicroserviceScoreBreakdown {
  name: string;
  score: number;
  weight: number;
  summary: string;
}

export interface MicroserviceServiceCandidate {
  name: string;
  packages: string[];
  evidence: string[];
  scaling_signals: string[];
  external_integrations: string[];
  transactional: boolean;
}

export interface MicroserviceDetailedEligibilityReport {
  project_structure: string[];
  package_structure: string[];
  module_boundaries: string[];
  dependency_coupling: string[];
  database_access_patterns: string[];
  communication_analysis: string[];
  deployment_independence: string[];
  scalability_indicators: string[];
}

export interface MicroserviceAnalysisDiagnostics {
  java_files_total: number;
  java_files_scanned: number;
  package_count: number;
  detected_modules: number;
  cross_module_dependencies: number;
  circular_dependencies: number;
  external_integration_count: number;
  scan_truncated: boolean;
}

export interface MicroserviceEligibilityResult {
  projectName: string;
  score: number;
  eligibility: string;
  recommendedArchitecture: string;
  summary: string;
  strengths: string[];
  risks: string[];
  serviceCandidates: MicroserviceServiceCandidate[];
  couplingIssues: string[];
  databaseConcerns: string[];
  scalingCandidates: string[];
  recommendedMigrationStrategy: string[];
  observations: string[];
  scoreBreakdown?: MicroserviceScoreBreakdown[];
  detailedEligibilityReport?: MicroserviceDetailedEligibilityReport;
  architecturalObservations?: string[];
  analysisDiagnostics?: MicroserviceAnalysisDiagnostics;
  reportGeneratedAt?: string;
  metadata?: Record<string, any>;
}

export interface JavaVersionInfo {
  source_versions: { value: string; label: string }[];
  target_versions: { value: string; label: string }[];
}

export interface JavaVersionRecommendationRequest {
  source_java_version: string;
  detected_java_version?: string | null;
  build_tool?: string | null;
  dependencies: DependencyInfo[];
  has_tests: boolean;
  api_endpoint_count: number;
  risk_level?: string | null;
}

export interface JavaVersionRecommendationResponse {
  recommended_target_version: string;
  recommended_versions?: string[];
  confidence: string;
  rationale: string[];
  alternatives: string[];
  alternative_options?: Array<{
    version: string;
    risk?: string;
    reason?: string;
  }>;
  raw_recommendation?: Record<string, unknown>;
}

export type GithubDocumentType = "brd" | "kt";

export interface GithubDocumentRequest {
  repo_url?: string;
  repository_url?: string;
  source_repo_url?: string;
  token?: string;
  github_token?: string;
  job_id?: string;
  migration_job_id?: string;
  source_repo?: string;
  target_repo?: string | null;
  source_java_version?: string;
  target_java_version?: string;
  document_type?: string;
}

export interface LocalProjectDocumentRequest extends GithubDocumentRequest {
  analysis: Record<string, any>;
}

export interface GithubDocumentResponse {
  html?: string;
  url?: string;
  filename: string;
}

function extractGithubDocumentHtml(data: Record<string, any>): string | undefined {
  const htmlCandidates = [
    data.html,
    data.document_html,
    data.html_content,
    data.content,
    data.document,
    data.markup,
    data?.data?.html,
    data?.data?.document_html,
    data?.data?.content,
  ];

  return htmlCandidates.find(
    (candidate) => typeof candidate === "string" && candidate.trim().length > 0
  );
}

function extractGithubDocumentUrl(data: Record<string, any>): string | undefined {
  const urlCandidates = [
    data.url,
    data.document_url,
    data.download_url,
    data.file_url,
    data?.data?.url,
    data?.data?.document_url,
    data?.data?.download_url,
  ];

  return urlCandidates.find(
    (candidate) => typeof candidate === "string" && candidate.trim().length > 0
  );
}

// Fetch GitHub repositories
export async function fetchRepositories(token: string): Promise<RepoInfo[]> {
  const response = await fetch(`${API_BASE_URL}/github/repos?token=${encodeURIComponent(token)}`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to fetch repositories');
  }
  return response.json();
}

// Analyze a repository
export async function analyzeRepository(token: string, owner: string, repo: string): Promise<RepoAnalysis> {
  const response = await fetch(
    `${API_BASE_URL}/github/repo/${owner}/${repo}/analyze?token=${encodeURIComponent(token)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to analyze repository');
  }
  return response.json();
}

// NEW: Analyze repository directly by URL (works for public repos without token)
export async function analyzeRepoUrl(repoUrl: string, token: string = "", forceRefresh: boolean = false): Promise<RepoUrlAnalysis> {
  const response = await fetch(
    `${API_BASE_URL}/github/analyze-url?repo_url=${encodeURIComponent(repoUrl)}&token=${encodeURIComponent(token)}&force_refresh=${forceRefresh}`
  );
  return parseJsonResponse<RepoUrlAnalysis>(response, 'Failed to analyze repository');
}

export async function getRepoVisibility(repoUrl: string, token: string = ""): Promise<RepoVisibilityInfo> {
  const response = await fetch(
    `${API_BASE_URL}/github/repo-visibility?repo_url=${encodeURIComponent(repoUrl)}&token=${encodeURIComponent(token)}`
  );
  return parseJsonResponse<RepoVisibilityInfo>(response, 'Failed to check repository visibility');
}

export async function getLocalProjectCapabilities(): Promise<LocalProjectCapabilities> {
  const response = await fetch(`${API_BASE_URL}/local-project/capabilities`);
  return parseJsonResponse<LocalProjectCapabilities>(response, "Failed to load local project capabilities");
}

export async function analyzeLocalProject(projectPath: string): Promise<LocalProjectAnalysisResponse> {
  const response = await fetch(`${API_BASE_URL}/local-project/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ project_path: projectPath }),
  });
  return parseJsonResponse<LocalProjectAnalysisResponse>(response, "Failed to analyze local project");
}

export async function uploadLocalProject(formData: FormData): Promise<LocalProjectAnalysisResponse> {
  const response = await fetch(`${API_BASE_URL}/local-project/upload`, {
    method: "POST",
    body: formData,
  });
  return parseJsonResponse<LocalProjectAnalysisResponse>(response, "Failed to upload local project");
}

export async function uploadLocalProjectChunk(
  uploadId: string,
  chunkIndex: number,
  totalChunks: number,
  chunk: Blob,
  fileName: string,
  projectName: string | null = null,
): Promise<LocalProjectAnalysisResponse | { status: string; upload_id: string; chunk_index: number; total_chunks: number }> {
  const formData = new FormData();
  formData.append("upload_id", uploadId);
  formData.append("chunk_index", String(chunkIndex));
  formData.append("total_chunks", String(totalChunks));
  formData.append("file_name", fileName);
  if (projectName) {
    formData.append("project_name", projectName);
  }
  formData.append("file", new File([chunk], fileName, { type: "application/octet-stream" }));

  const response = await fetch(`${API_BASE_URL}/local-project/upload-chunk`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || "Failed to upload local project chunk");
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("Invalid response from upload chunk endpoint");
  }

  return response.json();
}

export async function listLocalProjectFiles(projectPath: string, path: string = ""): Promise<RepoFilesResponse> {
  const response = await fetch(
    `${API_BASE_URL}/local-project/list-files?project_path=${encodeURIComponent(projectPath)}&path=${encodeURIComponent(path)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || "Failed to list local project files");
  }
  return response.json();
}

export async function getLocalProjectFileContent(projectPath: string, filePath: string): Promise<FileContentResponse> {
  const response = await fetch(
    `${API_BASE_URL}/local-project/file-content?project_path=${encodeURIComponent(projectPath)}&file_path=${encodeURIComponent(filePath)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || "Failed to get local project file content");
  }
  return response.json();
}

// NEW: List files in a repository (works for public repos without token)
export async function listRepoFiles(repoUrl: string, token: string = "", path: string = ""): Promise<RepoFilesResponse> {
  const response = await fetch(
    `${API_BASE_URL}/github/list-files?repo_url=${encodeURIComponent(repoUrl)}&token=${encodeURIComponent(token)}&path=${encodeURIComponent(path)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to list files');
  }
  return response.json();
}

// NEW: Get file content (works for public repos without token)
export async function getFileContent(repoUrl: string, filePath: string, token: string = ""): Promise<FileContentResponse> {
  const response = await fetch(
    `${API_BASE_URL}/github/file-content?repo_url=${encodeURIComponent(repoUrl)}&file_path=${encodeURIComponent(filePath)}&token=${encodeURIComponent(token)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to get file content');
  }
  return response.json();
}

export async function getMicroserviceEligibility(repoUrl: string, token: string = ""): Promise<MicroserviceEligibilityResult> {
  const response = await fetch(
    `${API_BASE_URL}/github/microservice-eligibility?repo_url=${encodeURIComponent(repoUrl)}&token=${encodeURIComponent(token)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to get microservice eligibility');
  }
  return response.json();
}

export async function getLocalProjectMicroserviceEligibility(projectPath: string): Promise<MicroserviceEligibilityResult> {
  const response = await fetch(`${API_BASE_URL}/local-project/microservice-eligibility`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ project_path: projectPath }),
  });
  return parseJsonResponse<MicroserviceEligibilityResult>(response, "Failed to get local project microservice eligibility");
}

// Get available Java versions
export async function getJavaVersions(): Promise<JavaVersionInfo> {
  const response = await fetch(`${API_BASE_URL}/java-versions`);
  return parseJsonResponse<JavaVersionInfo>(response, 'Failed to fetch Java versions');
}

export async function getJavaVersionRecommendation(
  request: JavaVersionRecommendationRequest
): Promise<JavaVersionRecommendationResponse> {
  const response = await fetch(`${API_BASE_URL}/java-version-recommendation`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
  return parseJsonResponse<JavaVersionRecommendationResponse>(
    response,
    "Failed to get Java version recommendation"
  );
}

export async function generateGithubDocument(
  documentType: GithubDocumentType,
  request: GithubDocumentRequest
): Promise<GithubDocumentResponse> {
  const response = await fetch(`${API_BASE_URL}/github/generate-${documentType}-document`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  const contentType = response.headers.get("content-type") || "";
  const bodyText = await response.text();
  const fallbackMessage = `Failed to generate ${documentType.toUpperCase()} document`;

  if (!response.ok) {
    if (contentType.includes("application/json")) {
      try {
        const data = JSON.parse(bodyText);
        const detail = data?.detail || data?.message || data?.error;
        throw new Error(
          typeof detail === "string" && detail.trim().length > 0 ? detail : fallbackMessage
        );
      } catch {
        throw new Error(bodyText || fallbackMessage);
      }
    }

    throw new Error(bodyText || fallbackMessage);
  }

  const repoNameCandidate =
    request.source_repo ||
    request.repository_url ||
    request.repo_url ||
    "repository";
  const repoName = repoNameCandidate
    .split("/")
    .filter(Boolean)
    .pop()
    ?.replace(/\.git$/i, "") || "repository";
  const filename = `${repoName.toUpperCase()}-TECHNICAL-DOCUMENT.html`;

  if (contentType.includes("application/json")) {
    const data = bodyText ? JSON.parse(bodyText) : {};
    const html = extractGithubDocumentHtml(data);
    const url = extractGithubDocumentUrl(data);

    if (!html && !url) {
      throw new Error(
        `${documentType.toUpperCase()} document endpoint responded without HTML or download URL`
      );
    }

    return {
      html,
      url,
      filename:
        typeof data?.filename === "string" && data.filename.trim().length > 0
          ? data.filename
          : filename,
    };
  }

  if (!bodyText.trim()) {
    throw new Error(`${documentType.toUpperCase()} document endpoint returned empty content`);
  }

  return {
    html: bodyText,
    filename,
  };
}

export async function generateLocalProjectDocument(
  request: LocalProjectDocumentRequest
): Promise<GithubDocumentResponse> {
  const response = await fetch(`${API_BASE_URL}/local-project/generate-brd-document`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
  return parseJsonResponse<GithubDocumentResponse>(response, "Failed to generate BRD document");
}

// Get available conversion types
export async function getConversionTypes(): Promise<ConversionType[]> {
  const response = await fetch(`${API_BASE_URL}/conversion-types`);
  return parseJsonResponse<ConversionType[]>(response, 'Failed to fetch conversion types');
}

// Start migration
export async function startMigration(request: MigrationRequest): Promise<MigrationResult> {
  const response = await fetch(`${API_BASE_URL}/migration/start`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to start migration');
  }
  return response.json();
}

export async function previewMigration(request: MigrationRequest): Promise<MigrationPreview> {
  const response = await fetch(`${API_BASE_URL}/migration/preview`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return parseJsonResponse<MigrationPreview>(response, 'Failed to preview migration changes');
}

// Get migration status
export async function getMigrationStatus(jobId: string): Promise<MigrationResult> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}`);
  if (!response.ok) {
    const payload = await response.clone().json().catch(() => null);
    const detail = payload?.detail;
    throw new ApiError(
      getErrorMessage(detail, 'Failed to get migration status'),
      response.status,
      detail && typeof detail === 'object' && !Array.isArray(detail) ? String((detail as Record<string, unknown>).code || '') || undefined : undefined,
      detail,
    );
  }
  return response.json();
}

// Get migration logs
export async function getMigrationLogs(jobId: string): Promise<{ job_id: string; logs: string[] }> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/logs`);
  if (!response.ok) {
    throw new Error('Failed to get migration logs');
  }
  return response.json();
}

// Get FOSSA scan results for a migration (if available)
export async function getMigrationFossa(jobId: string): Promise<{
  job_id: string;
  fossa: FossaScanResult;
}> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/fossa`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to get FOSSA results');
  }

  const data = await response.json();
  return {
    job_id: jobId,
    fossa: (data && data.fossa) ? data.fossa : data,
  };
}

// Download migrated project as ZIP
export async function downloadMigratedProject(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/download-zip`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download migrated project');
  }
  return response.blob();
}

// Download migration report
export async function downloadMigrationReport(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/report`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download migration report');
  }
  return response.blob();
}

// Download testcase + change report (Markdown)
export async function downloadTestcaseDoc(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/testcase-doc`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download testcase doc');
  }
  return response.blob();
}

export async function downloadTestcaseDocx(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/testcase-docx`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download testcase docx');
  }
  return response.blob();
}

// Download testcase + change report (HTML)
export async function downloadTestcaseReport(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/testcase-report`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download testcase report');
  }
  return response.blob();
}

export async function downloadUnitTestReport(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/unit-test-report`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download unit test report');
  }
  return response.blob();
}

export async function downloadSonarReportPdf(jobId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/migration/${jobId}/sonar-report-pdf`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new ApiError(detail || 'Failed to download Sonar PDF report', response.status, undefined, detail);
  }
  return response.blob();
}

export async function downloadJMeterPlan(jobId: string, baseUrl: string): Promise<Blob> {
  const response = await fetch(
    `${API_BASE_URL}/migration/${jobId}/jmeter?base_url=${encodeURIComponent(baseUrl)}`
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to download JMeter plan');
  }
  return response.blob();
}

export async function rerunMigrationTests(
  jobId: string,
  llmProvider: string = "huggingface",
  useLlmTests: boolean = true
): Promise<{
  job_id: string;
  tests_run: number;
  tests_passed: number;
  tests_failed: number;
  test_summary?: string | null;
  test_insights?: string[];
  test_llm_model?: string | null;
}> {
  const response = await fetch(
    `${API_BASE_URL}/migration/${jobId}/rerun-tests?llm_provider=${encodeURIComponent(llmProvider)}&use_llm_tests=${useLlmTests ? "true" : "false"}`,
    { method: "POST" }
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || "Failed to re-run tests");
  }
  return response.json();
}

// List all migrations
export async function listMigrations(): Promise<MigrationResult[]> {
  const response = await fetch(`${API_BASE_URL}/migrations`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to list migrations');
  }
  return response.json();
}

// Get available recipes
export async function getRecipes(): Promise<{ id: string; name: string; description: string }[]> {
  const response = await fetch(`${API_BASE_URL}/openrewrite/recipes`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to fetch recipes');
  }
  return response.json();
}

// Health check
export async function healthCheck(): Promise<{ status: string; timestamp: string }> {
  const response = await fetch(`${APP_BASE_URL}/health`);
  return parseJsonResponse<{ status: string; timestamp: string }>(response, 'Failed to reach backend health endpoint');
}

// Clone a repository and run a FOSSA analysis (backend will return simulated results when CLI unavailable)
export async function analyzeFossaForRepo(repoUrl: string, token: string = ""): Promise<{
  repo_url: string;
  fossa: FossaScanResult;
}> {
  const response = await fetch(`${API_BASE_URL}/fossa/analyze-url?repo_url=${encodeURIComponent(repoUrl)}&token=${encodeURIComponent(token)}`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to run FOSSA analyze');
  }
  return response.json();
}

// Update Java version in pom.xml or build.gradle
export interface UpdateJavaVersionResponse {
  success: boolean;
  file_path: string;
  java_version: string;
  message: string;
}

export async function updateJavaVersion(
  repoUrl: string, 
  javaVersion: string, 
  filePath: string, 
  token: string = ""
): Promise<UpdateJavaVersionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/github/update-java-version?repo_url=${encodeURIComponent(repoUrl)}&java_version=${encodeURIComponent(javaVersion)}&file_path=${encodeURIComponent(filePath)}&token=${encodeURIComponent(token)}`,
    { method: 'POST' }
  );
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to update Java version');
  }
  return response.json();
}

// ==================== HUGGING FACE LLM API FUNCTIONS ====================

export interface HuggingFaceBusinessLogicRequest {
  repo_url: string;
  token?: string;
  source_java_version: string;
  target_java_version: string;
  java_files?: string[];
}

export interface FileAnalysisResult {
  file_path: string;
  file_name: string;
  total_lines: number;
  issues: Array<{
    line_number: number;
    type: string;
    severity: 'high' | 'medium' | 'low';
    description: string;
    code_snippet?: string;
    suggested_fix?: string;
  }>;
  suggestions: string[];
  old_patterns_found: Array<{
    pattern: string;
    message: string;
    category: string;
    occurrences: number;
  }>;
}

export interface HuggingFaceBusinessLogicResponse {
  success: boolean;
  repo_url: string;
  analysis_type: string;
  source_version: string;
  target_version: string;
  files_analyzed: number;
  total_issues: number;
  total_old_patterns: number;
  file_results: FileAnalysisResult[];
  llm_available: boolean;
  model_used: string;
}

export interface HuggingFaceSonarResponse {
  success: boolean;
  repo_url: string;
  analysis_type: string;
  quality_gate: string;
  bugs: number;
  vulnerabilities: number;
  code_smells: number;
  coverage: number;
  duplications: number;
  issues: Array<{
    file_path: string;
    category: string;
    severity: string;
    message: string;
    line_number: number;
  }>;
  llm_insights: string[];
  llm_available: boolean;
  model_used: string;
}

export interface HuggingFaceFileSuggestionRequest {
  code_snippet: string;
  issue_description: string;
}

export interface HuggingFaceFileSuggestionResponse {
  success: boolean;
  original_code: string;
  issue_description: string;
  improved_code: string;
  llm_available: boolean;
}

export interface HuggingFaceStatusResponse {
  available: boolean;
  api_key_configured: boolean;
  models: Record<string, string>;
  timestamp: string;
}

// Hugging Face LLM Business Logic Analysis
export async function analyzeBusinessLogicWithLLM(
  request: HuggingFaceBusinessLogicRequest
): Promise<HuggingFaceBusinessLogicResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/huggingface/business-logic`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to analyze business logic with LLM');
  }
  return response.json();
}

// Hugging Face LLM SonarQube Analysis
export async function analyzeSonarWithLLM(
  repoUrl: string,
  token: string = ""
): Promise<HuggingFaceSonarResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/huggingface/sonar`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ repo_url: repoUrl, token }),
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to analyze code quality with LLM');
  }
  return response.json();
}

// Get AI improvement suggestion for specific code
export async function getFileImprovementSuggestion(
  request: HuggingFaceFileSuggestionRequest
): Promise<HuggingFaceFileSuggestionResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/huggingface/file-suggestion`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to get code improvement suggestion');
  }
  return response.json();
}

// Get Hugging Face LLM service status
export async function getHuggingFaceStatus(): Promise<HuggingFaceStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/huggingface/status`);
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || 'Failed to get Hugging Face status');
  }
  return response.json();
}
