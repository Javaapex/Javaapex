""" 
Java Migration Backend - Main FastAPI Application
Handles Java 7 → Java 18 migration automation using OpenRewrite
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, UploadFile
from fastapi.responses import Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import uuid
import os
import sys
import re
import html as _html
import logging
import shutil
from datetime import datetime, timezone
from github import GithubException
from urllib.parse import urlparse

# Force line-buffered output for immediate logging when supported by the runtime.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# Configure verbose logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    force=True
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/")


def _parse_origin_list(value: str) -> List[str]:
    seen = set()
    origins: List[str] = []
    for raw_origin in value.split(","):
        origin = _normalize_origin(raw_origin)
        if not origin or origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return origins


def _parse_cors_origins() -> List[str]:
    configured = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = _parse_origin_list(configured)
    if origins:
        return origins

    frontend_origin = _normalize_origin(os.environ.get("FRONTEND_ORIGIN", ""))
    if frontend_origin:
        return [frontend_origin]

    return [
        "https://java-apex-accelerator.onrender.com",
        "https://java-apex-backend.onrender.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5175",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://javaapex-frontend-r4sl.onrender.com"
    ]


CORS_ALLOWED_ORIGINS = _parse_cors_origins()


from services.github_service import GitHubService
from services.gitlab_service import GitLabService
from services.migration_service import MigrationService
from services.email_service import EmailService
from services.sonarqube_service import (
    SonarQubeConfigurationError,
    SonarQubeExecutionError,
    SonarQubeService,
)
from services.microservice_readiness_service import microservice_readiness_service
from services.microservice_splitter import split_project_into_microservices
from services.microservice_conversion_service import microservice_conversion_service
from services.repository_workspace_service import RepositoryWorkspace
from services.auth_service import router as auth_router
from routers.github_repository_router import router as github_repository_router
from routers.local_project_router import router as local_project_router
from routers.microservice_eligibility_router import router as microservice_eligibility_router
from services.fossa_service import FossaConfigurationError, FossaExecutionError, FossaService
from services.github_clone_analysis_service import github_clone_analysis_service
from services.local_project_service import local_project_service
from services.ai_service_huggingface import huggingface_ai_service
from services.persistent_job_store import PersistentJobStore


app = FastAPI(
    title="Java Migration Accelerator API",
    description="End-to-end Java 7 → Java 18 migration automation using OpenRewrite",
    version="1.0.0"
)


# Configure request limits for DigitalOcean App Platform
# DigitalOcean has stricter default limits than Render
# Limits are configured via environment variables and uvicorn command line args
# Custom middleware to log all HTTP requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    client_host = request.client.host if request.client else "unknown"
    method = request.method
    url = str(request.url)
    
    print(f"[HTTP] {method} {url} - From: {client_host}")
    sys.stdout.flush()
    
    response = await call_next(request)
    
    print(f"[HTTP] {method} {url} - Status: {response.status_code}")
    sys.stdout.flush()
    
    return response

# Custom middleware to handle large request bodies for DigitalOcean (up to 1GB+ files)
@app.middleware("http")
async def large_request_middleware(request: Request, call_next):
    # Check if this is a file upload request
    if request.method == "POST" and "/local-project/upload" in str(request.url):
        # Log large file uploads for monitoring
        content_length = request.headers.get("content-length")
        if content_length:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > 100:  # Log uploads over 100MB
                logger.info(f"Large file upload detected: {size_mb:.1f}MB")
    
    response = await call_next(request)
    return response

# Register auth router
app.include_router(auth_router, prefix="/api")
app.include_router(github_repository_router, prefix="/api")
app.include_router(local_project_router, prefix="/api")
app.include_router(microservice_eligibility_router, prefix="/api")

# Default GitHub token from environment variable (set in Render dashboard)
DEFAULT_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")
INDEX_FILE = os.path.join(STATIC_DIR, "index.html")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("Configured CORS allowed origins: %s", CORS_ALLOWED_ORIGINS)


def _first_nonempty_token(*values: Optional[str]) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _effective_github_token(token: str = "", github_token: str = "") -> str:
    return _first_nonempty_token(github_token, token, DEFAULT_GITHUB_TOKEN)


def _is_local_project_reference(source_reference: str) -> bool:
    return (source_reference or "").startswith("local://")


def _extract_local_project_path(source_reference: str) -> str:
    return (source_reference or "").replace("local://", "", 1)


async def _resolve_source_project_path(
    source_repo_url: str,
    repo_service,
    source_token: str,
) -> str:
    if _is_local_project_reference(source_repo_url):
        local_path = _extract_local_project_path(source_repo_url)
        return local_project_service.resolve_local_project_path(local_path)
    return await repo_service.clone_repository(source_token, source_repo_url)


async def _prepare_source_working_copy(
    source_repo_url: str,
    repo_service,
    source_token: str,
) -> str:
    if _is_local_project_reference(source_repo_url):
        local_path = _extract_local_project_path(source_repo_url)
        return await local_project_service.stage_project_copy(local_path)
    return await repo_service.clone_repository(source_token, source_repo_url)


def _infer_local_project_name(source_repo_url: str) -> str:
    local_path = _extract_local_project_path(source_repo_url)
    normalized = local_project_service.resolve_local_project_path(local_path)
    return os.path.basename(normalized.rstrip("\\/")) or "local-project"


def frontend_available() -> bool:
    return os.path.isfile(INDEX_FILE)


def serve_frontend_path(path: str = "") -> FileResponse:
    if not frontend_available():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    static_root = os.path.abspath(STATIC_DIR)
    normalized_path = path.strip("/")
    if normalized_path:
        candidate = os.path.abspath(os.path.join(static_root, normalized_path))
        if os.path.commonpath([static_root, candidate]) != static_root:
            raise HTTPException(status_code=404, detail="Invalid static path")

        if os.path.isfile(candidate):
            return FileResponse(candidate)

        if os.path.splitext(normalized_path)[1]:
            raise HTTPException(status_code=404, detail="Static asset not found")

    return FileResponse(INDEX_FILE)

# Initialize services
github_service = GitHubService()
gitlab_service = GitLabService()
migration_service = MigrationService()
email_service = EmailService()
sonarqube_service = SonarQubeService()
# FOSSA service (provides simulated/dummy data when the CLI/API is unavailable)
fossa_service = FossaService()

def raise_missing_migration_job(job_id: str) -> None:
    persistence_hint = (
        "Restart the migration, or verify the Redis-backed job store configuration and retention settings."
        if "migration_jobs" in globals() and getattr(migration_jobs, "persistence_enabled", False)
        else "Restart the migration. For production, persist job state in Redis or a database."
    )
    detail_message = (
        "Migration job status is no longer available. This can happen if the backend process restarts before the job is persisted, "
        "if persistence is not configured, or if the stored job has expired."
    )
    raise HTTPException(
        status_code=404,
        detail={
            "code": "MIGRATION_JOB_NOT_FOUND",
            "message": detail_message,
            "job_id": job_id,
            "hint": persistence_hint,
        },
    )


def save_migration_job(job: "MigrationResult") -> None:
    migration_jobs[job.job_id] = job


def _parse_positive_int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
        return parsed if parsed > 0 else 0
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %s", name, raw_value, default)
        return default


class JavaVersion(str, Enum):
    JAVA_7 = "7"
    JAVA_8 = "8"
    JAVA_11 = "11"
    JAVA_17 = "17"
    JAVA_18 = "18"
    JAVA_21 = "21"
    JAVA_22 = "22"
    JAVA_23 = "23"
    JAVA_24 = "24"
    JAVA_25 = "25"


class ConversionType(str, Enum):
    JAVA_VERSION = "java_version"
    MAVEN_TO_GRADLE = "maven_to_gradle"
    GRADLE_TO_MAVEN = "gradle_to_maven"
    JAVAX_TO_JAKARTA = "javax_to_jakarta"
    JAKARTA_TO_JAVAX = "jakarta_to_javax"
    SPRING_BOOT_2_TO_3 = "spring_boot_2_to_3"
    JUNIT_4_TO_5 = "junit_4_to_5"
    LOG4J_TO_SLF4J = "log4j_to_slf4j"


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueStatus(str, Enum):
    DETECTED = "detected"
    FIXED = "fixed"
    MANUAL_REVIEW = "manual_review"
    IGNORED = "ignored"


class MigrationStatus(str, Enum):
    PENDING = "pending"
    CLONING = "cloning"
    ANALYZING = "analyzing"
    MIGRATING = "migrating"
    TESTING = "testing"
    FOSSA_ANALYSIS = "fossa_analysis"
    SONAR_ANALYSIS = "sonar_analysis"
    PUSHING = "pushing"
    COMPLETED = "completed"
    FAILED = "failed"


class GitPlatform(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"


class MigrationRequest(BaseModel):
    source_repo_url: str = Field(description="Repository URL (GitHub or GitLab), or a local project reference like local://<absolute-path>")
    target_repo_name: str = Field(description="Target repository URL/name for new-repository migrations, target branch name for branch-based migrations, or target local folder name for local-output migrations")
    migration_approach: str = Field(default="fork", description="Migration publish mode: fork for a new repository, branch for pushing to a new branch in the source repository, or local for saving to a local folder")
    platform: GitPlatform = Field(default=GitPlatform.GITHUB, description="Git platform (GitHub or GitLab)")
    source_java_version: str = Field(default="7", description="Current Java version")
    target_java_version: JavaVersion = Field(default=JavaVersion.JAVA_18, description="Target Java version")
    token: Optional[str] = Field(default="", description="Git provider token. For GitHub private repositories this PAT is used for clone, analysis, and push operations.")
    github_token: Optional[str] = Field(default="", description="Optional GitHub PAT alias for private repository clone, analysis, and push operations.")
    build_tool: Optional[str] = Field(default=None, description="Detected source build tool, for example maven or gradle")
    conversion_types: List[str] = Field(default=["java_version"], description="Types of conversions to perform")
    email: Optional[str] = Field(default=None, description="Email for migration summary")
    run_tests: bool = Field(default=True, description="Run tests after migration")
    use_llm_tests: bool = Field(default=True, description="Use an LLM to generate tests and a test plan")
    llm_test_provider: str = Field(default="fordllm", description="LLM provider (fordllm | openai | groq | deepseek | huggingface | ollama | offline)")
    run_sonar: bool = Field(default=True, description="Run SonarQube analysis")
    run_fossa: bool = Field(default=False, description="Run FOSSA license and dependency scan")
    fix_business_logic: bool = Field(default=True, description="Attempt to fix business logic issues")
    migration_type: str = Field(default="monolithic", description="Migration output mode: monolithic or microservices")


class MigrationIssue(BaseModel):
    id: str
    severity: IssueSeverity
    status: IssueStatus
    category: str  # e.g., "API Change", "Deprecated Method", "Build Error"
    message: str
    file_path: str
    line_number: Optional[int] = None
    column: Optional[int] = None
    code_snippet: Optional[str] = None
    suggested_fix: Optional[str] = None
    fixed_at: Optional[datetime] = None
    conversion_type: str  # which conversion caused this


class DependencyInfo(BaseModel):
    group_id: str
    artifact_id: str
    current_version: str
    new_version: Optional[str] = None
    status: str  # "upgraded", "compatible", "needs_manual_review"


class JavaVersionRecommendationRequest(BaseModel):
    source_java_version: str
    detected_java_version: Optional[str] = None
    build_tool: Optional[str] = None
    dependencies: List[DependencyInfo] = []
    has_tests: bool = False
    api_endpoint_count: int = 0
    risk_level: Optional[str] = None


class JavaVersionAlternativeOption(BaseModel):
    version: str
    risk: Optional[str] = None
    reason: Optional[str] = None


class JavaVersionRecommendationResponse(BaseModel):
    recommended_target_version: str
    recommended_versions: List[str] = []
    confidence: str
    rationale: List[str] = []
    alternatives: List[str] = []
    alternative_options: List[JavaVersionAlternativeOption] = []
    raw_recommendation: Dict[str, Any] = {}


class MicroserviceEligibilityResult(BaseModel):
    eligible: bool
    confidence_score: int
    microservice_fit_score: Optional[int] = None
    migration_readiness_score: Optional[int] = None
    confidence: Optional[str] = None
    reasoning: Optional[str] = None
    assessment_label: Optional[str] = None
    assessment_summary: Optional[str] = None
    signals_for: List[str] = []
    signals_against: List[str] = []
    java_files_count: Optional[int] = None
    controllers_count: Optional[int] = None
    services_count: Optional[int] = None
    entities_count: Optional[int] = None
    endpoint_domains_count: Optional[int] = None
    inferred_service_boundaries_count: Optional[int] = None
    suggested_services: List[str] = []
    folder_structure: Optional[Any] = None


class MicroserviceEligibilityResponse(BaseModel):
    repo_url: str
    owner: str
    repo: str
    microservice_eligibility: MicroserviceEligibilityResult


class TestPipelineReport(BaseModel):
    """Report from LLM test pipeline execution"""
    provider: str
    project_kind: str
    generated_tests_relative: str
    test_strategy: Optional[str] = None
    existing_tests_detected: int = 0
    existing_test_files: List[str] = []
    migrated_test_files: List[str] = []
    generated_test_files: List[str] = []
    runner: Dict[str, Any] = {}
    manual_test_plan_path: Optional[str] = None
    migration_patch_path: Optional[str] = None
    deepeval_result: Optional[Dict[str, Any]] = None
    garak_result: Optional[Dict[str, Any]] = None
    coverage_result: Optional[Dict[str, Any]] = None


class FileDiffEntry(BaseModel):
    file_path: str
    diff: str
    change_count: int = 0


class MigrationResult(BaseModel):
    job_id: str
    status: MigrationStatus
    source_repo: str
    target_repo: Optional[str] = None
    source_java_version: str
    target_java_version: str
    conversion_types: List[str] = []
    started_at: datetime
    completed_at: Optional[datetime] = None
    progress_percent: int = 0
    current_step: str = ""
    dependencies: List[DependencyInfo] = []
    files_modified: int = 0
    issues_fixed: int = 0
    api_endpoints_validated: int = 0
    api_endpoints_working: int = 0
    api_endpoints: List[Dict[str, str]] = []
    sonar_quality_gate: Optional[str] = None
    sonar_bugs: int = 0
    sonar_vulnerabilities: int = 0
    sonar_code_smells: int = 0
    sonar_coverage: float = 0.0
    sonar_duplications: float = 0.0
    sonar_security_hotspots: int = 0
    sonar_scan_mode: Optional[str] = None
    sonar_real_scan: bool = False
    sonar_analysis_url: Optional[str] = None
    sonar_error_message: Optional[str] = None
    sonar_report: Optional[Dict[str, Any]] = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    test_summary: Optional[str] = None
    test_insights: List[str] = []
    test_llm_model: Optional[str] = None
    test_pipeline: Optional[TestPipelineReport] = None
    # FOSSA results
    fossa_policy_status: Optional[str] = None
    fossa_total_dependencies: int = 0
    fossa_license_issues: int = 0
    fossa_vulnerabilities: int = 0
    fossa_outdated_dependencies: int = 0
    fossa_scan_mode: Optional[str] = None
    fossa_real_scan: bool = False
    fossa_analysis_url: Optional[str] = None
    fossa_error_message: Optional[str] = None
    fossa_report: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    migration_log: List[str] = []
    # Issue tracking
    issues: List[MigrationIssue] = []
    total_errors: int = 0
    total_warnings: int = 0
    errors_fixed: int = 0
    warnings_fixed: int = 0
    # Local artifacts (only for local runs)
    clone_path: Optional[str] = None
    testcase_doc_path: Optional[str] = None
    microservice_output_path: Optional[str] = None
    migration_type: str = "monolithic"
    file_diffs: List[FileDiffEntry] = []
    extra_metadata: Optional[Dict[str, Any]] = None


FINISHED_MIGRATION_JOB_TTL_SECONDS = _parse_positive_int_env("MIGRATION_JOB_FINISHED_TTL_SECONDS", 7 * 24 * 60 * 60)
FAILED_MIGRATION_JOB_TTL_SECONDS = _parse_positive_int_env("MIGRATION_JOB_FAILED_TTL_SECONDS", FINISHED_MIGRATION_JOB_TTL_SECONDS)


def _migration_job_ttl(job: MigrationResult) -> Optional[int]:
    if job.status == MigrationStatus.COMPLETED:
        return FINISHED_MIGRATION_JOB_TTL_SECONDS or None
    if job.status == MigrationStatus.FAILED:
        return FAILED_MIGRATION_JOB_TTL_SECONDS or None
    return None


migration_jobs: PersistentJobStore[MigrationResult] = PersistentJobStore(
    serializer=lambda job: job.model_dump(mode="json"),
    deserializer=lambda data: MigrationResult.model_validate(data),
    redis_url=os.environ.get("REDIS_URL", ""),
    namespace=os.environ.get("MIGRATION_JOB_STORE_NAMESPACE", "migration"),
    ttl_for_value=_migration_job_ttl,
)


class RepoInfo(BaseModel):
    name: str
    full_name: str
    url: str
    default_branch: str
    language: Optional[str] = None
    description: Optional[str] = None


class RepoVisibilityInfo(BaseModel):
    owner: str
    repo: str
    visibility: str
    requires_token: bool
    message: str


@app.get("/")
@app.head("/")
async def root():
    if frontend_available():
        return serve_frontend_path("")
    return {"message": "Java Migration Accelerator API", "version": "1.0.0"}


@app.get("/health")
@app.head("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_store": {
            **migration_jobs.capabilities(),
            "finished_job_ttl_seconds": FINISHED_MIGRATION_JOB_TTL_SECONDS,
            "failed_job_ttl_seconds": FAILED_MIGRATION_JOB_TTL_SECONDS,
            "execution_mode": "in_process_background_tasks",
            "restart_safe_execution": False,
        },
    }


@app.get("/api/system/job-store")
async def get_job_store_capabilities():
    return {
        "job_store": {
            **migration_jobs.capabilities(),
            "finished_job_ttl_seconds": FINISHED_MIGRATION_JOB_TTL_SECONDS,
            "failed_job_ttl_seconds": FAILED_MIGRATION_JOB_TTL_SECONDS,
            "execution_mode": "in_process_background_tasks",
            "restart_safe_execution": False,
        }
    }


# GitHub Endpoints
@app.get("/api/github/repos", response_model=List[RepoInfo])
async def list_github_repos(token: str):
    """List all repositories accessible with the provided GitHub token"""
    try:
        repos = await github_service.list_repositories(token)
        return repos
    except GithubException as e:
        status_code = getattr(e, 'status', 400)
        error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
        
        if status_code == 401:
            error_msg = "Invalid PAT token."
        else:
            error_msg = f"GitHub API error ({status_code}): {error_msg}"
        
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/github/repo-visibility")
async def get_repo_visibility(repo_url: str, token: str = ""):
    """Check whether a repository is public or requires authentication."""
    owner, repo = await github_service.parse_repo_url(repo_url)
    try:
        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
        info = await github_service.get_repo_info(effective_token, owner, repo, repo_url)
        visibility = "private" if info.get("is_private") else "public"
        return {
            "owner": owner,
            "repo": repo,
            "visibility": visibility,
            "requires_token": visibility != "public",
            "message": "Repository is accessible." if visibility == "public" else "Repository requires authentication.",
        }
    except Exception as e:
        message = str(e)
        if (
            "not found" in message.lower()
            or "access denied" in message.lower()
            or "authentication failed" in message.lower()
            or "does not have access" in message.lower()
        ):
            return {
                "owner": owner,
                "repo": repo,
                "visibility": "private_or_inaccessible",
                "requires_token": True,
                "message": message,
            }
        raise HTTPException(status_code=500, detail=f"Failed to check repository visibility: {message}")


@app.post("/api/github/generate-kt-document")
@app.post("/api/github/generate-brd-document")
async def generate_brd_document(request: dict):
    """
    Generate a BRD/KT-style document for a GitHub repository.

    The original Ford-specific implementation referenced services and cache keys that
    do not exist in this codebase today. This version keeps the same endpoint shape,
    but adapts generation to the backend's existing GitHub analysis service.
    """
    try:
        from services.github_service import get_cached

        repo_url = (request or {}).get("repo_url")
        token = (request or {}).get("token", "")
        github_token = (request or {}).get("github_token", "")

        if not repo_url:
            raise HTTPException(status_code=400, detail="repo_url is required")

        effective_token = _effective_github_token(token=token, github_token=github_token)
        owner, repo = await github_service.parse_repo_url(repo_url)

        logger.info("[BRD DOCUMENT API] Retrieving/generating BRD document for %s/%s", owner, repo)
        safe_repo_name = re.sub(r"[^A-Za-z0-9._-]+", "-", repo).strip("-") or "repository"
        document_filename = f"{safe_repo_name.upper()}-TECHNICAL-DOCUMENT.html"

        analysis_cache_keys = [
            f"analysis:{owner}/{repo}",
            f"analysis:v2:{owner}/{repo}:deep=True",
            f"analysis:v2:{owner}/{repo}:deep=False",
        ]

        analysis = None
        cache_key_used = None
        if not effective_token:
            for cache_key in analysis_cache_keys:
                analysis = get_cached(cache_key)
                if analysis:
                    cache_key_used = cache_key
                    break

        if not analysis:
            logger.info("[BRD DOCUMENT API] No cached clone-first analysis found; running fresh analysis")
            _, analysis = await github_clone_analysis_service.analyze_repository(
                repo_reference=repo_url,
                token=effective_token,
                force_refresh=False,
            )
            cache_key_used = "fresh-analysis"

        if analysis.get("has_kt_document") and analysis.get("kt_document"):
            logger.info("[BRD DOCUMENT API] Using pre-generated BRD document from analysis cache")
            document = _enrich_brd_document(analysis.get("kt_document") or {}, analysis, f"{owner}/{repo}")
            html_content = _generate_brd_html(document, repo, repo_url, analysis_data=analysis)
            return {
                "success": True,
                "document": document,
                "html": html_content,
                "filename": document_filename,
                "generated_at": analysis.get("kt_document_generated_at"),
                "repo_url": repo_url,
                "source": f"Pre-generated BRD from cached analysis ({cache_key_used})",
                "metadata": analysis.get("kt_document_metadata", {}),
            }

        logger.info(
            "[BRD DOCUMENT API] Generating BRD from analysis data: deps=%s vulnerable=%s files=%s frameworks=%s",
            len(analysis.get("dependencies", [])),
            len(analysis.get("vulnerable_dependencies", [])),
            len(analysis.get("all_files", [])),
            analysis.get("detected_frameworks", []),
        )

        document = _build_brd_document_from_analysis(
            repo_name=f"{owner}/{repo}",
            repo_url=repo_url,
            analysis_data=analysis,
        )
        html_content = _generate_brd_html(document, repo, repo_url, analysis_data=analysis)
        generated_at = datetime.now().isoformat()

        analysis["has_kt_document"] = True
        analysis["kt_document"] = document
        analysis["kt_document_generated_at"] = generated_at
        analysis["kt_document_metadata"] = {
            "generator": "analysis-driven",
            "cache_key": cache_key_used,
            "dependency_count": len(analysis.get("dependencies", [])),
            "vulnerability_count": len(analysis.get("vulnerable_dependencies", [])),
            "file_count": len(analysis.get("all_files", [])),
        }

        return {
            "success": True,
            "document": document,
            "html": html_content,
            "filename": document_filename,
            "generated_at": generated_at,
            "repo_url": repo_url,
            "source": "Freshly generated BRD from repository analysis",
            "metadata": analysis["kt_document_metadata"],
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error("[BRD DOCUMENT] %s", str(e))
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to generate BRD document: {str(e)}")


@app.post("/api/local-project/generate-brd-document")
async def generate_local_project_brd_document(request: dict):
    """Generate a BRD-style document for an uploaded local project."""
    try:
        repo_url = (request or {}).get("repo_url") or (request or {}).get("repository_url") or (request or {}).get("source_repo_url")
        analysis = (request or {}).get("analysis")
        source_repo = (request or {}).get("source_repo")

        if not repo_url:
            raise HTTPException(status_code=400, detail="repo_url is required")
        if not isinstance(analysis, dict):
            raise HTTPException(status_code=400, detail="analysis is required and must be an object")

        safe_repo_name = re.sub(r"[^A-Za-z0-9._-]+", "-", (source_repo or repo_url or "local-project")).strip("-") or "repository"
        document_filename = f"{safe_repo_name.upper()}-TECHNICAL-DOCUMENT.html"

        logger.info("[LOCAL PROJECT BRD DOCUMENT API] Generating BRD document for %s", repo_url)
        document = _build_brd_document_from_analysis(
            repo_name=source_repo or repo_url,
            repo_url=repo_url,
            analysis_data=analysis,
        )
        html_content = _generate_brd_html(document, safe_repo_name, repo_url, analysis_data=analysis)
        generated_at = datetime.now().isoformat()

        return {
            "success": True,
            "document": document,
            "html": html_content,
            "filename": document_filename,
            "generated_at": generated_at,
            "repo_url": repo_url,
            "source": "Generated BRD from uploaded local project analysis",
            "metadata": {
                "generator": "local-project-analysis",
                "dependency_count": len(analysis.get("dependencies", [])),
                "file_count": len(analysis.get("all_files", [])),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error("[LOCAL PROJECT BRD DOCUMENT] %s", str(e))
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to generate BRD document: {str(e)}")


# New endpoints for direct repo URL input

async def _warm_brd_document_cache(repo_url: str, token: str = "", github_token: str = "") -> None:
    if not repo_url:
        return

    try:
        effective_token = _effective_github_token(token=token, github_token=github_token)
        owner, repo = await github_service.parse_repo_url(repo_url)
        _, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=repo_url,
            token=effective_token,
            force_refresh=False,
        )

        if analysis.get("has_kt_document") and analysis.get("kt_document"):
            logger.info("[BRD PREFETCH] Technical document already cached for %s/%s", owner, repo)
            return

        logger.info("[BRD PREFETCH] Pre-generating technical document for %s/%s", owner, repo)
        document = _build_brd_document_from_analysis(
            repo_name=f"{owner}/{repo}",
            repo_url=repo_url,
            analysis_data=analysis,
        )
        generated_at = datetime.now().isoformat()

        analysis["has_kt_document"] = True
        analysis["kt_document"] = document
        analysis["kt_document_generated_at"] = generated_at
        analysis["kt_document_metadata"] = {
            "generator": "analysis-driven-background-prefetch",
            "dependency_count": len(analysis.get("dependencies", [])),
            "vulnerability_count": len(analysis.get("vulnerable_dependencies", [])),
            "file_count": len(analysis.get("all_files", [])),
        }
        logger.info("[BRD PREFETCH] Technical document cache primed for %s/%s", owner, repo)
    except Exception:
        logger.exception("[BRD PREFETCH] Failed to pre-generate technical document for %s", repo_url)

@app.get("/api/github/analyze-url")
async def analyze_repo_url(
    repo_url: str,
    token: str = "",
    force_refresh: bool = False,
    background_tasks: BackgroundTasks = None,
):
    """Analyze a repository directly by URL using clone-first local workspace analysis."""
    try:
        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
        workspace, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=repo_url,
            token=effective_token,
            force_refresh=force_refresh,
        )
        if background_tasks and not analysis.get("has_kt_document"):
            background_tasks.add_task(_warm_brd_document_cache, repo_url, token, effective_token)
        return {
            "repo_url": repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "analysis": analysis
        }
    except GithubException as e:
        status_code = getattr(e, 'status', 400)
        error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
        
        if status_code == 404:
            if token and token.strip():
                error_msg = "Repository not found or access denied. Check that your Personal Access Token has 'repo' scope, the repository exists, and (if in an organization) your PAT is approved by the organization admin."
            else:
                error_msg = "Repository not found or is private. If this is a private repository, provide a Personal Access Token with 'repo' scope."
        elif status_code == 403:
            error_msg = "Access denied. The repository may be private or you may not have permission to access it."
        elif status_code == 401:
            error_msg = "Authentication failed. Please check your GitHub token."
        else:
            error_msg = f"GitHub API error ({status_code}): {error_msg}"
        
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        import traceback
        print(f"[analyze-url ERROR] repo_url={repo_url} token_provided={bool(token and token.strip())} error={str(e)}\nTRACE:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)} (see backend logs for details)")


@app.get("/api/github/repo-visibility", response_model=RepoVisibilityInfo)
async def get_github_repo_visibility(repo_url: str, token: str = ""):
    try:
        owner, repo = await github_service.parse_repo_url(repo_url)
        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
        repo_info = await github_service.get_repo_info(effective_token, owner, repo)

        visibility = "private" if repo_info.get("is_private") else "public"
        message = (
            "Private repository detected. Provide a Personal Access Token with repo access to analyze it."
            if visibility == "private"
            else "Public repository detected."
        )

        return RepoVisibilityInfo(
            owner=owner,
            repo=repo,
            visibility=visibility,
            requires_token=(visibility == "private"),
            message=message,
        )
    except Exception as e:
        error_msg = str(e)

        if "Invalid GitHub repository URL" in error_msg:
            raise HTTPException(status_code=400, detail=error_msg)

        if "Repository not found" in error_msg or "Access denied" in error_msg or "Authentication failed" in error_msg:
            owner, repo = await github_service.parse_repo_url(repo_url)
            return RepoVisibilityInfo(
                owner=owner,
                repo=repo,
                visibility="private_or_inaccessible",
                requires_token=True,
                message="Repository appears private or inaccessible. Provide a GitHub token with 'repo' scope.",
            )

        raise HTTPException(status_code=500, detail=f"Internal server error: {error_msg}")


async def compute_microservice_eligibility(
    analysis: Dict[str, Any],
    owner: str,
    repo: str,
    token: str,
    repo_reference: str,
    prepared_workspace: Any = None,
) -> MicroserviceEligibilityResult:
    api_endpoints = len(analysis.get("api_endpoints") or [])
    endpoint_entries = [
        endpoint
        for endpoint in (analysis.get("api_endpoints") or [])
        if isinstance(endpoint, dict)
    ]
    dependency_count = len(analysis.get("dependencies") or [])
    has_spring_web = any(
        re.search(r"spring-(boot-starter|web|mvc)", f"{dep.get('group_id', '')}:{dep.get('artifact_id', '')}", re.I)
        for dep in (analysis.get("dependencies") or [])
        if isinstance(dep, dict)
    )
    has_spring_boot_dependency = any(
        re.search(r"org\.springframework\.boot:|spring-boot", f"{dep.get('group_id', '')}:{dep.get('artifact_id', '')}", re.I)
        for dep in (analysis.get("dependencies") or [])
        if isinstance(dep, dict)
    )
    has_tests = bool(analysis.get("has_tests"))
    has_main_src = bool(analysis.get("structure", {}).get("has_src_main"))
    has_build_tool = bool(analysis.get("build_tool"))

    java_files_count = None
    if isinstance(analysis.get("java_file_count"), int):
        java_files_count = analysis["java_file_count"]
    elif isinstance(analysis.get("java_files"), list):
        java_files_count = len(analysis["java_files"])

    controllers = 0
    services = 0
    entities = 0
    controller_paths = set()
    service_paths = set()
    entity_paths = set()
    has_spring_boot_annotation = False

    def extract_endpoint_domain(path: Any) -> Optional[str]:
        if not isinstance(path, str):
            return None
        segments = [segment for segment in path.strip().split("/") if segment]
        ignored_prefixes = {"api", "rest", "services", "service", "v1", "v2", "v3", "v4"}
        for segment in segments:
            lowered = segment.strip().lower()
            if not lowered or lowered in ignored_prefixes or lowered.startswith("{") or lowered.startswith(":"):
                continue
            return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-") or None
        return None

    endpoint_domains = sorted({
        domain
        for domain in (
            extract_endpoint_domain(endpoint.get("path"))
            for endpoint in endpoint_entries
        )
        if domain
    })
    endpoint_domain_count = len(endpoint_domains)

    def strip_java_comments(content: str) -> str:
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        return re.sub(r"//.*", "", content)

    def java_path_from_entry(entry: Any) -> Optional[str]:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            value = entry.get("path") or entry.get("file") or entry.get("name")
            return value if isinstance(value, str) else None
        return None

    java_files = []
    seen_java_files = set()
    all_file_entries = {}
    max_file_inspections = max(24, int(os.getenv("MICROSERVICE_ELIGIBILITY_MAX_FILE_INSPECTIONS", "160")))

    for entry in (analysis.get("java_files") or []):
        path = java_path_from_entry(entry)
        if path and path.lower().endswith(".java") and path not in seen_java_files:
            java_files.append(path)
            seen_java_files.add(path)
            if isinstance(entry, dict):
                all_file_entries[path] = entry

    for entry in (analysis.get("all_files") or []):
        path = java_path_from_entry(entry)
        if path and path.lower().endswith(".java"):
            if path not in seen_java_files:
                java_files.append(path)
                seen_java_files.add(path)
            if isinstance(entry, dict):
                all_file_entries[path] = entry

    endpoint_file_names = {
        os.path.basename(str(endpoint.get("file", ""))).lower()
        for endpoint in endpoint_entries
        if endpoint.get("file")
    }

    canonical_java_paths = {path.lower(): path for path in java_files}

    def canonicalize_java_path(path: str) -> str:
        return canonical_java_paths.get(path.lower(), path)

    prioritized_java_files = []
    deprioritized_java_files = []
    likely_path_markers = ("/controller/", "/controllers/", "/service/", "/services/", "/resource/", "/resources/", "/endpoint/", "/api/", "/entity/", "/entities/", "/model/", "/models/", "/domain/")
    likely_name_suffixes = ("controller.java", "resource.java", "endpoint.java", "service.java", "serviceimpl.java", "manager.java", "facade.java", "entity.java", "model.java", "document.java")
    for file_path in java_files:
        normalized_path = file_path.replace("\\", "/")
        lower_path = normalized_path.lower()
        basename = os.path.basename(lower_path)
        if basename in endpoint_file_names or basename.endswith(likely_name_suffixes) or any(marker in lower_path for marker in likely_path_markers):
            prioritized_java_files.append(file_path)
        else:
            deprioritized_java_files.append(file_path)

    java_files_to_scan = (prioritized_java_files + deprioritized_java_files)[:max_file_inspections]
    use_clone_first_content = str(analysis.get("analysis_source") or "").strip().lower() == "clone_first"
    clone_first_workspace = prepared_workspace
    if use_clone_first_content:
        try:
            if clone_first_workspace is None:
                clone_first_workspace = await github_clone_analysis_service.prepare_workspace(
                    repo_reference=repo_reference,
                    token=token,
                    force_refresh=False,
                )
                logger.debug("Prepared clone-first workspace for microservice assessment %s", repo_reference)
        except Exception as workspace_err:
            logger.debug(
                "Could not prepare clone-first workspace for microservice assessment %s: %s",
                repo_reference,
                workspace_err,
                )

    for file_path in java_files_to_scan:
        file_path = canonicalize_java_path(file_path)
        normalized_path = file_path.replace("\\", "/")
        basename = os.path.basename(normalized_path)
        lower_path = normalized_path.lower()
        lower_basename = basename.lower()
        is_test_file = (
            "/src/test/" in lower_path
            or "/test/" in lower_path
            or lower_basename.endswith("test.java")
            or lower_basename.endswith("tests.java")
        )
        if is_test_file:
            continue

        content = ""
        file_entry = all_file_entries.get(file_path) or {}
        if isinstance(file_entry, dict) and isinstance(file_entry.get("content"), str):
            content = file_entry["content"]
        try:
            if not content:
                if clone_first_workspace is not None:
                    content = await github_clone_analysis_service.read_workspace_file_content(
                        clone_first_workspace,
                        file_path=file_path,
                    )
                else:
                    content = await github_service.get_file_content(token, owner, repo, file_path)
        except Exception as content_err:
            logger.debug("Could not fetch Java content for microservice assessment %s: %s", file_path, content_err)

        scan_content = strip_java_comments(content)
        class_name = basename[:-5] if basename.endswith(".java") else basename

        has_controller_annotation = bool(
            re.search(r"@\s*(?:[\w.]+\.)?(?:RestController|Controller)\b", scan_content)
            or re.search(r"@\s*(?:[\w.]+\.)?Path\b", scan_content)
        )
        has_endpoint_mapping = bool(
            re.search(r"@\s*(?:[\w.]+\.)?(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\b", scan_content)
        )
        has_spring_boot_class_annotation = bool(
            re.search(r"@\s*(?:[\w.]+\.)?(?:SpringBootApplication|EnableAutoConfiguration)\b", scan_content)
        )
        controller_by_path = (
            lower_basename in endpoint_file_names
            or class_name.lower().endswith(("controller", "resource", "endpoint"))
            or any(part in lower_path for part in ["/controller/", "/controllers/", "/resource/", "/resources/", "/endpoint/", "/api/"])
        )
        if has_spring_boot_class_annotation:
            has_spring_boot_annotation = True
        if has_controller_annotation or has_endpoint_mapping or controller_by_path:
            controller_paths.add(file_path)

        if (
            re.search(r"@\s*(?:[\w.]+\.)?(?:Service)\b", scan_content)
            or class_name.lower().endswith(("service", "serviceimpl", "manager", "facade"))
            or any(part in lower_path for part in ["/service/", "/services/"])
        ):
            service_paths.add(file_path)

        if (
            re.search(r"@\s*(?:[\w.]+\.)?(?:Entity|Embeddable|MappedSuperclass|Document)\b", scan_content)
            or re.search(r"@\s*(?:[\w.]+\.)?Table\b", scan_content)
            or class_name.lower().endswith(("entity", "model", "document"))
            or any(part in lower_path for part in ["/entity/", "/entities/", "/model/", "/models/", "/domain/"])
        ):
            entity_paths.add(file_path)

    controllers = len(controller_paths)
    services = len(service_paths)
    entities = len(entity_paths)
    has_spring_boot = has_spring_boot_dependency or has_spring_boot_annotation

    def humanize_service_name(raw: str) -> str:
        value = re.sub(r"\.java$", "", raw or "", flags=re.I)
        value = re.sub(r"(?i)(controller|service|serviceimpl|resource|endpoint)$", "", value)
        value = re.sub(r"[^A-Za-z0-9]+", " ", value)
        value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
        words = [word for word in value.strip().split() if word]
        return f"{' '.join(word.capitalize() for word in words) or 'Core'} Service"

    def normalize_suggested_services(value: Any) -> List[str]:
        services_out: List[str] = []
        candidates = value if isinstance(value, list) else []
        for item in candidates:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("service") or item.get("title") or "").strip()
            else:
                name = ""
            if not name:
                continue
            if not name.lower().endswith("service"):
                name = f"{name} Service"
            if name not in services_out:
                services_out.append(name)
        return services_out[:6]

    def build_fallback_suggested_services() -> List[str]:
        source_paths: List[str] = []
        seen_source_paths = set()
        for collection in (sorted(controller_paths), sorted(service_paths), sorted(entity_paths), java_files[:12]):
            for path in collection:
                if path not in seen_source_paths:
                    source_paths.append(path)
                    seen_source_paths.add(path)
        suggestions: List[str] = []
        seen_roots = set()
        generic_roots = {
            "app",
            "application",
            "base",
            "common",
            "controller",
            "core",
            "default",
            "endpoint",
            "entity",
            "facade",
            "manager",
            "model",
            "resource",
            "service",
        }
        for path in source_paths:
            name = humanize_service_name(os.path.basename(path))
            root_name = re.sub(r"(?i)\s+service$", "", name).strip().lower()
            if not root_name or root_name in generic_roots or root_name in seen_roots:
                continue
            suggestions.append(name)
            seen_roots.add(root_name)
            if len(suggestions) >= 4:
                break
        if not suggestions and has_spring_web:
            suggestions.append("Application Core Service")
        return suggestions

    normalized_build_tool = str(analysis.get("build_tool") or "").strip().lower()

    def build_folder_structure(service_names: List[str]) -> Optional[str]:
        if not service_names:
            return None
        is_maven = normalized_build_tool == "maven"
        root_build_file = "pom.xml" if is_maven else "build.gradle"
        module_build_file = "pom.xml" if is_maven else "build.gradle"
        lines = [root_build_file, "services"]
        for service_name in service_names[:6]:
            slug = re.sub(r"[^a-z0-9]+", "-", service_name.lower()).strip("-")
            if not slug.endswith("-service"):
                slug = f"{slug}-service"
            lines.extend([
                f"|-- {slug}",
                f"|   |-- {module_build_file}",
                "|   `-- src",
                "|       `-- main",
                "|           `-- java",
                "|               `-- com",
                "|                   `-- example",
                f"|                       `-- {slug.replace('-', '')}",
                "|                           |-- controller",
                "|                           |-- service",
                "|                           `-- repository",
            ])
        return "\n".join(lines)

    def normalize_folder_structure_for_build_tool(structure: str) -> str:
        if not structure:
            return structure
        normalized = structure
        if normalized_build_tool == "maven":
            normalized = normalized.replace("settings.gradle\n", "")
            normalized = normalized.replace("settings.gradle.kts\n", "")
            normalized = normalized.replace("build.gradle.kts", "pom.xml")
            normalized = normalized.replace("build.gradle", "pom.xml")
        elif normalized_build_tool == "gradle":
            if "settings.gradle" not in normalized and "settings.gradle.kts" not in normalized:
                normalized = "settings.gradle\n" + normalized
            normalized = normalized.replace("pom.xml", "build.gradle")
        return normalized.strip()

    def dedupe_signals(values: Any) -> List[str]:
        deduped: List[str] = []
        seen = set()
        for value in values or []:
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            key = normalized.lower()
            if normalized and key not in seen:
                deduped.append(normalized)
                seen.add(key)
        return deduped

    def evaluate_microservice_fit(candidate_services: List[str]) -> tuple[int, bool, List[str], List[str]]:
        positive_signals: List[str] = []
        negative_signals: List[str] = []
        service_boundary_count = len(candidate_services or [])

        if api_endpoints >= 5:
            positive_signals.append(f"{api_endpoints} API endpoints suggest multiple externally exposed capabilities")
        elif api_endpoints >= 2:
            positive_signals.append("More than one API endpoint detected")
        else:
            negative_signals.append("Too few API endpoints to justify splitting into multiple services")

        if endpoint_domain_count >= 3:
            positive_signals.append(f"Endpoints span {endpoint_domain_count} distinct route domains")
        elif endpoint_domain_count == 2:
            positive_signals.append("Endpoints cover at least two route domains")
        elif api_endpoints >= 3:
            negative_signals.append("Endpoints are concentrated in a single route domain")

        if has_spring_boot:
            positive_signals.append("Spring Boot application structure detected")
        else:
            negative_signals.append("Repository does not appear to be a Spring Boot application")

        if has_spring_web:
            positive_signals.append("Spring Web / REST stack detected")
        else:
            negative_signals.append("No Spring Web / REST layer detected")

        if dependency_count >= 8:
            positive_signals.append("Dependency surface suggests non-trivial application responsibilities")
        elif dependency_count >= 4:
            positive_signals.append("Dependency footprint indicates moderate application complexity")
        else:
            negative_signals.append("Limited dependency surface suggests a relatively simple application")

        if has_tests:
            positive_signals.append("Existing tests are available for migration validation")
        else:
            negative_signals.append("No automated tests detected, which raises migration risk")

        if has_main_src:
            positive_signals.append("Main Java source structure detected")
        else:
            negative_signals.append("No main Java source directory detected")

        if has_build_tool:
            positive_signals.append("Build tooling is present")
        else:
            negative_signals.append("No build tooling detected")

        if controllers >= 2:
            positive_signals.append("Multiple controllers indicate separable API entry points")
        elif controllers == 1:
            negative_signals.append("Only one controller detected, suggesting a single coarse API surface")
        else:
            negative_signals.append("No controller layer detected")

        if services >= 3:
            positive_signals.append("Several service classes suggest business-logic seams")
        elif services >= 2:
            positive_signals.append("More than one service class detected")
        else:
            negative_signals.append("Very limited service-layer separation detected")

        if entities >= 3:
            positive_signals.append("Multiple entities suggest several domain concepts")
        elif entities >= 1:
            positive_signals.append("Domain entities are present")

        if service_boundary_count >= 3 and (endpoint_domain_count >= 2 or controllers >= 2 or entities >= 3):
            positive_signals.append(f"{service_boundary_count} candidate service boundaries were inferred")
        elif service_boundary_count == 2 and (endpoint_domain_count >= 2 or controllers >= 2):
            positive_signals.append("At least two candidate service boundaries were inferred")
        else:
            negative_signals.append("Only one likely domain boundary was identified")

        if isinstance(java_files_count, int):
            if java_files_count < 12:
                negative_signals.append("Codebase is very small, so microservice overhead may outweigh the benefits")
            elif java_files_count < 20:
                negative_signals.append("Codebase is still fairly small for a confident microservice recommendation")

        if service_boundary_count >= 3 and endpoint_domain_count <= 1 and controllers <= 1:
            negative_signals.append("Inferred service boundaries are broader than the observable API split")

        boundary_strength = sum([
            1 if api_endpoints >= 4 else 0,
            1 if controllers >= 2 else 0,
            1 if services >= 3 else 0,
            1 if entities >= 2 else 0,
            1 if service_boundary_count >= 2 else 0,
            1 if endpoint_domain_count >= 2 else 0,
        ])

        fit_score = 26
        fit_score += min(api_endpoints, 8) * 4
        fit_score += min(endpoint_domain_count, 4) * 4
        fit_score += min(max(controllers - 1, 0), 3) * 5
        fit_score += min(services, 6) * 3
        fit_score += min(entities, 5) * 2
        fit_score += 10 if has_spring_boot else -28
        fit_score += 8 if has_spring_web else -8
        fit_score += 6 if dependency_count >= 8 else 3 if dependency_count >= 4 else -5
        fit_score += 5 if has_tests else -8
        fit_score += 3 if has_build_tool else -8
        fit_score += 2 if has_main_src else -10

        if service_boundary_count <= 1:
            fit_score -= 10
        if api_endpoints >= 4 and endpoint_domain_count <= 1:
            fit_score -= 14
        if controllers <= 1:
            fit_score -= 12
        if controllers == 1 and api_endpoints >= 5:
            fit_score -= 8
        if services <= 1:
            fit_score -= 10
        if not has_spring_boot:
            fit_score -= 12
        if api_endpoints <= 1:
            fit_score -= 16
        if isinstance(java_files_count, int):
            if java_files_count < 12:
                fit_score -= 12
            elif java_files_count < 20:
                fit_score -= 8
            elif java_files_count < 30:
                fit_score -= 4
        if service_boundary_count >= 3 and endpoint_domain_count <= 1 and controllers <= 1:
            fit_score -= 8
        if boundary_strength <= 2:
            fit_score -= 10

        max_fit_score = 94 if boundary_strength >= 4 and has_tests and controllers >= 2 and services >= 3 else 89
        if not has_spring_boot:
            max_fit_score = min(max_fit_score, 34)
        if controllers <= 1:
            max_fit_score = min(max_fit_score, 78)
        if api_endpoints >= 4 and endpoint_domain_count <= 1:
            max_fit_score = min(max_fit_score, 74)
        if isinstance(java_files_count, int) and java_files_count < 20:
            max_fit_score = min(max_fit_score, 72)
        fit_score = int(round(min(max_fit_score, max(15, fit_score))))
        eligible_fit = (
            has_spring_boot
            and fit_score >= 40
        )

        return (
            fit_score,
            eligible_fit,
            dedupe_signals(positive_signals),
            dedupe_signals(negative_signals),
        )

    def evaluate_migration_readiness(candidate_services: List[str]) -> tuple[int, List[str], List[str]]:
        positive_signals: List[str] = []
        negative_signals: List[str] = []
        service_boundary_count = len(candidate_services or [])

        readiness_score = 36

        if has_tests:
            readiness_score += 16
            positive_signals.append("Automated tests improve migration safety")
        else:
            readiness_score -= 14
            negative_signals.append("Missing automated tests increases migration risk")

        if has_build_tool:
            readiness_score += 12
            positive_signals.append("Build tooling is available for iterative migration")
        else:
            readiness_score -= 14
            negative_signals.append("No build tooling detected for repeatable migration validation")

        if has_main_src:
            readiness_score += 8
            positive_signals.append("Project structure is recognizable for migration tooling")
        else:
            readiness_score -= 10
            negative_signals.append("Source layout is incomplete or non-standard")

        if normalized_build_tool in {"maven", "gradle"}:
            readiness_score += 6
            positive_signals.append(f"{normalized_build_tool.title()} build conventions support stepwise migration")
        elif normalized_build_tool == "standalone":
            readiness_score -= 3
            negative_signals.append("Standalone build setup may require extra manual migration work")

        if dependency_count >= 4:
            readiness_score += 4
            positive_signals.append("Dependency metadata provides useful migration context")
        else:
            negative_signals.append("Limited dependency metadata reduces migration guidance")

        if dependency_count > 35:
            readiness_score -= 6
            negative_signals.append("Large dependency surface may complicate migration sequencing")

        if isinstance(java_files_count, int):
            if java_files_count <= 25:
                readiness_score += 6
                positive_signals.append("Relatively small codebase reduces the migration blast radius")
            elif java_files_count <= 120:
                readiness_score += 4
                positive_signals.append("Codebase size looks manageable for phased migration")
            elif java_files_count > 250:
                readiness_score -= 8
                negative_signals.append("Large codebase will likely require phased migration planning")

        if services >= 2:
            readiness_score += 5
            positive_signals.append("Service-layer separation can support incremental extraction")
        if controllers >= 1:
            readiness_score += 3
            positive_signals.append("HTTP entry points are identifiable for migration testing")
        if service_boundary_count >= 2:
            readiness_score += 4
            positive_signals.append("Potential extraction targets are visible for phased rollout")

        if not has_tests and services >= 3:
            readiness_score -= 4
            negative_signals.append("Business logic seams exist, but they are weakly protected by tests")

        readiness_score = int(round(min(92, max(20, readiness_score))))
        return (
            readiness_score,
            dedupe_signals(positive_signals),
            dedupe_signals(negative_signals),
        )

    def build_assessment_label(fit_score: int, readiness_score: int, service_boundary_count: int) -> str:
        if not has_spring_boot:
            return "Not Eligible for Microservices"
        if fit_score >= 78 and readiness_score >= 70 and endpoint_domain_count >= 2 and controllers >= 2:
            return "Strong Microservice Candidate"
        if fit_score >= 60:
            if endpoint_domain_count <= 1 or controllers <= 1:
                return "Possible, but Needs Domain Redesign"
            if readiness_score < 60:
                return "Architecturally Viable, but Delivery Risk Is Moderate"
            return "Viable Microservice Candidate"
        if fit_score >= 45 or service_boundary_count >= 2:
            return "Borderline Candidate for Microservices"
        if fit_score >= 40:
            return "Eligible for Microservices with Guidance"
        return "Better Kept as a Modular Monolith"

    def build_assessment_summary(fit_score: int, readiness_score: int, service_boundary_count: int) -> str:
        if not has_spring_boot:
            return (
                "This repository does not appear to be Spring Boot-based. "
                "For this assessment, only Spring Boot applications are considered eligible for microservice extraction."
            )
        boundary_phrase = (
            f"{service_boundary_count} inferred service boundar{'ies' if service_boundary_count != 1 else 'y'}"
            if service_boundary_count
            else "no clear service boundaries"
        )
        fit_read = (
            "Architecture fit looks strong"
            if fit_score >= 75
            else "Architecture fit looks moderate"
            if fit_score >= 60
            else "Architecture fit looks weak"
        )
        readiness_read = (
            "migration readiness looks strong"
            if readiness_score >= 75
            else "migration readiness looks moderate"
            if readiness_score >= 55
            else "migration readiness looks weak"
        )
        return (
            f"{fit_read} at {fit_score}%, while {readiness_read} at {readiness_score}%. "
            f"The assessment is based on {api_endpoints} API endpoint{'s' if api_endpoints != 1 else ''}, "
            f"{controllers} controller{'s' if controllers != 1 else ''}, {services} service class{'es' if services != 1 else ''}, "
            f"{entities} entit{'ies' if entities != 1 else 'y'}, {endpoint_domain_count} route domain{'s' if endpoint_domain_count != 1 else ''}, and {boundary_phrase}."
        )

    java_file_samples = java_files[:40]
    endpoint_samples = [
        f"{endpoint.get('method', 'GET')} {endpoint.get('path', '/')} ({endpoint.get('file', 'unknown')})"
        for endpoint in (analysis.get("api_endpoints") or [])[:25]
        if isinstance(endpoint, dict)
    ]
    dependency_samples = [
        f"{dep.get('group_id', '')}:{dep.get('artifact_id', '')}".strip(":")
        for dep in (analysis.get("dependencies") or [])[:30]
        if isinstance(dep, dict)
    ]
    detected_component_samples = {
        "controllers": sorted(controller_paths)[:20],
        "services": sorted(service_paths)[:20],
        "entities": sorted(entity_paths)[:20],
    }
    suggested_services = build_fallback_suggested_services()
    heuristic_fit_score, heuristic_eligible, heuristic_signals_for, heuristic_signals_against = evaluate_microservice_fit(suggested_services)
    readiness_score, readiness_signals_for, readiness_signals_against = evaluate_migration_readiness(suggested_services)
    folder_structure = build_folder_structure(suggested_services)

    # Build prompt for LLM analysis
    prompt = f"""Analyze this Java project for microservice eligibility and propose repository-specific microservice boundaries.

