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

type ApiQueryValue = string | number | boolean | null | undefined;

interface ApiRequestOptions extends Omit<RequestInit, "body" | "headers"> {
  baseUrl?: string;
  query?: Record<string, ApiQueryValue>;
  body?: BodyInit | object | null;
  headers?: HeadersInit;
}

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
      .map((item) => {
        if (item && typeof item === "object") {
          const typedItem = item as Record<string, unknown>;
          return typedItem.msg || typedItem.message || JSON.stringify(item);
        }
        return JSON.stringify(item);
      })
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

const ABSOLUTE_URL_PATTERN = /^https?:\/\//i;

function buildApiUrl(
  path: string,
  query: Record<string, ApiQueryValue> = {},
  baseUrl: string = API_BASE_URL
): string {
  const normalizedBaseUrl = baseUrl.replace(/\/+$/, "");
  const normalizedPath = path.replace(/^\/+/, "");
  const url = ABSOLUTE_URL_PATTERN.test(path)
    ? new URL(path)
    : new URL(normalizedPath, `${normalizedBaseUrl}/`);

  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null) {
      return;
    }
    url.searchParams.set(key, String(value));
  });

  return url.toString();
}

function isBodyInitLike(body: NonNullable<ApiRequestOptions["body"]>): body is BodyInit {
  return (
    typeof body === "string" ||
    body instanceof Blob ||
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof ArrayBuffer ||
    ArrayBuffer.isView(body)
  );
}

function buildRequestInit(options: Omit<ApiRequestOptions, "baseUrl" | "query">): RequestInit {
  const { body, headers, ...init } = options;
  const requestHeaders = new Headers(headers);

  if (body == null) {
    return { ...init, headers: requestHeaders };
  }

  if (isBodyInitLike(body)) {
    return { ...init, headers: requestHeaders, body };
  }

  if (!requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  return {
    ...init,
    headers: requestHeaders,
    body: JSON.stringify(body),
  };
}

async function performRequest(path: string, options: ApiRequestOptions = {}): Promise<Response> {
  const { baseUrl, query, ...requestInit } = options;
  return fetch(buildApiUrl(path, query, baseUrl), buildRequestInit(requestInit));
}

async function requestJson<T>(
  path: string,
  fallbackMessage: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const response = await performRequest(path, options);
  return parseJsonResponse<T>(response, fallbackMessage);
}

async function requestBlob(
  path: string,
  fallbackMessage: string,
  options: ApiRequestOptions = {}
): Promise<Blob> {
  const response = await performRequest(path, options);

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new ApiError(detail || fallbackMessage, response.status, undefined, detail);
  }

  return response.blob();
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
  visibility: "public" | "private" | "private_or_inaccessible" | "unknown";
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
  [key: string]: unknown;
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
  dependencies?: Array<Record<string, unknown>>;
  outdated_dependencies?: number | null;
  analysis_url?: string | null;
  error_message?: string | null;
  enrichment_error_message?: string | null;
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
  /** A single tool, or multiple tools to validate with. Omit for auto recommendation. */
  functional_test_method?: string | string[];
  functional_test_execution_mode?: string;
}

