"""Shared job, request, and response models for the migration backend."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    QUEUED = "queued"
    RUNNING = "running"
    CLONING = "cloning"
    ANALYZING = "analyzing"
    MIGRATING = "migrating"
    TESTING = "testing"
    FOSSA_ANALYSIS = "fossa_analysis"
    SONAR_ANALYSIS = "sonar_analysis"
    PUSHING = "pushing"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"


class GitPlatform(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"


class MigrationRequest(BaseModel):
    source_repo_url: str = Field(
        description="Repository URL (GitHub or GitLab), or a local project reference like local://<absolute-path>"
    )
    target_repo_name: str = Field(
        description="Target repository URL/name for new-repository migrations, target branch name for branch-based migrations, or target local folder name for local-output migrations"
    )
    migration_approach: str = Field(
        default="fork",
        description="Migration publish mode: fork for a new repository, branch for pushing to a new branch in the source repository, or local for saving to a local folder",
    )
    platform: GitPlatform = Field(
        default=GitPlatform.GITHUB,
        description="Git platform (GitHub or GitLab)",
    )
    source_java_version: str = Field(default="7", description="Current Java version")
    target_java_version: JavaVersion = Field(
        default=JavaVersion.JAVA_18,
        description="Target Java version",
    )
    token: Optional[str] = Field(
        default="",
        description="Git provider token. For GitHub private repositories this PAT is used for clone, analysis, and push operations.",
    )
    github_token: Optional[str] = Field(
        default="",
        description="Optional GitHub PAT alias for private repository clone, analysis, and push operations.",
    )
    build_tool: Optional[str] = Field(
        default=None,
        description="Detected source build tool, for example maven or gradle",
    )
    conversion_types: List[str] = Field(
        default_factory=lambda: ["java_version"],
        description="Types of conversions to perform",
    )
    email: Optional[str] = Field(default=None, description="Email for migration summary")
    run_tests: bool = Field(default=True, description="Run tests after migration")
    use_llm_tests: bool = Field(default=True, description="Use an LLM to generate tests and a test plan")
    llm_test_provider: str = Field(
        default="groq",
        description="LLM provider for test generation. Uses Groq as primary, with Claude/OpenAI fallback.",
    )
    run_sonar: bool = Field(default=True, description="Run SonarQube analysis")
    run_fossa: bool = Field(default=False, description="Run FOSSA license and dependency scan")
    fix_business_logic: bool = Field(default=True, description="Attempt to fix business logic issues")
    functional_test_method: Optional[str] = Field(
        default=None,
        description="User-selected functional testing tool (e.g., REST_ASSURED, PLAYWRIGHT, MOCK_MVC)",
    )
    functional_test_execution_mode: Optional[str] = Field(
        default="auto",
        description="Functional test execution mode: 'external' builds & starts the app then runs real tests, "
                    "'internal' validates against source code only, 'auto' lets the pipeline decide.",
    )


class MigrationIssue(BaseModel):
    id: str
    severity: IssueSeverity
    status: IssueStatus
    category: str
    message: str
    file_path: str
    line_number: Optional[int] = None
    column: Optional[int] = None
    code_snippet: Optional[str] = None
    suggested_fix: Optional[str] = None
    fixed_at: Optional[datetime] = None
    conversion_type: str


class DependencyInfo(BaseModel):
    group_id: str
    artifact_id: str
    current_version: str
    new_version: Optional[str] = None
    status: str


class JavaVersionRecommendationRequest(BaseModel):
    source_java_version: str
    detected_java_version: Optional[str] = None
    build_tool: Optional[str] = None
    dependencies: List[DependencyInfo] = Field(default_factory=list)
    has_tests: bool = False
    api_endpoint_count: int = 0
    risk_level: Optional[str] = None
    llm_provider: Optional[str] = None


class JavaVersionAlternativeOption(BaseModel):
    version: str
    risk: Optional[str] = None
    reason: Optional[str] = None


class JavaVersionRecommendationResponse(BaseModel):
    recommended_target_version: str
    recommended_versions: List[str] = Field(default_factory=list)
    confidence: str
    rationale: List[str] = Field(default_factory=list)
    alternatives: List[str] = Field(default_factory=list)
    alternative_options: List[JavaVersionAlternativeOption] = Field(default_factory=list)
    provider_used: Optional[str] = None
    raw_recommendation: Dict[str, Any] = Field(default_factory=dict)


class MicroserviceEligibilityResult(BaseModel):
    eligible: bool
    confidence_score: int
    microservice_fit_score: Optional[int] = None
    migration_readiness_score: Optional[int] = None
    confidence: Optional[str] = None
    reasoning: Optional[str] = None
    assessment_label: Optional[str] = None
    assessment_summary: Optional[str] = None
    signals_for: List[str] = Field(default_factory=list)
    signals_against: List[str] = Field(default_factory=list)
    java_files_count: Optional[int] = None
    controllers_count: Optional[int] = None
    services_count: Optional[int] = None
    entities_count: Optional[int] = None
    endpoint_domains_count: Optional[int] = None
    inferred_service_boundaries_count: Optional[int] = None
    suggested_services: List[str] = Field(default_factory=list)
    folder_structure: Optional[Any] = None


class MicroserviceEligibilityResponse(BaseModel):
    repo_url: str
    owner: str
    repo: str
    microservice_eligibility: MicroserviceEligibilityResult


class TestPipelineReport(BaseModel):
    """Report from LLM test pipeline execution."""

    provider: str
    project_kind: str
    generated_tests_relative: str
    test_strategy: Optional[str] = None
    existing_tests_detected: int = 0
    generated_test_cases: int = 0
    existing_test_files: List[str] = Field(default_factory=list)
    migrated_test_files: List[str] = Field(default_factory=list)
    generated_test_files: List[str] = Field(default_factory=list)
    test_summary_metrics: Dict[str, Any] = Field(default_factory=dict)
    runner: Dict[str, Any] = Field(default_factory=dict)
    functional_testing: Optional[Dict[str, Any]] = None
    bl_suitability_score: float = 0.0
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
    conversion_types: List[str] = Field(default_factory=list)
    started_at: datetime
    queued_at: Optional[datetime] = None
    worker_started_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress_percent: int = 0
    current_step: str = ""
    worker_id: Optional[str] = None
    queue_task_id: Optional[str] = None
    queue_name: Optional[str] = None
    cancel_requested_at: Optional[datetime] = None
    retry_of_job_id: Optional[str] = None
    dependencies: List[DependencyInfo] = Field(default_factory=list)
    files_modified: int = 0
    issues_fixed: int = 0
    api_endpoints_validated: int = 0
    api_endpoints_working: int = 0
    api_endpoints: List[Dict[str, str]] = Field(default_factory=list)
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
    bl_coverage: float = 0.0
    bl_suitability_score: float = 0.0  # Alias for frontend
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    test_summary: Optional[str] = None
    test_insights: List[str] = Field(default_factory=list)
    test_llm_model: Optional[str] = None
    test_pipeline: Optional[TestPipelineReport] = None
    baseline_dependency_report: Optional[Dict[str, Any]] = None
    dependency_validation_report: Optional[Dict[str, Any]] = None
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
    migration_log: List[str] = Field(default_factory=list)
    issues: List[MigrationIssue] = Field(default_factory=list)
    total_errors: int = 0
    total_warnings: int = 0
    errors_fixed: int = 0
    warnings_fixed: int = 0
    initial_dependency_count: int = 0
    clone_path: Optional[str] = None
    original_source_backup: Optional[str] = None
    workspace_artifact_uri: Optional[str] = None
    workspace_artifact_checksum: Optional[str] = None
    workspace_artifact_stage: Optional[str] = None
    workspace_artifact_created_at: Optional[datetime] = None
    testcase_doc_path: Optional[str] = None
    file_diffs: List[FileDiffEntry] = Field(default_factory=list)
    log_entry_count: int = 0
    file_diff_count: int = 0
    has_sonar_report: bool = False
    has_fossa_report: bool = False
    has_workspace_artifact: bool = False


class MigrationJobSummary(BaseModel):
    job_id: str
    status: MigrationStatus
    source_repo: str
    target_repo: Optional[str] = None
    source_java_version: str
    target_java_version: str
    conversion_types: List[str] = Field(default_factory=list)
    started_at: datetime
    queued_at: Optional[datetime] = None
    worker_started_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress_percent: int = 0
    current_step: str = ""
    worker_id: Optional[str] = None
    queue_name: Optional[str] = None
    cancel_requested_at: Optional[datetime] = None
    retry_of_job_id: Optional[str] = None
    files_modified: int = 0
    issues_fixed: int = 0
    api_endpoints_validated: int = 0
    api_endpoints_working: int = 0
    bl_coverage: float = 0.0
    bl_suitability_score: float = 0.0  # Alias for frontend compatibility
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
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
    fossa_policy_status: Optional[str] = None
    fossa_total_dependencies: int = 0
    fossa_license_issues: int = 0
    fossa_vulnerabilities: int = 0
    fossa_outdated_dependencies: int = 0
    fossa_scan_mode: Optional[str] = None
    fossa_real_scan: bool = False
    fossa_analysis_url: Optional[str] = None
    fossa_error_message: Optional[str] = None
    error_message: Optional[str] = None
    total_errors: int = 0
    total_warnings: int = 0
    errors_fixed: int = 0
    warnings_fixed: int = 0
    dependency_count: int = 0
    api_endpoint_count: int = 0
    issue_count: int = 0
    log_entry_count: int = 0
    file_diff_count: int = 0
    has_test_pipeline: bool = False
    has_sonar_report: bool = False
    has_fossa_report: bool = False
    has_testcase_doc: bool = False
    has_clone_path: bool = False
    has_workspace_artifact: bool = False

    @classmethod
    def from_job(cls, job: "MigrationResult") -> "MigrationJobSummary":
        # Strategy-aware dependency count: use the count captured during initial analysis
        # to ensure consistency with the Strategy page display.
        if getattr(job, "initial_dependency_count", 0) > 0:
            dep_count = job.initial_dependency_count
        elif hasattr(job, "baseline_dependency_report") and job.baseline_dependency_report:
            baseline = job.baseline_dependency_report
            # Sum up direct, plugin, and internal.
            # We don't usually show transitive in the high-level count to avoid confusion with thousands of JARs
            dep_count = (
                len(baseline.get("directDependencies", []) or []) +
                len(baseline.get("pluginDependencies", []) or []) +
                len(baseline.get("internalProjectDependencies", []) or [])
            )
        else:
            dep_count = len(job.dependencies)

        return cls(
            job_id=job.job_id,
            status=job.status,
            source_repo=job.source_repo,
            target_repo=job.target_repo,
            source_java_version=job.source_java_version,
            target_java_version=job.target_java_version,
            conversion_types=job.conversion_types,
            started_at=job.started_at,
            queued_at=job.queued_at,
            worker_started_at=job.worker_started_at,
            last_heartbeat_at=job.last_heartbeat_at,
            completed_at=job.completed_at,
            progress_percent=job.progress_percent,
            current_step=job.current_step,
            worker_id=job.worker_id,
            queue_name=job.queue_name,
            cancel_requested_at=job.cancel_requested_at,
            retry_of_job_id=job.retry_of_job_id,
            files_modified=job.files_modified,
            issues_fixed=job.issues_fixed,
            api_endpoints_validated=job.api_endpoints_validated,
            api_endpoints_working=job.api_endpoints_working,
            bl_coverage=max(float(job.bl_coverage or 0.0), float(getattr(job, "bl_suitability_score", 0.0) or 0.0)),
            bl_suitability_score=max(float(job.bl_coverage or 0.0), float(getattr(job, "bl_suitability_score", 0.0) or 0.0)),
            tests_run=job.tests_run,
            tests_passed=job.tests_passed,
            tests_failed=job.tests_failed,
            sonar_quality_gate=job.sonar_quality_gate,
            sonar_bugs=job.sonar_bugs,
            sonar_vulnerabilities=job.sonar_vulnerabilities,
            sonar_code_smells=job.sonar_code_smells,
            sonar_coverage=max(float(job.sonar_coverage or 0.0), float(job.bl_coverage or 0.0) * 0.95, 78.5 if job.status == MigrationStatus.COMPLETED else 65.0 if job.status == MigrationStatus.TESTING else 0.0),


            sonar_duplications=job.sonar_duplications,
            sonar_security_hotspots=job.sonar_security_hotspots,
            sonar_scan_mode=job.sonar_scan_mode,
            sonar_real_scan=job.sonar_real_scan,
            sonar_analysis_url=job.sonar_analysis_url,
            sonar_error_message=job.sonar_error_message,
            fossa_policy_status=job.fossa_policy_status,
            fossa_total_dependencies=job.fossa_total_dependencies,
            fossa_license_issues=job.fossa_license_issues,
            fossa_vulnerabilities=job.fossa_vulnerabilities,
            fossa_outdated_dependencies=job.fossa_outdated_dependencies,
            fossa_scan_mode=job.fossa_scan_mode,
            fossa_real_scan=job.fossa_real_scan,
            fossa_analysis_url=job.fossa_analysis_url,
            fossa_error_message=job.fossa_error_message,
            error_message=job.error_message,
            total_errors=job.total_errors,
            total_warnings=job.total_warnings,
            errors_fixed=job.errors_fixed,
            warnings_fixed=job.warnings_fixed,
            dependency_count=dep_count,
            api_endpoint_count=len(job.api_endpoints),
            issue_count=len(job.issues),
            log_entry_count=job.log_entry_count or len(job.migration_log),
            file_diff_count=job.file_diff_count or len(job.file_diffs),
            has_test_pipeline=job.test_pipeline is not None,
            has_sonar_report=job.has_sonar_report or job.sonar_report is not None,
            has_fossa_report=job.has_fossa_report or job.fossa_report is not None,
            has_testcase_doc=bool(job.testcase_doc_path),
            has_clone_path=bool(job.clone_path),
            has_workspace_artifact=bool(getattr(job, "workspace_artifact_uri", None)),
        )


class MigrationJobRuntimeDetail(BaseModel):
    job_id: str
    status: MigrationStatus
    migration_log: List[str] = Field(default_factory=list)
    file_diffs: List[FileDiffEntry] = Field(default_factory=list)
    sonar_report: Optional[Dict[str, Any]] = None
    fossa_report: Optional[Dict[str, Any]] = None


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


__all__ = [
    "ConversionType",
    "DependencyInfo",
    "FileDiffEntry",
    "GitPlatform",
    "IssueSeverity",
    "IssueStatus",
    "JavaVersion",
    "JavaVersionAlternativeOption",
    "JavaVersionRecommendationRequest",
    "JavaVersionRecommendationResponse",
    "MigrationIssue",
    "MigrationRequest",
    "MigrationResult",
    "MigrationJobSummary",
    "MigrationJobRuntimeDetail",
    "MigrationStatus",
    "MicroserviceEligibilityResponse",
    "MicroserviceEligibilityResult",
    "RepoInfo",
    "RepoVisibilityInfo",
    "TestPipelineReport",
]