Project Analysis:
- Repository: {owner}/{repo}
- Spring Boot Detected: {'Yes' if has_spring_boot else 'No'}
- API Endpoints: {api_endpoints}
- Dependencies: {dependency_count}
- Spring Web/REST Framework: {'Yes' if has_spring_web else 'No'}
- Has Tests: {'Yes' if has_tests else 'No'}
- Has Main Source Directory: {'Yes' if has_main_src else 'No'}
- Build Tool Present: {'Yes' if has_build_tool else 'No'}
- Java Files Count: {java_files_count or 'Unknown'}
- Detected Controllers Count: {controllers}
- Detected Services Count: {services}
- Detected Entities Count: {entities}
- API Endpoint Samples: {endpoint_samples}
- Java File Samples: {java_file_samples}
- Dependency Samples: {dependency_samples}
- Detected Component File Samples: {detected_component_samples}

Determine if this project is eligible for microservice architecture conversion.
Also suggest 2 to 6 meaningful microservice names based on business/domain clues from file names, packages, controllers, services, entities, and endpoints.

Return a JSON response with:
- eligible: boolean (true if suitable for microservices)
- confidence_score: number (0-100, how confident in the assessment)
- reasoning: string (brief explanation)
- signals_for: array of strings (positive indicators)
- signals_against: array of strings (negative indicators)
- suggested_services: array of short service names, each ending with "Service"
- folder_structure: string showing a concise recommended folder tree aligned with the detected build tool for the suggested services

Example response:
{{
  "eligible": true,
  "confidence_score": 85,
  "reasoning": "Project has multiple API endpoints and Spring Web framework, indicating good microservice potential.",
  "signals_for": ["Multiple API endpoints", "Spring Web framework detected"],
  "signals_against": ["No tests detected"],
  "suggested_services": ["User Management Service", "Billing Service", "Notification Service"],
  "folder_structure": "pom.xml\\nservices\\n|-- user-management-service\\n|   |-- pom.xml\\n|   `-- src/main/java/..."
}}

Be conservative about eligibility, but still provide suggested_services when there are clear domain boundaries.
Avoid extreme confidence values unless the evidence is overwhelming; most projects should fall between 45 and 90.
Return only valid JSON. Do not include markdown fences."""

    reasoning = ""
    try:
        # Query Hugging Face LLM using chat completions API
        import aiohttp
        
        api_key = os.getenv("HUGGINGFACE_API_KEY")
        if not api_key:
            raise Exception("HUGGINGFACE_API_KEY is not set")
        
        url = "https://router.huggingface.co/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "mistralai/Mistral-7B-Instruct-v0.3",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 3000,
            "temperature": 0.3
        }
        
        print(f"DEBUG: LLM prompt length: {len(prompt)} characters")
        estimated_tokens = len(prompt.split()) * 1.3  # Rough estimate
        print(f"DEBUG: Estimated tokens: {estimated_tokens}, max_tokens: {payload['max_tokens']}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=120) as response:
                print(f"DEBUG: LLM API response status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    response = result["choices"][0]["message"]["content"]
                    print(f"DEBUG: LLM response received, length: {len(response)}")
                else:
                    error_text = await response.text()
                    print(f"DEBUG: LLM API error: {response.status} - {error_text}")
                    logger.error(f"Hugging Face chat API error: {response.status} - {error_text}")
                    raise Exception(f"API Error: {response.status}")

        # Parse JSON response
        import json
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            llm_eligible = bool(parsed.get("eligible", False))
            llm_confidence_score = min(100, max(0, parsed.get("confidence_score", 50)))
            reasoning = parsed.get("reasoning", "LLM analysis completed")
            signals_for = parsed.get("signals_for", [])
            signals_against = parsed.get("signals_against", [])
            llm_suggested_services = normalize_suggested_services(parsed.get("suggested_services"))
            if llm_suggested_services:
                suggested_services = llm_suggested_services
                heuristic_fit_score, heuristic_eligible, heuristic_signals_for, heuristic_signals_against = evaluate_microservice_fit(suggested_services)
                readiness_score, readiness_signals_for, readiness_signals_against = evaluate_migration_readiness(suggested_services)
            if isinstance(parsed.get("folder_structure"), str) and parsed["folder_structure"].strip():
                folder_structure = normalize_folder_structure_for_build_tool(parsed["folder_structure"].strip())
            else:
                folder_structure = build_folder_structure(suggested_services)

            fit_score = int(round((heuristic_fit_score * 0.8) + (llm_confidence_score * 0.2)))
            fit_score = min(fit_score, heuristic_fit_score + 6)
            fit_score = min(94 if heuristic_eligible else 89, max(15, fit_score))
            eligible = fit_score >= 40 or heuristic_fit_score >= 40 or heuristic_eligible or llm_eligible
            signals_for = dedupe_signals(list(signals_for or []) + heuristic_signals_for + readiness_signals_for)
            signals_against = dedupe_signals(list(signals_against or []) + heuristic_signals_against + readiness_signals_against)
        else:
            raise ValueError("No JSON found in response")

    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}, falling back to rule-based logic")
        if not suggested_services:
            suggested_services = build_fallback_suggested_services()
            heuristic_fit_score, heuristic_eligible, heuristic_signals_for, heuristic_signals_against = evaluate_microservice_fit(suggested_services)
            readiness_score, readiness_signals_for, readiness_signals_against = evaluate_migration_readiness(suggested_services)
        fit_score = heuristic_fit_score
        eligible = heuristic_eligible
        signals_for = dedupe_signals(heuristic_signals_for + readiness_signals_for)
        signals_against = dedupe_signals(heuristic_signals_against + readiness_signals_against)
        folder_structure = build_folder_structure(suggested_services)

    inferred_service_boundaries_count = len(suggested_services or [])
    assessment_label = build_assessment_label(fit_score, readiness_score, inferred_service_boundaries_count)
    assessment_summary = build_assessment_summary(fit_score, readiness_score, inferred_service_boundaries_count)
    reasoning = (
        reasoning.strip()
        if isinstance(reasoning, str) and reasoning.strip()
        else assessment_summary
    )

    return MicroserviceEligibilityResult(
        eligible=eligible,
        confidence_score=fit_score,
        microservice_fit_score=fit_score,
        migration_readiness_score=readiness_score,
        reasoning=reasoning,
        assessment_label=assessment_label,
        assessment_summary=assessment_summary,
        signals_for=signals_for,
        signals_against=signals_against,
        java_files_count=java_files_count,
        controllers_count=controllers,
        services_count=services,
        entities_count=entities,
        endpoint_domains_count=endpoint_domain_count,
        inferred_service_boundaries_count=inferred_service_boundaries_count,
        suggested_services=suggested_services,
        folder_structure=folder_structure,
    )


@app.get("/api/github/microservice-eligibility-legacy", response_model=MicroserviceEligibilityResponse)
async def get_microservice_eligibility(repo_url: str, token: str = ""):
    try:
        if repo_url.startswith("local://"):
            # Handle local project
            local_path = repo_url[8:]  # Remove "local://"
            analysis_workspace = local_project_service.prepare_workspace(local_path)
            analysis = await local_project_service.analysis_service.analyze_workspace(analysis_workspace)
            effective_token = ""  # No token needed for local
        else:
            # Handle GitHub repository
            effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
            analysis_workspace, analysis = await github_clone_analysis_service.analyze_repository(
                repo_reference=repo_url,
                token=effective_token,
                force_refresh=False,
            )
        owner = analysis_workspace.owner
        repo = analysis_workspace.repo
        eligibility = await compute_microservice_eligibility(
            analysis,
            owner,
            repo,
            effective_token,
            repo_url,
            prepared_workspace=analysis_workspace,
        )
        return {
            "repo_url": repo_url,
            "owner": owner,
            "repo": repo,
            "microservice_eligibility": eligibility,
        }
    except GithubException as e:
        status_code = getattr(e, 'status', 400)
        error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
        if status_code == 404:
            error_msg = "Repository not found or is private. If this is a private repository, provide a Personal Access Token with 'repo' scope."
        elif status_code == 403:
            error_msg = "Access denied. The repository may be private or you may not have permission to access it."
        elif status_code == 401:
            error_msg = "Authentication failed. Please check your GitHub token."
        else:
            error_msg = f"GitHub API error ({status_code}): {error_msg}"
        raise HTTPException(status_code=status_code, detail=error_msg)
    except Exception as e:
        import traceback
        logger.error("[MICROSERVICE ELIGIBILITY] Failed for repo_url=%s: %s", repo_url, str(e))
        logger.debug(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


class MicroserviceConvertRequest(BaseModel):
    source_path: str = Field(description="Path to the monolithic Java project")
    output_path: Optional[str] = Field(default=None, description="Output path for generated microservices")
    auto_push: Optional[bool] = Field(default=False, description="Auto-push output to a new GitHub repo")
    push_repo_name: Optional[str] = Field(default=None, description="Name for the new GitHub repo")
    push_owner: Optional[str] = Field(default=None, description="GitHub org/user for the new repo")
    push_private: Optional[bool] = Field(default=False, description="Make the new repo private")
    github_token: Optional[str] = Field(default="", description="GitHub PAT for push")


@app.post("/api/microservice/convert")
async def convert_to_microservices(request: MicroserviceConvertRequest):
    """
    Convert a monolithic Java project to microservices.
    Generates independent Spring Boot projects with Docker, API Gateway, and Eureka discovery.
    """
    try:
        source = request.source_path
        if not os.path.isdir(source):
            raise HTTPException(status_code=400, detail=f"Source path does not exist: {source}")

        # Run readiness analysis
        workspace = RepositoryWorkspace(
            repo_url=f"local://{source}",
            normalized_repo_url=source,
            owner="local",
            repo=os.path.basename(source.rstrip("/\\")) or "project",
            workspace_path=source,
            default_branch="local",
            cache_key="local",
            auth_scope_key="local",
        )
        from services.migration_service import migration_service
        analysis = await migration_service.analyze_project(source)
        readiness_report = await microservice_readiness_service.analyze_repository(workspace, analysis)

        # Run conversion
        result = await microservice_conversion_service.convert(
            source_path=source,
            readiness_report=readiness_report,
            output_path=request.output_path,
        )

        # Auto-push to GitHub if requested
        push_info = None
        if request.auto_push:
            from services.github_autopush_service import github_autopush
            push_result = github_autopush.push(
                local_path=result.output_path,
                repo_name=request.push_repo_name,
                token=request.github_token,
                owner=request.push_owner,
                private=request.push_private or False,
            )
            if push_result.success:
                push_info = {
                    "repo_url": push_result.repo_url,
                    "branch": push_result.branch,
                    "files_pushed": push_result.files_pushed,
                }

        response = {
            "success": True,
            "output_path": result.output_path,
            "services_created": result.services_created,
            "shared_module": result.shared_module,
            "docker_compose_path": result.docker_compose_path,
            "summary": result.summary,
            "service_details": result.service_details,
            "readiness_score": readiness_report.score,
            "readiness_eligibility": readiness_report.eligibility,
        }
        if push_info:
            response["github_push"] = push_info
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Microservice conversion failed")
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")


# ---------------------------------------------------------------------------
# GitHub Auto-Push endpoint
# ---------------------------------------------------------------------------
@app.post("/api/github/push-to-new-repo")
async def push_to_new_github_repo(request: dict):
    """Push a local directory to a brand-new GitHub repository.

    Body JSON:
        local_path  (str, required) – absolute path to folder
        repo_name   (str, optional) – desired repo name
        owner       (str, optional) – GitHub org/user
        token       (str, optional) – PAT (falls back to GITHUB_TOKEN)
        private     (bool, optional, default false)
        branch      (str, optional, default "main")
        message     (str, optional)
        enterprise_url (str, optional)
    """
    from services.github_autopush_service import github_autopush

    local_path = request.get("local_path", "")
    if not local_path:
        raise HTTPException(status_code=400, detail="local_path is required")

    result = github_autopush.push(
        local_path=local_path,
        repo_name=request.get("repo_name"),
        token=request.get("token") or request.get("github_token"),
        owner=request.get("owner"),
        private=request.get("private", False),
        branch=request.get("branch", "main"),
        commit_message=request.get("message", "Initial commit – auto-generated microservices"),
        description=request.get("description", "Auto-generated microservices project by JavaAPEX"),
        enterprise_url=request.get("enterprise_url"),
    )

    if result.success:
        return {
            "status": "success",
            "repo_url": result.repo_url,
            "branch": result.branch,
            "files_pushed": result.files_pushed,
        }
    else:
        raise HTTPException(status_code=500, detail=result.error)


@app.get("/api/github/list-files")
async def list_repo_files(repo_url: str, token: str = "", path: str = ""):
    """List repository files using the managed clone-first workspace."""
    try:
        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
        workspace, files = await github_clone_analysis_service.list_files(
            repo_reference=repo_url,
            token=effective_token,
            path=path,
        )
        return {
            "repo_url": repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "path": path,
            "files": files,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/github/update-java-version")
async def update_java_version(repo_url: str, java_version: str, file_path: str, token: str = ""):
    """Update Java version in pom.xml or build.gradle file"""
    try:
        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
        owner, repo = await github_service.parse_repo_url(repo_url)
        
        # Clone repository
        clone_path = await github_service.clone_repository(effective_token, repo_url)
        
        # Update the file
        file_full_path = os.path.join(clone_path, file_path)
        if not os.path.exists(file_full_path):
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        
        with open(file_full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Update Java version based on file type
        if file_path.endswith('pom.xml'):
            # Update <java.version> or <maven.compiler.source>/<maven.compiler.target>
            import re
            new_content = content
            
            # Update java.version property
            java_version_pattern = r'<java\.version>([^<]+)</java\.version>'
            new_content = re.sub(java_version_pattern, f'<java.version>{java_version}</java.version>', new_content)
            
            # Update maven.compiler.source
            source_pattern = r'<maven\.compiler\.source>([^<]+)</maven.compiler.source>'
            new_content = re.sub(source_pattern, f'<maven.compiler.source>{java_version}</maven.compiler.source>', new_content)
            
            # Update maven.compiler.target
            target_pattern = r'<maven\.compiler\.target>([^<]+)</maven.compiler.target>'
            new_content = re.sub(target_pattern, f'<maven.compiler.target>{java_version}</maven.compiler.target>', new_content)
            
        elif file_path.endswith('build.gradle') or file_path.endswith('build.gradle.kts'):
            # Update sourceCompatibility/targetCompatibility
            import re
            new_content = content
            
            # Update sourceCompatibility
            source_pattern = r"sourceCompatibility\s*=\s*['\"](\d+)['\"]"
            new_content = re.sub(source_pattern, f"sourceCompatibility = '{java_version}'", new_content)
            
            # Update targetCompatibility
            target_pattern = r"targetCompatibility\s*=\s*['\"](\d+)['\"]"
            new_content = re.sub(target_pattern, f"targetCompatibility = '{java_version}'", new_content)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file type. Only pom.xml and build.gradle are supported")
        
        # Write updated content
        with open(file_full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return {
            "success": True,
            "file_path": file_path,
            "java_version": java_version,
            "message": f"Java version updated to {java_version} in {file_path}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[update-java-version ERROR] {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# GitLab Endpoints
@app.get("/api/gitlab/repos", response_model=List[RepoInfo])
async def list_gitlab_repos(token: str):
    """List all repositories accessible with the provided GitLab token"""
    try:
        repos = await gitlab_service.list_repositories(token)
        return repos
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/gitlab/repo/{owner}/{repo}/analyze")
async def analyze_gitlab_repository(owner: str, repo: str, token: str = ""):
    """Analyze a GitLab repository to detect Java version, dependencies, and structure"""
    try:
        analysis = await gitlab_service.analyze_repository(token, owner, repo)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/gitlab/analyze-url")
async def analyze_gitlab_repo_url(repo_url: str, token: str = ""):
    """Analyze a GitLab repository directly by URL"""
    try:
        owner, repo = await gitlab_service.parse_repo_url(repo_url)
        analysis = await gitlab_service.analyze_repository(token, owner, repo)
        return {
            "repo_url": repo_url,
            "owner": owner,
            "repo": repo,
            "analysis": analysis
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/gitlab/list-files")
async def list_gitlab_repo_files(repo_url: str, token: str = "", path: str = ""):
    """List all files in a GitLab repository"""
    try:
        owner, repo = await gitlab_service.parse_repo_url(repo_url)
        files = await gitlab_service.list_repo_files(token, owner, repo, path)
        return {
            "repo_url": repo_url,
            "owner": owner,
            "repo": repo,
            "path": path,
            "files": files
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/gitlab/file-content")
async def get_gitlab_file_content(repo_url: str, file_path: str, token: str = ""):
    """Get the content of a file from a GitLab repository"""
    try:
        owner, repo = await gitlab_service.parse_repo_url(repo_url)
        content = await gitlab_service.get_file_content(token, owner, repo, file_path)
        return {
            "repo_url": repo_url,
            "owner": owner,
            "repo": repo,
            "file_path": file_path,
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/fossa/status")
async def get_fossa_status():
    """Return FOSSA readiness information for the current deployment."""
    return fossa_service.get_capabilities()


@app.get("/api/sonar/status")
async def get_sonar_status():
    """Return Sonar readiness information for the current deployment."""
    return sonarqube_service.get_capabilities()


@app.get("/api/sonar/analyze-url")
async def analyze_sonar_for_repo(repo_url: str, token: str = "", allow_simulated: bool = False):
    """Clone a repository and run a Sonar analysis."""
    try:
        repo_service = gitlab_service if "gitlab.com" in repo_url else github_service
        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN
        clone_path = await repo_service.clone_repository(effective_token, repo_url)
        sonar_result = await sonarqube_service.analyze_project(
            clone_path,
            source_reference=repo_url,
            allow_simulated=allow_simulated,
        )
        return {"repo_url": repo_url, "sonar": sonar_result}
    except SonarQubeConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except SonarQubeExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        import traceback
        print(f"[SONAR ANALYZE ERROR] repo_url={repo_url} error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/fossa/analyze-url")
async def analyze_fossa_for_repo(repo_url: str, token: str = "", allow_simulated: bool = False):
    """Clone a repository and run a FOSSA analysis."""
    try:
        # Choose appropriate repo service based on URL
        if 'gitlab.com' in repo_url:
            repo_service = gitlab_service
        else:
            repo_service = github_service

        effective_token = token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN

        # Clone repository to a temporary working directory
        clone_path = await repo_service.clone_repository(effective_token, repo_url)

        fossa_result = await fossa_service.analyze_project(
            clone_path,
            allow_simulated=allow_simulated,
            source_reference=repo_url,
        )

        return { 'repo_url': repo_url, 'fossa': fossa_result }

    except FossaConfigurationError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FossaExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        import traceback
        print(f"[FOSSA ANALYZE ERROR] repo_url={repo_url} error={e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# Migration Endpoints
@app.post("/api/migration/start", response_model=MigrationResult)
async def start_migration(request: MigrationRequest, background_tasks: BackgroundTasks):
    """Start a new migration job"""
    job_id = str(uuid.uuid4())
    
    # Create initial job record
    job = MigrationResult(
        job_id=job_id,
        status=MigrationStatus.PENDING,
        source_repo=request.source_repo_url,
        source_java_version=request.source_java_version,
        target_java_version=request.target_java_version.value,
        conversion_types=request.conversion_types,
        migration_type=request.migration_type,
        started_at=datetime.now(timezone.utc),
        current_step="Initializing migration..."
    )
    
    migration_jobs[job_id] = job
    
    # Start migration in background
    background_tasks.add_task(
        run_migration,
        job_id,
        request
    )
    
    return job


@app.get("/api/migration/{job_id}", response_model=MigrationResult)
async def get_migration_status(job_id: str):
    """Get the status of a migration job"""
    if job_id not in migration_jobs:
        raise_missing_migration_job(job_id)
    return migration_jobs[job_id]


@app.get("/api/migration/{job_id}/fossa")
async def get_migration_fossa(job_id: str):
    """Return FOSSA scan results for a migration job."""
    if job_id not in migration_jobs:
        raise_missing_migration_job(job_id)

    job = migration_jobs[job_id]

    if job.fossa_report:
        return {'job_id': job_id, 'fossa': job.fossa_report}

    if getattr(job, 'fossa_policy_status', None) is not None or getattr(job, 'fossa_error_message', None):
        return {
            'job_id': job_id,
            'fossa': {
                'scan_mode': getattr(job, 'fossa_scan_mode', None),
                'real_scan': getattr(job, 'fossa_real_scan', False),
                'simulated': getattr(job, 'fossa_scan_mode', None) == 'simulated',
                'analysis_url': getattr(job, 'fossa_analysis_url', None),
                'compliance_status': getattr(job, 'fossa_policy_status', None),
                'total_dependencies': getattr(job, 'fossa_total_dependencies', 0),
                'license_issues': getattr(job, 'fossa_license_issues', 0),
                'vulnerabilities': getattr(job, 'fossa_vulnerabilities', 0),
                'outdated_dependencies': getattr(job, 'fossa_outdated_dependencies', 0),
                'error_message': getattr(job, 'fossa_error_message', None),
            },
        }

    return {
        'job_id': job_id,
        'fossa': {
            'scan_mode': 'pending',
            'real_scan': False,
            'simulated': False,
            'compliance_status': None,
            'total_dependencies': 0,
            'license_issues': 0,
            'vulnerabilities': 0,
            'outdated_dependencies': 0,
            'error_message': 'FOSSA results are not available for this migration yet.',
        },
    }


@app.get("/api/migration/{job_id}/logs")
async def get_migration_logs(job_id: str):
    """Get detailed logs for a migration job"""
    if job_id not in migration_jobs:
        raise_missing_migration_job(job_id)
    return {"job_id": job_id, "logs": migration_jobs[job_id].migration_log}

@app.post("/api/migration/{job_id}/rerun-tests")
async def rerun_migration_tests(
    job_id: str,
    llm_provider: str = "fordllm",
    use_llm_tests: bool = True,
):
    """Re-run tests for an existing migration job and update its test metrics."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")

    job = migration_jobs[job_id]

    clone_path = getattr(job, "clone_path", None)
    if not clone_path and getattr(job, "target_repo", None) and str(job.target_repo).startswith("local://"):
        clone_path = str(job.target_repo).replace("local://", "")

    if not clone_path or not os.path.isdir(clone_path):
        raise HTTPException(status_code=404, detail="Local migration directory not found for this job")

    try:
        add_log(job_id, "Re-running tests on existing migration job...")
    except Exception:
        pass

    test_result = await migration_service.run_tests(
        clone_path,
        llm_provider=llm_provider,
        use_llm_tests=use_llm_tests,
    )

    job.api_endpoints_validated = test_result.get("total_endpoints", 0)
    job.api_endpoints_working = test_result.get("working_endpoints", 0)
    job.tests_run = test_result.get("tests_run", 0)
    job.tests_passed = test_result.get("tests_passed", 0)
    job.tests_failed = test_result.get("tests_failed", 0)
    job.test_summary = test_result.get("test_summary")
    job.test_insights = test_result.get("test_insights") or []
    job.test_llm_model = test_result.get("test_llm_model") or test_result.get("test_model_used")

    pipeline = test_result.get("llm_pipeline") or {}
    if isinstance(pipeline, dict) and pipeline:
        try:
            job.test_pipeline = TestPipelineReport(
                provider=pipeline.get("provider", llm_provider),
                project_kind=pipeline.get("project_kind", ""),
                generated_tests_relative=pipeline.get("generated_tests_relative", ""),
                test_strategy=pipeline.get("test_strategy"),
                existing_tests_detected=int(pipeline.get("existing_tests_detected", 0) or 0),
                existing_test_files=pipeline.get("existing_test_files", []) or [],
                migrated_test_files=pipeline.get("migrated_test_files", []) or [],
                generated_test_files=pipeline.get("generated_test_files", []) or [],
                runner=pipeline.get("runner", {}) or {},
                manual_test_plan_path=pipeline.get("manual_test_plan_path"),
                migration_patch_path=pipeline.get("migration_patch_path"),
                deepeval_result=pipeline.get("deepeval"),
                garak_result=pipeline.get("garak"),
                coverage_result=pipeline.get("coverage"),
            )
        except Exception as exc:
            add_log(job_id, f"WARNING: Failed to map test pipeline report: {exc}")

    # If testcase docs were previously generated, clear the cached path so downloads refresh.
    try:
        job.testcase_doc_path = None
    except Exception:
        pass

    runner = test_result.get("runner") or {}
    if isinstance(runner, dict) and runner:
        try:
            cmd = runner.get("cmd") or []
            cmd_str = " ".join(str(x) for x in cmd[:10]) if isinstance(cmd, list) else str(cmd)
            add_log(
                job_id,
                f"Test Runner: tool={runner.get('tool')} exit={runner.get('exit_code')} "
                f"run={runner.get('tests_run')} pass={runner.get('tests_passed')} fail={runner.get('tests_failed')} "
                f"timeout={runner.get('timed_out')} cmd={cmd_str}",
            )
        except Exception:
            pass

    try:
        if job.test_summary:
            add_log(job_id, f"LLM Test Summary: {job.test_summary}")
        if job.test_pipeline:
            add_log(
                job_id,
                "Test Strategy: "
                f"{getattr(job.test_pipeline, 'test_strategy', 'unknown')} "
                f"(existing={getattr(job.test_pipeline, 'existing_tests_detected', 0)} "
                f"migrated={len(getattr(job.test_pipeline, 'migrated_test_files', []) or [])} "
                f"generated={len(getattr(job.test_pipeline, 'generated_test_files', []) or [])})"
            )
    except Exception:
        pass

    save_migration_job(job)

    return {
        "job_id": job_id,
        "tests_run": job.tests_run,
        "tests_passed": job.tests_passed,
        "tests_failed": job.tests_failed,
        "test_summary": job.test_summary,
        "test_insights": job.test_insights,
        "test_llm_model": job.test_llm_model,
        "test_pipeline": job.test_pipeline.model_dump() if job.test_pipeline else None,
        "runner": runner,
    }