export interface MigrationResult {
  job_id: string;
  status: string;
  source_repo: string;
  target_repo: string | null;
  source_java_version: string;
  target_java_version: string;
  conversion_types: string[];
  started_at: string;
  worker_started_at?: string | null;
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
  bl_coverage?: number;
  test_pipeline?: {
    provider: string;
    project_kind: string;
    generated_tests_relative: string;
    test_strategy?: string | null;
    existing_tests_detected?: number;
    existing_test_files?: string[];
    migrated_test_files?: string[];
    generated_test_files: string[];
    test_summary_metrics?: Record<string, unknown> | null;
    runner: Record<string, unknown>;
    functional_testing?: {
      status?: string;
      application_type?: string;
      recommended_tools?: string[];
      allocated_port?: number;
      base_url?: string;
      generated_files?: string[];
      test_cases?: Array<{
        name?: string;
        tool?: string;
        type?: string;
        method?: string;
        path?: string;
        route?: string;
        schema?: string;
        expectedStatus?: number;
        status?: string;
        validation_reason?: string;
        source_file?: string;
        controller?: string;
      }>;
      planning?: Record<string, unknown>;
      total_tests?: number;
      existing_test_files?: number;
      existing_test_cases?: number;
      generated_test_cases?: number;
      total_test_cases?: number;
      execution_mode?: string;
      fallback_reason?: string;
      container_required?: boolean;
      container_available?: boolean;
      app_start_command?: string | null;
      runner_commands?: Array<Record<string, unknown>>;
      execution?: {
        status?: string;
        message?: string;
        tests_run?: number;
        tests_passed?: number;
        tests_failed?: number;
        startup?: Record<string, unknown>;
        runners?: Array<{
          tool?: string;
          status?: string;
          executed?: boolean;
          tests_run?: number;
          tests_passed?: number;
          tests_failed?: number;
          message?: string;
          output_tail?: string;
          execution_mode?: string;
          report_available?: boolean;
          report_tool?: string;
          allure_report_available?: boolean;
          allure_report_tool?: string;
        }>;
      };
      message?: string;
    } | null;
    manual_test_plan_path?: string | null;
    migration_patch_path?: string | null;
    deepeval_result?: Record<string, unknown> | null;
    garak_result?: Record<string, unknown> | null;
    coverage_result?: Record<string, unknown> | null;
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
  dependency_count?: number;
}

export interface MigrationJobSummary {
  job_id: string;
  status: string;
  source_repo: string;
  target_repo: string | null;
  source_java_version: string;
  target_java_version: string;
  conversion_types: string[];
  started_at: string;
  worker_started_at?: string | null;
  completed_at: string | null;
  progress_percent: number;
  current_step: string;
  files_modified: number;
  issues_fixed: number;
  api_endpoints_validated: number;
  api_endpoints_working: number;
  tests_run: number;
  tests_passed: number;
  tests_failed: number;
  sonar_quality_gate?: string | null;
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
  fossa_policy_status?: string | null;
  fossa_total_dependencies?: number;
  fossa_license_issues?: number;
  fossa_vulnerabilities?: number;
  fossa_outdated_dependencies?: number;
  fossa_scan_mode?: string | null;
  fossa_real_scan?: boolean;
  fossa_analysis_url?: string | null;
  fossa_error_message?: string | null;
  error_message: string | null;
  total_errors: number;
  total_warnings: number;
  errors_fixed: number;
  warnings_fixed: number;
  dependency_count: number;
  api_endpoint_count: number;
  issue_count: number;
  log_entry_count: number;
  file_diff_count: number;
  has_test_pipeline: boolean;
  has_sonar_report: boolean;
  has_fossa_report: boolean;
  has_testcase_doc: boolean;
  has_clone_path: boolean;
}

export interface DetectedFramework {
  name: string;
  path: string;
  type: string;
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
  jsp_files?: string[];
  jsf_files?: string[];
  jsp_count?: number;
  jsf_count?: number;
  detected_frameworks?: DetectedFramework[];
  has_tests: boolean;
  dependencies: DependencyInfo[];
  api_endpoints: { path: string; method: string; file: string }[];
  structure: {
    has_pom_xml: boolean;
    has_build_gradle: boolean;
    has_src_main: boolean;
    has_src_test: boolean;
    has_build_gradle_kts: boolean;
    jsp_count?: number;
    jsf_count?: number;
  };
  // backend-provided microservice eligibility assessment
  microservice_eligibility?: MicroserviceEligibilityResult;
}

interface MicroserviceEligibilityAnalysisSnapshot {
  build_tool: string | null;
  java_file_count: number;
  has_tests: boolean;
  dependencies: DependencyInfo[];
  structure: RepoAnalysis["structure"];
}

function buildMicroserviceEligibilityAnalysisSnapshot(repoAnalysis: RepoAnalysis): MicroserviceEligibilityAnalysisSnapshot {
  return {
    build_tool: repoAnalysis.build_tool ?? null,
    java_file_count: repoAnalysis.java_files?.length ?? 0,
    has_tests: repoAnalysis.has_tests,
    dependencies: repoAnalysis.dependencies || [],
    structure: repoAnalysis.structure,
  };
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
  metadata?: Record<string, unknown>;
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
  llm_provider?: string | null;
}

export interface JavaVersionRecommendationResponse {
  recommended_target_version: string;
  recommended_versions?: string[];
  confidence: string;
  rationale: string[];
  alternatives: string[];
  provider_used?: string;
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
  analysis: Record<string, unknown>;
}

export interface GithubDocumentResponse {
  html?: string;
  url?: string;
  filename: string;
}

function extractGithubDocumentHtml(data: Record<string, unknown>): string | undefined {
  const nestedData = data.data && typeof data.data === "object"
    ? (data.data as Record<string, unknown>)
    : undefined;
  const htmlCandidates = [
    data.html,
    data.document_html,
    data.html_content,
    data.content,
    data.document,
    data.markup,
    nestedData?.html,
    nestedData?.document_html,
    nestedData?.content,
  ];

  const htmlCandidate = htmlCandidates.find(
    (candidate): candidate is string => typeof candidate === "string" && candidate.trim().length > 0
  );

  return htmlCandidate;
}

function extractGithubDocumentUrl(data: Record<string, unknown>): string | undefined {
  const nestedData = data.data && typeof data.data === "object"
    ? (data.data as Record<string, unknown>)
    : undefined;
  const urlCandidates = [
    data.url,
    data.document_url,
    data.download_url,
    data.file_url,
    nestedData?.url,
    nestedData?.document_url,
    nestedData?.download_url,
  ];

  const urlCandidate = urlCandidates.find(
    (candidate): candidate is string => typeof candidate === "string" && candidate.trim().length > 0
  );

  return urlCandidate;
}

function resolveDocumentUrl(url: string | undefined): string | undefined {
  if (!url || !url.trim()) {
    return undefined;
  }

  return ABSOLUTE_URL_PATTERN.test(url)
    ? url
    : new URL(url.replace(/^\/+/, ""), `${APP_BASE_URL}/`).toString();
}

export interface GithubAuthCallbackResponse {
  access_token?: string;
  user?: {
    login?: string;
    [key: string]: unknown;
  };
  error?: string;
}

export async function exchangeGithubAuthCode(code: string): Promise<GithubAuthCallbackResponse> {
  return requestJson<GithubAuthCallbackResponse>(
    "/auth/github/callback",
    "GitHub login failed",
    {
      query: { code },
    }
  );
}

// Fetch GitHub repositories
export async function fetchRepositories(token: string): Promise<RepoInfo[]> {
  return requestJson<RepoInfo[]>("/github/repos", "Failed to fetch repositories", {
    query: { token },
  });
}

// Analyze a repository
export async function analyzeRepository(token: string, owner: string, repo: string): Promise<RepoAnalysis> {
  return requestJson<RepoAnalysis>(
    `/github/repo/${owner}/${repo}/analyze`,
    "Failed to analyze repository",
    {
      query: { token },
    }
  );
}

// NEW: Analyze repository directly by URL (works for public repos without token)
export async function analyzeRepoUrl(repoUrl: string, token: string = "", forceRefresh: boolean = false): Promise<RepoUrlAnalysis> {
  return requestJson<RepoUrlAnalysis>("/github/analyze-url", "Failed to analyze repository", {
    query: { repo_url: repoUrl, token, force_refresh: forceRefresh },
  });
}

export async function getRepoVisibility(repoUrl: string, token: string = ""): Promise<RepoVisibilityInfo> {
  return requestJson<RepoVisibilityInfo>("/github/repo-visibility", "Failed to check repository visibility", {
    query: { repo_url: repoUrl, token },
  });
}

export async function getLocalProjectCapabilities(): Promise<LocalProjectCapabilities> {
  return requestJson<LocalProjectCapabilities>(
    "/local-project/capabilities",
    "Failed to load local project capabilities"
  );
}

export async function analyzeLocalProject(projectPath: string): Promise<LocalProjectAnalysisResponse> {
  return requestJson<LocalProjectAnalysisResponse>(
    "/local-project/analyze",
    "Failed to analyze local project",
    {
      method: "POST",
      body: { project_path: projectPath },
    }
  );
}

export async function uploadLocalProject(formData: FormData): Promise<LocalProjectAnalysisResponse> {
  return requestJson<LocalProjectAnalysisResponse>("/local-project/upload", "Failed to upload local project", {
    method: "POST",
    body: formData,
  });
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

  return requestJson<
    LocalProjectAnalysisResponse | { status: string; upload_id: string; chunk_index: number; total_chunks: number }
  >("/local-project/upload-chunk", "Failed to upload local project chunk", {
    method: "POST",
    body: formData,
  });
}

export async function listLocalProjectFiles(projectPath: string, path: string = ""): Promise<RepoFilesResponse> {
  return requestJson<RepoFilesResponse>("/local-project/list-files", "Failed to list local project files", {
    query: { project_path: projectPath, path },
  });
}

export async function getLocalProjectFileContent(projectPath: string, filePath: string): Promise<FileContentResponse> {
  return requestJson<FileContentResponse>(
    "/local-project/file-content",
    "Failed to get local project file content",
    {
      query: { project_path: projectPath, file_path: filePath },
    }
  );
}

// NEW: List files in a repository (works for public repos without token)
export async function listRepoFiles(repoUrl: string, token: string = "", path: string = ""): Promise<RepoFilesResponse> {
  return requestJson<RepoFilesResponse>("/github/list-files", "Failed to list files", {
    query: { repo_url: repoUrl, token, path },
  });
}

// NEW: Get file content (works for public repos without token)
export async function getFileContent(repoUrl: string, filePath: string, token: string = ""): Promise<FileContentResponse> {
  return requestJson<FileContentResponse>("/github/file-content", "Failed to get file content", {
    query: { repo_url: repoUrl, file_path: filePath, token },
  });
}

export async function getMicroserviceEligibility(
  repoUrl: string,
  token: string = "",
  repoAnalysis?: RepoAnalysis,
): Promise<MicroserviceEligibilityResult> {
  return requestJson<MicroserviceEligibilityResult>(
    "/github/microservice-eligibility",
    "Failed to get microservice eligibility",
    {
      method: "POST",
      body: {
        repo_url: repoUrl,
        token,
        analysis: repoAnalysis ? buildMicroserviceEligibilityAnalysisSnapshot(repoAnalysis) : undefined,
      },
    }
  );
}

export async function getLocalProjectMicroserviceEligibility(
  projectPath: string,
  repoAnalysis?: RepoAnalysis,
): Promise<MicroserviceEligibilityResult> {
  return requestJson<MicroserviceEligibilityResult>(
    "/local-project/microservice-eligibility",
    "Failed to get local project microservice eligibility",
    {
      method: "POST",
      body: {
        project_path: projectPath,
        analysis: repoAnalysis ? buildMicroserviceEligibilityAnalysisSnapshot(repoAnalysis) : undefined,
      },
    }
  );
}

// Get available Java versions
export async function getJavaVersions(): Promise<JavaVersionInfo> {
  return requestJson<JavaVersionInfo>("/java-versions", "Failed to fetch Java versions");
}

export async function getJavaVersionRecommendation(
  request: JavaVersionRecommendationRequest
): Promise<JavaVersionRecommendationResponse> {
  return requestJson<JavaVersionRecommendationResponse>(
    "/java-version-recommendation",
    "Failed to get Java version recommendation",
    {
      method: "POST",
      body: request,
    }
  );
}

export interface StrategyQueryRequest {
  repo_url?: string;
  question: string;
  analysis?: unknown;
  strategy_context?: StrategyPageContext | null;
  provider?: string | null;
}

export interface StrategyPageContext {
  page?: string;
  repository?: {
    name?: string | null;
    full_name?: string | null;
    url?: string | null;
    language?: string | null;
  };
  assessment?: {
    risk_level?: string | null;
    risk_reason?: string | null;
    build_tool?: string | null;
    java_version?: string | null;
    has_tests?: boolean | null;
    dependency_count?: number | null;
  };
  strategy?: {
    source_java_version?: string | null;
    target_java_version?: string | null;
    selected_conversions?: string[];
    source_already_at_latest_supported_version?: boolean | null;
  };
  migration_destination?: {
    approach?: string | null;
    label?: string | null;
    description?: string | null;
    target_repo_name?: string | null;
    target_repo_owner?: string | null;
    target_repo_host?: string | null;
    target_repo_name_editable?: boolean | null;
    target_repo_name_source?: string | null;
  };
  migration_approach_options?: Array<{
    value?: string | null;
    label?: string | null;
    desc?: string | null;
    tooltip?: string | null;
  }>;
  recommendation?: {
    recommended_target_version?: string | null;
    recommended_versions?: string[];
    confidence?: string | null;
    rationale?: string[];
    alternatives?: string[];
    alternative_options?: Array<{
      version: string;
      risk?: string;
      reason?: string;
    }>;
  };
  dependency_overview?: Array<{
    group_id?: string | null;
    artifact_id?: string | null;
    current_version?: string | null;
    status?: string | null;
  }>;
  dependency_risk_summary?: {
    critical?: number;
    high?: number;
    medium?: number;
    low?: number;
  };
  attention_dependencies?: Array<{
    display_name?: string | null;
    current_version?: string | null;
    risk?: string | null;
    reason?: string | null;
    status?: string | null;
    category?: string | null;
  }>;
  conversion_options?: Array<{
    key: string;
    title: string;
    status: string;
    description?: string;
  }>;
}

export interface StrategyAnswerResponse {
  answer: string;
  rationale?: string[];
  details?: Record<string, unknown>;
}

export async function queryStrategy(
  request: StrategyQueryRequest
): Promise<StrategyAnswerResponse> {
  return requestJson<StrategyAnswerResponse>(
    "/strategy/query",
    "Failed to query strategy assistant",
    {
      method: "POST",
      body: request,
    }
  );
}

export async function generateGithubDocument(
  documentType: GithubDocumentType,
  request: GithubDocumentRequest
): Promise<GithubDocumentResponse> {
  const response = await performRequest(`/github/generate-${documentType}-document`, {
    method: "POST",
    body: request,
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
      url: resolveDocumentUrl(url),
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
  const response = await requestJson<GithubDocumentResponse>(
    "/local-project/generate-brd-document",
    "Failed to generate BRD document",
    {
      method: "POST",
      body: request,
    }
  );
  return {
    ...response,
    url: resolveDocumentUrl(response.url),
  };
}

// Get available conversion types
export async function getConversionTypes(): Promise<ConversionType[]> {
  return requestJson<ConversionType[]>("/conversion-types", "Failed to fetch conversion types");
}

// Start migration
export async function startMigration(request: MigrationRequest): Promise<MigrationResult> {
  return requestJson<MigrationResult>("/migration/start", "Failed to start migration", {
    method: "POST",
    body: request,
  });
}

export async function previewMigration(request: MigrationRequest): Promise<MigrationPreview> {
  return requestJson<MigrationPreview>("/migration/preview", "Failed to preview migration changes", {
    method: "POST",
    body: request,
  });
}

// Get lightweight migration status
export async function getMigrationStatus(jobId: string): Promise<MigrationJobSummary> {
  return requestJson<MigrationJobSummary>(`/migration/${jobId}`, "Failed to get migration status");
}

export async function getMigrationDetail(jobId: string): Promise<MigrationResult> {
  return requestJson<MigrationResult>(`/migration/${jobId}/detail`, "Failed to get migration detail");
}

export async function getMigrationStatusSummary(jobId: string): Promise<MigrationJobSummary> {
  return requestJson<MigrationJobSummary>(`/migration/${jobId}/summary`, "Failed to get migration summary");
}

// Get migration logs
export async function getMigrationLogs(jobId: string): Promise<{ job_id: string; logs: string[] }> {
  return requestJson<{ job_id: string; logs: string[] }>(
    `/migration/${jobId}/logs`,
    "Failed to get migration logs"
  );
}

// Get FOSSA scan results for a migration (if available)
export async function getMigrationFossa(jobId: string): Promise<{
  job_id: string;
  fossa: FossaScanResult;
}> {
  const data = await requestJson<{ fossa?: FossaScanResult } | FossaScanResult>(
    `/migration/${jobId}/fossa`,
    "Failed to get FOSSA results"
  );
  return {
    job_id: jobId,
    fossa:
      "fossa" in data && data.fossa
        ? data.fossa
        : (data as FossaScanResult),
  };
}

// Download migrated project as ZIP
export async function downloadMigratedProject(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/download-zip`, "Failed to download migrated project");
}

// Download migration report
export async function downloadMigrationReport(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/report`, "Failed to download migration report");
}

// Download testcase + change report (Markdown)
export async function downloadTestcaseDoc(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/testcase-doc`, "Failed to download testcase doc");
}

export async function downloadTestcaseDocx(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/testcase-docx`, "Failed to download testcase docx");
}

// Download testcase + change report (HTML)
export async function downloadTestcaseReport(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/testcase-report`, "Failed to download testcase report");
}

export async function downloadUnitTestReport(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/unit-test-report`, "Failed to download unit test report");
}

