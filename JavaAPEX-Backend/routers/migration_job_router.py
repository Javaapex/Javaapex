"""Core migration job lifecycle endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from models.job_models import DependencyInfo, MigrationJobSummary, MigrationRequest, MigrationResult, MigrationStatus, TestPipelineReport
from utils.logging_utils import logging_context

logger = logging.getLogger(__name__)


def create_migration_job_router(
    *,
    artifact_service: Any,
    fossa_service: Any,
    job_queue: Any,
    job_service: Any,
    migration_service: Any,
    run_migration: Callable[[str, MigrationRequest], Awaitable[None]],
    allow_in_process_fallback: bool = True,
    force_in_process_execution: bool = False,
) -> APIRouter:
    router = APIRouter(tags=["migration-jobs"])

    async def refresh_job_fossa_report_if_needed(job: MigrationResult) -> None:
        if not job.fossa_report:
            return

        if not fossa_service.should_refresh_report_details(job.fossa_report):
            return

        refreshed_report = await fossa_service.refresh_report_details(
            job.fossa_report,
            analysis_url=getattr(job, "fossa_analysis_url", None) or job.fossa_report.get("analysis_url"),
            project_path=artifact_service.resolve_clone_path(job) or "",
        )
        job.fossa_report = refreshed_report
        job.fossa_policy_status = refreshed_report.get("compliance_status") or refreshed_report.get("policy_status")
        job.fossa_total_dependencies = int(refreshed_report.get("total_dependencies", 0) or 0)
        job.fossa_scan_mode = refreshed_report.get("scan_mode")
        job.fossa_real_scan = bool(refreshed_report.get("real_scan"))
        job.fossa_analysis_url = refreshed_report.get("analysis_url")
        job.fossa_error_message = refreshed_report.get("error_message")
        job.fossa_license_issues = int(refreshed_report.get("license_issues", 0) or 0)

        refreshed_vulnerabilities = refreshed_report.get("vulnerabilities") or {}
        if isinstance(refreshed_vulnerabilities, dict):
            job.fossa_vulnerabilities = sum(int(value or 0) for value in refreshed_vulnerabilities.values())
        else:
            job.fossa_vulnerabilities = int(refreshed_report.get("vulnerabilities", 0) or 0)

        job.fossa_outdated_dependencies = int(refreshed_report.get("outdated_dependencies", 0) or 0)
        job_service.save_job(job)

    def merge_dependency_upgrade_records(job: MigrationResult, updated_dependencies: List[dict[str, Any]]) -> None:
        if not updated_dependencies:
            return

        for updated_dependency in updated_dependencies:
            group_id = updated_dependency.get("group_id", "")
            artifact_id = updated_dependency.get("artifact_id", "")
            new_version = updated_dependency.get("new_version")
            current_version = updated_dependency.get("current_version", "")
            if not group_id or not artifact_id or not new_version:
                continue

            existing_dependency = next(
                (
                    dependency
                    for dependency in getattr(job, "dependencies", [])
                    if dependency.group_id == group_id and dependency.artifact_id == artifact_id
                ),
                None,
            )
            if existing_dependency is not None:
                existing_dependency.new_version = new_version
                existing_dependency.status = "upgraded"
                if current_version and not existing_dependency.current_version:
                    existing_dependency.current_version = current_version
                continue

            job.dependencies.append(
                DependencyInfo(
                    group_id=group_id,
                    artifact_id=artifact_id,
                    current_version=current_version,
                    new_version=new_version,
                    status="upgraded",
                )
            )

    @router.post("/migration/start", response_model=MigrationResult)
    async def start_migration(request: MigrationRequest, background_tasks: BackgroundTasks):
        """Start a new migration job."""
        job_id = str(uuid.uuid4())
        with logging_context(job_id=job_id):
            started_at = datetime.now(timezone.utc)
            if force_in_process_execution:
                job = MigrationResult(
                    job_id=job_id,
                    status=MigrationStatus.PENDING,
                    source_repo=request.source_repo_url,
                    source_java_version=request.source_java_version,
                    target_java_version=request.target_java_version.value,
                    conversion_types=request.conversion_types,
                    started_at=started_at,
                    queued_at=None,
                    current_step="Initializing migration...",
                )
                job_service.save_job(job)
                job_service.add_log(
                    job_id,
                    "Running migration directly in-process because FORCE_IN_PROCESS_MIGRATION is enabled.",
                )
                logger.warning(
                    "Bypassing worker queue and running migration in-process because force_in_process_execution is enabled."
                )
                background_tasks.add_task(run_migration, job_id, request)
                return job

            job = MigrationResult(
                job_id=job_id,
                status=MigrationStatus.QUEUED,
                source_repo=request.source_repo_url,
                source_java_version=request.source_java_version,
                target_java_version=request.target_java_version.value,
                conversion_types=request.conversion_types,
                started_at=started_at,
                queued_at=started_at,
                current_step="Queued for worker execution...",
            )
            job_service.save_job(job)
            logger.info("Queued migration job source=%s", request.source_repo_url)
            try:
                queued_task = job_queue.enqueue_migration(job_id, request)
                job_service.record_enqueue(
                    job_id,
                    task_id=queued_task.task_id,
                    queue_name=queued_task.queue_name,
                    queued_at=job.queued_at,
                )
                return job_service.require_job_detail(job_id)
            except Exception as exc:
                if not allow_in_process_fallback:
                    raise HTTPException(status_code=503, detail=f"Worker queue unavailable: {exc}") from exc

                logger.warning("Falling back to in-process migration execution because worker queue is unavailable: %s", exc)
                job.status = MigrationStatus.PENDING
                job.queued_at = None
                job.current_step = "Initializing migration..."
                job_service.save_job(job)
                background_tasks.add_task(run_migration, job_id, request)
                return job

    @router.get("/migration/{job_id}", response_model=MigrationJobSummary)
    async def get_migration_status(job_id: str):
        """Get the lightweight status of a migration job."""
        return job_service.get_job_summary(job_id)

    @router.get("/migration/{job_id}/detail", response_model=MigrationResult)
    async def get_migration_detail(job_id: str):
        """Get the detailed migration payload for a migration job."""
        job = job_service.require_job(job_id, include_runtime_detail=True)
        if job.fossa_report:
            try:
                await refresh_job_fossa_report_if_needed(job)
            except Exception:
                pass
        if job.test_pipeline is None:
            job.test_pipeline = TestPipelineReport(
                provider="none",
                project_kind="",
                generated_tests_relative="",
                test_strategy="none",
                test_summary_metrics={},
                runner={},
                existing_test_files=[],
                migrated_test_files=[],
                generated_test_files=[],
            )
        return job

    @router.post("/migration/{job_id}/cancel", response_model=MigrationResult)
    async def cancel_migration(job_id: str):
        """Request cancellation for a migration job."""
        try:
            return job_service.cancel_job(job_id, queue_revoke=job_queue.revoke)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to cancel migration job: {exc}") from exc

    @router.get("/migration/{job_id}/summary", response_model=MigrationJobSummary)
    async def get_migration_status_summary(job_id: str):
        """Get a lightweight status summary for a migration job."""
        return job_service.get_job_summary(job_id)

    @router.get("/migration/{job_id}/fossa")
    async def get_migration_fossa(job_id: str):
        """Return FOSSA scan results for a migration job."""
        job = job_service.require_job(job_id, include_runtime_detail=True)

        if job.fossa_report:
            try:
                await refresh_job_fossa_report_if_needed(job)
            except Exception:
                pass
            return {"job_id": job_id, "fossa": job.fossa_report}

        if getattr(job, "fossa_policy_status", None) is not None or getattr(job, "fossa_error_message", None):
            return {
                "job_id": job_id,
                "fossa": {
                    "scan_mode": getattr(job, "fossa_scan_mode", None),
                    "real_scan": getattr(job, "fossa_real_scan", False),
                    "simulated": getattr(job, "fossa_scan_mode", None) == "simulated",
                    "analysis_url": getattr(job, "fossa_analysis_url", None),
                    "compliance_status": getattr(job, "fossa_policy_status", None),
                    "total_dependencies": getattr(job, "fossa_total_dependencies", 0),
                    "license_issues": getattr(job, "fossa_license_issues", 0),
                    "vulnerabilities": getattr(job, "fossa_vulnerabilities", 0),
                    "outdated_dependencies": getattr(job, "fossa_outdated_dependencies", 0),
                    "error_message": getattr(job, "fossa_error_message", None),
                },
            }

        return {
            "job_id": job_id,
            "fossa": {
                "scan_mode": "pending",
                "real_scan": False,
                "simulated": False,
                "compliance_status": None,
                "total_dependencies": 0,
                "license_issues": 0,
                "vulnerabilities": 0,
                "outdated_dependencies": 0,
                "error_message": "FOSSA results are not available for this migration yet.",
            },
        }

    @router.get("/migration/{job_id}/logs")
    async def get_migration_logs(job_id: str):
        """Get detailed logs for a migration job."""
        return {"job_id": job_id, "logs": job_service.get_job_logs(job_id)}

    @router.post("/migration/{job_id}/rerun-tests")
    async def rerun_migration_tests(
        job_id: str,
        llm_provider: str = "ford_llm",
        use_llm_tests: bool = True,
    ):
        """Re-run tests for an existing migration job and update its test metrics."""
        with logging_context(job_id=job_id):
            job = job_service.require_job(job_id, detail="Migration job not found", include_runtime_detail=True)
            clone_path = artifact_service.require_clone_path(job)

            try:
                job_service.add_log(job_id, "Re-running tests on existing migration job...")
            except Exception:
                pass

            generation_issues = []
            for issue in job.issues:
                generation_issues.append(
                    {
                        "severity": issue.severity.value if hasattr(issue.severity, "value") else str(issue.severity),
                        "category": issue.category,
                        "message": issue.message,
                        "file_path": issue.file_path,
                    }
                )

            if job.sonar_report:
                for bug in job.sonar_report.get("bug_details", []):
                    generation_issues.append(
                        {
                            "severity": bug.get("severity", "MAJOR"),
                            "category": "Sonar Bug",
                            "message": bug.get("message"),
                            "file_path": bug.get("component", ""),
                        }
                    )

            test_result = await migration_service.run_tests(
                clone_path,
                llm_provider=llm_provider,
                use_llm_tests=use_llm_tests,
                target_java_version=getattr(job, "target_java_version", "") or "",
                issues=generation_issues,
                job_id=job_id,
            )

            job.api_endpoints_validated = test_result.get("total_endpoints", 0)
            job.api_endpoints_working = test_result.get("working_endpoints", 0)
            job.tests_run = test_result.get("tests_run", 0)
            job.tests_passed = test_result.get("tests_passed", 0)
            job.tests_failed = test_result.get("tests_failed", 0)
            job.test_summary = test_result.get("test_summary")
            job.test_insights = test_result.get("test_insights") or []
            pipeline = test_result.get("llm_pipeline") or {}
            job.test_llm_model = (
                (pipeline.get("model") if isinstance(pipeline, dict) else None)
                or test_result.get("test_llm_model")
                or test_result.get("test_model_used")
            )

            updated_dependencies = test_result.get("updated_dependencies", []) or []
            if updated_dependencies:
                merge_dependency_upgrade_records(job, updated_dependencies)

            if isinstance(pipeline, dict) and pipeline:
                try:
                    raw_metrics = pipeline.get("test_summary_metrics", {}) or {}
                    safe_metrics = {
                        "repo_total_files": int(raw_metrics.get("repo_total_files", 0) or 0),
                        "existing_test_files": int(raw_metrics.get("existing_test_files", 0) or 0),
                        "new_test_files": int(raw_metrics.get("new_test_files", 0) or 0),
                        "existing_test_cases": int(raw_metrics.get("existing_test_cases", 0) or 0),
                        "generated_test_cases": int(raw_metrics.get("generated_test_cases", 0) or 0),
                        "total_test_cases": int(raw_metrics.get("total_test_cases", 0) or 0),
                        "bl_suitability_score": float(raw_metrics.get("bl_suitability_score", 0.0) or 0.0),
                        "java_migration_version": str(raw_metrics.get("java_migration_version", "") or ""),
                    }
                    if raw_metrics.get("functional_application_type"):
                        safe_metrics["functional_application_type"] = raw_metrics["functional_application_type"]
                    if raw_metrics.get("functional_recommended_tools"):
                        safe_metrics["functional_recommended_tools"] = raw_metrics["functional_recommended_tools"]
                    if raw_metrics.get("functional_generated_tests"):
                        safe_metrics["functional_generated_tests"] = raw_metrics["functional_generated_tests"]
                    if raw_metrics.get("functional_execution_status"):
                        safe_metrics["functional_execution_status"] = raw_metrics["functional_execution_status"]
                    job.test_pipeline = TestPipelineReport(
                        provider=pipeline.get("provider", llm_provider),
                        project_kind=pipeline.get("project_kind", ""),
                        generated_tests_relative=pipeline.get("generated_tests_relative", ""),
                        test_strategy=pipeline.get("test_strategy"),
                        existing_tests_detected=int(pipeline.get("existing_tests_detected", 0) or 0),
                        generated_test_cases=int(pipeline.get("generated_test_cases", 0) or 0),
                        existing_test_files=pipeline.get("existing_test_files", []) or [],
                        migrated_test_files=pipeline.get("migrated_test_files", []) or [],
                        generated_test_files=pipeline.get("generated_test_files", []) or [],
                        test_summary_metrics=safe_metrics,
                        runner=pipeline.get("runner", {}) or {},
                        functional_testing=pipeline.get("functional_testing") or test_result.get("functional_pipeline"),
                        manual_test_plan_path=pipeline.get("manual_test_plan_path"),
                        migration_patch_path=pipeline.get("migration_patch_path"),
                        deepeval_result=pipeline.get("deepeval"),
                        garak_result=pipeline.get("garak"),
                        coverage_result=pipeline.get("coverage"),
                    )
                except Exception as exc:
                    job_service.add_log(job_id, f"WARNING: Failed to map test pipeline report: {exc}")
            elif not isinstance(pipeline, dict) or not pipeline:
                if job.test_pipeline is None:
                    job.test_pipeline = TestPipelineReport(
                        provider="none",
                        project_kind="",
                        generated_tests_relative="",
                        test_strategy="none",
                        test_summary_metrics={
                            "repo_total_files": 0,
                            "existing_test_files": 0,
                            "new_test_files": 0,
                            "existing_test_cases": 0,
                            "generated_test_cases": 0,
                            "total_test_cases": 0,
                            "bl_suitability_score": 0.0,
                        },
                        runner={},
                        existing_test_files=[],
                        migrated_test_files=[],
                        generated_test_files=[],
                    )

            try:
                job.testcase_doc_path = None
            except Exception:
                pass

            runner = test_result.get("runner") or {}
            if isinstance(runner, dict) and runner:
                try:
                    cmd = runner.get("cmd") or []
                    cmd_str = " ".join(str(x) for x in cmd[:10]) if isinstance(cmd, list) else str(cmd)
                    job_service.add_log(
                        job_id,
                        f"Test Runner: tool={runner.get('tool')} exit={runner.get('exit_code')} "
                        f"run={runner.get('tests_run')} pass={runner.get('tests_passed')} fail={runner.get('tests_failed')} "
                        f"timeout={runner.get('timed_out')} cmd={cmd_str}",
                    )
                    if runner.get("timed_out"):
                        job_service.add_log(
                            job_id,
                            "TEST TIMEOUT: The automated test run exceeded the configured timeout before completion.",
                        )
                    output_tail = str(runner.get("output_tail") or "").strip()
                    if output_tail and (runner.get("timed_out") or int(runner.get("exit_code", 0) or 0) != 0):
                        job_service.add_log(job_id, f"TEST OUTPUT TAIL:\n{output_tail}")
                except Exception:
                    pass

            try:
                if job.test_summary:
                    job_service.add_log(job_id, f"LLM Test Summary: {job.test_summary}")
                if job.test_pipeline:
                    job_service.add_log(
                        job_id,
                        "Test Strategy: "
                        f"{getattr(job.test_pipeline, 'test_strategy', 'unknown')} "
                        f"(existing={getattr(job.test_pipeline, 'existing_tests_detected', 0)} "
                        f"migrated={len(getattr(job.test_pipeline, 'migrated_test_files', []) or [])} "
                        f"generated={len(getattr(job.test_pipeline, 'generated_test_files', []) or [])})",
                    )
                if isinstance(pipeline, dict) and pipeline:
                    job_service.add_log(
                        job_id,
                        "LLM Usage: "
                        f"provider={pipeline.get('provider', llm_provider)} "
                        f"model={pipeline.get('model') or job.test_llm_model or 'unknown'} "
                        f"requests={pipeline.get('llm_requests_made', 0)}",
                    )
                    functional = pipeline.get("functional_testing") or {}
                    if isinstance(functional, dict) and functional:
                        execution = functional.get("execution") or {}
                        job_service.add_log(
                            job_id,
                            "Functional Testing: "
                            f"type={functional.get('application_type', 'unknown')} "
                            f"tools={','.join(functional.get('recommended_tools', []) or [])} "
                            f"status={functional.get('status', 'unknown')} "
                            f"run={execution.get('tests_run', functional.get('tests_run', 0))} "
                            f"pass={execution.get('tests_passed', functional.get('tests_passed', 0))} "
                            f"fail={execution.get('tests_failed', functional.get('tests_failed', 0))}",
                        )
            except Exception:
                pass

            job_service.save_job(job)

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

    @router.get("/migrations", response_model=List[MigrationJobSummary])
    async def list_migrations():
        """List lightweight summaries for all migration jobs."""
        return job_service.list_job_summaries()

    @router.get("/migrations/summary", response_model=List[MigrationJobSummary])
    async def list_migration_summaries():
        """Compatibility alias for the lightweight migration summaries list."""
        return job_service.list_job_summaries()

    @router.get("/migration/{job_id}/download-zip")
    async def download_migration_zip(job_id: str):
        """Download the migrated project as a ZIP file."""
        job = job_service.require_job(job_id, detail="Migration job not found")
        zip_file = artifact_service.create_zip_archive(job_id, job)
        return FileResponse(
            zip_file,
            media_type="application/zip",
            filename=f"migration-{job_id}.zip",
        )

    return router