@app.get("/api/migration/{job_id}/debug-microservice")
async def debug_microservice_output(job_id: str):
    """Debug endpoint to inspect the microservice output for a migration job."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")
    job = migration_jobs[job_id]
    ms_path = getattr(job, 'microservice_output_path', None)
    clone_path = getattr(job, 'clone_path', None)
    target_repo = getattr(job, 'target_repo', None)
    migration_type = getattr(job, 'migration_type', None)
    extra_metadata = getattr(job, 'extra_metadata', None)

    result = {
        "job_id": job_id,
        "status": str(job.status),
        "migration_type": migration_type,
        "microservice_output_path": ms_path,
        "clone_path": clone_path,
        "target_repo": target_repo,
        "microservice_services": (extra_metadata or {}).get("microservice_services"),
        "microservice_summary": (extra_metadata or {}).get("microservice_summary"),
    }

    # List files in microservice output dir
    if ms_path and os.path.isdir(ms_path):
        try:
            top_level = os.listdir(ms_path)
            result["ms_output_exists"] = True
            result["ms_output_contents"] = top_level[:30]
            # Show subdirectories in each service
            for item in top_level:
                item_path = os.path.join(ms_path, item)
                if os.path.isdir(item_path):
                    sub = os.listdir(item_path)
                    result[f"ms_{item}_contents"] = sub[:20]
        except Exception as e:
            result["ms_output_error"] = str(e)
    else:
        result["ms_output_exists"] = False

    # List files in clone_path
    if clone_path and os.path.isdir(clone_path):
        try:
            result["clone_path_contents"] = os.listdir(clone_path)[:30]
        except Exception:
            pass

    return result


@app.get("/api/migration/{job_id}/download-zip")
async def download_migration_zip(job_id: str):
    """Download the migrated project as a ZIP file"""
    import shutil
    import tempfile
    
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")
    
    job = migration_jobs[job_id]

    # Prefer a microservices extraction output if one exists
    clone_path = None
    ms_path = getattr(job, 'microservice_output_path', None)
    logger.info("Download ZIP for job %s: microservice_output_path=%s", job_id, ms_path)
    if ms_path:
        if os.path.exists(ms_path):
            clone_path = ms_path
            logger.info("Using microservice output path for ZIP: %s", clone_path)
            # Log contents for debugging
            try:
                contents = os.listdir(ms_path)
                logger.info("Microservice output contains: %s", contents[:20])
            except Exception:
                pass
        else:
            logger.warning("Microservice output path missing: %s", ms_path)
            add_log(job_id, f"Microservice output path missing: {ms_path}")
            job.microservice_output_path = None

    if not clone_path:
        if hasattr(job, 'target_repo') and job.target_repo:
            if job.target_repo.startswith("local://"):
                clone_path = job.target_repo.replace("local://", "")
            else:
                # For GitHub repos, we need to find the local clone path
                # It should be stored somewhere - let's check the work directory
                work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
                # Find the most recent directory matching the job
                clone_path = None
                if os.path.exists(work_dir):
                    for item in os.listdir(work_dir):
                        item_path = os.path.join(work_dir, item)
                        if os.path.isdir(item_path):
                            clone_path = item_path
                if not clone_path:
                    raise HTTPException(status_code=404, detail="Migration files not found")
        else:
            raise HTTPException(status_code=404, detail="Migration not completed yet")
    
    if not os.path.exists(clone_path):
        raise HTTPException(status_code=404, detail=f"Migration directory not found: {clone_path}")
    
    # Create a ZIP file
    zip_filename = f"migration-{job_id}"
    zip_path = os.path.join(tempfile.gettempdir(), zip_filename)
    
    try:
        shutil.make_archive(zip_path, 'zip', clone_path)
        zip_file = f"{zip_path}.zip"
        
        if os.path.exists(zip_file):
            return FileResponse(
                zip_file,
                media_type='application/zip',
                filename=f"{zip_filename}.zip"
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to create ZIP file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(e)}")


@app.get("/api/migrations", response_model=List[MigrationResult])
async def list_migrations():
    """List all migration jobs"""
    return list(migration_jobs.values())


@app.get("/api/migration/{job_id}/report")
async def download_migration_report(job_id: str):
    """Generate and download migration report as HTML"""
    print(f"DEBUG: Report requested for job_id: {job_id}")
    print(f"DEBUG: Available jobs: {list(migration_jobs.keys())}")

    if job_id not in migration_jobs:
        print(f"DEBUG: Job {job_id} not found in migration_jobs")
        raise HTTPException(status_code=404, detail=f"Migration job {job_id} not found")

    job = migration_jobs[job_id]
    logs = getattr(job, 'migration_log', [])

    print(f"DEBUG: Found job {job_id}, status: {job.status}, logs count: {len(logs)}")

    # Generate HTML report (modern template)
    html_content = generate_modern_html_report(job, logs)

    # Return HTML response with download headers
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename=migration-report-{job_id}.html"
        }
    )


@app.get("/api/migration/{job_id}/sonar-report-pdf")
async def download_sonar_report_pdf(job_id: str):
    """Generate and download a premium Sonar modernization/security assessment PDF."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail=f"Migration job {job_id} not found")

    job = migration_jobs[job_id]
    sonar_report = getattr(job, "sonar_report", None) or {}
    if not sonar_report and not getattr(job, "sonar_scan_mode", None):
        raise HTTPException(status_code=400, detail="No Sonar results are available for this migration job.")

    try:
        from pdf_generator.generator import build_sonar_assessment_pdf
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Sonar PDF dependencies are not available on the server. Install backend requirements and retry. ({exc})",
        )

    try:
        pdf_bytes = build_sonar_assessment_pdf(job)
    except Exception as exc:
        logger.exception("Failed to generate Sonar PDF for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"Failed to generate Sonar PDF: {exc}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=sonar-modernization-assessment-{job_id}.pdf"
        },
    )