export interface FunctionalTestScopePreview {
  uiScopeHtml: string;
  apiScopeHtml: string;
  uiTestCount: number;
  apiTestCount: number;
  uiTestCases?: FunctionalUiTestCase[];
  apiTestCases?: FunctionalApiTestCase[];
  existingTestFiles?: ExistingTestFile[];
  existingTestFilesAll?: ExistingTestFile[];
  existingTestFileCounts?: ExistingTestFileCounts;
  existingTestFilesTotal?: number;
  applicationType?: string;
}

export interface FunctionalUiTestCase {
  route: string;
  framework: string;
  description: string;
  fields?: string[];
  actions?: string[];
  interaction: string;
  source?: string;
}

export interface FunctionalApiTestCase {
  method: string;
  path: string;
  controller?: string;
  description: string;
  expectedStatus: number;
}

export interface ExistingTestFile {
  path: string;
  category: string; // "UNIT" | "E2E"
  label: string;    // "JUnit" | "MockMvc" | "Test Framework" | "E2E"
}

export interface ExistingTestFileCounts {
  junit: number;
  mockMvc: number;
  testFramework: number;
  e2e: number;
}

export async function previewFunctionalTestScope(
  projectName: string,
  endpoints: { path: string; method: string; file?: string; controller?: string }[],
  uiRoutes: { route: string; source_file?: string; page_type?: string; component?: string }[],
  pageData: Record<string, any>,
  selectedTools: string[] = [],
  repoUrl: string = "",
  token: string = "",
): Promise<FunctionalTestScopePreview> {
  return requestJson<FunctionalTestScopePreview>(
    `/functional-test-scope/preview`,
    "Failed to generate functional test scope preview",
    {
      method: "POST",
      body: {
        project_name: projectName,
        endpoints,
        uiRoutes,
        page_data: pageData,
        selected_tools: selectedTools,
        repo_url: repoUrl,
        token: token,
      },
    },
  );
}

export async function downloadSonarReportPdf(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/sonar-report-pdf`, "Failed to download Sonar PDF report");
}

export async function downloadJMeterPlan(jobId: string, baseUrl: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/jmeter`, "Failed to download JMeter plan", {
    query: { base_url: baseUrl },
  });
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
  return requestJson<{
    job_id: string;
    tests_run: number;
    tests_passed: number;
    tests_failed: number;
    test_summary?: string | null;
    test_insights?: string[];
    test_llm_model?: string | null;
  }>(`/migration/${jobId}/rerun-tests`, "Failed to re-run tests", {
    method: "POST",
    query: {
      llm_provider: llmProvider,
      use_llm_tests: useLlmTests ? "true" : "false",
    },
  });
}

// List all migrations
export async function listMigrations(): Promise<MigrationJobSummary[]> {
  return requestJson<MigrationJobSummary[]>("/migrations", "Failed to list migrations");
}

export async function listMigrationSummaries(): Promise<MigrationJobSummary[]> {
  return requestJson<MigrationJobSummary[]>("/migrations/summary", "Failed to list migration summaries");
}

// Get available recipes
export async function getRecipes(): Promise<{ id: string; name: string; description: string }[]> {
  return requestJson<{ id: string; name: string; description: string }[]>(
    "/openrewrite/recipes",
    "Failed to fetch recipes"
  );
}