@app.get("/api/migration/{job_id}/testcase-doc")
async def download_testcase_doc(job_id: str):
    """Download the Markdown testcase + change report for a migration job."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")

    job = migration_jobs[job_id]

    clone_path = getattr(job, "clone_path", None)
    if not clone_path and getattr(job, "target_repo", None) and str(job.target_repo).startswith("local://"):
        clone_path = str(job.target_repo).replace("local://", "")

    if not clone_path or not os.path.isdir(clone_path):
        raise HTTPException(status_code=404, detail="Local migration directory not found for this job")

    import tempfile

    doc_md = generate_testcase_doc_markdown(job, clone_path)
    doc_path = getattr(job, "testcase_doc_path", None) or os.path.join(clone_path, "TESTCASE_AND_CHANGES.md")
    try:
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(doc_md)
        job.testcase_doc_path = doc_path
    except Exception:
        # Fallback if clone_path isn't writable.
        tmp_path = os.path.join(tempfile.gettempdir(), f"TESTCASE_AND_CHANGES-{job_id}.md")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(doc_md)
        job.testcase_doc_path = tmp_path
        doc_path = tmp_path

    save_migration_job(job)

    return FileResponse(
        doc_path,
        media_type="text/markdown",
        filename=f"testcase-and-changes-{job_id}.md",
    )


@app.get("/api/migration/{job_id}/testcase-docx")
async def download_testcase_docx(job_id: str):
    """Download the DOCX testcase + change report for a migration job."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")

    job = migration_jobs[job_id]

    clone_path = getattr(job, "clone_path", None)
    if not clone_path and getattr(job, "target_repo", None) and str(job.target_repo).startswith("local://"):
        clone_path = str(job.target_repo).replace("local://", "")

    if not clone_path or not os.path.isdir(clone_path):
        raise HTTPException(status_code=404, detail="Local migration directory not found for this job")

    # Regenerate Markdown (source of truth) so downloads reflect the latest job state.
    import tempfile

    doc_md = generate_testcase_doc_markdown(job, clone_path)
    md_path = getattr(job, "testcase_doc_path", None) or os.path.join(clone_path, "TESTCASE_AND_CHANGES.md")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(doc_md)
        job.testcase_doc_path = md_path
    except Exception:
        tmp_md = os.path.join(tempfile.gettempdir(), f"TESTCASE_AND_CHANGES-{job_id}.md")
        with open(tmp_md, "w", encoding="utf-8") as f:
            f.write(doc_md)
        job.testcase_doc_path = tmp_md
        md_path = tmp_md

    save_migration_job(job)

    try:
        docx_path = generate_testcase_doc_docx(job, clone_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate DOCX: {exc}")

    return FileResponse(
        docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"testcase-and-changes-{job_id}.docx",
    )


@app.get("/api/migration/{job_id}/testcase-report")
async def download_testcase_report(job_id: str):
    """Download the testcase + change report as a styled HTML document."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")

    job = migration_jobs[job_id]

    clone_path = getattr(job, "clone_path", None)
    if not clone_path and getattr(job, "target_repo", None) and str(job.target_repo).startswith("local://"):
        clone_path = str(job.target_repo).replace("local://", "")

    if not clone_path or not os.path.isdir(clone_path):
        raise HTTPException(status_code=404, detail="Local migration directory not found for this job")

    html_content = generate_testcase_html_report(job, clone_path)
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename=testcase-and-changes-{job_id}.html"
        },
    )


@app.get("/api/migration/{job_id}/unit-test-report")
async def download_unit_test_report(job_id: str):
    """Download the unit test report as a styled HTML document."""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")

    job = migration_jobs[job_id]

    # Include a fully detailed report (same content as testcase+changes) when we have a local clone.
    details_html = ""
    clone_path = getattr(job, "clone_path", None)
    if not clone_path and getattr(job, "target_repo", None) and str(job.target_repo).startswith("local://"):
        clone_path = str(job.target_repo).replace("local://", "")
    if clone_path and os.path.isdir(clone_path):
        try:
            md = generate_testcase_doc_markdown(job, clone_path)
            details_html = _markdown_to_simple_html(md)
        except Exception:
            details_html = ""

    html_content = generate_unit_test_html_report(job, details_html=details_html)
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename=unit-test-report-{job_id}.html"
        },
    )


@app.get("/api/migration/{job_id}/jmeter")
async def generate_jmeter_test(job_id: str):
    """Generate and download JMeter test plan for migrated APIs"""
    if job_id not in migration_jobs:
        raise HTTPException(status_code=404, detail="Migration job not found")

    job = migration_jobs[job_id]
    # Store for reporting; generator will also use it.
    try:
        job.jmeter_base_url = base_url
    except Exception:
        pass
    save_migration_job(job)

    # Generate JMeter test plan XML
    jmeter_content = generate_jmeter_test_plan(job)

    # Return XML response with download headers
    return Response(
        content=jmeter_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f"attachment; filename=migration-test-{job_id}.jmx"
        }
    )


@app.post("/api/migration/preview")
async def preview_migration_changes(request: MigrationRequest):
    """Preview what changes will be made during migration without actually applying them"""
    try:
        print(f"[PREVIEW] Starting migration preview for: {request.source_repo_url}")

        # Determine which service to use based on platform
        if request.platform == GitPlatform.GITLAB:
            repo_service = gitlab_service
            source_token = (request.token or "").strip()
        else:  # GitHub is default
            repo_service = github_service
            source_token = _effective_github_token(token=request.token or "", github_token=request.github_token or "")

        # Prepare source project
        clone_path = await _resolve_source_project_path(
            request.source_repo_url,
            repo_service,
            source_token,
        )
        print(f"[PREVIEW] Source project prepared at: {clone_path}")

        # Analyze current state
        current_analysis = await migration_service.analyze_project(clone_path)

        # Simulate migration changes
        preview_changes = await migration_service.preview_migration_changes(
            clone_path,
            request.source_java_version,
            request.target_java_version.value,
            request.conversion_types,
            request.fix_business_logic
        )

        # Generate file diffs for key files
        file_diffs = await generate_file_diffs(clone_path, preview_changes)

        return {
            "repository": request.source_repo_url,
            "platform": request.platform.value,
            "source_version": request.source_java_version,
            "target_version": request.target_java_version.value,
            "conversions": request.conversion_types,
            "business_logic_fixes": request.fix_business_logic,
            "summary": {
                "files_to_modify": len(preview_changes.get("files_to_modify", [])),
                "files_to_create": len(preview_changes.get("files_to_create", [])),
                "files_to_remove": len(preview_changes.get("files_to_remove", [])),
                "total_changes": sum(len(changes) for changes in preview_changes.get("file_changes", {}).values())
            },
            "changes": preview_changes,
            "file_diffs": file_diffs[:10],  # Limit to first 10 files for performance
            "dependencies": {
                "current": current_analysis.get("dependencies", []),
                "upgrades": [d for d in current_analysis.get("dependencies", []) if d.get("status") == "upgraded"]
            }
        }

    except Exception as e:
        print(f"[PREVIEW] Error during preview: {e}")
        import traceback
        print(f"[PREVIEW] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


async def generate_file_diffs(clone_path: str, changes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate git-style diffs for changed files"""
    diffs = []

    try:
        import difflib
        import os

        files_to_check = changes.get("files_to_modify", [])[:5]  # Limit for performance

        for file_path in files_to_check:
            full_path = os.path.join(clone_path, file_path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        current_content = f.readlines()

                    # Apply simulated changes to get new content
                    new_content = simulate_file_changes(current_content, changes.get("file_changes", {}).get(file_path, []))

                    # Generate diff
                    diff = list(difflib.unified_diff(
                        current_content,
                        new_content,
                        fromfile=f"a/{file_path}",
                        tofile=f"b/{file_path}",
                        lineterm=""
                    ))

                    if diff:
                        diffs.append({
                            "file_path": file_path,
                            "diff": "\n".join(diff[:50]),  # Limit diff size
                            "change_count": len([line for line in diff if line.startswith(('+', '-'))])
                        })

                except Exception as e:
                    print(f"[DIFF] Error processing {file_path}: {e}")

    except ImportError:
        print("[DIFF] difflib not available for diff generation")

    return diffs


def simulate_file_changes(lines: List[str], changes: List[Dict[str, Any]]) -> List[str]:
    """Simulate applying changes to file content"""
    # This is a simplified simulation - in practice, we'd apply the actual transformations
    new_lines = lines.copy()

    for change in changes:
        if change.get("type") == "replace":
            # Simple text replacement simulation
            old_text = change.get("old", "")
            new_text = change.get("new", "")

            for i, line in enumerate(new_lines):
                if old_text in line:
                    new_lines[i] = line.replace(old_text, new_text)
                    break

    return new_lines


def generate_jmeter_test_plan(job: MigrationResult) -> str:
    """Generate a JMeter test plan XML for API testing"""
    # Base URL parts are provided via user variables; default points to a typical app port.
    base_url = getattr(job, "jmeter_base_url", None) or "http://localhost:8080"

    # Prefer detected endpoints from analysis; fall back to a minimal safe set.
    detected = getattr(job, "api_endpoints", None) or []
    api_endpoints: List[Dict[str, str]] = []
    if isinstance(detected, list) and detected:
        for ep in detected:
            try:
                path = (ep.get("path") or "").strip()
                method = (ep.get("method") or "GET").strip().upper()
                file = (ep.get("file") or "").strip()
            except Exception:
                continue

            # JMeter defaults: only include safe GET endpoints automatically.
            if method == "REQUEST":
                method = "GET"
            if method != "GET":
                continue
            if not path:
                continue
            if not path.startswith("/"):
                path = "/" + path
            api_endpoints.append({"path": path, "method": method, "description": file or "API Endpoint"})

    if not api_endpoints:
        api_endpoints = [
            {"path": "/health", "method": "GET", "description": "Health Check"},
        ]

    # Parse base url into protocol/host/port and optional base path.
    try:
        from urllib.parse import urlparse
        raw = base_url.strip()
        if "://" not in raw:
            raw = "http://" + raw
        parsed = urlparse(raw)
        protocol = (parsed.scheme or "http").lower()
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if protocol == "https" else 80)
        base_path = (parsed.path or "").strip()
        if base_path and not base_path.startswith("/"):
            base_path = "/" + base_path
        base_path = base_path.rstrip("/")
    except Exception:
        protocol, host, port, base_path = "http", "localhost", 8080, ""

    if base_path:
        for ep in api_endpoints:
            p = ep.get("path") or ""
            if p and not p.startswith("/"):
                p = "/" + p
            if p and not p.startswith(base_path + "/") and p != base_path:
                ep["path"] = base_path + p

    # JMeter test plan XML template
    jmeter_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Migration API Tests - {job.job_id}" enabled="true">
      <stringProp name="TestPlan.comments">Generated JMeter test plan for migrated APIs</stringProp>
      <boolProp name="TestPlan.functional_mode">false</boolProp>
      <boolProp name="TestPlan.tearDown_on_shutdown">true</boolProp>
      <boolProp name="TestPlan.serialize_threadgroups">false</boolProp>
      <elementProp name="TestPlan.user_defined_variables" elementType="Arguments" guiclass="ArgumentsPanel" testclass="Arguments" testname="User Defined Variables" enabled="true">
        <collectionProp name="Arguments.arguments">
          <elementProp name="BASE_URL" elementType="Argument">
            <stringProp name="Argument.name">BASE_URL</stringProp>
            <stringProp name="Argument.value">{base_url}</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="BASE_PROTOCOL" elementType="Argument">
            <stringProp name="Argument.name">BASE_PROTOCOL</stringProp>
            <stringProp name="Argument.value">{protocol}</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="BASE_HOST" elementType="Argument">
            <stringProp name="Argument.name">BASE_HOST</stringProp>
            <stringProp name="Argument.value">{host}</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="BASE_PORT" elementType="Argument">
            <stringProp name="Argument.name">BASE_PORT</stringProp>
            <stringProp name="Argument.value">{port}</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="BASE_PATH" elementType="Argument">
            <stringProp name="Argument.name">BASE_PATH</stringProp>
            <stringProp name="Argument.value">{base_path}</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="THREAD_COUNT" elementType="Argument">
            <stringProp name="Argument.name">THREAD_COUNT</stringProp>
            <stringProp name="Argument.value">10</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="RAMP_UP_TIME" elementType="Argument">
            <stringProp name="Argument.name">RAMP_UP_TIME</stringProp>
            <stringProp name="Argument.value">30</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
          <elementProp name="LOOP_COUNT" elementType="Argument">
            <stringProp name="Argument.name">LOOP_COUNT</stringProp>
            <stringProp name="Argument.value">5</stringProp>
            <stringProp name="Argument.metadata">=</stringProp>
          </elementProp>
        </collectionProp>
      </elementProp>
      <stringProp name="TestPlan.user_define_classpath"></stringProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="API Test Thread Group" enabled="true">
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlGui" testclass="LoopController" testname="Loop Controller" enabled="true">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <stringProp name="LoopController.loops">${{LOOP_COUNT}}</stringProp>
        </elementProp>
        <stringProp name="ThreadGroup.num_threads">${{THREAD_COUNT}}</stringProp>
        <stringProp name="ThreadGroup.ramp_time">${{RAMP_UP_TIME}}</stringProp>
        <longProp name="ThreadGroup.start_time">1</longProp>
        <longProp name="ThreadGroup.end_time">1</longProp>
        <boolProp name="ThreadGroup.scheduler">false</boolProp>
        <stringProp name="ThreadGroup.duration"></stringProp>
        <stringProp name="ThreadGroup.delay"></stringProp>
        <boolProp name="ThreadGroup.same_user_on_next_iteration">true</boolProp>
      </ThreadGroup>
      <hashTree>
        <!-- HTTP Request Defaults -->
        <ConfigTestElement guiclass="HttpDefaultsGui" testclass="ConfigTestElement" testname="HTTP Request Defaults" enabled="true">
          <elementProp name="HTTPsampler.Arguments" elementType="Arguments" guiclass="HTTPArgumentsPanel" testclass="Arguments" testname="User Defined Variables" enabled="true">
            <collectionProp name="Arguments.arguments"/>
          </elementProp>
          <stringProp name="HTTPSampler.domain">${{BASE_HOST}}</stringProp>
          <stringProp name="HTTPSampler.port">${{BASE_PORT}}</stringProp>
          <stringProp name="HTTPSampler.protocol">${{BASE_PROTOCOL}}</stringProp>
          <stringProp name="HTTPSampler.contentEncoding"></stringProp>
          <stringProp name="HTTPSampler.path"></stringProp>
          <stringProp name="HTTPSampler.concurrentPool">6</stringProp>
          <stringProp name="HTTPSampler.connect_timeout">60000</stringProp>
          <stringProp name="HTTPSampler.response_timeout">60000</stringProp>
        </ConfigTestElement>
        <hashTree/>

        <!-- HTTP Header Manager -->
        <HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" testname="HTTP Header Manager" enabled="true">
          <collectionProp name="HeaderManager.headers">
            <elementProp name="" elementType="Header">
              <stringProp name="Header.name">Content-Type</stringProp>
              <stringProp name="Header.value">application/json</stringProp>
            </elementProp>
            <elementProp name="" elementType="Header">
              <stringProp name="Header.name">Accept</stringProp>
              <stringProp name="Header.value">application/json</stringProp>
            </elementProp>
          </collectionProp>
        </HeaderManager>
        <hashTree/>

        <!-- Result Collector -->
        <ResultCollector guiclass="ViewResultsFullVisualizer" testclass="ResultCollector" testname="View Results Tree" enabled="true">
          <boolProp name="ResultCollector.error_logging">false</boolProp>
          <objProp>
            <name>saveConfig</name>
            <value class="SampleSaveConfiguration">
              <time>true</time>
              <latency>true</latency>
              <timestamp>true</timestamp>
              <success>true</success>
              <label>true</label>
              <code>true</code>
              <message>true</message>
              <threadName>true</threadName>
              <dataType>true</dataType>
              <encoding>false</encoding>
              <assertions>true</assertions>
              <subresults>true</subresults>
              <responseData>false</responseData>
              <samplerData>false</samplerData>
              <xml>false</xml>
              <fieldNames>true</fieldNames>
              <responseHeaders>false</responseHeaders>
              <requestHeaders>false</requestHeaders>
              <responseDataOnError>false</responseDataOnError>
              <saveAssertionResultsFailureMessage>true</saveAssertionResultsFailureMessage>
              <assertionsResultsToSave>0</assertionsResultsToSave>
              <bytes>true</bytes>
              <sentBytes>true</sentBytes>
              <url>true</url>
              <threadCounts>true</threadCounts>
              <idleTime>true</idleTime>
              <connectTime>true</connectTime>
            </value>
          </objProp>
          <stringProp name="filename"></stringProp>
        </ResultCollector>
        <hashTree/>

        <!-- Summary Report -->
        <ResultCollector guiclass="SummaryReport" testclass="ResultCollector" testname="Summary Report" enabled="true">
          <boolProp name="ResultCollector.error_logging">false</boolProp>
          <objProp>
            <name>saveConfig</name>
            <value class="SampleSaveConfiguration">
              <time>true</time>
              <latency>true</latency>
              <timestamp>true</timestamp>
              <success>true</success>
              <label>true</label>
              <code>true</code>
              <message>true</message>
              <threadName>true</threadName>
              <dataType>true</dataType>
              <encoding>false</encoding>
              <assertions>true</assertions>
              <subresults>true</subresults>
              <responseData>false</responseData>
              <samplerData>false</samplerData>
              <xml>false</xml>
              <fieldNames>true</fieldNames>
              <responseHeaders>false</responseHeaders>
              <requestHeaders>false</requestHeaders>
              <responseDataOnError>false</responseDataOnError>
              <saveAssertionResultsFailureMessage>true</saveAssertionResultsFailureMessage>
              <assertionsResultsToSave>0</assertionsResultsToSave>
              <bytes>true</bytes>
              <sentBytes>true</sentBytes>
              <url>true</url>
              <threadCounts>true</threadCounts>
              <idleTime>true</idleTime>
              <connectTime>true</connectTime>
            </value>
          </objProp>
          <stringProp name="filename"></stringProp>
        </ResultCollector>
        <hashTree/>
'''

    # Add HTTP samplers for each API endpoint
    for i, endpoint in enumerate(api_endpoints):
        sampler_name = f"{endpoint['method']} {endpoint['path']}"
        jmeter_xml += f'''
        <!-- {endpoint['description']} -->
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="{sampler_name}" enabled="true">
          <elementProp name="HTTPsampler.Arguments" elementType="Arguments" guiclass="HTTPArgumentsPanel" testclass="Arguments" testname="User Defined Variables" enabled="true">
            <collectionProp name="Arguments.arguments"/>
          </elementProp>
          <stringProp name="HTTPSampler.domain"></stringProp>
          <stringProp name="HTTPSampler.port"></stringProp>
          <stringProp name="HTTPSampler.protocol"></stringProp>
          <stringProp name="HTTPSampler.contentEncoding"></stringProp>
          <stringProp name="HTTPSampler.path">{endpoint['path']}</stringProp>
          <stringProp name="HTTPSampler.method">{endpoint['method']}</stringProp>
          <boolProp name="HTTPSampler.follow_redirects">true</boolProp>
          <boolProp name="HTTPSampler.auto_redirects">false</boolProp>
          <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
          <boolProp name="HTTPSampler.DO_MULTIPART_POST">false</boolProp>
          <stringProp name="HTTPSampler.embedded_url_re"></stringProp>
          <stringProp name="HTTPSampler.connect_timeout"></stringProp>
          <stringProp name="HTTPSampler.response_timeout"></stringProp>
        </HTTPSamplerProxy>
        <hashTree>
          <!-- Response Assertion -->
          <ResponseAssertion guiclass="AssertionGui" testclass="ResponseAssertion" testname="Response Code Assertion" enabled="true">
            <collectionProp name="Asserion.test_strings">
              <stringProp name="51751">2\\d\\d</stringProp>
            </collectionProp>
            <stringProp name="Assertion.custom_message"></stringProp>
            <stringProp name="Assertion.test_field">Assertion.response_code</stringProp>
            <boolProp name="Assertion.assume_success">false</boolProp>
            <intProp name="Assertion.test_type">2</intProp>
          </ResponseAssertion>
          <hashTree/>
        </hashTree>
'''

    # Close the test plan
    jmeter_xml += '''
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
'''

    return jmeter_xml

def _escape(text: Any) -> str:
    return _html.escape("" if text is None else str(text), quote=True)


def _infer_repo_name(repo_url: str) -> str:
    try:
        s = (repo_url or "").rstrip("/")
        if not s:
            return "Repository"
        if "://" in s:
            s = s.split("://", 1)[1]
        parts = [p for p in s.split("/") if p]
        if parts:
            name = parts[-1]
            if name.lower().endswith(".git"):
                name = name[:-4]
            return name or "Repository"
        return "Repository"
    except Exception:
        return "Repository"


def _extract_target_repository_name(target_repo_name: str) -> str:
    raw_value = (target_repo_name or "").strip().rstrip("/")
    if not raw_value:
        return ""

    candidate = raw_value
    if "://" in raw_value:
        parsed = urlparse(raw_value)
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            candidate = path_parts[-1]
    elif "/" in raw_value:
        path_parts = [part for part in raw_value.split("/") if part]
        if path_parts:
            candidate = path_parts[-1]

    if candidate.lower().endswith(".git"):
        candidate = candidate[:-4]

    return re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip("-")


def _parse_target_repository_destination(target_repo_name: str, default_owner: str = "Javaapex") -> tuple[str, str]:
    raw_value = (target_repo_name or "").strip().rstrip("/")
    if not raw_value:
        return default_owner, ""

    owner = default_owner
    repo_name = ""

    if "://" in raw_value:
        parsed = urlparse(raw_value)
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2:
            owner = path_parts[0]
            repo_name = path_parts[1]
        elif path_parts:
            repo_name = path_parts[-1]
    elif "/" in raw_value:
        path_parts = [part for part in raw_value.split("/") if part]
        if len(path_parts) >= 2:
            owner = path_parts[0]
            repo_name = path_parts[1]
        elif path_parts:
            repo_name = path_parts[-1]
    else:
        repo_name = raw_value

    if repo_name.lower().endswith(".git"):
        repo_name = repo_name[:-4]

    owner = re.sub(r"[^A-Za-z0-9._-]+", "-", owner).strip("-") or default_owner
    repo_name = re.sub(r"[^A-Za-z0-9._-]+", "-", repo_name).strip("-")
    return owner, repo_name


def _sanitize_local_publish_folder_name(folder_name: str, fallback_name: str) -> str:
    raw_value = (folder_name or "").strip().rstrip("\\/")
    candidate = raw_value

    if "://" in candidate:
        parsed = urlparse(candidate)
        candidate = parsed.path.rstrip("\\/")

    candidate = os.path.basename(candidate) if candidate else ""
    if candidate.lower().endswith(".git"):
        candidate = candidate[:-4]

    candidate = re.sub(r"[<>:\"/\\|?*\x00-\x1F]+", "-", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")

    fallback = re.sub(r"[<>:\"/\\|?*\x00-\x1F]+", "-", fallback_name or "repo-Migrated")
    fallback = re.sub(r"\s+", " ", fallback).strip(" .") or "repo-Migrated"
    return candidate or fallback


def _publish_migrated_project_locally(
    clone_path: str,
    requested_folder_name: str,
    default_folder_name: str,
) -> str:
    import tempfile

    work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
    local_publish_root = os.path.join(work_dir, "local_migration_outputs")
    os.makedirs(local_publish_root, exist_ok=True)

    requested_path = (requested_folder_name or "").strip().strip("\"'")
    use_explicit_absolute_path = os.path.isabs(requested_path)

    if use_explicit_absolute_path:
        destination_path = os.path.abspath(os.path.normpath(requested_path))
    else:
        folder_name = _sanitize_local_publish_folder_name(requested_folder_name, default_folder_name)
        destination_path = os.path.join(local_publish_root, folder_name)

    if os.path.abspath(destination_path) == os.path.abspath(clone_path):
        return destination_path

    if os.path.exists(destination_path):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination_parent = os.path.dirname(destination_path)
        destination_name = os.path.basename(destination_path.rstrip("\\/")) or default_folder_name
        destination_path = os.path.join(destination_parent, f"{destination_name}-{timestamp}")

    os.makedirs(os.path.dirname(destination_path), exist_ok=True)

    shutil.move(clone_path, destination_path)
    return destination_path


def _job_status_ui(job_status: str) -> Dict[str, str]:
    s = (job_status or "").lower()
    if s == "completed":
        return {"label": "Migration Completed", "class": "status-completed"}
    if s == "failed":
        return {"label": "Migration Failed", "class": "status-failed"}
    return {"label": f"Migration {job_status or 'Running'}", "class": "status-running"}


def _markdown_to_simple_html(md: str) -> str:
    """
    Minimal Markdown renderer for our own generated artifacts:
    headings, bullet lists, fenced code blocks, inline code.
    """
    lines = (md or "").splitlines()
    out: List[str] = []

    in_code = False
    code_lang = ""
    list_open = False

    def close_list():
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    for raw in lines:
        line = raw.rstrip("\n")

        if line.strip().startswith("```"):
            fence = line.strip()
            if in_code:
                out.append("</code></pre>")
                in_code = False
                code_lang = ""
            else:
                close_list()
                in_code = True
                code_lang = fence.strip("`").strip()
                lang_attr = f' data-lang="{_escape(code_lang)}"' if code_lang else ""
                out.append(f"<pre class=\"code\"><code{lang_attr}>")
            continue

        if in_code:
            out.append(_escape(line) + "\n")
            continue

        if not line.strip():
            close_list()
            out.append("<div class=\"spacer\"></div>")
            continue

        if line.startswith("# "):
            close_list()
            out.append(f"<h1>{_escape(line[2:].strip())}</h1>")
            continue
        if line.startswith("## "):
            close_list()
            out.append(f"<h2>{_escape(line[3:].strip())}</h2>")
            continue
        if line.startswith("### "):
            close_list()
            out.append(f"<h3>{_escape(line[4:].strip())}</h3>")
            continue
        if line.startswith("#### "):
            close_list()
            out.append(f"<h4>{_escape(line[5:].strip())}</h4>")
            continue

        if line.startswith("- "):
            if not list_open:
                out.append("<ul>")
                list_open = True
            item = line[2:].strip()
            # Inline code blocks: `code`
            item = re.sub(r"`([^`]+)`", lambda m: f"<code>{_escape(m.group(1))}</code>", item)
            out.append(f"<li>{item}</li>")
            continue

        close_list()
        p = re.sub(r"`([^`]+)`", lambda m: f"<code>{_escape(m.group(1))}</code>", _escape(line))
        out.append(f"<p>{p}</p>")

    if in_code:
        out.append("</code></pre>")
    close_list()
    return "\n".join(out)


def _build_brd_document_from_analysis(repo_name: str, repo_url: str, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a BRD/KT document from repository analysis data.

    This is the local, runnable replacement for the Ford-specific LLM generator
    referenced in the supplied snippet.
    """
    dependencies = analysis_data.get("dependencies", []) or []
    all_files = analysis_data.get("all_files", []) or []
    vulnerable_deps = analysis_data.get("vulnerable_dependencies", []) or []
    detected_frameworks = analysis_data.get("detected_frameworks", []) or []
    api_endpoints = analysis_data.get("api_endpoints", []) or []
    build_tool = analysis_data.get("build_tool") or "unknown"
    java_version = (
        analysis_data.get("java_version")
        or analysis_data.get("java_version_from_build")
        or "unknown"
    )

    repo_short_name = repo_name.split("/", 1)[-1] if "/" in repo_name else repo_name
    file_count = len(all_files)
    endpoint_count = len(api_endpoints)
    dep_count = len(dependencies)
    vuln_count = len(vulnerable_deps)

    modules = []
    top_level_dirs = set()
    for item in all_files:
        path = item.get("path", item.get("name", "")) if isinstance(item, dict) else str(item)
        parts = path.replace("\\", "/").split("/")
        if len(parts) > 1 and parts[0] not in {"src", "target", "build", ".github"}:
            top_level_dirs.add(parts[0])
    for name in sorted(top_level_dirs)[:6]:
        modules.append({
            "name": name,
            "description": f"Top-level module or package group detected in repository structure.",
            "files": name,
        })

    if not modules:
        modules = [{
            "name": repo_short_name,
            "description": "Primary application module detected from repository layout.",
            "files": "src/",
        }]

    document = {
        "document_info": {
            "title": f"Business Requirements Document - {repo_name}",
            "repository": repo_name,
            "repo_url": repo_url,
            "generated_at": datetime.now().isoformat(),
            "build_tool": build_tool,
            "java_version": java_version,
            "frameworks": detected_frameworks,
        },
        "executive_summary": (
            f"{repo_name} is a Java application built with {build_tool}. "
            f"The repository analysis identified {file_count} files, {dep_count} dependencies, "
            f"{endpoint_count} API endpoints, and {vuln_count} known vulnerable dependencies."
        ),
        "business_objectives": [
            {
                "id": "BO-01",
                "objective": "Establish a migration-ready baseline",
                "target": f"Document architecture, dependencies, and integration points for {repo_name}.",
            },
            {
                "id": "BO-02",
                "objective": "Reduce modernization risk",
                "target": f"Resolve all {vuln_count} known vulnerable dependency findings.",
            },
            {
                "id": "BO-03",
                "objective": "Preserve build reliability",
                "target": f"Maintain successful {build_tool} builds on Java {java_version}.",
            },
            {
                "id": "BO-04",
                "objective": "Improve team knowledge transfer",
                "target": "Provide a structured BRD that supports onboarding and migration planning.",
            },
        ],
        "scope_in": [
            "Repository structure and source inventory",
            "Dependency inventory and basic risk review",
            "API endpoint inventory",
            "Build tool and Java runtime baseline",
            "High-level architecture and module mapping",
        ],
        "scope_out": [
            "Runtime load testing",
            "Production-only operational tuning",
            "End-user UAT validation",
            "Detailed implementation scheduling",
        ],
        "tech_stack": [],
        "modules": modules,
        "api_endpoints": api_endpoints,
        "use_cases": [
            {
                "id": "UC-01",
                "name": f"Analyze and build {repo_short_name}",
                "actor": "Developer",
                "main_flow": f"1. Clone repository  2. Install dependencies  3. Execute {build_tool} build  4. Validate output",
                "post_condition": "Project can be built and analyzed successfully.",
            }
        ],
        "capabilities": [],
        "db_tables": [],
        "class_inventory": [],
        "languages": [],
        "risks": [],
        "glossary": [],
        "external_api_calls": [],
        "dependency_risks": [
            {
                "dependency": f"{dep.get('group_id', '')}:{dep.get('artifact_id', '')}".strip(":"),
                "current_version": dep.get("current_version") or dep.get("version") or "unknown",
                "latest_version": dep.get("new_version") or "latest",
                "risk_level": "high" if any(
                    token in (dep.get("artifact_id", "") + dep.get("group_id", "")).lower()
                    for token in ["log4j", "commons-collections", "jackson", "spring"]
                ) else "medium",
                "notes": "Review compatibility and security posture during migration.",
            }
            for dep in dependencies[:8]
        ],
    }

    return _enrich_brd_document(document, analysis_data, repo_name)


def _generate_brd_html(document: Dict[str, Any], repo_name: str, repo_url: str, analysis_data: Optional[Dict[str, Any]] = None) -> str:
    """Render a multi-page technical document view modeled after the richer reference report."""

    analysis_data = analysis_data or {}

    def _coerce_list(value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if value in (None, "", {}, ()):
            return []
        return [value]

    def _stringify(value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, list):
            return ", ".join(_stringify(item) for item in value if _stringify(item))
        if isinstance(value, dict):
            return ", ".join(
                f"{key}: {_stringify(item)}"
                for key, item in value.items()
                if _stringify(item)
            )
        return str(value)

    def _safe_int(value: Any) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    def _first_nonempty(values: List[Any], default: str = "") -> str:
        for value in values:
            rendered = _stringify(value).strip()
            if rendered:
                return rendered
        return default

    def _titleize(value: str) -> str:
        text = str(value or "").replace("_", " ").replace("-", " ").strip()
        if not text:
            return ""
        return " ".join(part[:1].upper() + part[1:] for part in text.split())

    def _render_text(value: Any, default: str = "No data available.") -> str:
        text = _stringify(value).strip()
        if not text:
            return f"<p class=\"muted\">{_escape(default)}</p>"
        return "<p>" + "<br>".join(_escape(part) for part in text.splitlines() if part.strip()) + "</p>"

    def _render_kv_table(items: List[tuple], table_class: str = "static-table") -> str:
        rows = []
        for key, value in items:
            rendered = _stringify(value)
            if not rendered:
                continue
            rows.append(f"<tr><td>{_escape(key)}</td><td>{_escape(rendered)}</td></tr>")
        if not rows:
            rows.append("<tr><td colspan=\"2\">No data available</td></tr>")
        return f"<table class=\"{table_class}\"><tbody>{''.join(rows)}</tbody></table>"

    def _render_object_table(items: Any, columns: List[tuple], table_class: str = "brd-table", empty_message: str = "No data available.") -> str:
        rows = []
        for item in _coerce_list(items):
            if not isinstance(item, dict):
                continue
            row_cells = []
            for column in columns:
                key = column[1]
                style = column[2] if len(column) > 2 else ""
                value = _stringify(item.get(key, ""))
                style_attr = f" style=\"{style}\"" if style else ""
                row_cells.append(f"<td{style_attr}>{_escape(value) if value else '&mdash;'}</td>")
            rows.append(f"<tr>{''.join(row_cells)}</tr>")
        if not rows:
            return f"<p class=\"muted\">{_escape(empty_message)}</p>"
        header = []
        for column in columns:
            label = column[0]
            style = column[2] if len(column) > 2 else ""
            style_attr = f" style=\"{style}\"" if style else ""
            header.append(f"<th{style_attr}>{_escape(label)}</th>")
        return f"<table class=\"{table_class}\"><thead><tr>{''.join(header)}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    def _render_pills(items: Any, fallback: Optional[List[str]] = None) -> str:
        values = [str(item).strip() for item in _coerce_list(items) if str(item).strip()]
        if not values and fallback:
            values = [str(item).strip() for item in fallback if str(item).strip()]
        if not values:
            values = ["No frameworks detected"]
        return "".join(f"<span class=\"tech-pill\">{_escape(value)}</span>" for value in values[:12])

    def _render_objectives(items: Any) -> str:
        cards = []
        for index, item in enumerate(_coerce_list(items), start=1):
            if not isinstance(item, dict):
                continue
            cards.append(
                "<div class=\"phase-item\">"
                f"<div class=\"phase-num\">Objective {index:02d}</div>"
                f"<div class=\"phase-title\">{_escape(item.get('objective', item.get('id', f'Objective {index}')))}</div>"
                f"<div class=\"phase-desc\">{_escape(_stringify(item.get('target', '')) or 'Target to be finalized')}</div>"
                "</div>"
            )
        return f"<div class=\"phase-list\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No objectives available.</p>"

    def _render_metric_grid(items: List[tuple], grid_class: str = "metric-grid") -> str:
        cards = []
        for label, value in items:
            rendered = _stringify(value)
            if not rendered:
                continue
            cards.append(
                "<div class=\"metric-card\">"
                f"<div class=\"metric-label\">{_escape(label)}</div>"
                f"<div class=\"metric-value\">{_escape(rendered)}</div>"
                "</div>"
            )
        return f"<div class=\"{grid_class}\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No metrics available.</p>"

    def _render_scope(items: Any, title: str, css_class: str) -> str:
        rows = []
        for item in _coerce_list(items):
            label = _stringify(item)
            if label:
                rows.append(
                    "<div class=\"scope-item\">"
                    f"<span class=\"scope-mark\">{_escape('+' if css_class == 'in-scope' else '-')}</span>"
                    f"<span>{_escape(label)}</span>"
                    "</div>"
                )
        content = "".join(rows) or "<div class=\"scope-item\"><span class=\"scope-mark\">-</span><span>No scope items defined.</span></div>"
        return (
            f"<div class=\"scope-box {css_class}\">"
            f"<h4>{_escape(title)}</h4>"
            f"{content}"
            "</div>"
        )

    def _render_capabilities(items: Any) -> str:
        cards = []
        for item in _coerce_list(items):
            if not isinstance(item, dict):
                continue
            features = _coerce_list(item.get("features"))
            feature_html = "".join(f"<li>{_escape(_stringify(feature))}</li>" for feature in features[:4] if _stringify(feature))
            process_html = "".join(
                f"<li>{_escape(_stringify(step))}</li>"
                for step in _coerce_list(item.get("processes"))[:3]
                if _stringify(step)
            )
            cards.append(
                "<div class=\"arch-card capability-card\">"
                f"<h3>{_escape(item.get('name', 'Capability'))}</h3>"
                f"<p>{_escape(_stringify(item.get('overview')) or _stringify(item.get('business_value')) or 'Capability summary unavailable.')}</p>"
                f"<h4 class=\"sub\">Key Business Features</h4><ul class=\"mini-list\">{feature_html or '<li>No feature breakdown available.</li>'}</ul>"
                f"<h4 class=\"sub\">Primary Business Processes</h4><ul class=\"mini-list\">{process_html or '<li>No process narrative available.</li>'}</ul>"
                "</div>"
            )
        return f"<div class=\"full-arch capability-grid\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No capability breakdown available.</p>"

    def _render_module_cards(items: Any) -> str:
        cards = []
        for item in _coerce_list(items):
            if not isinstance(item, dict):
                continue
            cards.append(
                "<div class=\"module-card\">"
                f"<h4>{_escape(item.get('name', 'Module'))}</h4>"
                f"<p>{_escape(_stringify(item.get('description')) or 'Module description unavailable.')}</p>"
                f"<div class=\"module-tag\">{_escape(_stringify(item.get('files')) or 'N/A')}</div>"
                "</div>"
            )
        return f"<div class=\"module-grid\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No modules detected.</p>"

    def _render_db_tables(items: Any) -> str:
        empty_field_row = '<div class="er-field"><span class="fname">No fields detected</span><span class="ftype">&nbsp;</span></div>'
        cards = []
        for item in _coerce_list(items):
            if not isinstance(item, dict):
                continue
            fields = item.get("fields", [])
            field_rows = []
            for field in _coerce_list(fields):
                if not isinstance(field, dict):
                    continue
                field_rows.append(
                    "<div class=\"er-field\">"
                    f"<span class=\"fname\">{_escape(_stringify(field.get('name')) or 'field')}</span>"
                    f"<span class=\"ftype\">{_escape(_stringify(field.get('type')) or 'unknown')}</span>"
                    "</div>"
                )
            field_content = "".join(field_rows) or empty_field_row
            cards.append(
                "<div class=\"er-table\">"
                f"<div class=\"er-table-head dark\">{_escape(item.get('table_name', 'table'))}</div>"
                f"{field_content}"
                "</div>"
            )
        return f"<div class=\"er-grid\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No data entities or tables detected.</p>"

    def _render_page(page_id: str, page_number: int, content: str, extra_class: str = "") -> str:
        class_name = "page"
        if extra_class:
            class_name += f" {extra_class}"
        return (
            f"<div class=\"{class_name}\" id=\"{_escape(page_id)}\">"
            "<div class=\"page-inner\">"
            f"<div class=\"page-anchor\" id=\"{_escape(page_id)}-anchor\"></div>"
            f"{content}"
            f"<div class=\"pg-watermark\">{_escape(repo_short_name)} Technical Document v1.0 - Confidential</div>"
            f"<div class=\"pg-num\">{page_number:02d}</div>"
            "</div></div>"
        )

    def _split_steps(value: Any) -> List[str]:
        text = _stringify(value)
        if not text:
            return []
        normalized = text.replace("  ", "\n")
        parts = re.split(r"(?:\n+|\s(?=\d+\.)|;\s+)", normalized)
        cleaned = []
        for part in parts:
            chunk = re.sub(r"^\d+\.\s*", "", part).strip(" -")
            if chunk:
                cleaned.append(chunk)
        return cleaned

    def _render_bullet_list(items: Any, empty_message: str = "No data available.", css_class: str = "bullet-list") -> str:
        rows = []
        for item in _coerce_list(items):
            label = _stringify(item).strip()
            if label:
                rows.append(f"<li>{_escape(label)}</li>")
        return f"<ul class=\"{css_class}\">{''.join(rows)}</ul>" if rows else f"<p class=\"muted\">{_escape(empty_message)}</p>"

    def _infer_endpoint_group(path: str) -> str:
        clean = str(path or "/").strip()
        parts = [part for part in clean.split("/") if part and not part.startswith("{")]
        if parts and parts[0].lower() == "api":
            parts = parts[1:]
        if parts and re.fullmatch(r"v\d+", parts[0].lower()):
            parts = parts[1:]
        return _titleize(parts[0]) if parts else "Platform"

    def _normalize_endpoint(item: Any) -> Optional[Dict[str, str]]:
        if not isinstance(item, dict):
            return None
        path = _first_nonempty([
            item.get("endpoint"),
            item.get("path"),
            item.get("url"),
            item.get("route"),
        ], "/")
        method = _first_nonempty([item.get("method"), item.get("http_method")], "GET").upper()
        description = _first_nonempty([
            item.get("description"),
            item.get("summary"),
            item.get("name"),
        ], "Endpoint detected from repository analysis.")
        return {
            "group": _first_nonempty([item.get("group"), item.get("module")], _infer_endpoint_group(path)),
            "method": method,
            "endpoint": path,
            "description": description,
            "file": _first_nonempty([item.get("file"), item.get("source")], ""),
        }

    def _group_endpoints(items: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
        grouped: Dict[str, List[Dict[str, str]]] = {}
        for item in items:
            grouped.setdefault(item["group"], []).append(item)
        return grouped

    def _render_architecture_diagram(rows: List[tuple]) -> str:
        empty_arch_card = '<div class="arch-card node-card">No components detected</div>'
        sections = []
        for css_class, label, items in rows:
            cards = "".join(f"<div class=\"arch-card node-card\">{_escape(card)}</div>" for card in items if card)
            arch_row_content = cards or empty_arch_card
            sections.append(
                f"<div class=\"arch-section {css_class}\">"
                f"<div class=\"arch-section-label\">{_escape(label)}</div>"
                f"<div class=\"arch-row\">{arch_row_content}</div>"
                "</div>"
            )
        legend = (
            "<div class=\"arch-legend\">"
            "<div class=\"arch-legend-item\"><span class=\"arch-legend-dot dot-actor\"></span>Actors</div>"
            "<div class=\"arch-legend-item\"><span class=\"arch-legend-dot dot-ui\"></span>Presentation</div>"
            "<div class=\"arch-legend-item\"><span class=\"arch-legend-dot dot-biz\"></span>Business</div>"
            "<div class=\"arch-legend-item\"><span class=\"arch-legend-dot dot-data\"></span>Data / External</div>"
            "</div>"
        )
        return (
            "<div class=\"arch-diagram\">"
            f"{''.join(sections)}"
            f"{legend}"
            f"<div class=\"arch-fig-caption\">Figure 4.1 - {_escape(repo_short_name)} High-Level Architecture Diagram</div>"
            "</div>"
        )

    def _render_app_flow(steps: List[Dict[str, str]], title: str) -> str:
        cards = []
        for index, step in enumerate(steps):
            cards.append(
                "<div class=\"app-screen\">"
                f"<div class=\"app-screen-icon\">{index + 1:02d}</div>"
                f"<div class=\"app-screen-name\">{_escape(step.get('name', f'Step {index + 1}'))}</div>"
                f"<div class=\"app-screen-desc\">{_escape(step.get('desc', 'Flow stage detected from repository analysis.'))}</div>"
                "</div>"
            )
            if index < len(steps) - 1:
                cards.append("<div class=\"app-flow-arrow\"></div>")
        return (
            "<div class=\"app-flow\">"
            f"<div class=\"app-flow-title\">{_escape(title)}</div>"
            f"<div class=\"app-flow-track\">{''.join(cards)}</div>"
            "</div>"
        )

    def _render_use_case_cards(items: Any) -> str:
        empty_use_case_step = '<div class="use-case-step">Main flow pending</div>'
        cards = []
        priorities = ["High", "High", "Medium", "Medium", "Low", "Low"]
        for index, item in enumerate(_coerce_list(items), start=1):
            if not isinstance(item, dict):
                continue
            steps = _split_steps(item.get("main_flow"))
            step_html = "".join(f"<div class=\"use-case-step\">{_escape(step)}</div>" for step in steps[:6])
            use_case_steps_html = step_html or empty_use_case_step
            priority = priorities[index - 1] if index - 1 < len(priorities) else "Medium"
            cards.append(
                "<div class=\"use-case-card\">"
                f"<div class=\"use-case-id\">{_escape(item.get('id', f'UC-{index:03d}'))}</div>"
                f"<div class=\"use-case-title\">{_escape(item.get('name', f'Use Case {index}'))}</div>"
                "<div class=\"use-case-meta\">"
                f"<div class=\"use-case-meta-item\"><span>Actor:</span>{_escape(_stringify(item.get('actor')) or 'User')}</div>"
                f"<div class=\"use-case-meta-item\"><span>Priority:</span><span class=\"badge\">{_escape(priority)}</span></div>"
                "<div class=\"use-case-meta-item\"><span>Precondition:</span>System is accessible</div>"
                f"<div class=\"use-case-meta-item\"><span>Postcondition:</span>{_escape(_stringify(item.get('post_condition')) or 'Outcome to be validated')}</div>"
                "</div>"
                f"<div class=\"use-case-steps\">{use_case_steps_html}</div>"
                "</div>"
            )
        return "".join(cards) or "<p class=\"muted\">No use cases are available.</p>"

    def _render_class_cards(items: Any, fallbacks: List[Dict[str, str]]) -> str:
        source_items = [item for item in _coerce_list(items) if isinstance(item, dict)]
        if not source_items:
            source_items = fallbacks
        cards = []
        for item in source_items[:8]:
            name = _first_nonempty([
                item.get("class_name"),
                item.get("name"),
                item.get("table_name"),
            ], "Component")
            package = _first_nonempty([item.get("package"), item.get("files")], "Detected from repository")
            role = _first_nonempty([item.get("responsibility"), item.get("description")], "Repository component")
            methods = _coerce_list(item.get("methods")) or ["See source code"]
            fields = _coerce_list(item.get("fields")) or [{"name": "(detected from source)", "type": _first_nonempty([item.get("type"), item.get("role")], "Component")}]
            field_html = "".join(
                "<div class=\"class-field\">"
                f"<span class=\"fname\">{_escape(_stringify(field.get('name')) if isinstance(field, dict) else _stringify(field))}</span>"
                f"<span class=\"ftype\">{_escape(_stringify(field.get('type')) if isinstance(field, dict) else 'field')}</span>"
                "</div>"
                for field in fields[:4]
            )
            method_html = "".join(
                "<div class=\"class-field\">"
                f"<span class=\"fname\">{_escape(_stringify(method.get('name')) if isinstance(method, dict) else _stringify(method))}</span>"
                f"<span class=\"ftype\">{_escape(_stringify(method.get('type')) if isinstance(method, dict) else 'method')}</span>"
                "</div>"
                for method in methods[:4]
            )
            cards.append(
                "<div class=\"class-card\">"
                f"<div class=\"class-card-head\"><span>Entity / Program</span>{_escape(name)}</div>"
                f"<div class=\"class-card-sub\">{_escape(package)}</div>"
                f"<p>{_escape(role)}</p>"
                "<div class=\"class-section-title\">Attributes</div>"
                f"{field_html}"
                "<div class=\"class-section-title\">Methods / Operations</div>"
                f"{method_html}"
                "</div>"
            )
        return f"<div class=\"class-grid\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No class inventory is available.</p>"

    def _render_sequence_cards(sequences: List[Dict[str, Any]]) -> str:
        cards = []
        for sequence in sequences:
            steps_html = "".join(
                f"<div class=\"sequence-step\"><span>{index:02d}</span>{_escape(step)}</div>"
                for index, step in enumerate(sequence.get("steps", []), start=1)
            )
            cards.append(
                "<div class=\"sequence-card\">"
                f"<div class=\"sequence-title\">{_escape(sequence.get('title', 'Sequence'))}</div>"
                f"<p>{_escape(sequence.get('summary', 'Repository interaction sequence inferred from code analysis.'))}</p>"
                f"{steps_html}"
                "</div>"
            )
        return "".join(cards) or "<p class=\"muted\">No sequence flows are available.</p>"

    def _render_integration_cards(items: List[Dict[str, str]], direction: str) -> str:
        cards = []
        for item in items:
            cards.append(
                f"<div class=\"integration-card {'outbound' if direction.lower().startswith('out') else ''}\">"
                f"<div class=\"integration-tag\">{_escape(direction)} - {_escape(_first_nonempty([item.get('protocol'), item.get('technology')], 'Service'))}</div>"
                f"<div class=\"integration-title\">{_escape(_first_nonempty([item.get('name'), item.get('endpoint')], 'Integration'))}</div>"
                "<div class=\"integration-meta\">"
                f"<div class=\"integration-meta-row\"><span>Technology:</span>{_escape(_first_nonempty([item.get('protocol'), item.get('technology')], 'HTTP / Service'))}</div>"
                f"<div class=\"integration-meta-row\"><span>Format:</span>{_escape(_first_nonempty([item.get('format')], 'JSON / Structured Payload'))}</div>"
                f"<div class=\"integration-meta-row\"><span>Endpoint:</span>{_escape(_first_nonempty([item.get('endpoint')], 'Repository-defined interface'))}</div>"
                f"<div class=\"integration-meta-row\"><span>Notes:</span>{_escape(_first_nonempty([item.get('notes')], 'Integration contract inferred from repository analysis.'))}</div>"
                "</div>"
                f"<div class=\"integration-desc\">{_escape(_first_nonempty([item.get('purpose'), item.get('description')], 'Integration purpose captured from generated BRD payload.'))}</div>"
                "</div>"
            )
        return "".join(cards) if cards else "<p class=\"muted\">No integrations were captured.</p>"

    def _render_api_inventory(items: List[Dict[str, str]], grouped: Dict[str, List[Dict[str, str]]]) -> str:
        if not items:
            return "<p class=\"muted\">No API endpoints were detected.</p>"
        all_endpoints = []
        for endpoint in items:
            all_endpoints.append(
                "<div class=\"api-endpoint\">"
                f"<span class=\"method-badge method-{_escape(endpoint['method'].lower())}\">{_escape(endpoint['method'])}</span>"
                f"<span class=\"api-path\">{_escape(endpoint['endpoint'])}</span>"
                f"<div class=\"api-desc\">{_escape(endpoint['description'])}</div>"
                "</div>"
            )
        groups_html = []
        for group_name, group_items in list(grouped.items())[:5]:
            endpoints_html = []
            for endpoint in group_items[:6]:
                endpoints_html.append(
                    "<div class=\"api-endpoint compact\">"
                    f"<span class=\"method-badge method-{_escape(endpoint['method'].lower())}\">{_escape(endpoint['method'])}</span>"
                    f"<span class=\"api-path\">{_escape(endpoint['endpoint'])}</span>"
                    f"<div class=\"api-desc\">{_escape(endpoint['description'])}</div>"
                    "</div>"
                )
            groups_html.append(
                "<div class=\"api-group\">"
                f"<div class=\"api-group-title\">{_escape(group_name)}</div>"
                f"{''.join(endpoints_html)}"
                "</div>"
            )
        return (
            "<div class=\"api-group\">"
            f"<div class=\"api-group-title\">Complete API Inventory ({len(items)} endpoints)</div>"
            f"{''.join(all_endpoints)}"
            "</div>"
            f"{''.join(groups_html)}"
        )

    def _render_glossary_cards(items: Any) -> str:
        cards = []
        for item in _coerce_list(items):
            if not isinstance(item, dict):
                continue
            cards.append(
                "<div class=\"glossary-item\">"
                f"<div class=\"glossary-term\">{_escape(item.get('term', 'Term'))}</div>"
                f"<div class=\"glossary-def\">{_escape(_stringify(item.get('definition')) or 'Definition not available.')}</div>"
                "</div>"
            )
        return f"<div class=\"glossary-grid\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No glossary terms are available.</p>"

    def _render_file_table(items: List[Dict[str, str]], empty_message: str, limit: Optional[int] = None) -> str:
        rows = []
        for item in items[:limit] if limit else items:
            rows.append(
                "<tr>"
                f"<td>{_escape(item.get('path', 'N/A'))}</td>"
                f"<td>{_escape(item.get('category', 'file'))}</td>"
                f"<td>{_escape(item.get('note', 'Detected from repository analysis.'))}</td>"
                "</tr>"
            )
        if not rows:
            return f"<p class=\"muted\">{_escape(empty_message)}</p>"
        return (
            "<table class=\"brd-table\">"
            "<thead><tr><th style=\"width:42%\">Path</th><th style=\"width:18%\">Category</th><th>Notes</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def _render_people_cards(items: List[Dict[str, str]]) -> str:
        cards = []
        for item in items:
            cards.append(
                "<div class=\"person-card\">"
                f"<div class=\"person-role\">{_escape(item.get('role', 'Owner'))}</div>"
                f"<div class=\"person-name\">{_escape(item.get('name', 'To Be Assigned'))}</div>"
                f"<div class=\"person-notes\">{_escape(item.get('notes', 'Coordinate ownership during delivery planning.'))}</div>"
                "</div>"
            )
        return f"<div class=\"people-grid\">{''.join(cards)}</div>" if cards else "<p class=\"muted\">No ownership entries are available.</p>"

    info = document.get("document_info", {}) if isinstance(document.get("document_info"), dict) else {}
    repo_short_name = repo_name.split("/", 1)[-1] if "/" in repo_name else repo_name
    repo_display_name = repo_short_name.upper()
    build_tool = info.get("build_tool") or analysis_data.get("build_tool") or "unknown"
    java_version = info.get("java_version") or analysis_data.get("java_version") or analysis_data.get("java_version_from_build") or "unknown"
    frameworks = _coerce_list(info.get("frameworks") or analysis_data.get("detected_frameworks") or [])
    generated_at = info.get("generated_at") or datetime.now().isoformat()
    dependencies = _coerce_list(analysis_data.get("dependencies", []))
    all_files = _coerce_list(analysis_data.get("all_files", []))
    vulnerable_deps = _coerce_list(analysis_data.get("vulnerable_dependencies", []))
    tech_stack = _coerce_list(document.get("tech_stack", []))
    modules = _coerce_list(document.get("modules", []))
    use_cases = _coerce_list(document.get("use_cases", []))
    risks = _coerce_list(document.get("risks", []))
    glossary = _coerce_list(document.get("glossary", []))
    db_tables = _coerce_list(document.get("db_tables", []))
    capabilities = _coerce_list(document.get("capabilities", []))
    languages = _coerce_list(document.get("languages", []))
    dependency_risks = _coerce_list(document.get("dependency_risks", []))
    class_inventory = _coerce_list(document.get("class_inventory", []))
    external_api_calls = _coerce_list(document.get("external_api_calls", []))
    scope_in = _coerce_list(document.get("scope_in", []))
    scope_out = _coerce_list(document.get("scope_out", []))

    normalized_endpoints = [
        endpoint
        for endpoint in (_normalize_endpoint(item) for item in _coerce_list(document.get("api_endpoints", [])))
        if endpoint
    ]
    endpoint_groups = _group_endpoints(normalized_endpoints)

    try:
        generated_display = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).strftime("%B %d, %Y")
    except ValueError:
        generated_display = str(generated_at).replace("T", " ")

    total_programs = _stringify(document.get("total_programs")) or _stringify(len(all_files))
    total_loc = _stringify(document.get("total_loc")) or _stringify(sum(_safe_int(lang.get("loc", 0)) for lang in languages if isinstance(lang, dict)))
    orphan_files = _stringify(document.get("orphan_files")) or "0"
    primary_language = _stringify(languages[0].get("language")) if languages and isinstance(languages[0], dict) else "Java"
    processing_modes = "Online / Batch" if normalized_endpoints else "Batch / Service"
    platform = "JVM / Cloud" if java_version != "unknown" else "Managed Runtime"

    module_names = [
        _first_nonempty([item.get("name")], "")
        for item in modules
        if isinstance(item, dict) and _first_nonempty([item.get("name")], "")
    ]
    capability_names = [
        _first_nonempty([item.get("name")], "")
        for item in capabilities
        if isinstance(item, dict) and _first_nonempty([item.get("name")], "")
    ]
    class_names = [
        _first_nonempty([item.get("class_name"), item.get("name")], "")
        for item in class_inventory
        if isinstance(item, dict) and _first_nonempty([item.get("class_name"), item.get("name")], "")
    ]
    table_names = [
        _first_nonempty([item.get("table_name"), item.get("name")], "")
        for item in db_tables
        if isinstance(item, dict) and _first_nonempty([item.get("table_name"), item.get("name")], "")
    ]

    controller_names = [name for name in class_names if "controller" in name.lower()]
    service_names = [name for name in class_names if "service" in name.lower()]
    repository_names = [name for name in class_names if any(token in name.lower() for token in ["repository", "dao", "client"])]
    entity_names = [name for name in class_names if any(token in name.lower() for token in ["entity", "model", "dto", "response", "request"])]
    external_names = [
        _first_nonempty([item.get("name"), item.get("endpoint")], "")
        for item in external_api_calls
        if isinstance(item, dict) and _first_nonempty([item.get("name"), item.get("endpoint")], "")
    ]

    actors = ["API Consumer", "Operations", "Support / Admin"] if normalized_endpoints else ["Developer", "Operations", "Support / Admin"]
    presentation_layer = controller_names[:3] or [item["endpoint"] for item in normalized_endpoints[:3]] or ["Presentation Layer", "Entry Controller"]
    business_layer = service_names[:3] or capability_names[:3] or module_names[:3] or ["Business Service", "Rules Engine"]
    data_access_layer = repository_names[:3] or ["Repository Layer", "Configuration Store", "Cache Manager"]
    data_layer = table_names[:3] or entity_names[:3] or ["Application Data", "File Storage"]
    external_layer = external_names[:3] or frameworks[:3] or ["CI / CD", "Monitoring", "External API"]

    architecture_rows = [
        ("s-actor", "Actors / Users", actors),
        ("s-ui", "Presentation Layer", presentation_layer),
        ("s-biz", "Application / Business Logic Layer", business_layer),
        ("s-data-access", "Data Access Layer", data_access_layer),
        ("s-data", "Data Layer", data_layer),
        ("s-ext", "External Integrations", external_layer),
    ]

    app_flow_steps = [
        {"name": actors[0], "desc": "A request or scheduled invocation starts the application flow."},
        {"name": presentation_layer[0], "desc": "Input is validated and routed to the application boundary."},
        {"name": business_layer[0], "desc": "Core business rules and orchestration are applied."},
        {"name": data_layer[0], "desc": "State is persisted, retrieved, or transformed as needed."},
        {"name": "Response / Outcome", "desc": "The final result is returned to the caller or downstream process."},
    ]

    use_case_flows = []
    for item in use_cases[:5]:
        if not isinstance(item, dict):
            continue
        use_case_flows.append({
            "title": _first_nonempty([item.get("name"), item.get("id")], "Use Case"),
            "steps": _split_steps(item.get("main_flow"))[:5] or ["Initiate request", "Process business rules", "Return result"],
            "summary": _first_nonempty([item.get("post_condition")], "Outcome captured from generated BRD payload."),
        })

    if not use_case_flows:
        use_case_flows = [
            {
                "title": f"Build and Validate {repo_short_name}",
                "steps": ["Clone repository", f"Resolve {build_tool} dependencies", "Execute build", "Validate outputs"],
                "summary": "Primary maintenance flow inferred from repository analysis.",
            }
        ]

    sequence_flows = [
        {
            "title": "Inbound Request Sequence",
            "summary": "Sequence showing how requests move through the application boundary and service layers.",
            "steps": [step["name"] for step in app_flow_steps[:4]],
        },
        {
            "title": "Delivery / Maintenance Sequence",
            "summary": "Sequence showing how engineers update, validate, and release the application safely.",
            "steps": ["Engineer updates module", f"{build_tool.title()} resolves dependencies", "Tests / checks execute", "Artifact is published or deployed"],
        },
    ]

    inbound_integrations = []
    if normalized_endpoints:
        inbound_integrations.append({
            "name": "Client API Requests",
            "protocol": "REST / HTTP",
            "format": "JSON",
            "endpoint": normalized_endpoints[0]["endpoint"],
            "purpose": "Inbound requests enter the application through repository-detected endpoints.",
            "notes": "Authentication, validation, and routing occur before business execution.",
        })
    inbound_integrations.append({
        "name": "Build / Platform Inputs",
        "protocol": build_tool.title(),
        "format": "Configuration / Source",
        "endpoint": repo_url or repo_name,
        "purpose": "Build pipelines and maintainers provide source, configuration, and deployment instructions.",
        "notes": "Supports repeatable engineering workflows across environments.",
    })

    outbound_integrations = []
    for item in external_api_calls[:3]:
        if not isinstance(item, dict):
            continue
        outbound_integrations.append({
            "name": _first_nonempty([item.get("name"), item.get("endpoint")], "External Service"),
            "protocol": _first_nonempty([item.get("protocol"), item.get("technology")], "HTTP / Service"),
            "format": _first_nonempty([item.get("format")], "JSON"),
            "endpoint": _first_nonempty([item.get("endpoint")], "Repository-defined endpoint"),
            "purpose": _first_nonempty([item.get("purpose"), item.get("description")], "Outbound integration captured from repository analysis."),
            "notes": _first_nonempty([item.get("notes")], "Validate contract and error handling with application owners."),
        })
    if not outbound_integrations:
        outbound_integrations.append({
            "name": "External Services / Tooling",
            "protocol": "HTTP / Integration",
            "format": "JSON / Structured Payload",
            "endpoint": "Repository-defined external touchpoints",
            "purpose": "Outbound calls, data exchange, or operational hooks inferred from dependencies and modules.",
            "notes": "Confirm external contracts during detailed design.",
        })

    file_rows = []
    for entry in all_files:
        if isinstance(entry, dict):
            path = _first_nonempty([entry.get("path"), entry.get("name")], "")
        else:
            path = str(entry)
        if not path:
            continue
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "file"
        file_rows.append({
            "path": path,
            "category": _titleize(ext),
            "note": "Repository source asset",
        })

    orphan_rows = []
    for row in file_rows:
        lower = row["path"].lower()
        if any(token in lower for token in ["test", "spec", "example", "sample"]):
            orphan_rows.append({
                "path": row["path"],
                "category": row["category"],
                "note": "Review whether this file participates in production runtime paths.",
            })

    security_checklist = [
        "Authentication and authorization model are documented and validated.",
        f"Dependency posture reviewed for {len(vulnerable_deps)} known vulnerable findings.",
        "Secrets, tokens, and environment-specific configuration are externalized.",
        "Audit logging and operational observability paths are identified.",
    ]
    acceptance_criteria = [
        f"{build_tool.title()} build completes successfully on Java {java_version}.",
        "Primary repository modules and use cases are represented in the technical baseline.",
        "Detected APIs, data stores, and risks are reviewable by engineering stakeholders.",
        "Document output is suitable for onboarding and modernization planning workshops.",
    ]
    known_limitations = [
        "Static analysis cannot fully replace runtime validation and business walkthroughs.",
        "External integration contracts may require confirmation from system owners.",
        "Entity relationships may be inferred when explicit schema artifacts are unavailable.",
    ]

    support_channels = [
        {"role": "Engineering Support", "name": "Repository Maintainers", "notes": "First stop for module ownership, defects, and repository changes."},
        {"role": "Build / Release", "name": f"{build_tool.title()} Pipeline Owners", "notes": "Coordinate build failures, dependency updates, and release automation."},
        {"role": "Security / Compliance", "name": "Application Security Team", "notes": "Review vulnerability posture, secrets handling, and compliance gates."},
    ]
    go_to_people = [
        {"role": "Application Owner", "name": repo_short_name, "notes": "Primary business and technical context owner for this repository."},
        {"role": "API / Integration Lead", "name": presentation_layer[0], "notes": "Owns interface behavior, contract reviews, and integration questions."},
        {"role": "Data / Domain Lead", "name": data_layer[0], "notes": "Owns entity structure, data quality assumptions, and persistence concerns."},
        {"role": "Delivery Lead", "name": business_layer[0], "notes": "Coordinates implementation sequencing, rollout, and acceptance readiness."},
    ]

    cover_meta_left = "".join([
        f"<div class=\"cover-meta-row\"><span>Repository</span><span>{_escape(repo_name)}</span></div>",
        f"<div class=\"cover-meta-row\"><span>Document Type</span><span>Technical Document</span></div>",
        f"<div class=\"cover-meta-row\"><span>Generated</span><span>{_escape(generated_display)}</span></div>",
        f"<div class=\"cover-meta-row\"><span>Repository URL</span><span>{_escape(repo_url or 'N/A')}</span></div>",
    ])
    cover_meta_right = "".join([
        f"<div class=\"cover-meta-row\"><span>Build Tool</span><span>{_escape(build_tool.title())}</span></div>",
        f"<div class=\"cover-meta-row\"><span>Java Version</span><span>{_escape(java_version)}</span></div>",
        f"<div class=\"cover-meta-row\"><span>Dependencies</span><span>{_escape(str(len(dependencies)))}</span></div>",
        f"<div class=\"cover-meta-row\"><span>API Endpoints</span><span>{_escape(str(len(normalized_endpoints)))}</span></div>",
    ])

    chapters = [
        ("ch1", "Introduction"),
        ("ch2", "Purpose and Scope"),
        ("ch3", "Business Functionality / Key Features"),
        ("ch4", "High-Level Architecture"),
        ("ch5", "Technical Stack & Technologies"),
        ("ch6", "Data Management Overview"),
        ("ch7", "Database Schema & ER Diagram"),
        ("ch8", "Process Overview (Online & Batch)"),
        ("ch9", "Application Flow & User Journey"),
        ("ch10", "Use Case Specifications"),
        ("ch11", "Object / Class Model"),
        ("ch12", "Activity & Process Flows"),
        ("ch13", "Sequence Diagrams"),
        ("ch14", "Integration Points"),
        ("ch15", "API Design & Specification"),
        ("ch16", "Non Functional Requirements"),
        ("ch17", "Current Risks / Challenges"),
        ("ch18", "Repository File-by-File Guide"),
        ("ch19", "Security, Acceptance & Limitations"),
        ("ch20", "Support"),
        ("ch21", "Go to Person"),
        ("ch22", "Glossary of Terms and Acronyms"),
        ("ch23", "References and Appendices"),
    ]

    disclaimer_page = (
        "<div class=\"org-logo-bar\">"
        "<div class=\"org-logo-circle\">TD</div>"
        "<div class=\"org-logo-name\">Application Modernization Baseline</div>"
        "</div>"
        "<div class=\"disclaimer-block\">"
        "This document is an automatically generated repository baseline intended to support modernization discovery, "
        "architecture review, and delivery planning. The analysis reflects the repository contents available at generation time "
        "and should be validated against runtime and business context before delivery commitments are made."
        "</div>"
        f"<div class=\"disclaimer-doc-title\">{_escape(repo_display_name)} - TECHNICAL DOCUMENT</div>"
        "<div class=\"section-label\">Document Control</div>"
        + _render_kv_table([
            ("Repository", repo_name),
            ("Repository URL", repo_url or "N/A"),
            ("Build Tool", build_tool),
            ("Java Version", java_version),
            ("Frameworks", frameworks),
            ("Generated On", generated_display),
        ], table_class="update-table")
        + "<div class=\"section-label\">Reference Notes</div>"
        + _render_kv_table([
            ("Purpose", "Establish a high-confidence technical baseline for analysis, migration planning, and onboarding."),
            ("Source", "Derived from repository metadata, dependency inspection, structural enrichment, and generated BRD payload."),
            ("Audience", "Engineering leads, modernization teams, solution architects, and delivery stakeholders."),
        ])
    )

    cover_page = (
        "<div class=\"cover-header\">"
        "<div class=\"cover-logo-bar\">"
        "<div class=\"cover-logo-circle\">TD</div>"
        "<div class=\"cover-logo-name\">Technical Baseline</div>"
        "</div>"
        "<div class=\"cover-title-block\">"
        "<div class=\"cover-doc-type\">Application Overview Document for Modernization</div>"
        f"<div class=\"cover-title\">{_escape(repo_display_name)}</div>"
        "<div class=\"cover-subtitle\">Repository-driven technical baseline and modernization document</div>"
        "</div>"
        "</div>"
        "<div class=\"cover-body\">"
        "<div class=\"cover-meta-group\">"
        "<h4>Document</h4>"
        f"{cover_meta_left}"
        "</div>"
        "<div class=\"cover-meta-group\">"
        "<h4>Platform</h4>"
        f"{cover_meta_right}"
        "</div>"
        "<div class=\"cover-stack\">"
        "<h4>Technology Stack</h4>"
        f"<div class=\"tech-pills\">{_render_pills(frameworks, fallback=[primary_language, build_tool.title(), 'REST'])}</div>"
        "</div>"
        "</div>"
        "<div class=\"cover-footer\">"
        f"<span>{_escape(generated_display)} - {_escape(repo_short_name)} - For Internal Use Only</span>"
        "<span class=\"confidential\">Confidential</span>"
        "</div>"
    )

    intro_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 1</div>"
        "<div class=\"ch-title\">Introduction</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Purpose of the document and application purpose</div>"
        "</div>"
        "<h2>1.1 Purpose of the Document</h2>"
        + _render_text(
            "This document provides a comprehensive technical overview of the application, covering its architecture, "
            f"{len(dependencies)} dependencies, data flows, interface surfaces, and delivery posture. It is intended for architects, "
            "developers, migration teams, and business stakeholders involved in modernization planning."
        )
        + "<h2>1.2 Application Purpose</h2>"
        + _render_text(document.get("executive_summary", ""))
        + "<div class=\"callout info\"><strong>Modernization Note</strong> This document is optimized for repository-first assessment and should be validated with runtime and business owners before final commitments are made.</div>"
        + "<h2>Application at a Glance</h2>"
        + _render_kv_table([
            ("Application Name", repo_short_name),
            ("Repository", repo_name),
            ("Primary Language", primary_language),
            ("Platform / OS", platform),
            ("Processing Modes", processing_modes),
            ("Total Programs", total_programs),
            ("Total LOC", total_loc or "0"),
            ("Orphan Files", orphan_files),
        ], table_class="brd-table")
    )

    scope_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 2</div>"
        "<div class=\"ch-title\">Purpose and Scope</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Detailed purpose, objectives, and scope boundaries</div>"
        "</div>"
        "<h2>2.1 Detailed Purpose</h2>"
        + _render_text(
            f"The {repo_short_name} application is currently baselined as a {primary_language}-centric codebase built with "
            f"{build_tool}. This document consolidates {len(all_files)} detected files, {len(dependencies)} dependencies, "
            f"{len(modules)} modules, and {len(normalized_endpoints)} API endpoints into a delivery-friendly modernization narrative."
        )
        + "<h2>2.2 Business Objectives</h2>"
        + _render_objectives(document.get("business_objectives", []))
        + "<h2>2.3 Scope</h2>"
        + "<div class=\"scope-grid\">"
        + _render_scope(scope_in, "In Scope", "in-scope")
        + _render_scope(scope_out, "Out of Scope", "out-scope")
        + "</div>"
    )

    functionality_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 3</div>"
        "<div class=\"ch-title\">Business Functionality / Key Features</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Capability-by-capability overview, key features, and module signals</div>"
        "</div>"
        "<h2>3.1 Capability Overview</h2>"
        + _render_capabilities(capabilities)
        + "<h2>3.2 Module Inventory</h2>"
        + _render_object_table(modules, [
            ("Module", "name", "width:24%"),
            ("Description", "description"),
            ("Files / Path", "files", "width:24%"),
        ])
        + "<h2>3.3 Functional Notes</h2>"
        + _render_module_cards(modules[:6])
    )

    architecture_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 4</div>"
        "<div class=\"ch-title\">High-Level Architecture</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Architectural layers, design patterns, and component relationships</div>"
        "</div>"
        + _render_text(f"The {repo_short_name} application follows a layered architecture pattern derived from repository structure, class inventory, and integration signals.")
        + _render_architecture_diagram(architecture_rows)
        + "<h2>4.1 CBID</h2>"
        + _render_kv_table([
            ("Layering Pattern", "Presentation, business, data access, and data responsibilities are separated across repository components."),
            ("Dependency Strategy", f"Build orchestration and dependency management are handled through {build_tool}."),
            ("Integration Approach", "Request / response interfaces and external service interactions are represented through controllers, clients, and repositories."),
        ], table_class="brd-table")
        + "<h2>4.2 Business Flow Overview</h2>"
        + _render_text("Business flow begins at the application boundary, is processed through repository-defined business services, and completes with persisted state and downstream responses.")
    )

    stack_tech_summary = tech_stack[:5]
    stack_tech_inventory_pages = [
        tech_stack[index:index + 26]
        for index in range(5, len(tech_stack), 26)
    ]
    stack_db_summary = [
        {"technology": name, "type": "Data Store", "usage": "Inferred persistence entity or storage concern."}
        for name in (table_names[:4] or ["Application Data Store"])
    ]
    stack_metrics = [
        ("Core Technologies", len(tech_stack) or "N/A"),
        ("Languages", len(languages) or "N/A"),
        ("Frameworks", frameworks[:3] if frameworks else "Repository-detected stack"),
        ("Data Stores", len(table_names) or "Inferred"),
    ]
    stack_page_primary = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 5</div>"
        "<div class=\"ch-title\">Technical Stack<br>&amp; Technologies</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Programming languages, runtime signals, data stores, tooling, and operating posture</div>"
        "</div>"
        "<div class=\"stack-lead\">"
        + _render_text(
            f"This page provides the high-level platform snapshot for {repo_short_name}: the primary runtime, core technologies, "
            "language mix, and the main data-facing signals detected from the repository."
        )
        + "</div>"
        + _render_metric_grid(stack_metrics, grid_class="metric-grid stack-metric-grid")
        + "<div class=\"stack-section\">"
        + "<h2>5.0 Core Technologies</h2>"
        + "<p class=\"stack-note\">This summary highlights the main platform and framework technologies first. The full detected inventory is split across the following Chapter 5 continuation pages.</p>"
        + _render_object_table(stack_tech_summary, [
            ("Category", "category", "width:18%"),
            ("Technology", "technology", "width:24%"),
            ("Version", "version", "width:14%"),
            ("Purpose", "purpose"),
        ], table_class="brd-table stack-compact-table", empty_message="No technology stack entries were generated.")
        + "</div>"
        + "<div class=\"stack-dual-grid\">"
        + "<div class=\"stack-section stack-panel\">"
        + "<h2>5.1 Programming Languages</h2>"
        + _render_object_table(languages, [
            ("Language", "language", "width:24%"),
            ("Programs", "programs", "width:14%"),
            ("LOC", "loc", "width:14%"),
            ("Usage / Notes", "notes"),
        ], table_class="brd-table stack-compact-table", empty_message="Language statistics are not available.")
        + "</div>"
        + "<div class=\"stack-section stack-panel\">"
        + "<h2>5.2 Online Environment</h2>"
        + _render_kv_table([
            ("Runtime", f"Java {java_version}"),
            ("Platform", platform),
            ("Processing Modes", processing_modes),
            ("Primary Frameworks", frameworks or ["Repository-detected frameworks"]),
        ], table_class="brd-table")
        + "<div class=\"stack-mini-callout\">"
        + "<strong>Environment Note</strong>"
        + "<p>The runtime and platform entries shown here reflect repository-level signals. Validate deployment topology and hosting assumptions against the live environment.</p>"
        + "</div>"
        + "</div>"
        + "</div>"
    )

    stack_inventory_pages = []
    for inventory_index, inventory_items in enumerate(stack_tech_inventory_pages, start=1):
        stack_inventory_pages.append(
            "<div class=\"ch-header ch-header-continued\">"
            "<div class=\"ch-header-left\">"
            "<div class=\"ch-num\">Chapter 5 Continued</div>"
            "<div class=\"ch-title\">Technical Stack<br>&amp; Technologies</div>"
            "</div>"
            f"<div class=\"ch-subtitle\">Detailed technology inventory - part {inventory_index}</div>"
            "</div>"
            + "<div class=\"stack-section stack-section-last\">"
            + f"<h2>Detailed Technology Inventory {inventory_index}</h2>"
            + _render_object_table(inventory_items, [
                ("Category", "category", "width:18%"),
                ("Technology", "technology", "width:24%"),
                ("Version", "version", "width:14%"),
                ("Purpose", "purpose"),
            ], table_class="brd-table stack-inventory-table", empty_message="No additional technology entries were detected.")
            + "</div>"
        )

    stack_page_operations = (
        "<div class=\"ch-header ch-header-continued\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 5 Continued</div>"
        "<div class=\"ch-title\">Technical Stack<br>&amp; Technologies</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Data, job orchestration, scheduling, and middleware continuation</div>"
        "</div>"
        + "<div class=\"stack-section\">"
        + "<h2>5.3 Databases / File Systems</h2>"
        + _render_object_table(
            stack_db_summary,
            [("Technology", "technology", "width:28%"), ("Type", "type", "width:18%"), ("Usage", "usage")],
            table_class="brd-table stack-compact-table",
            empty_message="No database or file system artifacts were detected.",
        )
        + "</div>"
        + "<div class=\"stack-section\">"
        + "<h2>5.4 Job Control</h2>"
        + _render_text(f"{build_tool.title()} serves as the primary job control and orchestration mechanism for the repository's build, packaging, and validation lifecycle.")
        + "</div>"
        + "<div class=\"stack-section\">"
        + "<h2>5.5 Job Scheduling</h2>"
        + _render_text("Job scheduling is represented through repository-defined automation, background processing hooks, or environment-level orchestration. Validate runtime schedules with application owners.")
        + "</div>"
        + "<div class=\"stack-section\">"
        + "<h2>5.6 Middleware / Messaging</h2>"
        + _render_kv_table([
            ("Application Framework", _first_nonempty(frameworks, "Repository-defined framework stack")),
            ("Integration Pattern", "Request / response and service-based integrations"),
            ("Configuration Backbone", "Source-controlled configuration plus runtime environment inputs"),
        ], table_class="brd-table stack-compact-table")
        + "</div>"
    )

    stack_page_platform = (
        "<div class=\"ch-header ch-header-continued\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 5 Continued</div>"
        "<div class=\"ch-title\">Technical Stack<br>&amp; Technologies</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Security posture, support tooling, and platform continuation</div>"
        "</div>"
        + "<div class=\"stack-section\">"
        + "<h2>5.7 Security Framework</h2>"
        + _render_text("Security controls are inferred from dependency posture, repository structure, and API surfaces. Validate authentication, authorization, and secrets handling against runtime architecture.")
        + "</div>"
        + "<div class=\"stack-section\">"
        + "<h2>5.8 Development & Support Tools</h2>"
        + _render_kv_table([
            (build_tool.title(), "Primary build and validation automation"),
            ("Git", "Version control and repository collaboration"),
            ("CI / CD", "Pipeline-driven quality checks, packaging, and release support"),
        ], table_class="brd-table stack-compact-table")
        + "</div>"
        + "<div class=\"stack-section stack-section-last\">"
        + "<h2>5.9 Operating System</h2>"
        + _render_text("The application is designed for cross-environment execution through its managed runtime and repository-controlled build chain. Confirm production OS and containerization assumptions during deployment planning.")
        + "</div>"
    )

    data_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 6</div>"
        "<div class=\"ch-title\">Data Management Overview</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Data entities, high-level data flow, and repository dependencies</div>"
        "</div>"
        "<h2>6.1 Data Entities / Stores</h2>"
        + _render_db_tables(db_tables)
        + "<h2>6.2 Data Flow (High-Level)</h2>"
        + "<h4 class=\"sub\">Data Entry Points</h4>"
        + _render_bullet_list([endpoint["endpoint"] for endpoint in normalized_endpoints[:4]] or ["Configuration files", "Batch inputs", "Repository-managed interfaces"], css_class="bullet-list")
        + "<h4 class=\"sub\">Data Processing Workflows</h4>"
        + _render_bullet_list([
            "Business logic transformation",
            "Validation and sanitization",
            "Persistence and retrieval orchestration",
        ], css_class="bullet-list")
        + "<h4 class=\"sub\">Data Exit Points</h4>"
        + _render_bullet_list([
            "API response payloads",
            "Database persistence",
            "Operational logs / audit outputs",
        ], css_class="bullet-list")
        + "<h2>6.3 Data Dependencies</h2>"
        + "<div class=\"callout\"><strong>Critical Dependencies</strong>"
        + _render_bullet_list([
            "Configuration and secrets availability",
            "Repository-defined data stores and file system access",
            "External services required by core business workflows",
        ], css_class="bullet-list compact")
        + "</div>"
    )

    relationship_rows = []
    for index, child in enumerate(table_names[1:5], start=1):
        relationship_rows.append({
            "parent": table_names[0],
            "child": child,
            "relationship": "1:N" if index % 2 else "1:1",
        })
    if not relationship_rows and table_names:
        relationship_rows.append({"parent": table_names[0], "child": table_names[0], "relationship": "self / inferred"})

    schema_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 7</div>"
        "<div class=\"ch-title\">Database Schema<br>&amp; ER Diagram</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Entity relationship model, table definitions, and key relationships</div>"
        "</div>"
        + _render_text(f"Entity-relationship model derived from {repo_short_name} code analysis.")
        + "<h2>7.0 Entity / Table Overview</h2>"
        + _render_bullet_list([
            f"{table.get('table_name', 'table')}: " + ", ".join(
                _stringify(field.get("name"))
                for field in _coerce_list(table.get("fields"))
                if isinstance(field, dict) and _stringify(field.get("name"))
            )
            for table in db_tables[:8]
            if isinstance(table, dict)
        ], empty_message="No entity summaries were generated.")
        + _render_db_tables(db_tables)
        + f"<div class=\"er-fig-caption\">Figure 7.1 - {_escape(repo_short_name)} Entity Relationship Diagram</div>"
        + "<h2>7.1 Key Relationships</h2>"
        + _render_object_table(relationship_rows, [
            ("Parent Table", "parent", "width:30%"),
            ("Child Table", "child", "width:30%"),
            ("Relationship", "relationship"),
        ], empty_message="No key relationships were inferred.")
    )

    online_process_rows = [
        {
            "txn": endpoint["method"],
            "module": endpoint["endpoint"],
            "description": endpoint["description"],
        }
        for endpoint in normalized_endpoints[:6]
    ]
    batch_cycle_rows = [
        {"cycle": "Build / CI", "jobs": f"{build_tool.title()} pipeline", "purpose": "Compile, validate, and package the application."},
        {"cycle": "Scheduled Maintenance", "jobs": "Background jobs / automation", "purpose": "Runtime housekeeping and synchronization activities inferred from repository structure."},
        {"cycle": "Operational Monitoring", "jobs": "Health / metrics / logs", "purpose": "Maintain runtime visibility and release confidence."},
    ]

    process_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 8</div>"
        "<div class=\"ch-title\">Process Overview<br>(Online &amp; Batch)</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Online transactions, batch cycles, and scheduler responsibilities</div>"
        "</div>"
        "<h2>8.1 Online Processes</h2>"
        + _render_object_table(online_process_rows, [
            ("Transaction Code", "txn", "width:18%"),
            ("Program / Module", "module", "width:34%"),
            ("Description", "description"),
        ], empty_message="No online process endpoints were detected.")
        + "<h2>8.2 Batch Processes</h2>"
        + "<h4 class=\"sub\">Batch Cycles</h4>"
        + _render_object_table(batch_cycle_rows, [
            ("Cycle", "cycle", "width:22%"),
            ("Key Job(s)", "jobs", "width:28%"),
            ("Purpose", "purpose"),
        ], empty_message="No batch cycles were inferred.")
        + "<h4 class=\"sub\">Job Stream Dependencies</h4>"
        + "<div class=\"callout info\"><strong>Scheduler Note</strong><p>Job stream dependencies are managed through the repository build chain, environment orchestration, and runtime automation hooks. Confirm exact scheduling responsibilities with application owners.</p></div>"
    )

    application_flow_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 9</div>"
        "<div class=\"ch-title\">Application Flow<br>&amp; User Journey</div>"
        "</div>"
        "<div class=\"ch-subtitle\">User interactions, routing flow, and major application stages</div>"
        "</div>"
        "<h2>9.1 Key Transactions / Screen Flows</h2>"
        + _render_app_flow(app_flow_steps, f"{repo_short_name} Application Flow")
        + "<h2>9.2 Key Screen Flows</h2>"
        + "<h4 class=\"sub\">End-to-End Repository Flow</h4>"
        + _render_text("This flow describes how a caller or automation path enters the application boundary, executes business logic, interacts with data and integrations, and returns a final outcome.")
        + "<h4 class=\"sub\">Operational / Maintenance Flow</h4>"
        + _render_text("This flow highlights how engineers update, validate, and support the application through repository-driven automation, quality checks, and release preparation.")
        + "<h4 class=\"sub\">Security and Access Flow</h4>"
        + _render_text("This flow outlines how callers are authenticated, authorized, and safely routed before accessing protected functionality and downstream dependencies.")
    )

    use_case_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 10</div>"
        "<div class=\"ch-title\">Use Case<br>Specifications</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Actor interactions, preconditions, and use case specifications</div>"
        "</div>"
        + _render_use_case_cards(use_cases)
    )

    class_fallbacks = [
        {"name": name, "description": "Repository module or capability represented as a class-model fallback.", "files": name, "role": "Component"}
        for name in (class_names[:4] or module_names[:4] or capability_names[:4] or [repo_short_name])
    ]
    class_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 11</div>"
        "<div class=\"ch-title\">Object Model</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Object-oriented class inventory and repository components</div>"
        "</div>"
        + _render_text(f"Class inventory extracted from the {repo_short_name} codebase. Components are shown using repository-derived class and module signals.")
        + _render_class_cards(class_inventory, class_fallbacks)
    )

    activity_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 12</div>"
        "<div class=\"ch-title\">Activity &amp;<br>Process Flows</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Step-by-step workflow and activity flow analysis</div>"
        "</div>"
        + "".join(
            "<div class=\"sequence-card activity-card\">"
            f"<div class=\"sequence-title\">12.{index} {_escape(flow['title'])}</div>"
            f"<p>{_escape(flow['summary'])}</p>"
            + "".join(f"<div class=\"sequence-step\"><span>{step_index:02d}</span>{_escape(step)}</div>" for step_index, step in enumerate(flow["steps"], start=1))
            + "</div>"
            for index, flow in enumerate(use_case_flows[:3], start=1)
        )
    )

    sequence_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 13</div>"
        "<div class=\"ch-title\">Sequence Diagrams</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Interaction ordering between callers, services, data, and operations</div>"
        "</div>"
        + _render_sequence_cards(sequence_flows)
    )

    integration_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 14</div>"
        "<div class=\"ch-title\">Integration Points</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Inbound integrations, outbound integrations, and integration technologies</div>"
        "</div>"
        "<h2>14.1 Inbound Integrations</h2>"
        + _render_integration_cards(inbound_integrations, "Inbound")
        + "<h2>14.2 Outbound Integrations</h2>"
        + _render_integration_cards(outbound_integrations, "Outbound")
        + "<h2>14.3 Integration Technologies</h2>"
        + _render_kv_table([
            ("Request / Response", "Primary mechanism for API, service, and operational interactions."),
            ("Configuration Inputs", "Repository-managed configuration and environment-specific values."),
            ("Build / Deployment Automation", f"{build_tool.title()} and pipeline-driven release support."),
        ], table_class="brd-table")
    )

    api_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 15</div>"
        "<div class=\"ch-title\">API Design &amp;<br>Specification</div>"
        "</div>"
        "<div class=\"ch-subtitle\">RESTful API specification with endpoints, grouping, and descriptions</div>"
        "</div>"
        "<div class=\"callout info\"><strong>API Note</strong><p>API endpoints detected from repository source analysis are shown below and grouped by inferred functional area.</p></div>"
        + _render_api_inventory(normalized_endpoints, endpoint_groups)
    )

    nfr_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 16</div>"
        "<div class=\"ch-title\">Non Functional<br>Requirements</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Security, availability, performance, scalability, and compliance</div>"
        "</div>"
        "<h2>16.1 Security Overview</h2>"
        + "<h4 class=\"sub\">16.1.1 Authentication</h4>"
        + _render_bullet_list(["Repository-defined identity and access controls", "Token / credential validation at service boundaries", "Secrets externalization and environment isolation"], css_class="bullet-list")
        + "<h4 class=\"sub\">16.1.2 Authorization</h4>"
        + _render_bullet_list(["Least-privilege access to application features", "Role-based or policy-based authorization checks", "Restricted operational actions for privileged users"], css_class="bullet-list")
        + "<h4 class=\"sub\">16.1.3 Data Security</h4>"
        + _render_bullet_list(["Sensitive configuration managed outside source control", "Secure transport for external and internal integrations", "Auditability for critical operational actions"], css_class="bullet-list")
        + "<h2>16.2 Availability</h2>"
        + _render_text(f"Availability depends on repeatable {build_tool} builds, reliable startup behavior, and stable access to required integrations and configuration sources.")
        + "<h2>16.3 Performance</h2>"
        + _render_text("Performance expectations should preserve current business flows while modernization work is introduced incrementally. Validate runtime SLAs with production stakeholders.")
        + "<h2>16.4 Scalability &amp; Resilience</h2>"
        + _render_text("Scalability and resilience depend on stateless processing where possible, safe retry boundaries, and deployment/runtime topology that matches traffic and integration behavior.")
        + "<h2>16.5 Compliance</h2>"
        + _render_text("Compliance posture should be confirmed against organizational security standards, audit requirements, and any data-handling obligations that apply to the application domain.")
    )

    risk_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 17</div>"
        "<div class=\"ch-title\">Current Risks / Challenges</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Technical, operational, security, and maintenance concerns</div>"
        "</div>"
        "<h2>17.1 Technical Risks</h2>"
        + _render_object_table(risks, [
            ("Category", "category", "width:14%"),
            ("Title", "title", "width:24%"),
            ("Description", "description"),
            ("Mitigation", "mitigation"),
        ], empty_message="No technical risks were generated.")
        + "<h2>17.2 Dependency Risk Highlights</h2>"
        + _render_object_table(dependency_risks, [
            ("Dependency", "dependency", "width:28%"),
            ("Current", "current_version", "width:12%"),
            ("Target", "latest_version", "width:12%"),
            ("Risk", "risk_level", "width:10%"),
            ("Notes", "notes"),
        ], empty_message="No dependency-specific risk highlights were captured.")
    )

    repo_guide_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 18</div>"
        "<div class=\"ch-title\">Repository File-by-File Guide</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Module guide, representative paths, and repository orientation</div>"
        "</div>"
        "<h2>18.1 Module Guide</h2>"
        + _render_object_table(modules, [
            ("Area", "name", "width:22%"),
            ("Guide", "description"),
            ("Representative Path", "files", "width:24%"),
        ], empty_message="No repository guide entries are available.")
        + "<h2>18.2 Representative Repository Files</h2>"
        + _render_file_table(file_rows, "No repository files were available for listing.", limit=24)
    )

    security_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 19</div>"
        "<div class=\"ch-title\">Security, Acceptance &amp; Limitations</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Security checklist, acceptance criteria, and known limitations</div>"
        "</div>"
        "<h2>19.1 Security Checklist</h2>"
        + _render_bullet_list(security_checklist, css_class="bullet-list")
        + "<h2>19.2 Acceptance Criteria</h2>"
        + _render_bullet_list(acceptance_criteria, css_class="bullet-list")
        + "<h2>19.3 Known Limitations</h2>"
        + _render_bullet_list(known_limitations, css_class="bullet-list")
    )

    support_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 20</div>"
        "<div class=\"ch-title\">Support</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Support channels, ownership paths, and operational coordination</div>"
        "</div>"
        "<p>For support contacts, please refer to the ownership roles and module maintainers aligned to this repository baseline.</p>"
        "<h2>20.1 Support Channels</h2>"
        + _render_people_cards(support_channels)
        + "<h2>20.2 Escalation Matrix</h2>"
        + _render_kv_table([
            ("Priority 1", "Application owner and delivery lead"),
            ("Priority 2", "Build / release owners and module maintainers"),
            ("Priority 3", "Security / platform stakeholders as required"),
        ], table_class="brd-table")
    )

    goto_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 21</div>"
        "<div class=\"ch-title\">Go to Person</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Primary ownership roles for application, API, data, and delivery concerns</div>"
        "</div>"
        + _render_people_cards(go_to_people)
    )

    glossary_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 22</div>"
        "<div class=\"ch-title\">Glossary of Terms<br>and Acronyms</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Shared terminology used throughout the technical document</div>"
        "</div>"
        + _render_glossary_cards(glossary)
    )

    appendices_page = (
        "<div class=\"ch-header\">"
        "<div class=\"ch-header-left\">"
        "<div class=\"ch-num\">Chapter 23</div>"
        "<div class=\"ch-title\">References and Appendices</div>"
        "</div>"
        "<div class=\"ch-subtitle\">Complete file listing, orphan review, and generation summary</div>"
        "</div>"
        + f"<h2>23.1 Complete File Listing Used For Comprehension ({len(file_rows)} files)</h2>"
        + _render_file_table(file_rows, "No repository files were available for listing.", limit=60)
        + "<h2>23.2 Orphan Files by Category</h2>"
        + _render_file_table(orphan_rows, "No orphan-like files were inferred from repository patterns.", limit=30)
        + "<h2>23.3 Processing Summary</h2>"
        + _render_text(
            f"Based on the provided input documentation and data, this application overview document analyzes {len(all_files)} files, "
            f"{len(dependencies)} dependencies, {len(modules)} modules, {len(normalized_endpoints)} endpoints, and {len(db_tables)} data entities."
        )
        + "<h2>23.4 Revision History</h2>"
        + _render_kv_table([
            ("Version", "1.0"),
            ("Generated On", generated_display),
            ("Generated From", repo_name),
            ("Notes", "Expanded technical document structure aligned to the reference Technical-Document layout."),
        ], table_class="brd-table")
    )

    styles = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>"""
    styles += _escape(f"{repo_display_name} - TECHNICAL DOCUMENT")
    styles += """</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
@page {
  size: A4;
  margin: 0;
}
:root {
  --ink: #1a1a1a;
  --paper: #ffffff;
  --cream: #f5f5f4;
  --border: #d0d0d0;
  --muted: #555555;
  --page-w: 794px;
  --bg: #d4d4d4;
  --brand-dark: #1a1a2e;
  --brand-mid: #2d2d4e;
  --accent: #8f3d2e;
}
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 100%; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg);
  font-family: 'DM Mono', monospace;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.8;
  letter-spacing: 0.01em;
  min-height: 100vh;
}
a { color: inherit; }
code {
  background: #f1f1f3;
  border-radius: 4px;
  padding: 1px 4px;
  font-size: 11px;
}
p {
  color: #333;
  margin-bottom: 11px;
  font-size: 12.5px;
  line-height: 1.74;
}
h2 {
  font-family: 'Syne', sans-serif;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink);
  margin: 30px 0 12px;
  padding-bottom: 5px;
  border-bottom: 1px solid var(--border);
}
h3 {
  font-family: 'DM Serif Display', serif;
  font-size: 16px;
  margin: 20px 0 9px;
}
h4.sub {
  font-family: 'Syne', sans-serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 14px 0 7px;
}
.doc-wrapper {
  width: 100%;
  margin: 0 auto;
  padding: 56px 0 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.page {
  background: var(--paper);
  margin: 0 auto 28px auto;
  box-shadow: 0 6px 40px rgba(0,0,0,.17), 0 1px 4px rgba(0,0,0,.07);
  position: relative;
  overflow: hidden;
  width: var(--page-w);
  max-width: calc(100% - 40px);
  border-radius: 12px;
}
.page-inner {
  padding: 50px 60px;
  width: 100%;
  position: relative;
}
.page-anchor {
  position: relative;
  top: -8px;
  display: block;
  height: 0;
  width: 0;
}
.cover-page .page-inner {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 0;
  min-height: 860px;
}
.disclaimer-page .page-inner {
  padding: 52px 70px 50px;
}
.pg-num {
  position: absolute;
  bottom: 20px;
  right: 32px;
  font-size: 10px;
  color: #bbb;
  letter-spacing: .1em;
}
.pg-watermark {
  position: absolute;
  bottom: 20px;
  left: 32px;
  font-size: 9px;
  color: #ccc;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.org-logo-bar,
.cover-logo-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.org-logo-bar {
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 2px solid var(--border);
}
.org-logo-circle,
.cover-logo-circle {
  width: 42px;
  height: 42px;
  border: 2px solid var(--ink);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'DM Serif Display', serif;
}
.cover-logo-circle {
  width: 36px;
  height: 36px;
  border-width: 1.5px;
}
.org-logo-name,
.cover-logo-name {
  font-family: 'Syne', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.disclaimer-block {
  font-family: 'DM Serif Display', serif;
  font-style: italic;
  font-size: 13px;
  line-height: 1.9;
  color: #333;
  border-left: 3px solid var(--ink);
  padding-left: 22px;
  margin-bottom: 34px;
}
.disclaimer-doc-title {
  font-family: 'DM Serif Display', serif;
  font-size: 24px;
  line-height: 1.3;
  color: var(--ink);
  margin-bottom: 28px;
}
.section-label {
  font-family: 'Syne', sans-serif;
  font-weight: 800;
  font-size: 12px;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 38px 0 18px;
  border-left: 4px solid var(--ink);
  padding-left: 12px;
}
.update-table,
.static-table,
.brd-table,
.toc-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.update-table th,
.static-table th,
.brd-table th,
.toc-table th {
  background: var(--ink);
  color: #fff;
  padding: 10px 14px;
  text-align: left;
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: .15em;
  text-transform: uppercase;
  font-weight: 600;
}
.update-table td,
.static-table td,
.brd-table td,
.toc-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  overflow-wrap: break-word;
  word-break: break-word;
}
.update-table tbody tr:nth-child(even) td,
.static-table tbody tr:nth-child(even) td,
.brd-table tbody tr:nth-child(even),
.toc-table tbody tr:nth-child(even) {
  background: var(--cream);
}
.static-table td:first-child,
.update-table td:first-child,
.brd-table td:first-child {
  font-weight: 600;
}
.cover-header {
  background: #fff;
  position: relative;
  overflow: hidden;
}
.cover-logo-bar {
  padding: 20px 52px;
  border-bottom: 1px solid rgba(0,0,0,.09);
}
.cover-title-block {
  padding: 18px 52px 22px;
}
.cover-doc-type {
  font-size: 9px;
  letter-spacing: .28em;
  text-transform: uppercase;
  color: rgba(100,100,100,.6);
  margin-bottom: 8px;
}
.cover-title {
  font-family: 'DM Serif Display', serif;
  font-size: 44px;
  line-height: 1.1;
  color: #0a0a0a;
  margin-bottom: 4px;
  word-break: break-word;
}
.cover-subtitle {
  font-family: 'DM Serif Display', serif;
  font-size: 18px;
  color: rgba(60,60,60,.55);
  font-style: italic;
}
.cover-body {
  padding: 28px 52px;
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  align-content: start;
}
.cover-meta-group h4,
.cover-stack h4 {
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 11px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}
.cover-meta-row {
  display: flex;
  justify-content: space-between;
  font-size: 11.5px;
  padding: 5px 0;
  border-bottom: 1px solid var(--cream);
  gap: 10px;
}
.cover-meta-row span:first-child { color: var(--muted); }
.cover-meta-row span:last-child { font-weight: 500; text-align: right; }
.cover-stack {
  grid-column: 1 / -1;
  padding: 16px 0 8px;
  border-top: 1.5px solid var(--border);
}
.tech-pills {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 6px;
}
.tech-pill {
  background: #f5f5f0;
  color: var(--ink);
  font-size: 10px;
  padding: 6px 12px;
  letter-spacing: .03em;
  border: 1px solid var(--border);
  border-left: 3px solid var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cover-footer {
  background: var(--cream);
  border-top: 2px solid var(--border);
  padding: 18px 52px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: var(--muted);
  letter-spacing: .05em;
}
.confidential {
  background: var(--ink);
  color: #fff;
  padding: 4px 12px;
  font-size: 9px;
  letter-spacing: .15em;
  text-transform: uppercase;
}
.toc-page-title {
  font-family: 'DM Serif Display', serif;
  font-size: 30px;
  margin-bottom: 7px;
}
.toc-page-subtitle {
  font-size: 10px;
  color: var(--muted);
  letter-spacing: .08em;
  margin-bottom: 26px;
  padding-bottom: 14px;
  border-bottom: 2px solid var(--ink);
}
.toc-link,
.toc-page-link {
  display: block;
  width: 100%;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.toc-link:hover,
.toc-page-link:hover {
  text-decoration-thickness: 2px;
}
.toc-table td:first-child {
  font-size: 10px;
  letter-spacing: .1em;
  text-transform: uppercase;
  width: 120px;
}
.toc-table td:last-child,
.toc-table th:last-child {
  width: 60px;
  text-align: center;
}
.muted { color: var(--muted); }
.ch-header {
  padding-bottom: 22px;
  margin-bottom: 40px;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 18px;
  border-bottom: 1px solid var(--border);
}
.ch-num {
  font-size: 12px;
  letter-spacing: .2em;
  color: var(--ink);
  text-transform: uppercase;
  margin-bottom: 7px;
  font-weight: 800;
}
.ch-title {
  font-family: 'DM Serif Display', serif;
  font-size: 34px;
  line-height: 1.1;
}
.ch-subtitle {
  font-size: 12px;
  color: var(--muted);
  max-width: 300px;
  text-align: right;
  line-height: 1.55;
}
.ch-header-continued {
  margin-bottom: 32px;
}
.callout {
  padding: 14px 18px;
  margin: 14px 0;
  font-size: 12px;
  line-height: 1.65;
  border-left: 4px solid var(--ink);
  background: var(--cream);
}
.callout.info { border-color: var(--accent); background: #fdf7f2; }
.callout strong {
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: .15em;
  text-transform: uppercase;
  display: block;
  margin-bottom: 5px;
}
.phase-list,
.scope-grid,
.capability-grid,
.metric-grid,
.module-grid,
.glossary-grid,
.people-grid {
  display: grid;
  gap: 18px;
  margin-top: 12px;
}
.phase-list,
.scope-grid,
.capability-grid,
.metric-grid,
.module-grid,
.glossary-grid,
.people-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.phase-item,
.scope-box,
.arch-card,
.metric-card,
.module-card,
.glossary-item,
.person-card,
.sequence-card {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
}
.phase-num,
.metric-label,
.integration-tag,
.class-section-title,
.person-role {
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 8px;
}
.phase-title,
.integration-title,
.sequence-title,
.person-name {
  font-family: 'Syne', sans-serif;
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 8px;
}
.scope-box h4 {
  font-family: 'Syne', sans-serif;
  font-size: 10px;
  letter-spacing: .16em;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.scope-item {
  display: flex;
  gap: 8px;
  margin-bottom: 7px;
  font-size: 11.5px;
  line-height: 1.45;
}
.scope-mark { flex-shrink: 0; font-weight: 700; }
.in-scope { border-top: 3px solid var(--ink); }
.out-scope { border-top: 3px solid #888; }
.mini-list,
.bullet-list {
  margin: 8px 0 0 18px;
}
.mini-list li,
.bullet-list li {
  margin: 6px 0;
  font-size: 11.5px;
  line-height: 1.55;
}
.bullet-list.compact li { margin: 4px 0; }
.module-card p,
.person-notes,
.glossary-def,
.class-card p {
  font-size: 11.5px;
  color: var(--muted);
}
.module-tag,
.badge {
  display: inline-block;
  background: var(--cream);
  border: 1px solid var(--border);
  font-size: 9px;
  padding: 3px 8px;
  margin-top: 10px;
  letter-spacing: .05em;
}
.arch-diagram {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.arch-section {
  border: 1px solid var(--border);
  padding: 14px 16px;
  background: #fafafa;
}
.arch-section-label {
  font-family: 'Syne', sans-serif;
  font-size: 10px;
  letter-spacing: .14em;
  text-transform: uppercase;
  margin-bottom: 10px;
  color: var(--muted);
}
.arch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.node-card {
  min-width: 120px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff;
}
.s-data { background: #f4f4f6; }
.arch-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 6px;
}
.arch-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  color: var(--muted);
}
.arch-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  border: 1px solid var(--border);
}
.dot-actor { background: #f5f5f5; }
.dot-ui { background: #ececec; }
.dot-biz { background: #e8e5e2; }
.dot-data { background: #d7d7dd; }
.arch-fig-caption,
.er-fig-caption {
  margin-top: 10px;
  color: var(--muted);
  font-size: 10px;
}
.er-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 10px;
}
.er-table {
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}
.er-table-head.dark {
  background: var(--brand-dark);
  color: #fff;
  padding: 12px 16px;
  font-family: 'Syne', sans-serif;
  font-size: 11px;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.er-field,
.class-field {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}
.fname { font-weight: 700; }
.ftype { color: var(--muted); }
.app-flow {
  border: 1px solid var(--border);
  padding: 18px;
  background: #fcfcfb;
}
.app-flow-title {
  font-family: 'Syne', sans-serif;
  font-size: 10px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 14px;
}
.app-flow-track {
  display: flex;
  align-items: stretch;
  gap: 10px;
  flex-wrap: wrap;
}
.app-screen {
  flex: 1 1 140px;
  min-width: 140px;
  border: 1px solid var(--border);
  background: #fff;
  padding: 14px;
}
.app-screen-icon {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  margin-bottom: 10px;
}
.app-screen-name {
  font-family: 'Syne', sans-serif;
  font-size: 12px;
  font-weight: 700;
  margin-bottom: 6px;
}
.app-screen-desc {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.55;
}
.app-flow-arrow {
  width: 18px;
  min-height: 10px;
  position: relative;
  align-self: center;
}
.app-flow-arrow::before {
  content: '';
  display: block;
  width: 100%;
  border-top: 1px dashed var(--border);
  position: absolute;
  top: 50%;
}
.use-case-card,
.class-card,
.integration-card,
.api-group {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 16px;
}
.use-case-id,
.api-group-title,
.class-card-head span,
.integration-tag {
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--muted);
}
.use-case-title,
.class-card-head,
.api-group-title {
  font-family: 'Syne', sans-serif;
  font-size: 14px;
  font-weight: 700;
  margin: 8px 0 10px;
}
.use-case-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
  margin-bottom: 14px;
}
.use-case-meta-item,
.integration-meta-row {
  font-size: 11px;
  color: #333;
}
.use-case-meta-item span:first-child,
.integration-meta-row span:first-child {
  color: var(--muted);
  margin-right: 4px;
}
.use-case-steps {
  display: grid;
  gap: 8px;
}
.use-case-step,
.sequence-step {
  border: 1px solid var(--border);
  background: #fafafa;
  padding: 9px 12px;
  font-size: 11px;
  line-height: 1.5;
}
.class-card-head {
  display: flex;
  flex-direction: column;
}
.class-card-sub {
  font-size: 10px;
  color: var(--muted);
  margin-bottom: 10px;
}
.class-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.sequence-card {
  margin-bottom: 16px;
}
.sequence-step {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 8px;
}
.sequence-step span {
  width: 24px;
  flex-shrink: 0;
  font-family: 'Syne', sans-serif;
  color: var(--muted);
}
.integration-card.outbound {
  border-left: 3px solid var(--accent);
}
.integration-meta {
  display: grid;
  gap: 6px;
  margin: 10px 0 12px;
}
.integration-desc {
  font-size: 11.5px;
  color: #333;
}
.api-endpoint {
  border-top: 1px solid var(--border);
  padding: 12px 0 0;
  margin-top: 12px;
}
.api-endpoint.compact { margin-top: 10px; }
.method-badge {
  display: inline-block;
  min-width: 58px;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 9px;
  text-align: center;
  font-family: 'Syne', sans-serif;
  letter-spacing: .1em;
  margin-right: 10px;
  color: #fff;
}
.method-get { background: #2c7a7b; }
.method-post { background: #2f855a; }
.method-put { background: #b7791f; }
.method-delete { background: #c53030; }
.method-patch { background: #805ad5; }
.api-path {
  font-family: 'DM Mono', monospace;
  font-size: 11px;
  color: var(--ink);
}
.api-desc {
  margin-top: 8px;
  font-size: 11.5px;
  color: #333;
  line-height: 1.6;
}
.glossary-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.glossary-term {
  font-family: 'Syne', sans-serif;
  font-size: 12px;
  font-weight: 700;
}
.people-grid .person-card {
  min-height: 140px;
}
.stack-page .page-inner,
.stack-page-contd .page-inner {
  padding-top: 46px;
  padding-bottom: 60px;
}
.stack-lead {
  margin-bottom: 24px;
}
.stack-lead p {
  font-size: 12px;
  line-height: 1.82;
  color: #3a3a3a;
}
.stack-metric-grid {
  margin-bottom: 26px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.stack-metric-grid .metric-card {
  min-height: 106px;
  padding: 18px 20px;
}
.stack-metric-grid .metric-value {
  font-size: 18px;
  line-height: 1.42;
}
.stack-section {
  margin-bottom: 32px;
  padding: 18px 20px 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fcfcfb;
}
.stack-section > h2 {
  margin-top: 0;
  margin-bottom: 16px;
}
.stack-section .brd-table,
.stack-section .static-table,
.stack-section .update-table {
  margin-top: 14px;
}
.stack-compact-table th,
.stack-compact-table td {
  padding-top: 8px;
  padding-bottom: 8px;
}
.stack-inventory-table th,
.stack-inventory-table td {
  padding: 6px 9px;
  font-size: 10px;
  line-height: 1.38;
}
.stack-section p {
  margin-bottom: 0;
}
.stack-note {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.7;
}
.stack-dual-grid {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 20px;
  margin-bottom: 4px;
}
.stack-panel {
  margin-bottom: 0;
}
.stack-mini-callout {
  margin-top: 14px;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
}
.stack-mini-callout strong {
  display: inline-block;
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 6px;
}
.stack-mini-callout p {
  font-size: 11px;
  line-height: 1.7;
  color: #444;
}
.stack-section-last {
  margin-bottom: 8px;
}
@media (max-width: 900px) {
  .page { max-width: calc(100% - 12px); }
  .page-inner { padding: 28px 22px 50px; }
  .disclaimer-page .page-inner { padding: 30px 24px 50px; }
  .cover-page .page-inner { min-height: auto; }
  .cover-logo-bar,
  .cover-title-block,
  .cover-body,
  .cover-footer { padding-left: 22px; padding-right: 22px; }
  .cover-body,
  .phase-list,
  .scope-grid,
  .capability-grid,
  .metric-grid,
  .stack-dual-grid,
  .module-grid,
  .glossary-grid,
  .people-grid,
  .er-grid,
  .class-grid,
  .use-case-meta { grid-template-columns: 1fr; }
  .cover-footer,
  .ch-header,
  .app-flow-track { flex-direction: column; align-items: flex-start; }
  .ch-subtitle { text-align: left; max-width: none; }
  .pg-watermark { left: 22px; }
}
</style>
</head>
<body>
<main class="doc-wrapper">
"""

    content_pages = [
        ("ch1", intro_page, ""),
        ("ch2", scope_page, ""),
        ("ch3", functionality_page, ""),
        ("ch4", architecture_page, ""),
        ("ch5", stack_page_primary, "stack-page"),
    ]
    for inventory_index, inventory_page in enumerate(stack_inventory_pages, start=1):
        content_pages.append((f"ch5i{inventory_index}", inventory_page, "stack-page-contd stack-inventory-page"))
    content_pages.extend([
        ("ch5a", stack_page_operations, "stack-page-contd"),
        ("ch5b", stack_page_platform, "stack-page-contd"),
        ("ch6", data_page, ""),
        ("ch7", schema_page, ""),
        ("ch8", process_page, ""),
        ("ch9", application_flow_page, ""),
        ("ch10", use_case_page, ""),
        ("ch11", class_page, ""),
        ("ch12", activity_page, ""),
        ("ch13", sequence_page, ""),
        ("ch14", integration_page, ""),
        ("ch15", api_page, ""),
        ("ch16", nfr_page, ""),
        ("ch17", risk_page, ""),
        ("ch18", repo_guide_page, ""),
        ("ch19", security_page, ""),
        ("ch20", support_page, ""),
        ("ch21", goto_page, ""),
        ("ch22", glossary_page, ""),
        ("ch23", appendices_page, ""),
    ])

    all_page_ids = ["disclaimer", "cover", "toc"] + [page_id for page_id, _, _ in content_pages]
    page_lookup = {page_id: index + 1 for index, page_id in enumerate(all_page_ids)}

    toc_rows = []
    for index, (chapter_id, title) in enumerate(chapters, start=1):
        toc_rows.append(
            "<tr>"
            f"<td>Section {index}</td>"
            f"<td><a class=\"toc-link\" href=\"#{_escape(chapter_id)}\">{_escape(title)}</a></td>"
            f"<td><a class=\"toc-page-link\" href=\"#{_escape(chapter_id)}\">{page_lookup[chapter_id]:02d}</a></td>"
            "</tr>"
        )

    html_parts = [
        styles,
        _render_page("disclaimer", page_lookup["disclaimer"], disclaimer_page, extra_class="disclaimer-page"),
        _render_page("cover", page_lookup["cover"], cover_page, extra_class="cover-page"),
        _render_page(
            "toc",
            page_lookup["toc"],
            "<div class=\"toc-page-title\">Table of Contents</div>"
            "<div class=\"toc-page-subtitle\">Application Overview Document for Modernization - "
            + _escape(repo_short_name)
            + " - v1.0</div>"
            + "<table class=\"toc-table\"><thead><tr><th>Section</th><th>Title</th><th>Page</th></tr></thead><tbody>"
            + "".join(toc_rows)
            + "</tbody></table>",
        ),
    ]
    for page_id, page_content, extra_class in content_pages:
        html_parts.append(_render_page(page_id, page_lookup[page_id], page_content, extra_class=extra_class))
    html_parts.extend([
        "</main></body></html>",
    ])
    return "".join(html_parts)


def _enrich_brd_document(document: dict, analysis_data: dict, repo_name: str) -> dict:
    """
    Enrich the generated BRD document with real data from analysis_data.

    Key behaviors preserved from the supplied implementation:
    1. Keep exact dependency details when present
    2. Replace generic DB tables with entity-derived tables
    3. Confirm class names against actual files
    4. Ensure at least 5 use cases including setup/configuration
    5. Add measurable business objective targets
    6. Preserve detected module structure
    """
    import copy

    doc = copy.deepcopy(document)

    real_deps = analysis_data.get("dependencies", [])
    real_files = analysis_data.get("all_files", [])
    build_tool = analysis_data.get("build_tool", "unknown")
    java_version = analysis_data.get("java_version") or analysis_data.get("java_version_from_build") or "unknown"
    detected_frameworks = analysis_data.get("detected_frameworks", [])
    vulnerable_deps = analysis_data.get("vulnerable_dependencies", [])
    build_files_info = analysis_data.get("build_files_info", {})

    logger.info(
        "[BRD ENRICH] Enriching with %s deps, %s files, build_tool=%s, java=%s",
        len(real_deps),
        len(real_files),
        build_tool,
        java_version,
    )

    tech_stack = doc.get("tech_stack", [])
    if isinstance(tech_stack, list):
        real_dep_map = {}
        for dep in real_deps:
            aid = dep.get("artifact_id", "").lower()
            gid = dep.get("group_id", "").lower()
            ver = dep.get("current_version") or dep.get("version") or ""
            if aid:
                real_dep_map[aid] = {"group_id": dep.get("group_id", ""), "version": ver}
                real_dep_map[f"{gid}:{aid}"] = {"group_id": dep.get("group_id", ""), "version": ver}

        for entry in tech_stack:
            if isinstance(entry, dict):
                tech_name = entry.get("technology", "").lower().replace(" ", "-")
                for dep_key, dep_info in real_dep_map.items():
                    if tech_name in dep_key or dep_key in tech_name:
                        if dep_info["version"] and dep_info["version"] != "unknown":
                            entry["version"] = dep_info["version"]
                            break

        existing_techs = {e.get("technology", "").lower() for e in tech_stack if isinstance(e, dict)}
        for dep in real_deps:
            aid = dep.get("artifact_id", "")
            ver = dep.get("current_version") or dep.get("version") or ""
            if aid.lower() not in existing_techs and ver and ver != "unknown":
                gid = dep.get("group_id", "")
                category = "Dependency"
                gid_lower = gid.lower()
                if "test" in gid_lower or aid.lower() in ("junit", "mockito-core", "junit-jupiter-api", "testng"):
                    category = "Testing"
                elif "spring" in gid_lower:
                    category = "Framework"
                elif "log" in aid.lower() or "slf4j" in gid_lower:
                    category = "Logging"
                elif "jackson" in gid_lower or "gson" in gid_lower:
                    category = "Serialization"
                elif "gradle" in gid_lower or "maven" in gid_lower:
                    category = "Build"
                tech_stack.append({
                    "category": category,
                    "technology": aid,
                    "version": ver,
                    "purpose": f"{gid}:{aid}",
                })
        doc["tech_stack"] = tech_stack

    tech_names_lower = {e.get("technology", "").lower() for e in doc.get("tech_stack", []) if isinstance(e, dict)}
    if build_tool and build_tool.lower() not in tech_names_lower:
        build_ver = build_files_info.get("build_tool_version", "")
        doc["tech_stack"].insert(0, {
            "category": "Build",
            "technology": build_tool.title(),
            "version": build_ver,
            "purpose": "Build automation",
        })
    if java_version and java_version != "unknown":
        has_java = any(
            "java" in e.get("technology", "").lower() or "jdk" in e.get("technology", "").lower()
            for e in doc.get("tech_stack", [])
            if isinstance(e, dict)
        )
        if not has_java:
            doc["tech_stack"].insert(0, {
                "category": "Language",
                "technology": "Java (JDK)",
                "version": java_version,
                "purpose": "Primary language",
            })

    db_tables = doc.get("db_tables", [])
    entity_files = []
    for f in real_files:
        fname = f.get("name", "") or f.get("path", "") if isinstance(f, dict) else str(f)
        fname_lower = fname.lower()
        if fname_lower.endswith(".java"):
            base = fname.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].replace(".java", "")
            if base and (
                any(kw in fname_lower for kw in ["model", "entity", "dto", "domain", "config", "pojo", "bean"])
                or (
                    base[0].isupper()
                    and not any(
                        kw in base.lower()
                        for kw in ["test", "spec", "controller", "service", "repository", "dao", "util", "helper", "exception"]
                    )
                )
            ):
                entity_files.append(base)

    if isinstance(db_tables, list) and entity_files:
        entity_names_lower = {e.lower() for e in entity_files}
        generic_table_names = {
            "users", "orders", "bookings", "payments", "products",
            "customers", "sessions", "transactions", "application_data",
            "user_data", "audit_log",
        }
        has_generic = any(
            isinstance(t, dict)
            and t.get("table_name", "").lower() in generic_table_names
            and t.get("table_name", "").lower() not in entity_names_lower
            for t in db_tables
        )
        if has_generic or not db_tables:
            logger.warning("[BRD ENRICH] Replacing generic DB tables with entity-derived tables")

            def _camel_to_snake(name: str) -> str:
                s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
                s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", s)
                return s.lower().strip("_")

            new_tables = []
            for ent_name in entity_files[:8]:
                table_name = _camel_to_snake(ent_name)
                new_tables.append({
                    "table_name": table_name,
                    "fields": [
                        {"name": "id", "type": "BIGINT", "key": "PK", "nullable": False, "references": ""},
                        {"name": f"{table_name}_name", "type": "VARCHAR(255)", "key": "none", "nullable": True, "references": ""},
                        {"name": "created_at", "type": "TIMESTAMP", "key": "none", "nullable": False, "references": ""},
                        {"name": "updated_at", "type": "TIMESTAMP", "key": "none", "nullable": True, "references": ""},
                    ],
                })
            doc["db_tables"] = new_tables if new_tables else db_tables
    elif not db_tables and entity_files:
        new_tables = []
        for ent_name in entity_files[:8]:
            table_name = re.sub(r"(?<!^)(?=[A-Z])", "_", ent_name).lower()
            new_tables.append({
                "table_name": table_name,
                "fields": [
                    {"name": "id", "type": "BIGINT", "key": "PK", "nullable": False, "references": ""},
                    {"name": f"{table_name}_data", "type": "VARCHAR(500)", "key": "none", "nullable": True, "references": ""},
                    {"name": "created_at", "type": "TIMESTAMP", "key": "none", "nullable": False, "references": ""},
                ],
            })
        doc["db_tables"] = new_tables

    actual_classes = set()
    for f in real_files:
        fname = f.get("name", "") or f.get("path", "") if isinstance(f, dict) else str(f)
        if fname.endswith(".java"):
            actual_classes.add(fname.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].replace(".java", ""))

    class_inv = doc.get("class_inventory", [])
    if isinstance(class_inv, list) and actual_classes:
        for cls in class_inv:
            if isinstance(cls, dict):
                cls["_confirmed"] = cls.get("class_name", "") in actual_classes

    use_cases = doc.get("use_cases", [])
    if not isinstance(use_cases, list):
        use_cases = []

    has_config_uc = any(
        isinstance(uc, dict)
        and (
            "config" in uc.get("name", "").lower()
            or "setup" in uc.get("name", "").lower()
            or uc.get("id", "") == "UC-04"
        )
        for uc in use_cases
    )
    if not has_config_uc:
        use_cases.append({
            "id": f"UC-{len(use_cases) + 1:02d}",
            "name": f"Configure and Build {repo_name}",
            "actor": "Developer / Maintainer",
            "main_flow": (
                f"1. Clone repository  2. Configure {build_tool} build settings  "
                f"3. Set Java {java_version} as target  4. Resolve dependencies  "
                f"5. Execute build  6. Verify build output"
            ),
            "post_condition": f"Project builds successfully with {build_tool} and Java {java_version}",
        })

    while len(use_cases) < 5:
        idx = len(use_cases) + 1
        if idx == 2 and real_deps:
            use_cases.append({
                "id": f"UC-{idx:02d}",
                "name": "Dependency Management",
                "actor": "Developer",
                "main_flow": (
                    f"1. Review {len(real_deps)} project dependencies  2. Check for vulnerabilities  "
                    f"3. Upgrade outdated versions  4. Verify compatibility"
                ),
                "post_condition": "All dependencies are up-to-date and secure",
            })
        elif idx == 3:
            use_cases.append({
                "id": f"UC-{idx:02d}",
                "name": "Code Quality Review",
                "actor": "Developer / Reviewer",
                "main_flow": "1. Run static analysis  2. Review code smells  3. Check test coverage  4. Address findings",
                "post_condition": "Code passes quality gate with acceptable metrics",
            })
        else:
            use_cases.append({
                "id": f"UC-{idx:02d}",
                "name": f"Feature Workflow {idx}",
                "actor": "End User",
                "main_flow": "1. Access application  2. Perform primary action  3. Verify result",
                "post_condition": "Action completed successfully",
            })
    doc["use_cases"] = use_cases

    biz_objs = doc.get("business_objectives", [])
    if isinstance(biz_objs, list):
        measurable_targets = [
            f"Zero critical CVEs in {len(real_deps)} project dependencies",
            f"100% build success rate with {build_tool} on Java {java_version}",
            f"Maintain {len(real_files)} source files with < 5% code duplication",
            "Achieve >= 80% unit test coverage across all modules",
            f"Resolve all {len(vulnerable_deps)} known vulnerability findings",
        ]
        for i, obj in enumerate(biz_objs):
            if isinstance(obj, dict):
                target = obj.get("target", "")
                is_vague = (
                    target
                    and not any(c.isdigit() for c in target)
                    and "%" not in target
                    and "<" not in target
                    and ">" not in target
                    and "zero" not in target.lower()
                )
                if is_vague and i < len(measurable_targets):
                    obj["target"] = measurable_targets[i]
        doc["business_objectives"] = biz_objs

    modules = doc.get("modules", [])
    real_modules = set()
    gradle_files = build_files_info.get("gradle_files", [])
    pom_files = build_files_info.get("pom_files", [])
    for bf in gradle_files + pom_files:
        rel = (bf.get("relative_path", "") or bf.get("path", "")) if isinstance(bf, dict) else str(bf)
        parts = rel.replace("\\", "/").split("/")
        if len(parts) > 1:
            real_modules.add(parts[0])
    for f in real_files:
        fname = f.get("path", "") or f.get("name", "") if isinstance(f, dict) else str(f)
        parts = fname.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[0] != "src" and parts[1] == "src":
            real_modules.add(parts[0])
    if real_modules:
        existing_module_names = {m.get("name", "").lower() for m in modules if isinstance(m, dict)}
        for mod_name in sorted(real_modules):
            if mod_name.lower() not in existing_module_names:
                modules.append({
                    "name": mod_name,
                    "description": f"Submodule detected from {build_tool} build structure",
                    "files": f"{mod_name}/build.gradle" if build_tool.lower() == "gradle" else f"{mod_name}/pom.xml",
                })
    doc["modules"] = modules

    doc_info = doc.get("document_info", {})
    if isinstance(doc_info, dict) and not doc_info.get("frameworks") and detected_frameworks:
        doc_info["frameworks"] = detected_frameworks
        doc["document_info"] = doc_info

    if not doc.get("languages"):
        ext_map = {}
        for f in real_files:
            fname = f.get("path", f.get("name", "")) if isinstance(f, dict) else str(f)
            if "." not in fname:
                continue
            ext = fname.rsplit(".", 1)[-1].lower()
            ext_map.setdefault(ext, []).append(fname)
        ext_to_lang = {
            "java": "Java", "py": "Python", "js": "JavaScript", "ts": "TypeScript",
            "kt": "Kotlin", "scala": "Scala", "groovy": "Groovy", "rb": "Ruby",
            "cs": "C#", "cpp": "C++", "c": "C", "go": "Go", "rs": "Rust",
            "xml": "XML/Config", "yml": "YAML", "yaml": "YAML", "properties": "Properties",
            "json": "JSON", "sql": "SQL", "html": "HTML", "css": "CSS", "sh": "Shell",
            "bat": "Batch", "gradle": "Gradle", "toml": "TOML",
        }
        if "yml" in ext_map and "yaml" in ext_map:
            ext_map["yml"].extend(ext_map.pop("yaml"))
        elif "yaml" in ext_map:
            ext_map["yml"] = ext_map.pop("yaml")
        languages_list = []
        total_files = 0
        for ext, files in sorted(ext_map.items(), key=lambda x: -len(x[1])):
            lang = ext_to_lang.get(ext, ext.upper())
            cnt = len(files)
            est_loc = cnt * 80 if ext in ("java", "py", "js", "ts", "kt", "scala", "cs", "go", "rs") else cnt * 30
            test_files_in = [f for f in files if "test" in f.lower()]
            used = cnt - len(test_files_in)
            languages_list.append({
                "language": lang,
                "programs": str(cnt),
                "loc": str(est_loc),
                "used_files": str(used),
                "orphan_files": "0",
                "used_loc": str(int(est_loc * used / cnt)) if cnt else "0",
                "orphan_loc": "0",
                "notes": f"Auto-detected from {cnt} .{ext} files",
            })
            total_files += cnt
            if len(languages_list) >= 3:
                break
        doc["languages"] = languages_list
        doc["total_programs"] = str(total_files)
        doc["total_loc"] = str(sum(int(l.get("loc", 0)) for l in languages_list))
        doc["orphan_files"] = "0"

    capabilities = doc.get("capabilities", [])
    if not capabilities:
        mods = doc.get("modules", [])
        for i, m in enumerate(mods[:3]):
            if isinstance(m, dict):
                mod_name = m.get("name", f"Module {i + 1}")
                mod_desc = m.get("description", "")
                capabilities.append({
                    "name": mod_name,
                    "overview": mod_desc or f"Core functionality provided by the {mod_name} module",
                    "business_value": f"Supports critical business operations through {mod_name}",
                    "features": [
                        f"{mod_name} core processing",
                        f"{mod_name} data management",
                        f"{mod_name} validation and error handling",
                        f"{mod_name} integration support",
                    ],
                    "processes": [
                        f"Initialize {mod_name}",
                        f"Process {mod_name} requests",
                        f"Validate {mod_name} outputs",
                    ],
                })
        if not capabilities:
            capabilities = [
                {
                    "name": repo_name,
                    "overview": f"Primary application functionality of {repo_name}",
                    "business_value": "Delivers core business operations",
                    "features": ["Request handling", "Data processing", "Response generation", "Error management"],
                    "processes": ["Accept input", "Process business logic", "Return results"],
                },
                {
                    "name": "Configuration & Build",
                    "overview": f"Build and configuration management via {build_tool}",
                    "business_value": "Ensures consistent builds and deployments",
                    "features": ["Dependency management", "Build automation", "Environment configuration"],
                    "processes": ["Resolve dependencies", "Compile source", "Package artifacts"],
                },
                {
                    "name": "Testing & Quality",
                    "overview": "Automated testing and code quality assurance",
                    "business_value": "Maintains code reliability and reduces defects",
                    "features": ["Unit testing", "Integration testing", "Code coverage"],
                    "processes": ["Execute test suites", "Generate reports", "Validate coverage thresholds"],
                },
            ]
        doc["capabilities"] = capabilities
    else:
        for cap in capabilities:
            if isinstance(cap, dict):
                cap_name = cap.get("name", "Module")
                if not cap.get("features"):
                    cap["features"] = [
                        f"{cap_name} core processing",
                        f"{cap_name} data management",
                        f"{cap_name} validation",
                        f"{cap_name} integration",
                    ]
                if not cap.get("processes"):
                    cap["processes"] = [f"Initialize {cap_name}", f"Process {cap_name}", f"Finalize {cap_name}"]
                if not cap.get("business_value"):
                    cap["business_value"] = cap.get("overview", cap.get("description", "Supports business operations"))

    if not doc.get("risks"):
        risks = []
        for dr in doc.get("dependency_risks", [])[:2]:
            if isinstance(dr, dict):
                risks.append({
                    "category": "technical",
                    "title": f"Dependency Risk: {dr.get('dependency', 'Unknown')}",
                    "description": (
                        f"Version {dr.get('current_version', '?')} has risk level "
                        f"{dr.get('risk_level', '?')}. {dr.get('notes', '')}"
                    ),
                    "mitigation": f"Upgrade to {dr.get('latest_version', 'latest')} and run regression tests",
                })
        if vulnerable_deps:
            risks.append({
                "category": "security",
                "title": f"Vulnerable Dependencies ({len(vulnerable_deps)} found)",
                "description": f"Security scan identified {len(vulnerable_deps)} dependencies with known vulnerabilities",
                "mitigation": "Apply security patches, upgrade affected libraries, and re-run security scans",
            })
        risks.append({
            "category": "operational",
            "title": "Environment Configuration Drift",
            "description": "Differences between development, staging, and production configurations may cause build or deployment failures",
            "mitigation": "Implement environment parity checks and automated configuration validation",
        })
        if java_version and java_version != "unknown":
            risks.append({
                "category": "technical",
                "title": f"Java {java_version} Lifecycle Risk",
                "description": f"Java {java_version} may restrict access to current security patches and ecosystem upgrades",
                "mitigation": "Plan migration toward a current LTS version and validate dependency compatibility",
            })
        risks.append({
            "category": "maintenance",
            "title": "Technical Debt Accumulation",
            "description": f"Codebase with {len(real_files)} files requires ongoing refactoring and test coverage improvements",
            "mitigation": "Adopt quality gates, prioritize refactoring, and track coverage in CI",
        })
        doc["risks"] = risks

    if not doc.get("glossary") or len(doc.get("glossary", [])) < 5:
        base_glossary = [
            {"term": "BRD", "definition": "Business Requirements Document."},
            {"term": "API", "definition": "Application Programming Interface."},
            {"term": "JVM", "definition": "Java Virtual Machine runtime environment."},
            {"term": "REST", "definition": "Architectural style for HTTP-based service communication."},
            {"term": "CRUD", "definition": "Create, Read, Update, Delete operations."},
            {"term": "NFR", "definition": "Non-functional requirement such as performance or security."},
            {"term": "RBAC", "definition": "Role-based access control authorization model."},
            {"term": "DTO", "definition": "Data transfer object between layers."},
            {"term": "SLA", "definition": "Service level agreement target."},
            {"term": "CVE", "definition": "Common Vulnerabilities and Exposures identifier."},
        ]
        existing = doc.get("glossary", [])
        existing_terms = {g.get("term", "").lower() for g in existing if isinstance(g, dict)}
        for item in base_glossary:
            if item["term"].lower() not in existing_terms:
                existing.append(item)
        doc["glossary"] = existing[:16]

    logger.info(
        "[BRD ENRICH] Done: tech_stack=%s modules=%s use_cases=%s objectives=%s languages=%s capabilities=%s risks=%s glossary=%s",
        len(doc.get("tech_stack", [])),
        len(doc.get("modules", [])),
        len(doc.get("use_cases", [])),
        len(doc.get("business_objectives", [])),
        len(doc.get("languages", [])),
        len(doc.get("capabilities", [])),
        len(doc.get("risks", [])),
        len(doc.get("glossary", [])),
    )
    return doc


def generate_modern_html_report(job: "MigrationResult", logs: List[str]) -> str:
    """
    Dark HTML report styled like the provided `migration_test_report.html` template,
    but generated dynamically from the job object.
    """
    status = _job_status_ui(getattr(job, "status", ""))
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    source_repo = getattr(job, "source_repo", "") or "N/A"
    target_repo = getattr(job, "target_repo", "") or "N/A"
    project_name = _infer_repo_name(source_repo if isinstance(source_repo, str) else "")

    files_modified = int(getattr(job, "files_modified", 0) or 0)
    issues_fixed = int(getattr(job, "issues_fixed", 0) or 0)
    errors_remaining = int(getattr(job, "total_errors", 0) or 0)
    warnings_remaining = int(getattr(job, "total_warnings", 0) or 0)

    tests_run = int(getattr(job, "tests_run", 0) or 0)
    tests_passed = int(getattr(job, "tests_passed", 0) or 0)
    tests_failed = int(getattr(job, "tests_failed", 0) or 0)
    success_rate = (tests_passed / tests_run * 100.0) if tests_run > 0 else 0.0

    generated_tests = 0
    try:
        pipeline = getattr(job, "test_pipeline", None)
        if pipeline and getattr(pipeline, "generated_test_files", None):
            generated_tests = len(pipeline.generated_test_files or [])
    except Exception:
        generated_tests = 0

    sonar_gate = getattr(job, "sonar_quality_gate", None) or "Not Run"
    sonar_passed = isinstance(sonar_gate, str) and sonar_gate.upper() == "PASSED"

    def repo_link(url: str) -> str:
        if isinstance(url, str) and url.startswith("http"):
            return f"<a class=\"link\" href=\"{_escape(url)}\" target=\"_blank\" rel=\"noreferrer\">{_escape(url)}</a>"
        return f"<span class=\"muted\">{_escape(url)}</span>"

    last_logs = logs[-200:] if logs else []
    logs_html = "\n".join(_escape(x) for x in last_logs)

    test_summary = getattr(job, "test_summary", None) or ""
    test_insights = getattr(job, "test_insights", None) or []
    if not isinstance(test_insights, list):
        test_insights = []

    insights_html = ""
    if test_insights:
        items = "\n".join(f"<li>{_escape(i)}</li>" for i in test_insights[:30])
        insights_html = f"<ul class=\"insights\">{items}</ul>"

    source_java = _escape(getattr(job, "source_java_version", "") or "N/A")
    target_java = _escape(getattr(job, "target_java_version", "") or "N/A")
    build_tool = _escape(getattr(job, "build_tool", "") or getattr(job, "project_type", "") or "N/A")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Java Migration Report - {_escape(getattr(job, "job_id", ""))}</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0a0c10;
      --surface: #111318;
      --surface2: #181c24;
      --border: #1e2330;
      --accent-green: #00e5a0;
      --accent-yellow: #f5c542;
      --accent-red: #ff4d6d;
      --accent-blue: #4da6ff;
      --accent-orange: #ff8c42;
      --text: #e8eaf0;
      --text-muted: #5a6070;
      --text-dim: #8892a0;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Syne', sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
    }}
    body::before {{
      content: '';
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(0,229,160,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,229,160,0.03) 1px, transparent 1px);
      background-size: 40px 40px;
      pointer-events: none;
      z-index: 0;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 32px;
      position: relative;
      z-index: 1;
    }}
    header {{
      padding: 48px 0 24px;
      border-bottom: 1px solid var(--border);
    }}
    .header-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 24px;
      flex-wrap: wrap;
    }}
    .report-badge {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      color: var(--accent-green);
      letter-spacing: 3px;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    h1 {{ font-size: 40px; line-height: 1.1; letter-spacing: -1px; }}
    h1 span {{ color: var(--accent-green); }}
    .header-meta {{ display:flex; flex-direction:column; gap:8px; align-items:flex-end; }}
    .meta-item {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-dim); }}
    .status-pill {{
      display:inline-flex;
      align-items:center;
      padding: 6px 12px;
      border-radius: 999px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      border: 1px solid transparent;
      letter-spacing: 1px;
      text-transform: uppercase;
    }}
    .status-completed {{ background: rgba(0,229,160,0.08); color: var(--accent-green); border-color: rgba(0,229,160,0.25);}}
    .status-running {{ background: rgba(245,197,66,0.10); color: var(--accent-yellow); border-color: rgba(245,197,66,0.25);}}
    .status-failed {{ background: rgba(255,77,109,0.10); color: var(--accent-red); border-color: rgba(255,77,109,0.25);}}
    .sonar-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 6px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 10px;
      background: rgba(0,229,160,0.1);
      color: var(--accent-green);
      border: 1px solid rgba(0,229,160,0.25);
    }}
    .sonar-badge.fail {{
      background: rgba(255,77,109,0.10);
      color: var(--accent-red);
      border-color: rgba(255,77,109,0.25);
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin: 22px 0 22px;
    }}
    .stat-card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01));
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px 16px 14px;
      position: relative;
      overflow: hidden;
    }}
    .stat-label {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      color: var(--text-dim);
      letter-spacing: 1.5px;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .stat-value {{ font-size: 30px; font-weight: 800; letter-spacing: -0.5px; }}
    .stat-sub {{ margin-top: 6px; font-size: 12px; color: var(--text-dim); }}
    .green .stat-value {{ color: var(--accent-green); }}
    .yellow .stat-value {{ color: var(--accent-yellow); }}
    .red .stat-value {{ color: var(--accent-red); }}
    .blue .stat-value {{ color: var(--accent-blue); }}
    .orange .stat-value {{ color: var(--accent-orange); }}
    .section-title {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--text-dim);
      margin: 28px 0 10px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
    }}
    .grid-2 {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }}
    .kv {{ display:flex; gap:10px; flex-wrap:wrap; font-family:'JetBrains Mono', monospace; font-size:12px; color: var(--text-dim); }}
    .kv b {{ color: var(--text); font-weight: 700; }}
    .link {{ color: var(--accent-blue); text-decoration: none; word-break: break-all; }}
    .muted {{ color: var(--text-dim); word-break: break-all; }}
    .divider {{ height:1px; background: var(--border); margin: 18px 0; }}
    .mono {{ font-family: 'JetBrains Mono', monospace; }}
    .code {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 14px; overflow:auto; }}
    .code code {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; white-space: pre; }}
    .insights {{ margin-top: 10px; padding-left: 18px; color: var(--text-dim); }}
    .insights li {{ margin: 6px 0; }}
    footer {{ padding: 28px 0 40px; color: var(--text-muted); font-family:'JetBrains Mono', monospace; font-size: 11px; }}
    @media (max-width: 700px) {{
      h1 {{ font-size: 32px; }}
      .header-meta {{ align-items:flex-start; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="header-top">
        <div>
          <div class="report-badge">Java Migration · Report</div>
          <h1>{_escape(project_name)} <span>·</span> Summary</h1>
        </div>
        <div class="header-meta">
          <span class="status-pill {status["class"]}">{_escape(status["label"])}</span>
          <span class="meta-item">Generated: {now_utc} · UTC</span>
          <span class="meta-item">Job ID: {_escape(getattr(job, "job_id", ""))}</span>
          <span class="sonar-badge{' fail' if not sonar_passed and sonar_gate != 'Not Run' else ''}">{'✓' if sonar_passed else '•'} SonarQube: {_escape(sonar_gate)}</span>
        </div>
      </div>
    </header>

    <div class="summary-grid">
      <div class="stat-card green">
        <div class="stat-label">Files Modified</div>
        <div class="stat-value">{files_modified}</div>
        <div class="stat-sub">Changed source files</div>
      </div>
      <div class="stat-card yellow">
        <div class="stat-label">Issues Fixed</div>
        <div class="stat-value">{issues_fixed}</div>
        <div class="stat-sub">Auto-fixes applied</div>
      </div>
      <div class="stat-card red">
        <div class="stat-label">Errors Remaining</div>
        <div class="stat-value">{errors_remaining}</div>
        <div class="stat-sub">From detected issues</div>
      </div>
      <div class="stat-card blue">
        <div class="stat-label">Test Cases Generated</div>
        <div class="stat-value">{generated_tests}</div>
        <div class="stat-sub">Unit tests: {tests_run} run · {tests_passed} passed · {tests_failed} failed</div>
      </div>
      <div class="stat-card orange">
        <div class="stat-label">Warnings Remaining</div>
        <div class="stat-value">{warnings_remaining}</div>
        <div class="stat-sub">From detected issues</div>
      </div>
    </div>

    <div class="section-title">Repository</div>
    <div class="grid-2">
      <div class="card">
        <div class="kv"><b>Source</b> {repo_link(source_repo)}</div>
        <div class="divider"></div>
        <div class="kv"><b>Java</b> {source_java} → {target_java}</div>
        <div class="kv"><b>Build</b> {build_tool}</div>
      </div>
      <div class="card">
        <div class="kv"><b>Target</b> {repo_link(target_repo)}</div>
        <div class="divider"></div>
        <div class="kv"><b>API endpoints</b> {_escape(getattr(job, "api_endpoints_working", 0) or 0)}/{_escape(getattr(job, "api_endpoints_validated", 0) or 0)} working</div>
        <div class="kv"><b>Test success</b> {success_rate:.1f}%</div>
      </div>
    </div>

    <div class="section-title">Test Summary</div>
    <div class="card">
      <div class="mono">{_escape(test_summary) if test_summary else 'No test summary available.'}</div>
      {insights_html}
    </div>

    <div class="section-title">Migration Log</div>
    <div class="card">
      <pre class="code"><code>{logs_html}</code></pre>
    </div>

    <footer>
      Generated by Java Migration Accelerator · {now_utc} UTC
    </footer>
  </div>
</body>
</html>"""


def generate_testcase_html_report(job: "MigrationResult", clone_path: str) -> str:
    md = generate_testcase_doc_markdown(job, clone_path)
    body = _markdown_to_simple_html(md)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    project_name = _infer_repo_name(getattr(job, "source_repo", "") or "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Testcase & Changes - {_escape(getattr(job, "job_id", ""))}</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0a0c10;
      --surface: #111318;
      --surface2: #181c24;
      --border: #1e2330;
      --accent-green: #00e5a0;
      --accent-blue: #4da6ff;
      --text: #e8eaf0;
      --text-dim: #8892a0;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: var(--bg); color: var(--text); font-family: 'Syne', sans-serif; }}
    body::before {{
      content: '';
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(0,229,160,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,229,160,0.03) 1px, transparent 1px);
      background-size: 40px 40px;
      pointer-events: none;
      z-index: 0;
    }}
    .container {{ max-width: 1000px; margin: 0 auto; padding: 0 28px; position: relative; z-index: 1; }}
    header {{ padding: 44px 0 18px; border-bottom: 1px solid var(--border); }}
    .badge {{ font-family:'JetBrains Mono', monospace; font-size: 11px; color: var(--accent-green); letter-spacing: 3px; text-transform: uppercase; margin-bottom: 10px; }}
    h1 {{ font-size: 34px; line-height: 1.1; }}
    .meta {{ margin-top: 10px; font-family:'JetBrains Mono', monospace; font-size: 12px; color: var(--text-dim); display:flex; gap: 14px; flex-wrap: wrap; }}
    main {{ padding: 22px 0 40px; }}
    .doc {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; }}
    h1, h2, h3, h4 {{ margin: 16px 0 10px; }}
    p {{ color: var(--text-dim); line-height: 1.7; margin: 8px 0; }}
    ul {{ padding-left: 18px; color: var(--text-dim); }}
    li {{ margin: 6px 0; }}
    code {{ font-family:'JetBrains Mono', monospace; font-size: 12px; background: rgba(77,166,255,0.08); border: 1px solid rgba(77,166,255,0.18); padding: 1px 6px; border-radius: 6px; color: var(--accent-blue);}}
    .code {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 14px; overflow:auto; }}
    .code code {{ background: transparent; border: none; padding: 0; color: var(--text); }}
    .spacer {{ height: 8px; }}
    a {{ color: var(--accent-blue); text-decoration: none; }}
    footer {{ padding: 18px 0 32px; color: var(--text-dim); font-family:'JetBrains Mono', monospace; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="badge">Java Migration · Testcase & Changes</div>
      <h1>{_escape(project_name)}</h1>
      <div class="meta">
        <span>Job ID: {_escape(getattr(job, "job_id", ""))}</span>
        <span>Generated: {now_utc} · UTC</span>
      </div>
    </header>
    <main>
      <div class="doc">
        {body}
      </div>
    </main>
    <footer>Generated by Java Migration Accelerator · {now_utc} UTC</footer>
  </div>
</body>
</html>"""


def generate_unit_test_html_report(job: "MigrationResult", details_html: str = "") -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    tests_run = int(getattr(job, "tests_run", 0) or 0)
    tests_passed = int(getattr(job, "tests_passed", 0) or 0)
    tests_failed = int(getattr(job, "tests_failed", 0) or 0)
    success_rate = (tests_passed / tests_run * 100.0) if tests_run > 0 else 0.0

    model = getattr(job, "test_llm_model", None) or "N/A"
    summary = getattr(job, "test_summary", None) or ""
    insights = getattr(job, "test_insights", None) or []
    if not isinstance(insights, list):
        insights = []

    runner = {}
    generated_files: List[str] = []
    try:
        tp = getattr(job, "test_pipeline", None)
        if tp and getattr(tp, "runner", None):
            runner = tp.runner or {}
        if tp and getattr(tp, "generated_test_files", None):
            generated_files = tp.generated_test_files or []
    except Exception:
        runner = {}
        generated_files = []

    runner_lines: List[str] = []
    if isinstance(runner, dict) and runner:
        runner_lines.append(f"tool={runner.get('tool')} exit={runner.get('exit_code')} timeout={runner.get('timed_out')} parser={runner.get('parser')}")
        cmd = runner.get("cmd")
        if isinstance(cmd, list) and cmd:
            runner_lines.append("cmd=" + " ".join(str(x) for x in cmd))
        out = runner.get("output")
        if isinstance(out, str) and out.strip():
            tail = out.strip()
            if len(tail) > 4000:
                tail = tail[-4000:]
            runner_lines.append("")
            runner_lines.append("--- output (tail) ---")
            runner_lines.append(tail)
        reports = runner.get("reports") if isinstance(runner.get("reports"), dict) else None
        if reports:
            runner_lines.append(f"junit_report_files={reports.get('report_files_count', 0)}")
            parse_errs = reports.get("report_parse_errors") or []
            if parse_errs:
                runner_lines.append(f"junit_parse_errors={len(parse_errs)}")

    generated_html = ""
    if generated_files:
        items = "\n".join(f"<li><code>{_escape(p)}</code></li>" for p in generated_files[:200])
        generated_html = f"""
          <div class="section-title">Generated Test Files</div>
          <div class="card">
            <ul class="list">{items}</ul>
          </div>
        """

    insights_html = ""
    if insights:
        items = "\n".join(f"<li>{_escape(i)}</li>" for i in insights[:50])
        insights_html = f"<ul class=\"list\">{items}</ul>"

    runner_block = ""
    if runner_lines:
        runner_block = "<pre class=\"code\"><code>" + _escape("\n".join(runner_lines)) + "</code></pre>"

    details_section = ""
    if details_html and details_html.strip():
        details_section = f"""
          <div class="section-title">Detailed Report</div>
          <div class="card details">
            {details_html}
          </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Unit Test Report - {_escape(getattr(job, "job_id", ""))}</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0a0c10;
      --surface: #111318;
      --surface2: #181c24;
      --border: #1e2330;
      --accent-green: #00e5a0;
      --accent-yellow: #f5c542;
      --accent-red: #ff4d6d;
      --accent-blue: #4da6ff;
      --text: #e8eaf0;
      --text-dim: #8892a0;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: var(--bg); color: var(--text); font-family: 'Syne', sans-serif; }}
    body::before {{
      content: '';
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(0,229,160,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,229,160,0.03) 1px, transparent 1px);
      background-size: 40px 40px;
      pointer-events: none;
      z-index: 0;
    }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 0 28px; position: relative; z-index: 1; }}
    header {{ padding: 44px 0 18px; border-bottom: 1px solid var(--border); }}
    .badge {{ font-family:'JetBrains Mono', monospace; font-size: 11px; color: var(--accent-green); letter-spacing: 3px; text-transform: uppercase; margin-bottom: 10px; }}
    h1 {{ font-size: 34px; line-height: 1.1; }}
    .meta {{ margin-top: 10px; font-family:'JetBrains Mono', monospace; font-size: 12px; color: var(--text-dim); display:flex; gap: 14px; flex-wrap: wrap; }}
    .section-title {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: var(--text-dim); margin: 22px 0 10px; }}
    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
    .stat {{ background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
    .label {{ font-family:'JetBrains Mono', monospace; font-size: 11px; color: var(--text-dim); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 8px; }}
    .value {{ font-size: 30px; font-weight: 800; letter-spacing: -0.5px; }}
    .value.blue {{ color: var(--accent-blue); }}
    .value.green {{ color: var(--accent-green); }}
    .value.red {{ color: var(--accent-red); }}
    .value.yellow {{ color: var(--accent-yellow); }}
    .code {{ background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 14px; overflow:auto; }}
    .code code {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; white-space: pre; }}
    .list {{ padding-left: 18px; color: var(--text-dim); }}
    .list li {{ margin: 6px 0; }}
    code {{ font-family:'JetBrains Mono', monospace; font-size: 12px; background: rgba(77,166,255,0.08); border: 1px solid rgba(77,166,255,0.18); padding: 1px 6px; border-radius: 6px; color: var(--accent-blue);}}
    .muted {{ color: var(--text-dim); }}
    /* Markdown detail styles */
    .details h1, .details h2, .details h3, .details h4 {{ margin: 16px 0 10px; }}
    .details p {{ color: var(--text-dim); line-height: 1.7; margin: 8px 0; }}
    .details ul {{ padding-left: 18px; color: var(--text-dim); }}
    .details li {{ margin: 6px 0; }}
    .details .spacer {{ height: 8px; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="badge">Java Migration · Unit Test Report</div>
      <h1>Test Results</h1>
      <div class="meta">
        <span>Job ID: {_escape(getattr(job, "job_id", ""))}</span>
        <span>Generated: {now_utc} · UTC</span>
        <span class="muted">LLM model: {_escape(model)}</span>
      </div>
    </header>

    <div class="section-title">Summary</div>
    <div class="grid">
      <div class="stat">
        <div class="label">Tests Run</div>
        <div class="value blue">{tests_run}</div>
      </div>
      <div class="stat">
        <div class="label">Tests Passed</div>
        <div class="value green">{tests_passed}</div>
      </div>
      <div class="stat">
        <div class="label">Tests Failed</div>
        <div class="value red">{tests_failed}</div>
      </div>
      <div class="stat">
        <div class="label">Success Rate</div>
        <div class="value yellow">{success_rate:.1f}%</div>
      </div>
      <div class="stat">
        <div class="label">Testcases Generated</div>
        <div class="value blue">{len(generated_files)}</div>
      </div>
    </div>

    <div class="section-title">LLM Summary</div>
    <div class="card">
      <div class="muted">{_escape(summary) if summary else 'No summary available.'}</div>
      {insights_html}
    </div>

    <div class="section-title">Runner</div>
    <div class="card">
      {runner_block if runner_block else '<div class="muted">No runner details available.</div>'}
    </div>

    {generated_html}

    {details_section}
  </div>
</body>
</html>"""


def generate_simple_html_report(job: MigrationResult, logs: List[str]) -> str:
    """Generate a comprehensive HTML migration report with links and automated data"""
    status_color = {
        'completed': '#48bb78',
        'failed': '#f56565',
        'running': '#ed8936'
    }.get(job.status, '#6b7280')

    # Determine if SonarQube quality gate passed (show green if PASSED)
    sonar_passed = job.sonar_quality_gate and job.sonar_quality_gate.upper() == "PASSED"
    sonar_color = "#22c55e" if sonar_passed else "#ef4444"

    # Unit test metrics: use real runner counts.
    total_tests = int(getattr(job, "tests_run", 0) or 0)
    passed_tests = int(getattr(job, "tests_passed", 0) or 0)
    failed_tests = int(getattr(job, "tests_failed", 0) or 0)
    if total_tests <= 0 and (passed_tests > 0 or failed_tests > 0):
        total_tests = passed_tests + failed_tests
    test_success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0.0

    # Create clickable repo links
    source_repo_link = f'<a href="{job.source_repo}" target="_blank" style="color: #2563eb; text-decoration: none;">{job.source_repo}</a>' if job.source_repo.startswith('http') else job.source_repo
    target_repo_link = ""
    if job.target_repo:
        if job.target_repo.startswith('http'):
            target_repo_link = f'<a href="{job.target_repo}" target="_blank" style="color: #22c55e; text-decoration: none;">{job.target_repo}</a>'
        elif job.target_repo.startswith('local://'):
            target_repo_link = f'<span style="color: #6b7280;">{job.target_repo.replace("local://", "Local: ")}</span>'
        else:
            target_repo_link = job.target_repo

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Java Migration Report - {job.job_id}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f8fafc;
            color: #1e293b;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
            font-weight: 700;
        }}
        .header p {{
            margin: 10px 0 0 0;
            opacity: 0.9;
            font-size: 1.1em;
        }}
        .section {{
            background: white;
            margin: 20px 0;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #e2e8f0;
        }}
        .section h2 {{
            margin-top: 0;
            color: #1e293b;
            font-size: 1.5em;
            font-weight: 600;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 10px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .metric-card {{
            background: #f8fafc;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            transition: transform 0.2s ease;
        }}
        .metric-card:hover {{
            transform: translateY(-2px);
        }}
        .metric-label {{
            font-size: 0.9em;
            color: #64748b;
            margin-bottom: 8px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .metric-value {{
            font-size: 2em;
            font-weight: 700;
            color: #1e293b;
        }}
        .status-badge {{
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .status-completed {{ background: #dcfce7; color: #166534; }}
        .status-failed {{ background: #fef2f2; color: #991b1b; }}
        .status-running {{ background: #fef3c7; color: #92400e; }}
        .logs {{
            background: #1e293b;
            color: #e2e8f0;
            padding: 20px;
            border-radius: 8px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 0.9em;
            max-height: 400px;
            overflow-y: auto;
            white-space: pre-wrap;
        }}
        .log-entry {{
            margin-bottom: 5px;
            padding: 2px 0;
        }}
        .test-summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .test-card {{
            text-align: center;
            padding: 15px;
            background: #f8fafc;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}
        .test-number {{
            font-size: 2em;
            font-weight: 700;
            color: #1e293b;
            display: block;
        }}
        .test-label {{
            font-size: 0.9em;
            color: #64748b;
            font-weight: 500;
            margin-top: 5px;
        }}
        .sonar-status {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9em;
        }}
        .sonar-passed {{ background: #dcfce7; color: #166534; }}
        .sonar-failed {{ background: #fef2f2; color: #991b1b; }}
        .repo-links {{
            background: #f8fafc;
            padding: 20px;
            border-radius: 8px;
            margin-top: 20px;
        }}
        .repo-links h3 {{
            margin-top: 0;
            color: #1e293b;
            font-size: 1.2em;
        }}
        .repo-link {{
            display: block;
            margin: 10px 0;
            padding: 10px 15px;
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            text-decoration: none;
            color: #2563eb;
            transition: all 0.2s ease;
        }}
        .repo-link:hover {{
            background: #eff6ff;
            border-color: #3b82f6;
        }}
        .success-rate {{
            font-size: 1.5em;
            font-weight: 700;
            color: {("#22c55e" if test_success_rate >= 80 else "#ef4444")};
        }}
        @media (max-width: 768px) {{
            .metrics-grid {{
                grid-template-columns: 1fr;
            }}
            .test-summary {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Java Migration Report</h1>
            <p>Job ID: {job.job_id}</p>
            <p>Status: <span class="status-badge status-{job.status.lower()}">{job.status.upper()}</span></p>
        </div>

        <div class="section">
            <h2>📊 Migration Summary</h2>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">Source Repository</div>
                    <div class="metric-value" style="font-size: 1em; word-break: break-all;">{source_repo_link}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Target Repository</div>
                    <div class="metric-value" style="font-size: 1em; word-break: break-all;">{target_repo_link or 'N/A'}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Java Version Migration</div>
                    <div class="metric-value">{job.source_java_version} → {job.target_java_version}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Files Modified</div>
                    <div class="metric-value">{job.files_modified}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Issues Fixed</div>
                    <div class="metric-value">{job.issues_fixed}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">SonarQube Quality Gate</div>
                    <div class="sonar-status sonar-{"passed" if sonar_passed else "failed"}">
                        {job.sonar_quality_gate or 'Not Run'}
                    </div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>🧪 Automated Test Results</h2>
            <div class="test-summary">
                <div class="test-card">
                    <span class="test-number">{total_tests}</span>
                    <div class="test-label">Total Tests</div>
                </div>
                <div class="test-card">
                    <span class="test-number" style="color: #22c55e;">{passed_tests}</span>
                    <div class="test-label">Tests Passed</div>
                </div>
                <div class="test-card">
                    <span class="test-number" style="color: #ef4444;">{failed_tests}</span>
                    <div class="test-label">Tests Failed</div>
                </div>
                <div class="test-card">
                    <span class="success-rate">{test_success_rate:.1f}%</span>
                    <div class="test-label">Success Rate</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>📋 Migration Logs</h2>
            <div class="logs">
"""

    # Add logs with better formatting
    for log in logs[-50:]:  # Show last 50 logs
        # Color code log levels
        if '[ERROR]' in log or 'ERROR:' in log:
            log_class = 'style="color: #ef4444;"'
        elif '[WARNING]' in log or 'WARNING:' in log:
            log_class = 'style="color: #f59e0b;"'
        elif '[SUCCESS]' in log or '✅' in log:
            log_class = 'style="color: #22c55e;"'
        else:
            log_class = ''

        html += f'<div class="log-entry" {log_class}>{log}</div>'

    html += """
            </div>
        </div>

        <div class="section">
            <h2>🔗 Repository Links</h2>
            <div class="repo-links">
                <h3>Quick Access Links</h3>
    """

    if job.source_repo and job.source_repo.startswith('http'):
        html += f'<a href="{job.source_repo}" target="_blank" class="repo-link">🔗 Source Repository: {job.source_repo}</a>'

    if job.target_repo and job.target_repo.startswith('http'):
        html += f'<a href="{job.target_repo}" target="_blank" class="repo-link">🎯 Target Repository: {job.target_repo}</a>'

    html += """
            </div>
        </div>
    </div>
</body>
</html>
"""

    return html

def _run_cmd(cwd: str, args: List[str]) -> Dict[str, Any]:
    import subprocess
    try:
        p = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
        )
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except Exception as exc:
        return {"ok": False, "code": -1, "stdout": "", "stderr": str(exc)}


def _normalize_git_path(path: str) -> str:
    return path.strip().strip('"').replace("\\", "/")


def _parse_git_status_change(line: str) -> Optional[Dict[str, str]]:
    if not line:
        return None

    if line.startswith("?? "):
        file_path = _normalize_git_path(line[3:])
        return {
            "file_path": file_path,
            "old_path": file_path,
            "change_type": "added",
        }

    if len(line) < 4:
        return None

    status = line[:2]
    path_part = line[3:].strip()
    old_path = None
    file_path = path_part

    if " -> " in path_part:
        old_path, file_path = path_part.split(" -> ", 1)

    normalized_old_path = _normalize_git_path(old_path or file_path)
    normalized_file_path = _normalize_git_path(file_path)
    status_flags = set(status.replace(" ", ""))

    if "D" in status_flags:
        change_type = "deleted"
    elif "A" in status_flags:
        change_type = "added"
    else:
        change_type = "modified"

    return {
        "file_path": normalized_file_path,
        "old_path": normalized_old_path,
        "change_type": change_type,
    }


def _read_git_revision_text(clone_path: str, git_path: str, file_path: str) -> str:
    result = _run_cmd(clone_path, [git_path, "show", f"HEAD:{_normalize_git_path(file_path)}"])
    return result["stdout"] if result.get("ok") else ""


def _read_working_tree_text(clone_path: str, file_path: str) -> str:
    full_path = os.path.join(clone_path, file_path.replace("/", os.sep))
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return ""

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def generate_repository_file_diffs(
    clone_path: str,
    max_files: Optional[int] = None,
    max_lines_per_diff: int = 240,
) -> List[FileDiffEntry]:
    import difflib
    import shutil

    git_path = shutil.which("git")
    if not git_path or not clone_path or not os.path.isdir(os.path.join(clone_path, ".git")):
        return []

    status = _run_cmd(
        clone_path,
        [git_path, "status", "--porcelain=v1", "--untracked-files=all"],
    )

    if not status.get("ok") or not status.get("stdout"):
        return []

    diffs: List[FileDiffEntry] = []

    status_lines = status["stdout"].splitlines()
    if max_files is not None:
        status_lines = status_lines[:max_files]

    for raw_line in status_lines:
        change = _parse_git_status_change(raw_line)
        if not change:
            continue

        file_path = change["file_path"]
        old_path = change["old_path"]
        change_type = change["change_type"]

        old_text = "" if change_type == "added" else _read_git_revision_text(clone_path, git_path, old_path)
        new_text = "" if change_type == "deleted" else _read_working_tree_text(clone_path, file_path)

        fromfile = "/dev/null" if change_type == "added" else f"a/{old_path}"
        tofile = "/dev/null" if change_type == "deleted" else f"b/{file_path}"
        diff_lines = [f"diff --git a/{old_path} b/{file_path}"]

        if old_path != file_path:
            diff_lines.append(f"rename from {old_path}")
            diff_lines.append(f"rename to {file_path}")

        if change_type == "added":
            diff_lines.append("new file mode 100644")
        elif change_type == "deleted":
            diff_lines.append("deleted file mode 100644")

        diff_lines.extend(
            list(
                difflib.unified_diff(
                    old_text.splitlines(),
                    new_text.splitlines(),
                    fromfile=fromfile,
                    tofile=tofile,
                    n=3,
                    lineterm="",
                )
            )
        )

        if not diff_lines:
            continue

        change_count = sum(
            1
            for diff_line in diff_lines
            if (diff_line.startswith("+") and not diff_line.startswith("+++"))
            or (diff_line.startswith("-") and not diff_line.startswith("---"))
        )

        visible_diff_lines = diff_lines
        if len(diff_lines) > max_lines_per_diff:
            visible_diff_lines = diff_lines[:max_lines_per_diff] + [
                f"@@ ... diff truncated after {max_lines_per_diff} lines ... @@"
            ]

        diffs.append(
            FileDiffEntry(
                file_path=file_path,
                diff="\n".join(visible_diff_lines),
                change_count=change_count,
            )
        )

    return diffs


def generate_testcase_doc_markdown(job: MigrationResult, clone_path: str) -> str:
    """
    Generates a single downloadable Markdown document that captures:
    - migration inputs and outputs
    - what changed (git status + diff)
    - generated tests/test plan artifacts (if any)
    """
    import shutil

    lines: List[str] = []
    lines.append(f"# Testcase and Change Report")
    lines.append("")
    lines.append(f"Job ID: `{job.job_id}`")
    lines.append(f"Status: `{job.status}`")
    lines.append(f"Generated At (UTC): `{datetime.now(timezone.utc).isoformat()}`")
    lines.append("")
    lines.append("## Migration Summary")
    lines.append(f"- Source repo: `{job.source_repo}`")
    lines.append(f"- Target repo: `{job.target_repo or ''}`")
    lines.append(f"- Source Java: `{job.source_java_version}`")
    lines.append(f"- Target Java: `{job.target_java_version}`")
    lines.append(f"- Conversion types: `{', '.join(job.conversion_types or [])}`")
    lines.append(f"- Files modified: `{job.files_modified}`")
    lines.append(f"- Issues fixed: `{job.issues_fixed}`")
    lines.append("")

    lines.append("## Test Results")
    lines.append(f"- Tests run: `{getattr(job, 'tests_run', 0)}`")
    lines.append(f"- Tests passed: `{getattr(job, 'tests_passed', 0)}`")
    lines.append(f"- Tests failed: `{getattr(job, 'tests_failed', 0)}`")
    if getattr(job, "test_llm_model", None):
        lines.append(f"- LLM model: `{job.test_llm_model}`")
    if getattr(job, "test_summary", None):
        lines.append("")
        lines.append("### LLM Summary")
        lines.append(job.test_summary)
    if getattr(job, "test_insights", None):
        insights = job.test_insights or []
        if insights:
            lines.append("")
            lines.append("### LLM Insights")
            for insight in insights[:50]:
                lines.append(f"- {insight}")
    lines.append("")

    # Include runner details if available (helps explain why tests are 0/0/0).
    runner = None
    if getattr(job, "test_pipeline", None) and getattr(job.test_pipeline, "runner", None):
        runner = job.test_pipeline.runner
    if isinstance(runner, dict) and runner:
        lines.append("### Test Runner")
        tool = runner.get("tool")
        exit_code = runner.get("exit_code")
        timed_out = runner.get("timed_out")
        parser = runner.get("parser")
        lines.append(f"- Tool: `{tool}`")
        lines.append(f"- Exit code: `{exit_code}`")
        lines.append(f"- Timed out: `{timed_out}`")
        if parser:
            lines.append(f"- Parser: `{parser}`")
        cmd = runner.get("cmd") or []
        if isinstance(cmd, list) and cmd:
            cmd_str = " ".join(str(x) for x in cmd)
            lines.append(f"- Command: `{cmd_str}`")

        reports = runner.get("reports") if isinstance(runner.get("reports"), dict) else None
        if reports:
            lines.append(f"- JUnit report files: `{reports.get('report_files_count', 0)}`")
            if reports.get("report_parse_errors"):
                lines.append(f"- JUnit report parse errors: `{len(reports.get('report_parse_errors') or [])}`")

    if getattr(job, "test_pipeline", None):
        tp = job.test_pipeline
        lines.append("## Generated Test Artifacts")
        lines.append(f"- Provider: `{tp.provider}`")
        lines.append(f"- Project kind: `{tp.project_kind}`")
        if getattr(tp, "test_strategy", None):
            lines.append(f"- Test strategy: `{tp.test_strategy}`")
        lines.append(f"- Existing test cases detected: `{getattr(tp, 'existing_tests_detected', 0)}`")
        lines.append(f"- Existing test cases migrated: `{len(getattr(tp, 'migrated_test_files', []) or [])}`")
        lines.append(f"- Generated tests: `{tp.generated_tests_relative}`")
        lines.append(f"- Test cases generated: `{len(tp.generated_test_files or [])}`")
        if tp.manual_test_plan_path:
            lines.append(f"- Manual test plan: `{tp.manual_test_plan_path}`")
        if tp.migration_patch_path:
            lines.append(f"- Migration patch diff: `{tp.migration_patch_path}`")
        if getattr(tp, "migrated_test_files", None):
            lines.append("")
            lines.append("### Migrated Existing Test Files")
            for p in (tp.migrated_test_files or [])[:200]:
                lines.append(f"- `{p}`")
        if tp.generated_test_files:
            lines.append("")
            lines.append("### Generated Test Files")
            for p in tp.generated_test_files[:200]:
                lines.append(f"- `{p}`")

        # Inline the generated manual test plan if available.
        if tp.manual_test_plan_path and os.path.exists(tp.manual_test_plan_path):
            try:
                plan_text = Path(tp.manual_test_plan_path).read_text(encoding="utf-8", errors="ignore")
                if plan_text.strip():
                    lines.append("")
                    lines.append("### Manual And Automation Test Plan (Generated)")
                    lines.append("```markdown")
                    lines.append(plan_text.strip()[:12000])
                    if len(plan_text) > 12000:
                        lines.append("\n...(truncated)...")
                    lines.append("```")
            except Exception:
                pass

        # Inline a snippet of generated tests so the doc shows what was added.
        if tp.generated_test_files:
            lines.append("")
            lines.append("### Generated Tests (Snippets)")
            for p in tp.generated_test_files[:8]:
                try:
                    if not p or not os.path.exists(p):
                        continue
                    txt = Path(p).read_text(encoding="utf-8", errors="ignore")
                    rel = ""
                    try:
                        rel = str(Path(p).resolve().relative_to(Path(clone_path).resolve()))
                    except Exception:
                        rel = os.path.basename(p)
                    fence = "java" if p.endswith(".java") else ""
                    lines.append(f"#### `{rel}`")
                    lines.append(f"```{fence}".rstrip())
                    lines.append(txt.strip()[:8000])
                    if len(txt) > 8000:
                        lines.append("\n...(truncated)...")
                    lines.append("```")
                except Exception:
                    continue
    lines.append("")

    lines.append("## What Changed (Before vs After)")
    stored_file_diffs = getattr(job, "file_diffs", None) or []
    git_path = shutil.which("git")
    if stored_file_diffs:
        total_additions = 0
        total_deletions = 0
        for file_diff in stored_file_diffs:
            diff_text = getattr(file_diff, "diff", "") or ""
            total_additions += sum(
                1
                for line in diff_text.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            total_deletions += sum(
                1
                for line in diff_text.splitlines()
                if line.startswith("-") and not line.startswith("---")
            )

        lines.append("### Captured Diff Summary")
        lines.append(f"- Files changed: `{len(stored_file_diffs)}`")
        lines.append(f"- Additions: `{total_additions}`")
        lines.append(f"- Deletions: `{total_deletions}`")
        lines.append("")
        lines.append("### Git Diff (Unified)")
        lines.append("```diff")
        for file_diff in stored_file_diffs:
            diff_text = getattr(file_diff, "diff", "") or ""
            if diff_text:
                lines.append(diff_text)
        lines.append("```")
        lines.append("")
    elif not git_path or not (clone_path and os.path.isdir(os.path.join(clone_path, ".git"))):
        lines.append("Git diff is unavailable for this run (missing git or .git directory).")
        lines.append("You can still download the migrated project ZIP to review changes.")
        lines.append("")
    else:
        status = _run_cmd(clone_path, [git_path, "status", "--porcelain=v1"])
        diff_stat = _run_cmd(clone_path, [git_path, "diff", "--stat"])
        diff = _run_cmd(clone_path, [git_path, "diff"])

        lines.append("### Git Status")
        lines.append("```")
        lines.append(status["stdout"] or "(clean)")
        lines.append("```")
        lines.append("")
        lines.append("### Git Diff Stat")
        lines.append("```")
        lines.append(diff_stat["stdout"] or "(no changes)")
        lines.append("```")
        lines.append("")
        lines.append("### Git Diff (Unified)")
        lines.append("```diff")
        # Allow large diffs; Markdown is the artifact, not an API response field.
        lines.append(diff["stdout"] or "")
        lines.append("```")
        lines.append("")

    if getattr(job, "migration_log", None):
        logs = job.migration_log or []
        lines.append("## Migration Log")
        lines.append("```")
        lines.extend(logs[-500:])
        lines.append("```")
        lines.append("")

    if getattr(job, "issues", None):
        issues = job.issues or []
        if issues:
            lines.append("## Known Issues")
            for issue in issues[:200]:
                where = f"{issue.file_path}:{issue.line_number or ''}".rstrip(":")
                lines.append(f"- [{issue.severity}] {issue.message} (`{where}`)")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def generate_testcase_doc_docx(job: MigrationResult, clone_path: str) -> str:
    """
    Writes a DOCX version of the testcase/change report and returns the filepath.
    DOCX can be opened in MS Word / Google Docs and exported as PDF.
    """
    import tempfile
    from docx import Document
    from docx.shared import Pt

    md = generate_testcase_doc_markdown(job, clone_path)
    doc = Document()

    def add_code_block(code: str):
        p = doc.add_paragraph()
        run = p.add_run(code)
        run.font.name = "Courier New"
        run.font.size = Pt(9)

    in_code = False
    code_lines: List[str] = []

    for raw in md.splitlines():
        line = raw.rstrip("\n")
        if line.strip().startswith("```"):
            if in_code:
                add_code_block("\n".join(code_lines).strip("\n"))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
        elif line.startswith("#### "):
            doc.add_heading(line[5:].strip(), level=4)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
        elif not line.strip():
            doc.add_paragraph("")
        else:
            doc.add_paragraph(line)

    if code_lines:
        add_code_block("\n".join(code_lines).strip("\n"))

    out = os.path.join(clone_path, "TESTCASE_AND_CHANGES.docx")
    try:
        doc.save(out)
        return out
    except Exception:
        # Fallback to temp dir if clone_path isn't writable for some reason.
        tmp = tempfile.gettempdir()
        out2 = os.path.join(tmp, f"TESTCASE_AND_CHANGES-{job.job_id}.docx")
        doc.save(out2)
        return out2

def calculate_duration(start_time, end_time):
    """Calculate duration between two timestamps"""
    if not start_time or not end_time:
        return "N/A"

    try:
        # Handle different time formats
        if hasattr(start_time, 'timestamp') and hasattr(end_time, 'timestamp'):
            duration = end_time - start_time
            total_seconds = int(duration.total_seconds())
        else:
            return "N/A"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    except:
        return "N/A"


# Version and Recipe Endpoints
@app.get("/api/java-versions")
async def get_java_versions():
    """Get supported Java versions for migration"""
    all_versions = [
        {"value": "7", "label": "Java 7"},
        {"value": "8", "label": "Java 8 (LTS)"},
        {"value": "9", "label": "Java 9"},
        {"value": "10", "label": "Java 10"},
        {"value": "11", "label": "Java 11 (LTS)"},
        {"value": "12", "label": "Java 12"},
        {"value": "13", "label": "Java 13"},
        {"value": "14", "label": "Java 14"},
        {"value": "15", "label": "Java 15"},
        {"value": "16", "label": "Java 16"},
        {"value": "17", "label": "Java 17 (LTS)"},
        {"value": "18", "label": "Java 18"},
        {"value": "19", "label": "Java 19"},
        {"value": "20", "label": "Java 20"},
        {"value": "21", "label": "Java 21 (LTS)"},
        {"value": "22", "label": "Java 22"},
        {"value": "23", "label": "Java 23"},
        {"value": "24", "label": "Java 24"},
        {"value": "25", "label": "Java 25 (LTS)"}
    ]
    return {
        "source_versions": all_versions,
        "target_versions": all_versions
    }


@app.post("/api/java-version-recommendation", response_model=JavaVersionRecommendationResponse)
async def get_java_version_recommendation(request: JavaVersionRecommendationRequest):
    """Recommend a target Java version using simple project heuristics."""
    supported_versions = ["8", "11", "17", "21", "22", "23", "24", "25"]
    lts_versions = ["8", "11", "17", "21", "25"]
    feature_release_versions = ["22", "23", "24"]

    def to_int(value: Optional[str]) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return 0

    def next_higher_versions(candidates: List[str]) -> List[str]:
        return [version for version in candidates if to_int(version) > source_version]

    def first_higher_version(candidates: List[str]) -> Optional[str]:
        for version in candidates:
            if to_int(version) > source_version:
                return version
        return None

    source_version = to_int(request.detected_java_version or request.source_java_version)
    dependency_count = len(request.dependencies or [])
    endpoint_count = max(0, request.api_endpoint_count or 0)
    risk_level = (request.risk_level or "").strip().lower()
    build_tool = (request.build_tool or "").strip().lower()

    spring_deps = 0
    legacy_deps = 0
    for dep in request.dependencies or []:
        dep_id = f"{dep.group_id}:{dep.artifact_id}".lower()
        if "spring" in dep_id:
            spring_deps += 1
        if any(token in dep_id for token in ["log4j", "javax", "junit", "hibernate", "tomcat"]):
            legacy_deps += 1

    recommended_target = "17"
    confidence = "medium"
    rationale: List[str] = []
    alternatives: List[str] = []
    alternative_options: List[JavaVersionAlternativeOption] = []

    if source_version >= 21:
        recommended_target = "25"
        confidence = "high"
        rationale.append("Project is already on Java 21, so Java 25 is the next LTS upgrade target.")
    elif source_version >= 17:
        recommended_target = "21"
        confidence = "high"
        rationale.append("Project is already on a modern Java baseline, so moving to Java 21 is a low-friction upgrade.")
    elif source_version >= 11:
        recommended_target = "17"
        confidence = "high"
        rationale.append("Java 17 is a stable LTS target with broad ecosystem support for Java 11+ projects.")
    else:
        recommended_target = "17"
        rationale.append("Java 17 is the safest default LTS landing zone for legacy Java applications.")

    if risk_level in {"high", "critical"}:
        safest_lts_target = first_higher_version(["17", "21", "25"])
        if safest_lts_target:
            recommended_target = safest_lts_target
            confidence = "high"
            rationale.append(
                f"High-risk projects are best modernized toward the nearest higher LTS release, so Java {safest_lts_target} is recommended."
            )
    elif build_tool == "gradle" and source_version >= 21 and dependency_count <= 20 and endpoint_count <= 20:
        recommended_target = "25"
        confidence = "high"
        rationale.append("The project appears modern enough that Java 25 is a practical next-step LTS target.")
    elif build_tool == "gradle" and source_version >= 17 and dependency_count <= 20 and endpoint_count <= 20:
        recommended_target = "21"
        confidence = "medium"
        rationale.append("The project appears modern enough that Java 21 is a reasonable next-step LTS target.")

    if spring_deps >= 3 and source_version >= 21 and risk_level not in {"high", "critical"}:
        recommended_target = "25"
        rationale.append("A Spring-heavy codebase already on Java 21 can benefit from targeting Java 25 LTS.")
    elif spring_deps >= 3 and source_version >= 11 and risk_level not in {"high", "critical"}:
        recommended_target = "21"
        rationale.append("A Spring-heavy codebase with a reasonably modern baseline can benefit from targeting Java 21 LTS.")

    if legacy_deps >= 3:
        conservative_target = first_higher_version(["17", "21", "25"])
        if conservative_target:
            recommended_target = conservative_target
            confidence = "high"
            rationale.append(
                f"Several legacy dependencies were detected, so Java {conservative_target} is the lowest-risk higher LTS target."
            )

    if request.has_tests:
        rationale.append("Existing test coverage lowers migration risk and supports a more confident upgrade path.")
    else:
        rationale.append("Limited test coverage suggests choosing a conservative LTS version first.")

    ordered_alternative_candidates = next_higher_versions(["17", "21", "25", "24", "23", "22"])

    for candidate in ordered_alternative_candidates:
        if candidate == recommended_target:
            continue
        alternatives.append(candidate)

    for version in alternatives[:2]:
        risk = "medium"
        reason = "Viable alternative depending on ecosystem compatibility."
        if version == "17":
            risk = "low"
            reason = "Most conservative LTS option with strong library support."
        elif version == "21":
            risk = "medium"
            reason = "Modern LTS option with newer platform features."
        elif version == "25":
            risk = "medium"
            reason = "Latest LTS option with the longest current support horizon."
        elif version == "24":
            risk = "high"
            reason = "Recent feature release; use only if your toolchain already supports Java 24."
        elif version == "23":
            risk = "high"
            reason = "Feature release, not LTS; use only if your toolchain fully supports it."
        elif version == "22":
            risk = "high"
            reason = "Older feature release, not LTS; typically choose an LTS target instead."
        alternative_options.append(
            JavaVersionAlternativeOption(version=version, risk=risk, reason=reason)
        )

    if not alternatives:
        alternatives = next_higher_versions(lts_versions)
        if recommended_target in alternatives:
            alternatives = [version for version in alternatives if version != recommended_target]
        if not alternatives:
            alternatives = next_higher_versions(feature_release_versions)
        if alternatives:
            alternative_options = [
                JavaVersionAlternativeOption(
                    version=alternatives[0],
                    risk="low" if alternatives[0] == "17" else "medium" if alternatives[0] in {"21", "25"} else "high",
                    reason=(
                        "Fallback alternative based on supported LTS releases."
                        if alternatives[0] in {"17", "21", "25"}
                        else "Fallback alternative based on supported feature releases."
                    ),
                )
            ]

    ordered_recommendations = [recommended_target] + [
        version for version in supported_versions
        if version != recommended_target and version in alternatives
    ]

    return JavaVersionRecommendationResponse(
        recommended_target_version=recommended_target,
        recommended_versions=ordered_recommendations,
        confidence=confidence,
        rationale=rationale,
        alternatives=alternatives,
        alternative_options=alternative_options,
        raw_recommendation={
            "source_java_version": request.source_java_version,
            "detected_java_version": request.detected_java_version,
            "build_tool": request.build_tool,
            "dependency_count": dependency_count,
            "api_endpoint_count": endpoint_count,
            "risk_level": request.risk_level,
            "has_tests": request.has_tests,
            "spring_dependency_count": spring_deps,
            "legacy_dependency_count": legacy_deps,
        },
    )


@app.get("/api/openrewrite/recipes")
async def get_available_recipes():
    """Get available OpenRewrite recipes for migration"""
    return migration_service.get_available_recipes()


@app.get("/api/conversion-types")
async def get_conversion_types():
    """Get available conversion types for migration"""
    return [
        {
            "id": "java_version",
            "name": "Java Version Upgrade",
            "description": "Upgrade Java version (e.g., Java 8 → Java 17)",
            "category": "Language",
            "icon": "☕"
        },
        {
            "id": "maven_to_gradle",
            "name": "Maven → Gradle",
            "description": "Convert Maven (pom.xml) to Gradle (build.gradle)",
            "category": "Build Tool",
            "icon": "🔧"
        },
        {
            "id": "gradle_to_maven",
            "name": "Gradle → Maven",
            "description": "Convert Gradle (build.gradle) to Maven (pom.xml)",
            "category": "Build Tool",
            "icon": "🔧"
        },
        {
            "id": "javax_to_jakarta",
            "name": "javax → Jakarta EE",
            "description": "Migrate javax.* packages to jakarta.* (EE 8 → EE 9+)",
            "category": "Framework",
            "icon": "📦"
        },
        {
            "id": "jakarta_to_javax",
            "name": "Jakarta EE → javax",
            "description": "Migrate jakarta.* packages back to javax.*",
            "category": "Framework",
            "icon": "📦"
        },
        {
            "id": "spring_boot_2_to_3",
            "name": "Spring Boot 2 → 3",
            "description": "Upgrade Spring Boot 2.x to 3.x with Jakarta EE",
            "category": "Framework",
            "icon": "🌱"
        },
        {
            "id": "junit_4_to_5",
            "name": "JUnit 4 → JUnit 5",
            "description": "Migrate JUnit 4 tests to JUnit 5 (Jupiter)",
            "category": "Testing",
            "icon": "✅"
        },
        {
            "id": "log4j_to_slf4j",
            "name": "Log4j → SLF4J",
            "description": "Migrate Log4j to SLF4J logging facade",
            "category": "Logging",
            "icon": "📝"
        }
    ]


async def run_migration(job_id: str, request: MigrationRequest):
    """Background task to run the full migration pipeline"""
    job = migration_jobs[job_id]

    try:
        # Determine which service to use based on platform
        if request.platform == GitPlatform.GITLAB:
            repo_service = gitlab_service
            source_token = (request.token or "").strip()
        else:  # GitHub is default
            repo_service = github_service
            source_token = _effective_github_token(token=request.token or "", github_token=request.github_token or "")

        # Step 1: Prepare source working copy
        update_job(job_id, MigrationStatus.CLONING, 5, "Preparing source project...")
        clone_path = await _prepare_source_working_copy(
            request.source_repo_url,
            repo_service,
            source_token,
        )
        add_log(job_id, f"Source project prepared at {clone_path}")
        job.clone_path = clone_path
        
        # Step 2: Analyze project and detect initial issues
        update_job(job_id, MigrationStatus.ANALYZING, 15, "Analyzing project structure and detecting issues...")
        analysis = await migration_service.analyze_project(clone_path)
        job.api_endpoints = analysis.get("api_endpoints", []) or []

        # Convert dependencies dicts to DependencyInfo objects
        deps = analysis.get("dependencies", [])
        job.dependencies = [
            DependencyInfo(
                group_id=d.get("group_id", ""),
                artifact_id=d.get("artifact_id", ""),
                current_version=d.get("current_version", ""),
                new_version=d.get("new_version"),
                status=d.get("status", "analyzing")
            ) for d in deps
        ]
        
        # Generate initial issues based on selected conversions
        initial_issues = generate_migration_issues(
            clone_path, 
            request.conversion_types,
            request.source_java_version,
            request.target_java_version.value
        )
        job.issues = initial_issues
        job.total_errors = len([i for i in initial_issues if i.severity == IssueSeverity.ERROR])
        job.total_warnings = len([i for i in initial_issues if i.severity == IssueSeverity.WARNING])
        add_log(job_id, f"Found {job.total_errors} errors, {job.total_warnings} warnings to process")
        
        # Step 3: Run migrations for each selected conversion type
        progress = 30
        for conv_type in request.conversion_types:
            update_job(job_id, MigrationStatus.MIGRATING, progress, f"Running {conv_type} migration...")
            add_log(job_id, f"Processing conversion: {conv_type}")
    
            """
            if conv_type == "java_version":
                migration_result = await migration_service.run_migration(
                    clone_path,
                    request.source_java_version,
                    request.target_java_version.value,
                    request.fix_business_logic
                )
            else:
                migration_result = await migration_service.run_conversion(
                    clone_path,
                    conv_type
                )
            """

            # build tools code
            
            if conv_type == "java_version":
                migration_result = await migration_service.run_migration(
                    clone_path,
                    request.source_java_version,
                    request.target_java_version.value,
                    request.fix_business_logic
                )
            elif conv_type in ["maven_to_gradle", "gradle_to_maven"]:
                build_file = "pom.xml" if conv_type == "maven_to_gradle" else "build.gradle"
                target_file = "build.gradle" if conv_type == "maven_to_gradle" else "pom.xml"
                build_file_path = os.path.join(clone_path, build_file)
                
                if os.path.exists(build_file_path):
                    add_log(job_id, f"Translating {build_file} to {target_file} via AI...")
                    with open(build_file_path, "r", encoding="utf-8") as f:
                        build_content = f.read()
                    
                    try:
                        # 1. Ask Hugging Face to translate it
                        converted = await migration_service.convert_build_file_with_llm(
                            build_content=build_content,
                            conversion_type=conv_type,
                            detected_build_tool=request.build_tool
                        )
                        # 2. Save the new build file
                        with open(os.path.join(clone_path, target_file), "w", encoding="utf-8") as f:
                            f.write(converted)
                        """    
                        # 3. Safely delete the old structure
                        os.remove(build_file_path)
                        """
                        # 3. Safely delete the old structure and stray wrappers
                        os.remove(build_file_path)
                        
                        if conv_type == "maven_to_gradle":
                            # Clean up Maven remnants
                            for f in ["mvnw", "mvnw.cmd"]:
                                fp = os.path.join(clone_path, f)
                                if os.path.exists(fp): os.remove(fp)
                            if os.path.exists(os.path.join(clone_path, ".mvn")):
                                shutil.rmtree(os.path.join(clone_path, ".mvn"), ignore_errors=True)
                                
                        elif conv_type == "gradle_to_maven":
                            # Clean up Gradle remnants
                            for f in ["gradlew", "gradlew.bat", "gradle.bat", "settings.gradle", "settings.gradle.kts"]:
                                fp = os.path.join(clone_path, f)
                                if os.path.exists(fp): os.remove(fp)
                            if os.path.exists(os.path.join(clone_path, "gradle")):
                                shutil.rmtree(os.path.join(clone_path, "gradle"), ignore_errors=True)

                        
                        add_log(job_id, f"Successfully created {target_file}")
                        migration_result = {"files_modified": 1, "issues_fixed": 0}
                    except Exception as e:
                        add_log(job_id, f"ERROR in build conversion: {str(e)}")
                        migration_result = {"files_modified": 0, "issues_fixed": 0}
                else:
                    add_log(job_id, f"Skipping {conv_type}: {build_file} not found in project.")
                    migration_result = {"files_modified": 0, "issues_fixed": 0}
            else:
                migration_result = await migration_service.run_conversion(
                    clone_path,
                    conv_type
                )

            # Update fixed issues
            fixed_count = migration_result.get("issues_fixed", 0)
            job.files_modified += migration_result.get("files_modified", 0)
            job.issues_fixed += fixed_count
            
            # Mark issues as fixed
            mark_issues_fixed(job, conv_type, fixed_count)
            
            progress += 10
        
        add_log(job_id, f"Modified {job.files_modified} files, fixed {job.issues_fixed} issues")
        job.errors_fixed = len([i for i in job.issues if i.severity == IssueSeverity.ERROR and i.status == IssueStatus.FIXED])
        job.warnings_fixed = len([i for i in job.issues if i.severity == IssueSeverity.WARNING and i.status == IssueStatus.FIXED])
        
  # Step 4: Run tests
        if request.run_tests:
            update_job(job_id, MigrationStatus.TESTING, 60, "Running tests and validating APIs...")
            llm_provider = request.llm_test_provider or "fordllm"
            use_llm_tests = getattr(request, "use_llm_tests", True)
            test_result = await migration_service.run_tests(
                    clone_path,
                llm_provider=llm_provider,
                use_llm_tests=use_llm_tests
            )
            job.api_endpoints_validated = test_result.get("total_endpoints", 0)
            job.api_endpoints_working = test_result.get("working_endpoints", 0)
            job.tests_run = test_result.get("tests_run", 0)
            job.tests_passed = test_result.get("tests_passed", 0)
            job.tests_failed = test_result.get("tests_failed", 0)
            job.test_summary = test_result.get("test_summary")
            job.test_insights = test_result.get("test_insights") or []
            # migration_service returns this key; keep backward compatibility if older callers used test_model_used.
            job.test_llm_model = test_result.get("test_llm_model") or test_result.get("test_model_used")

            # Preserve the full pipeline artifact paths for downloadable documentation.
            pipeline = test_result.get("llm_pipeline") or {}
            if isinstance(pipeline, dict) and pipeline:
                try:
                    job.test_pipeline = TestPipelineReport(
                        provider=pipeline.get("provider", llm_provider),
                        project_kind=pipeline.get("project_kind", ""),
                        generated_tests_relative=pipeline.get("generated_tests_relative", ""),
                        test_strategy=pipeline.get("test_strategy"),
                        existing_tests_detected=int(pipeline.get("existing_tests_detected", 0) or 0),
                        existing_test_files=pipeline.get("existing_test_files", []) or [],
                        migrated_test_files=pipeline.get("migrated_test_files", []) or [],
                        generated_test_files=pipeline.get("generated_test_files", []) or [],
                        runner=pipeline.get("runner", {}) or {},
                        manual_test_plan_path=pipeline.get("manual_test_plan_path"),
                        migration_patch_path=pipeline.get("migration_patch_path"),
                        deepeval_result=pipeline.get("deepeval"),
                        garak_result=pipeline.get("garak"),
                        coverage_result=pipeline.get("coverage"),
                    )
                except Exception as exc:
                    add_log(job_id, f"WARNING: Failed to map test pipeline report: {exc}")
            if job.test_summary:
                add_log(job_id, f"LLM Test Summary: {job.test_summary}")
            if job.test_pipeline:
                try:
                    add_log(
                        job_id,
                        "Test Strategy: "
                        f"{getattr(job.test_pipeline, 'test_strategy', 'unknown')} "
                        f"(existing={getattr(job.test_pipeline, 'existing_tests_detected', 0)} "
                        f"migrated={len(getattr(job.test_pipeline, 'migrated_test_files', []) or [])} "
                        f"generated={len(getattr(job.test_pipeline, 'generated_test_files', []) or [])})"
                    )
                except Exception:
                    pass
            runner = test_result.get("runner") or {}
            if isinstance(runner, dict) and runner:
                try:
                    cmd = runner.get("cmd") or []
                    cmd_str = " ".join(str(x) for x in cmd[:10]) if isinstance(cmd, list) else str(cmd)
                    add_log(
                        job_id,
                        f"Test Runner: tool={runner.get('tool')} exit={runner.get('exit_code')} "
                        f"run={runner.get('tests_run')} pass={runner.get('tests_passed')} fail={runner.get('tests_failed')} "
                        f"timeout={runner.get('timed_out')} cmd={cmd_str}"
                    )
                except Exception:
                    pass
            add_log(job_id, f"Tests: {job.api_endpoints_working}/{job.api_endpoints_validated} endpoints working")
        
        # Step 5: SonarQube analysis
        if request.run_sonar:
            update_job(job_id, MigrationStatus.SONAR_ANALYSIS, 75, "Running SonarQube code quality analysis...")
            try:
                sonar_result = await sonarqube_service.analyze_project(
                    clone_path,
                    source_reference=request.source_repo_url,
                    build_tool=request.build_tool,
                )
                job.sonar_report = sonar_result
                job.sonar_quality_gate = sonar_result.get("quality_gate", "N/A")
                job.sonar_bugs = int(sonar_result.get("bugs", 0) or 0)
                job.sonar_vulnerabilities = int(sonar_result.get("vulnerabilities", 0) or 0)
                job.sonar_code_smells = int(sonar_result.get("code_smells", 0) or 0)
                job.sonar_coverage = float(sonar_result.get("coverage", 0.0) or 0.0)
                job.sonar_duplications = float(sonar_result.get("duplications", 0.0) or 0.0)
                job.sonar_security_hotspots = int(sonar_result.get("security_hotspots", 0) or 0)
                job.sonar_scan_mode = sonar_result.get("scan_mode")
                job.sonar_real_scan = bool(sonar_result.get("real_scan"))
                job.sonar_analysis_url = sonar_result.get("analysis_url")
                job.sonar_error_message = sonar_result.get("error_message")
                add_log(
                    job_id,
                    f"Sonar: mode={job.sonar_scan_mode} gate={job.sonar_quality_gate} "
                    f"bugs={job.sonar_bugs} vuln={job.sonar_vulnerabilities} smells={job.sonar_code_smells}"
                )
            except Exception as sonar_err:
                job.sonar_quality_gate = "UNAVAILABLE"
                job.sonar_bugs = 0
                job.sonar_vulnerabilities = 0
                job.sonar_code_smells = 0
                job.sonar_coverage = 0.0
                job.sonar_duplications = 0.0
                job.sonar_security_hotspots = 0
                job.sonar_scan_mode = "unavailable"
                job.sonar_real_scan = False
                job.sonar_analysis_url = None
                job.sonar_error_message = str(sonar_err)
                job.sonar_report = {
                    "scan_mode": "unavailable",
                    "real_scan": False,
                    "simulated": False,
                    "ready": False,
                    "quality_gate": "UNAVAILABLE",
                    "bugs": 0,
                    "vulnerabilities": 0,
                    "code_smells": 0,
                    "coverage": 0.0,
                    "duplications": 0.0,
                    "security_hotspots": 0,
                    "analysis_url": None,
                    "error_message": str(sonar_err),
                }
                add_log(job_id, f"SONAR ERROR: {str(sonar_err)}")

        # Step 5b: FOSSA analysis (optional)
        if getattr(request, 'run_fossa', False):
            update_job(job_id, MigrationStatus.FOSSA_ANALYSIS, 80, "Running FOSSA license & dependency scan...")
            try:
                fossa_result = await fossa_service.analyze_project(
                    clone_path,
                    source_reference=request.source_repo_url,
                )
                job.fossa_report = fossa_result
                job.fossa_policy_status = fossa_result.get('compliance_status') or fossa_result.get('policy_status')
                job.fossa_total_dependencies = int(fossa_result.get('total_dependencies', 0) or 0)
                job.fossa_scan_mode = fossa_result.get('scan_mode')
                job.fossa_real_scan = bool(fossa_result.get('real_scan'))
                job.fossa_analysis_url = fossa_result.get('analysis_url')
                job.fossa_error_message = fossa_result.get('error_message')

                license_map = fossa_result.get('licenses') or {}
                if isinstance(fossa_result.get('license_issues'), int):
                    job.fossa_license_issues = int(fossa_result.get('license_issues', 0) or 0)
                elif isinstance(license_map, dict):
                    job.fossa_license_issues = int(license_map.get('UNKNOWN', 0) or 0)
                else:
                    job.fossa_license_issues = int(fossa_result.get('license_issues', 0) or 0)

                vulns = fossa_result.get('vulnerabilities') or {}
                if isinstance(vulns, dict):
                    job.fossa_vulnerabilities = sum(int(v or 0) for v in vulns.values())
                else:
                    job.fossa_vulnerabilities = int(fossa_result.get('vulnerabilities', 0) or 0)

                if isinstance(fossa_result.get('dependencies'), list):
                    job.fossa_outdated_dependencies = sum(1 for d in fossa_result.get('dependencies', []) if d.get('status') in ('outdated', 'out-of-date') or d.get('outdated') is True)
                else:
                    job.fossa_outdated_dependencies = int(fossa_result.get('outdated_dependencies', 0) or 0)

                add_log(
                    job_id,
                    f"FOSSA: mode={job.fossa_scan_mode} policy={job.fossa_policy_status} deps={job.fossa_total_dependencies} vuln={job.fossa_vulnerabilities}"
                )
            except Exception as fossa_err:
                job.fossa_scan_mode = "unavailable"
                job.fossa_real_scan = False
                job.fossa_policy_status = "UNAVAILABLE"
                job.fossa_error_message = str(fossa_err)
                job.fossa_report = {
                    "scan_mode": "unavailable",
                    "real_scan": False,
                    "simulated": False,
                    "ready": False,
                    "analysis_url": None,
                    "compliance_status": "UNAVAILABLE",
                    "licenses": {},
                    "license_issues": 0,
                    "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                    "vulnerability_details": [],
                    "dependencies": [],
                    "total_dependencies": 0,
                    "outdated_dependencies": 0,
                    "error_message": str(fossa_err),
                }
                add_log(job_id, f"FOSSA ERROR: {str(fossa_err)}")

        if request.migration_type == "microservices":
            update_job(job_id, MigrationStatus.ANALYZING, 85, "Converting monolith to microservices architecture...")
            try:
                if _is_local_project_reference(request.source_repo_url):
                    workspace = RepositoryWorkspace(
                        repo_url=request.source_repo_url,
                        normalized_repo_url=request.source_repo_url,
                        owner="local",
                        repo=os.path.basename(clone_path.rstrip("/\\")) or "local-project",
                        workspace_path=clone_path,
                        default_branch="local",
                        cache_key="local",
                        auth_scope_key="local",
                    )
                else:
                    workspace = RepositoryWorkspace(
                        repo_url=request.source_repo_url,
                        normalized_repo_url=request.source_repo_url,
                        owner="",
                        repo=os.path.basename(clone_path.rstrip("/\\")) or "repo",
                        workspace_path=clone_path,
                        default_branch="main",
                        cache_key="remote",
                        auth_scope_key="public",
                    )

                # Run readiness analysis first
                add_log(job_id, "Running microservice readiness analysis...")
                microservice_report = await microservice_readiness_service.analyze_repository(workspace, analysis)
                candidates = getattr(microservice_report, "serviceCandidates", []) or []
                add_log(job_id, f"Readiness analysis found {len(candidates)} service candidates: {[c.name for c in candidates] if candidates else 'None'}")

                # Run full microservice conversion (LLM-powered + scaffolding)
                add_log(job_id, "Generating independent Spring Boot microservice projects...")
                conversion_result = await microservice_conversion_service.convert(
                    source_path=clone_path,
                    readiness_report=microservice_report,
                )
                job.microservice_output_path = conversion_result.output_path
                add_log(job_id, conversion_result.summary)
                add_log(job_id, f"Services created: {', '.join(conversion_result.services_created)}")
                add_log(job_id, f"Docker Compose: {conversion_result.docker_compose_path}")
                add_log(job_id, f"Microservice output path: {conversion_result.output_path}")

                # ── CRITICAL: Replace clone_path contents with the microservices output ──
                # This ensures the ZIP download, push, and local-publish all serve
                # the microservices architecture regardless of which code path is used.
                ms_out = conversion_result.output_path
                if ms_out and os.path.isdir(ms_out):
                    # Wipe the old monolithic contents from clone_path (keep .git)
                    for item in os.listdir(clone_path):
                        if item == ".git":
                            continue
                        item_path = os.path.join(clone_path, item)
                        try:
                            safe_path = ("\\\\?\\" + os.path.abspath(item_path)) if os.name == "nt" else item_path
                            if os.path.isdir(item_path):
                                shutil.rmtree(safe_path)
                            else:
                                os.remove(safe_path)
                        except Exception:
                            pass
                    # Copy all microservice output into clone_path
                    def _long_path_copy_tree(src_dir, dst_dir):
                        """Copy directory tree with Windows long-path support."""
                        errors = []
                        for dirpath, dirnames, filenames in os.walk(src_dir):
                            rel = os.path.relpath(dirpath, src_dir)
                            target_dir = os.path.join(dst_dir, rel)
                            # Use \\?\ prefix for long paths on Windows
                            safe_target = ("\\\\?\\" + os.path.abspath(target_dir)) if os.name == "nt" and len(target_dir) > 240 else target_dir
                            os.makedirs(safe_target, exist_ok=True)
                            for fn in filenames:
                                s = os.path.join(dirpath, fn)
                                d = os.path.join(target_dir, fn)
                                safe_s = ("\\\\?\\" + os.path.abspath(s)) if os.name == "nt" and len(s) > 240 else s
                                safe_d = ("\\\\?\\" + os.path.abspath(d)) if os.name == "nt" and len(d) > 240 else d
                                try:
                                    shutil.copy2(safe_s, safe_d)
                                except Exception as e:
                                    errors.append((s, d, str(e)))
                        return errors

                    for item in os.listdir(ms_out):
                        src_item = os.path.join(ms_out, item)
                        dst_item = os.path.join(clone_path, item)
                        try:
                            if os.path.isdir(src_item):
                                copy_errors = _long_path_copy_tree(src_item, dst_item)
                                if copy_errors:
                                    add_log(job_id, f"WARNING: {len(copy_errors)} files in {item} had long-path copy issues (skipped)")
                            else:
                                shutil.copy2(src_item, dst_item)
                        except Exception as cp_err:
                            add_log(job_id, f"WARNING: Could not copy {item}: {cp_err}")
                    add_log(job_id, f"✅ Replaced monolithic project with microservices architecture in {clone_path}")
                    # Also point microservice_output_path to clone_path now
                    job.microservice_output_path = clone_path
                else:
                    add_log(job_id, f"WARNING: Microservice output dir not found at {ms_out}")

                # Also store service details in job metadata for the frontend
                if job.extra_metadata is None:
                    job.extra_metadata = {}
                job.extra_metadata["microservice_services"] = conversion_result.service_details
                job.extra_metadata["microservice_summary"] = conversion_result.summary

            except Exception as microservice_err:
                import traceback
                tb = traceback.format_exc()
                add_log(job_id, f"WARNING: Microservice conversion failed: {microservice_err}")
                add_log(job_id, f"Traceback: {tb[-500:]}")
                logger.exception("Microservice conversion error")
                job.microservice_output_path = None

        migration_file_diffs: List[FileDiffEntry] = []
        try:
            migration_file_diffs = generate_repository_file_diffs(clone_path)
            add_log(job_id, f"Captured {len(migration_file_diffs)} file diffs for the migration report")
        except Exception as diff_err:
            add_log(job_id, f"WARNING: Failed to capture file diffs: {diff_err}")

        # Step 6: Create new repo and push (use default token if not provided)
        from datetime import datetime
        if _is_local_project_reference(request.source_repo_url):
            source_repo_name = _infer_local_project_name(request.source_repo_url)
        else:
            source_owner, source_repo_name = await repo_service.parse_repo_url(request.source_repo_url)
        now = datetime.now().strftime("%Y%m%d-%H%M%S")
        migration_approach = (request.migration_approach or "fork").strip().lower()
        requested_target_value = (request.target_repo_name or "").strip()
        target_repo_owner, target_repo_name = _parse_target_repository_destination(
            requested_target_value,
            default_owner="Javaapex",
        )
        target_repo_name = target_repo_name or f"{source_repo_name}-migrated-java{request.target_java_version.value}-{now}"
        target_branch_name = requested_target_value or f"migration/{source_repo_name}-Migrated{now.replace('-', '')}"
        target_local_folder_name = _sanitize_local_publish_folder_name(
            requested_target_value,
            f"{source_repo_name}-Migrated",
        )

        # Use user token or fall back to default token
        github_token = _effective_github_token(token=request.token or "", github_token=request.github_token or "")
        using_user_token = bool(_first_nonempty_token(request.github_token or "", request.token or ""))
        add_log(job_id, f"Using GitHub token: {'user-provided' if using_user_token else 'default'}")
        
        # Push migrated code to the selected target
        push_status_message = (
            f"Pushing migrated code to branch '{target_branch_name}'..."
            if migration_approach == "branch"
            else f"Saving migrated code to local folder '{target_local_folder_name}'..."
            if migration_approach == "local"
            else "Creating new repository and pushing migrated code..."
        )
        update_job(job_id, MigrationStatus.PUSHING, 90, push_status_message)
        try:
            if migration_approach == "branch":
                target_branch_url = await repo_service.push_to_branch(
                    github_token,
                    request.source_repo_url,
                    clone_path,
                    target_branch_name,
                )
                job.target_repo = target_branch_url
                add_log(job_id, f"✅ Pushed migrated code to branch: {target_branch_url}")
            elif migration_approach == "local":
                old_clone_path = clone_path
                local_target_path = _publish_migrated_project_locally(
                    clone_path,
                    requested_target_value,
                    f"{source_repo_name}-Migrated",
                )
                clone_path = local_target_path
                job.clone_path = local_target_path
                job.target_repo = f"local://{local_target_path}"
                # If microservice_output_path was inside the old clone dir, update it
                if getattr(job, 'microservice_output_path', None) and job.microservice_output_path:
                    old_ms_path = job.microservice_output_path
                    if old_ms_path.startswith(old_clone_path):
                        relative = os.path.relpath(old_ms_path, old_clone_path)
                        job.microservice_output_path = os.path.join(local_target_path, relative)
                        add_log(job_id, f"Updated microservice output path: {job.microservice_output_path}")
                add_log(job_id, f"Saved migrated code to local folder: {local_target_path}")
            else:
                if request.platform == GitPlatform.GITHUB:
                    new_repo_url = await repo_service.create_and_push_repo(
                        github_token,
                        target_repo_name,
                        clone_path,
                        f"Migrated from {request.source_repo_url} (Java {request.source_java_version} → Java {request.target_java_version.value})",
                        owner=target_repo_owner,
                    )
                else:
                    new_repo_url = await repo_service.create_and_push_repo(
                        github_token,
                        target_repo_name,
                        clone_path,
                        f"Migrated from {request.source_repo_url} (Java {request.source_java_version} → Java {request.target_java_version.value})",
                    )
                job.target_repo = new_repo_url
                add_log(job_id, f"✅ Created new repository: {new_repo_url}")
        except Exception as push_error:
            add_log(job_id, f"⚠️ GitHub push failed: {str(push_error)}")
            add_log(job_id, f"📁 Migrated code saved locally at: {clone_path}")
            job.target_repo = f"local://{clone_path}"

        job.file_diffs = migration_file_diffs
        
        # Generate a single testcase + change doc for download and long-term audit.
        try:
            doc_md = generate_testcase_doc_markdown(job, clone_path)
            doc_path = os.path.join(clone_path, "TESTCASE_AND_CHANGES.md")
            with open(doc_path, "w", encoding="utf-8") as f:
                f.write(doc_md)
            job.testcase_doc_path = doc_path
            add_log(job_id, f"Testcase doc generated at: {doc_path}")
        except Exception as doc_err:
            add_log(job_id, f"WARNING: Failed to generate testcase doc: {doc_err}")
        
        # Step 7: Send email notification
        if request.email and request.email.strip():
            success = await email_service.send_migration_summary(request.email.strip(), job)
            if success:
                add_log(job_id, f"Migration summary sent to {request.email}")
            else:
                add_log(job_id, f"Failed to send migration summary to {request.email}")

        # Complete
        update_job(job_id, MigrationStatus.COMPLETED, 100, "Migration completed successfully!")
        job.completed_at = datetime.now(timezone.utc)
        save_migration_job(job)
        
    except Exception as e:
        import traceback
        job.status = MigrationStatus.FAILED
        job.error_message = str(e)
        error_traceback = traceback.format_exc()
        add_log(job_id, f"ERROR: {str(e)}")
        add_log(job_id, f"TRACEBACK: {error_traceback}")
        save_migration_job(job)
        logger.error(f"Migration {job_id} failed: {str(e)}")
        logger.error(f"Traceback: {error_traceback}")


def generate_migration_issues(
    project_path: str,
    conversion_types: List[str],
    source_version: str,
    target_version: str
) -> List[MigrationIssue]:
    """Scan project and generate REAL migration issues based on code analysis"""
    issues = []
    issue_id = 0
    
    # Find ALL Java directories - not just standard Maven structure
    java_dirs = []
    
    # Standard Maven/Gradle structure
    src_main = os.path.join(project_path, "src", "main", "java")
    src_test = os.path.join(project_path, "src", "test", "java")
    if os.path.exists(src_main):
        java_dirs.append(src_main)
    if os.path.exists(src_test):
        java_dirs.append(src_test)
    
    # Also check root src folder (some projects use src/)
    src_root = os.path.join(project_path, "src")
    if os.path.exists(src_root) and src_root not in java_dirs:
        java_dirs.append(src_root)
    
    # Check for any java files directly in project root (standalone Java files!)
    java_dirs.append(project_path)
    
    source = int(source_version)
    target = int(target_version)
    
    print(f"Scanning directories: {java_dirs}")
    
    # Define patterns to search for based on conversion types
    patterns = {}
    
    if "java_version" in conversion_types:
        patterns["java_version"] = [
            # Deprecated primitive constructors
            (r'new Integer\s*\(', "error", "Deprecated Method", "new Integer() is deprecated - use Integer.valueOf()"),
            (r'new Long\s*\(', "error", "Deprecated Method", "new Long() is deprecated - use Long.valueOf()"),
            (r'new Double\s*\(', "error", "Deprecated Method", "new Double() is deprecated - use Double.valueOf()"),
            (r'new Boolean\s*\(', "error", "Deprecated Method", "new Boolean() is deprecated - use Boolean.valueOf()"),
            (r'new Float\s*\(', "error", "Deprecated Method", "new Float() is deprecated - use Float.valueOf()"),
            (r'new Character\s*\(', "error", "Deprecated Method", "new Character() is deprecated - use Character.valueOf()"),
            (r'new Byte\s*\(', "error", "Deprecated Method", "new Byte() is deprecated - use Byte.valueOf()"),
            (r'new Short\s*\(', "error", "Deprecated Method", "new Short() is deprecated - use Short.valueOf()"),
            # Deprecated reflection
            (r'\.newInstance\s*\(\s*\)', "error", "Deprecated Method", "Class.newInstance() is deprecated - use getDeclaredConstructor().newInstance()"),
            # Old date/time
            (r'new Date\s*\(\s*\)', "warning", "Deprecated API", "Consider using java.time.LocalDateTime instead of java.util.Date"),
            (r'SimpleDateFormat', "warning", "Thread Safety", "SimpleDateFormat is not thread-safe - consider DateTimeFormatter"),
            (r'java\.util\.Date', "warning", "Deprecated API", "Consider migrating to java.time API (LocalDate, LocalDateTime)"),
            (r'java\.util\.Calendar', "warning", "Deprecated API", "Consider migrating to java.time API"),
            # Raw types and generics
            (r'(?<![<\w])List\s+\w+\s*=', "warning", "Type Safety", "Raw type usage detected - use generics List<T>"),
            (r'(?<![<\w])Map\s+\w+\s*=', "warning", "Type Safety", "Raw type usage detected - use generics Map<K,V>"),
            (r'(?<![<\w])Set\s+\w+\s*=', "warning", "Type Safety", "Raw type usage detected - use generics Set<T>"),
            (r'(?<![<\w])ArrayList\s+\w+\s*=', "warning", "Type Safety", "Raw type usage detected - use ArrayList<T>"),
            (r'(?<![<\w])HashMap\s+\w+\s*=', "warning", "Type Safety", "Raw type usage detected - use HashMap<K,V>"),
            (r'(?<![<\w])HashSet\s+\w+\s*=', "warning", "Type Safety", "Raw type usage detected - use HashSet<T>"),
            (r'(?<![<\w])Vector\s+\w+\s*=', "warning", "Type Safety", "Vector is legacy - use ArrayList<T> instead"),
            (r'(?<![<\w])Hashtable\s+\w+\s*=', "warning", "Type Safety", "Hashtable is legacy - use HashMap<K,V> instead"),
            # Scanner without resource management
            (r'new Scanner\s*\([^)]*\)\s*;', "warning", "Resource Management", "Scanner should be in try-with-resources for automatic closing"),
            # Old IO patterns
            (r'FileInputStream|FileOutputStream|FileReader|FileWriter', "warning", "Resource Management", "Consider using try-with-resources and Files.* methods"),
            # String concatenation issues
            (r'\+\s*"\s*"|\"\s*"\s*\+', "info", "Performance", "Empty string concatenation detected - can be simplified"),
            # Exception handling
            (r'catch\s*\(\s*Exception\s+\w+\s*\)', "warning", "Code Quality", "Catching generic Exception - consider specific exception types"),
            (r'catch\s*\(\s*Throwable\s+\w+\s*\)', "warning", "Code Quality", "Catching Throwable includes Errors - use Exception instead"),
            (r'e\.printStackTrace\s*\(\s*\)', "warning", "Code Quality", "printStackTrace() - consider proper logging instead"),
            # Null safety
            (r'\.equals\s*\(\s*null\s*\)', "error", "Null Safety", ".equals(null) always false - use == null check"),
            # Swing/AWT thread safety
            (r'extends\s+JFrame|extends\s+JPanel', "info", "Thread Safety", "Swing component - ensure EDT usage for thread safety"),
        ]
        
        if target >= 9:
            patterns["java_version"].extend([
                (r'sun\.misc\.', "error", "Removed Class", "sun.misc.* classes removed in Java 9+ - use standard alternatives"),
                (r'sun\.reflect\.', "error", "Removed Class", "sun.reflect.* classes removed - use java.lang.reflect"),
            ])
        
        if target >= 11:
            patterns["java_version"].extend([
                (r'\.trim\(\)\.isEmpty\(\)', "info", "Modern API", "Can use String.isBlank() (Java 11+) for whitespace check"),
                (r'\.trim\(\)\.length\(\)\s*==\s*0', "info", "Modern API", "Can use String.isBlank() (Java 11+)"),
            ])
        
        if target >= 17:
            patterns["java_version"].extend([
                (r'import\s+javax\.swing\.', "info", "Modern API", "Swing still works in Java 17, but consider JavaFX for new UIs"),
            ])
    
    if "javax_to_jakarta" in conversion_types or (target >= 17 and "java_version" in conversion_types):
        patterns["javax_to_jakarta"] = [
            (r'import javax\.servlet\.', "error", "Package Migration", "javax.servlet.* → jakarta.servlet.* (required for Java 17+/Spring Boot 3)"),
            (r'import javax\.persistence\.', "error", "Package Migration", "javax.persistence.* → jakarta.persistence.* (required for Java 17+)"),
            (r'import javax\.validation\.', "error", "Package Migration", "javax.validation.* → jakarta.validation.* (required for Java 17+)"),
            (r'import javax\.annotation\.', "warning", "Package Migration", "javax.annotation.* → jakarta.annotation.* (recommended for Java 17+)"),
            (r'import javax\.inject\.', "error", "Package Migration", "javax.inject.* → jakarta.inject.* (required for Jakarta EE)"),
            (r'import javax\.ws\.rs\.', "error", "Package Migration", "javax.ws.rs.* → jakarta.ws.rs.* (required for JAX-RS 3.x)"),
        ]
    
    if "spring_boot_2_to_3" in conversion_types:
        patterns["spring_boot_2_to_3"] = [
            (r'WebSecurityConfigurerAdapter', "error", "Security Config", "WebSecurityConfigurerAdapter removed in Spring Security 6 - use SecurityFilterChain"),
            (r'@EnableGlobalMethodSecurity', "warning", "Security Config", "@EnableGlobalMethodSecurity deprecated - use @EnableMethodSecurity"),
            (r'antMatchers', "error", "Security Config", "antMatchers() removed - use requestMatchers()"),
            (r'mvcMatchers', "error", "Security Config", "mvcMatchers() removed - use requestMatchers()"),
        ]
    
    if "junit_4_to_5" in conversion_types:
        patterns["junit_4_to_5"] = [
            (r'import org\.junit\.Test;', "error", "Import Change", "org.junit.Test → org.junit.jupiter.api.Test"),
            (r'import org\.junit\.Before;', "warning", "Import Change", "@Before → @BeforeEach (JUnit 5)"),
            (r'import org\.junit\.After;', "warning", "Import Change", "@After → @AfterEach (JUnit 5)"),
            (r'import org\.junit\.BeforeClass;', "warning", "Import Change", "@BeforeClass → @BeforeAll (JUnit 5)"),
            (r'import org\.junit\.Ignore;', "warning", "Import Change", "@Ignore → @Disabled (JUnit 5)"),
            (r'@RunWith', "warning", "Annotation Change", "@RunWith → @ExtendWith (JUnit 5)"),
        ]
    
    if "log4j_to_slf4j" in conversion_types:
        patterns["log4j_to_slf4j"] = [
            (r'import org\.apache\.log4j\.', "error", "Import Change", "org.apache.log4j.* → org.slf4j.* (SLF4J facade)"),
            (r'Logger\.getLogger\s*\(', "error", "Logger Factory", "Logger.getLogger() → LoggerFactory.getLogger()"),
        ]
    
    # Scan all Java files in all discovered directories
    scanned_files = set()  # Track to avoid duplicates
    
    for src_dir in java_dirs:
        if not os.path.exists(src_dir):
            continue
        
        for root, dirs, files in os.walk(src_dir):
            # Skip hidden directories and common non-source directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'build', 'out', 'node_modules']]
            for file in files:
                if file.endswith('.java'):
                    filepath = os.path.join(root, file)
                    
                    # Skip if already scanned (avoid duplicates when scanning overlapping dirs)
                    if filepath in scanned_files:
                        continue
                    scanned_files.add(filepath)
                    
                    relative_path = os.path.relpath(filepath, project_path)
                    
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()
                        
                        for conv_type, pattern_list in patterns.items():
                            for pattern, severity, category, message in pattern_list:
                                for line_num, line in enumerate(lines, 1):
                                    if re.search(pattern, line):
                                        issue_id += 1
                                        issues.append(MigrationIssue(
                                            id=f"ISS-{issue_id:04d}",
                                            severity=IssueSeverity(severity),
                                            status=IssueStatus.DETECTED,
                                            category=category,
                                            message=message,
                                            file_path=relative_path,
                                            line_number=line_num,
                                            code_snippet=line.strip()[:100],
                                            conversion_type=conv_type if conv_type in conversion_types else "java_version"
                                        ))
                                        break  # Only one issue per pattern per file
                    
                    except Exception as e:
                        print(f"Error scanning {filepath}: {e}")
    
    # Also check pom.xml for dependency issues
    pom_path = os.path.join(project_path, "pom.xml")
    if os.path.exists(pom_path):
        try:
            with open(pom_path, 'r', encoding='utf-8') as f:
                pom_lines = f.readlines()
            
            for line_num, line in enumerate(pom_lines, 1):
                # Check for old Spring Boot version
                if 'spring-boot' in line.lower() and re.search(r'<version>2\.[0-9]', line):
                    issue_id += 1
                    issues.append(MigrationIssue(
                        id=f"ISS-{issue_id:04d}",
                        severity=IssueSeverity.WARNING,
                        status=IssueStatus.DETECTED,
                        category="Dependency Update",
                        message="Spring Boot 2.x should be upgraded to 3.x for Java 17+",
                        file_path="pom.xml",
                        line_number=line_num,
                        conversion_type="java_version"
                    ))
        except:
            pass
    
    return issues


def mark_issues_fixed(job: MigrationResult, conversion_type: str, count: int):
    """Mark ALL issues as fixed for a specific conversion type (migration fixes them)"""
    for issue in job.issues:
        if issue.conversion_type == conversion_type:
            issue.status = IssueStatus.FIXED
            issue.fixed_at = datetime.now(timezone.utc)


def update_job(job_id: str, status: MigrationStatus, progress: int, step: str):
    """Update job status"""
    if job_id in migration_jobs:
        job = migration_jobs[job_id]
        job.status = status
        job.progress_percent = progress
        job.current_step = step
        save_migration_job(job)
        add_log(job_id, step)


def add_log(job_id: str, message: str):
    """Add a log message to the job"""
    if job_id in migration_jobs:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        job = migration_jobs[job_id]
        job.migration_log.append(f"[{timestamp}] {message}")
        save_migration_job(job)


@app.get("/{full_path:path}")
async def frontend_app(full_path: str):
    if full_path.startswith("api/") or full_path in {"health", "docs", "openapi.json", "redoc"}:
        raise HTTPException(status_code=404, detail="Not found")
    return serve_frontend_path(full_path)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        app,
        host=host,
        port=port,
        limit_max_requests=None,
        timeout_keep_alive=300,
        timeout_graceful_shutdown=30,
        h11_max_incomplete_event_size=1073741824,
    )

"""
# new end point for maven to gradle conversion

@app.post("/api/standalone/convert-build")
async def standalone_convert_build(request: BuildConversionRequest):
    Standalone endpoint for direct AI build conversion without running a full migration job.
    try:
        # Call the LLM directly via MigrationService
        converted_code = await migration_service.convert_build_file_with_llm(
            build_content=request.build_content,
            conversion_type=request.conversion_type
        )
        return {"success": True, "converted_content": converted_code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""