// Health check
export async function healthCheck(): Promise<{ status: string; timestamp: string }> {
  return requestJson<{ status: string; timestamp: string }>(
    "/health",
    "Failed to reach backend health endpoint",
    {
      baseUrl: APP_BASE_URL,
    }
  );
}

// Clone a repository and run a FOSSA analysis (backend will return simulated results when CLI unavailable)
export async function analyzeFossaForRepo(repoUrl: string, token: string = ""): Promise<{
  repo_url: string;
  fossa: FossaScanResult;
}> {
  return requestJson<{ repo_url: string; fossa: FossaScanResult }>(
    "/fossa/analyze-url",
    "Failed to run FOSSA analyze",
    {
      query: { repo_url: repoUrl, token },
    }
  );
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
  return requestJson<UpdateJavaVersionResponse>(
    "/github/update-java-version",
    "Failed to update Java version",
    {
      method: "POST",
      query: {
        repo_url: repoUrl,
        java_version: javaVersion,
        file_path: filePath,
        token,
      },
    }
  );
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
  return requestJson<HuggingFaceBusinessLogicResponse>(
    "/ai/huggingface/business-logic",
    "Failed to analyze business logic with LLM",
    {
      method: "POST",
      body: request,
    }
  );
}

// Hugging Face LLM SonarQube Analysis
export async function analyzeSonarWithLLM(
  repoUrl: string,
  token: string = ""
): Promise<HuggingFaceSonarResponse> {
  return requestJson<HuggingFaceSonarResponse>(
    "/ai/huggingface/sonar",
    "Failed to analyze code quality with LLM",
    {
      method: "POST",
      body: { repo_url: repoUrl, token },
    }
  );
}

// Get AI improvement suggestion for specific code
export async function getFileImprovementSuggestion(
  request: HuggingFaceFileSuggestionRequest
): Promise<HuggingFaceFileSuggestionResponse> {
  return requestJson<HuggingFaceFileSuggestionResponse>(
    "/ai/huggingface/file-suggestion",
    "Failed to get code improvement suggestion",
    {
      method: "POST",
      body: request,
    }
  );
}

// Get Hugging Face LLM service status
export async function getHuggingFaceStatus(): Promise<HuggingFaceStatusResponse> {
  return requestJson<HuggingFaceStatusResponse>(
    "/ai/huggingface/status",
    "Failed to get Hugging Face status"
  );
}

// Fetch the content of a single generated functional test file for viewing or download
export async function getFunctionalTestFileContent(jobId: string, path: string): Promise<string> {
  const response = await performRequest(`/migration/${jobId}/functional-test-file`, {
    query: { path },
  });
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new ApiError(detail || "Failed to fetch functional test file", response.status, undefined, detail);
  }
  return response.text();
}

// Download all generated functional test files as a ZIP archive
export async function downloadFunctionalTestsZip(jobId: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/functional-tests-zip`, "Failed to download functional tests ZIP archive");
}

// Download a single functional test case file as a blob
export async function downloadFunctionalTestFile(jobId: string, path: string): Promise<Blob> {
  return requestBlob(`/migration/${jobId}/functional-test-file`, "Failed to download functional test file", {
    query: { path },
  });
}

// Build the URL for a Playwright/Selenium HTML report (opened in a new tab)
export function getFunctionalTestReportUrl(jobId: string, tool: string): string {
  return `${API_BASE_URL}/migration/${jobId}/functional-test-report/${tool.toLowerCase()}`;
}
