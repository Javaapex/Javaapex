"""Job persistence and lifecycle helpers for migration jobs."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import HTTPException

from models.job_models import (
    FileDiffEntry,
    IssueStatus,
    MigrationJobRuntimeDetail,
    MigrationJobSummary,
    MigrationResult,
    MigrationStatus,
)
from services.persistent_job_store import PersistentJobStore, PersistentListStore
from utils.config import JOB_STALE_TIMEOUT_SEC

logger = logging.getLogger(__name__)

ACTIVE_MIGRATION_JOB_STATUSES = {
    MigrationStatus.RUNNING,
    MigrationStatus.CLONING,
    MigrationStatus.ANALYZING,
    MigrationStatus.MIGRATING,
    MigrationStatus.TESTING,
    MigrationStatus.SONAR_ANALYSIS,
    MigrationStatus.FOSSA_ANALYSIS,
    MigrationStatus.PUSHING,
}

TERMINAL_MIGRATION_JOB_STATUSES = {
    MigrationStatus.COMPLETED,
    MigrationStatus.FAILED,
    MigrationStatus.CANCELLED,
    MigrationStatus.STALE,
}

STALE_CANDIDATE_MIGRATION_JOB_STATUSES = ACTIVE_MIGRATION_JOB_STATUSES | {
    MigrationStatus.CANCEL_REQUESTED,
}


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


FINISHED_MIGRATION_JOB_TTL_SECONDS = _parse_positive_int_env(
    "MIGRATION_JOB_FINISHED_TTL_SECONDS",
    24 * 60 * 60,
)
FAILED_MIGRATION_JOB_TTL_SECONDS = _parse_positive_int_env(
    "MIGRATION_JOB_FAILED_TTL_SECONDS",
    72 * 60 * 60,
)


def _job_store_redis_url() -> str:
    return (
        os.environ.get("REDIS_URL", "").strip()
        or os.environ.get("CELERY_BROKER_URL", "").strip()
        or os.environ.get("CELERY_RESULT_BACKEND", "").strip()
    )


def _migration_job_ttl(job: MigrationResult) -> Optional[int]:
    if job.status == MigrationStatus.COMPLETED:
        return FINISHED_MIGRATION_JOB_TTL_SECONDS or None
    if job.status == MigrationStatus.FAILED:
        return FAILED_MIGRATION_JOB_TTL_SECONDS or None
    return None


def _migration_job_runtime_detail_ttl(detail: MigrationJobRuntimeDetail) -> Optional[int]:
    if detail.status == MigrationStatus.COMPLETED:
        return FINISHED_MIGRATION_JOB_TTL_SECONDS or None
    if detail.status == MigrationStatus.FAILED:
        return FAILED_MIGRATION_JOB_TTL_SECONDS or None
    return None


def _migration_job_status_ttl(status: MigrationStatus) -> Optional[int]:
    if status == MigrationStatus.COMPLETED:
        return FINISHED_MIGRATION_JOB_TTL_SECONDS or None
    if status == MigrationStatus.FAILED:
        return FAILED_MIGRATION_JOB_TTL_SECONDS or None
    return None


def create_migration_job_store() -> PersistentJobStore[MigrationResult]:
    return PersistentJobStore(
        serializer=lambda job: job.model_dump(mode="json"),
        deserializer=lambda data: MigrationResult.model_validate(data),
        redis_url=_job_store_redis_url(),
        namespace=os.environ.get("MIGRATION_JOB_STORE_NAMESPACE", "migration"),
        ttl_for_value=_migration_job_ttl,
        cache_in_memory_when_redis=True,
        max_cached_items=_parse_positive_int_env("MIGRATION_JOB_STORE_CACHE_MAX_ITEMS", 256),
    )


def create_migration_job_runtime_detail_store() -> PersistentJobStore[MigrationJobRuntimeDetail]:
    return PersistentJobStore(
        serializer=lambda detail: detail.model_dump(mode="json"),
        deserializer=lambda data: MigrationJobRuntimeDetail.model_validate(data),
        redis_url=_job_store_redis_url(),
        namespace=os.environ.get("MIGRATION_JOB_DETAIL_STORE_NAMESPACE", "migration_detail"),
        ttl_for_value=_migration_job_runtime_detail_ttl,
        cache_in_memory_when_redis=False,
        max_cached_items=_parse_positive_int_env("MIGRATION_JOB_DETAIL_STORE_CACHE_MAX_ITEMS", 32),
    )


def create_migration_job_log_store() -> PersistentListStore[str]:
    return PersistentListStore(
        serializer=lambda entry: entry,
        deserializer=lambda data: str(data),
        redis_url=_job_store_redis_url(),
        namespace=os.environ.get("MIGRATION_JOB_LOG_STORE_NAMESPACE", "migration_logs"),
        cache_in_memory_when_redis=False,
        max_cached_items=_parse_positive_int_env("MIGRATION_JOB_LOG_CACHE_MAX_ITEMS", 16),
    )


class MigrationJobService:
    def __init__(
        self,
        store: PersistentJobStore[MigrationResult],
        runtime_detail_store: Optional[PersistentJobStore[MigrationJobRuntimeDetail]] = None,
        runtime_log_store: Optional[PersistentListStore[str]] = None,
    ) -> None:
        self.store = store
        self.runtime_detail_store = runtime_detail_store
        self.runtime_log_store = runtime_log_store

    def _get_runtime_detail_base(self, job_id: str) -> MigrationJobRuntimeDetail:
        detail: MigrationJobRuntimeDetail
        if self.runtime_detail_store is None:
            detail = MigrationJobRuntimeDetail(job_id=job_id, status=MigrationStatus.PENDING)
        else:
            try:
                detail = self.runtime_detail_store[job_id]
            except KeyError:
                if job_id in self.store:
                    status = self.store[job_id].status
                else:
                    status = MigrationStatus.PENDING
                detail = MigrationJobRuntimeDetail(job_id=job_id, status=status)
        return detail

    def _get_runtime_detail(self, job_id: str) -> MigrationJobRuntimeDetail:
        detail = self._get_runtime_detail_base(job_id)
        if self.runtime_log_store is not None:
            runtime_logs = self.runtime_log_store.get_list(job_id)
            if not runtime_logs and detail.migration_log:
                runtime_logs = list(detail.migration_log)
                self.runtime_log_store.set_list(
                    job_id,
                    runtime_logs,
                    ttl_seconds=_migration_job_status_ttl(detail.status),
                )
            detail.migration_log = runtime_logs
        return detail

    def _save_runtime_detail(self, detail: MigrationJobRuntimeDetail, *, persist_logs: bool = True) -> None:
        if self.runtime_log_store is not None:
            log_ttl_seconds = _migration_job_status_ttl(detail.status)
            if persist_logs:
                self.runtime_log_store.set_list(
                    detail.job_id,
                    list(detail.migration_log),
                    ttl_seconds=log_ttl_seconds,
                )
            else:
                self.runtime_log_store.expire(detail.job_id, log_ttl_seconds)

        if self.runtime_detail_store is None:
            return

        detail_to_store = detail.model_copy(deep=True)
        if self.runtime_log_store is not None:
            detail_to_store.migration_log = []
        self.runtime_detail_store[detail.job_id] = detail_to_store

    def _get_runtime_logs(self, job_id: str) -> list[str]:
        if self.runtime_log_store is not None:
            return self.runtime_log_store.get_list(job_id)
        return list(self._get_runtime_detail(job_id).migration_log)

    def _apply_runtime_detail_metadata(
        self,
        job: MigrationResult,
        detail: MigrationJobRuntimeDetail,
    ) -> MigrationResult:
        if detail.migration_log:
            job.log_entry_count = len(detail.migration_log)
        job.file_diff_count = len(detail.file_diffs)
        job.has_sonar_report = detail.sonar_report is not None
        job.has_fossa_report = detail.fossa_report is not None
        job.has_workspace_artifact = bool(getattr(job, "workspace_artifact_uri", None))

        # Ensure bl_suitability_score alias is always synced
        if hasattr(job, "bl_coverage") and hasattr(job, "bl_suitability_score"):
            if job.bl_coverage > 0 and job.bl_suitability_score == 0:
                job.bl_suitability_score = job.bl_coverage
            elif job.bl_suitability_score > 0 and job.bl_coverage == 0:
                job.bl_coverage = job.bl_suitability_score

        return job

    def _strip_runtime_detail(
        self,
        job: MigrationResult,
        *,
        detail: MigrationJobRuntimeDetail,
    ) -> MigrationResult:
        stripped = job.model_copy(deep=True)
        self._apply_runtime_detail_metadata(stripped, detail)
        stripped.migration_log = []
        stripped.file_diffs = []
        stripped.sonar_report = None
        stripped.fossa_report = None
        return stripped

    def _refresh_stale_job(self, job: MigrationResult) -> MigrationResult:
        if job.status not in STALE_CANDIDATE_MIGRATION_JOB_STATUSES:
            return job
        if job.last_heartbeat_at is None:
            return job

        heartbeat_at = job.last_heartbeat_at
        if getattr(heartbeat_at, "tzinfo", None) is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)

        age_seconds = (datetime.now(timezone.utc) - heartbeat_at).total_seconds()
        if age_seconds <= JOB_STALE_TIMEOUT_SEC:
            return job

        stale_message = f"Worker heartbeat expired after {int(age_seconds)}s; marking migration job as stale."
        job.status = MigrationStatus.STALE
        job.error_message = stale_message
        job.completed_at = datetime.now(timezone.utc)
        self.save_job(job)
        self.add_log(job.job_id, stale_message)
        return job

    def hydrate_runtime_detail(self, job: MigrationResult) -> MigrationResult:
        detail = self._get_runtime_detail(job.job_id)
        hydrated = job.model_copy(deep=True)
        hydrated.migration_log = list(detail.migration_log)
        hydrated.file_diffs = list(detail.file_diffs)
        hydrated.sonar_report = detail.sonar_report
        hydrated.fossa_report = detail.fossa_report
        return self._apply_runtime_detail_metadata(hydrated, detail)

    def save_job(self, job: MigrationResult) -> None:
        existing_detail = self._get_runtime_detail_base(job.job_id)
        runtime_logs = (
            list(job.migration_log)
            if job.migration_log
            else ([] if self.runtime_log_store is not None else list(existing_detail.migration_log))
        )
        detail = MigrationJobRuntimeDetail(
            job_id=job.job_id,
            status=job.status,
            migration_log=runtime_logs,
            file_diffs=list(job.file_diffs) if job.file_diffs else list(existing_detail.file_diffs),
            sonar_report=job.sonar_report if job.sonar_report is not None else existing_detail.sonar_report,
            fossa_report=job.fossa_report if job.fossa_report is not None else existing_detail.fossa_report,
        )
        self._save_runtime_detail(detail, persist_logs=bool(job.migration_log) or self.runtime_log_store is None)
        self.store[job.job_id] = self._strip_runtime_detail(job, detail=detail)

    def has_job(self, job_id: str) -> bool:
        return job_id in self.store

    def get_job(self, job_id: str, include_runtime_detail: bool = False) -> MigrationResult:
        job = self.store[job_id]
        job = self._refresh_stale_job(job)
        return self.hydrate_runtime_detail(job) if include_runtime_detail else job

    def get_job_detail(self, job_id: str) -> MigrationResult:
        return self.get_job(job_id, include_runtime_detail=True)

    def update_job_fields(self, job_id: str, **fields: object) -> MigrationResult:
        job = self.require_job(job_id, include_runtime_detail=True)
        for field_name, field_value in fields.items():
            if hasattr(job, field_name):
                setattr(job, field_name, field_value)
        self.save_job(job)
        return job

    def require_job(
        self,
        job_id: str,
        detail: Optional[object] = None,
        include_runtime_detail: bool = False,
    ) -> MigrationResult:
        if job_id not in self.store:
            self.raise_missing_job(job_id, detail=detail)
        return self.get_job(job_id, include_runtime_detail=include_runtime_detail)

    def require_job_detail(self, job_id: str, detail: Optional[object] = None) -> MigrationResult:
        return self.require_job(job_id, detail=detail, include_runtime_detail=True)

    def list_jobs(self, include_runtime_detail: bool = False) -> list[MigrationResult]:
        jobs = [self._refresh_stale_job(job) for job in list(self.store.values())]
        if not include_runtime_detail:
            return jobs
        return [self.hydrate_runtime_detail(job) for job in jobs]

    def summarize_job(self, job: MigrationResult) -> MigrationJobSummary:
        return MigrationJobSummary.from_job(job)

    def get_job_summary(self, job_id: str, detail: Optional[object] = None) -> MigrationJobSummary:
        return self.summarize_job(self.require_job(job_id, detail=detail))

    def list_job_summaries(self) -> list[MigrationJobSummary]:
        return [self.summarize_job(job) for job in self.list_jobs()]

    def raise_missing_job(self, job_id: str, detail: Optional[object] = None) -> None:
        if detail is not None:
            raise HTTPException(status_code=404, detail=detail)

        persistence_hint = (
            "Restart the migration, or verify the Redis-backed job store configuration and retention settings."
            if getattr(self.store, "persistence_enabled", False)
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

    def mark_issues_fixed(self, job: MigrationResult, conversion_type: str, count: int) -> None:
        remaining = max(int(count or 0), 0)
        if remaining <= 0:
            return

        for issue in job.issues:
            if remaining <= 0:
                break
            if issue.conversion_type == conversion_type:
                if issue.status == IssueStatus.FIXED:
                    continue
                issue.status = IssueStatus.FIXED
                issue.fixed_at = datetime.now(timezone.utc)
                remaining -= 1

    def update_job(self, job_id: str, status: MigrationStatus, progress: int, step: str) -> None:
        if job_id in self.store:
            job = self.store[job_id]
            job.status = status
            job.progress_percent = progress
            job.current_step = step
            if status in ACTIVE_MIGRATION_JOB_STATUSES:
                job.completed_at = None
                if job.error_message and "Worker heartbeat expired" in job.error_message:
                    job.error_message = None
            self.save_job(job)
            self.add_log(job_id, step)

    def record_enqueue(self, job_id: str, *, task_id: str, queue_name: str, queued_at: Optional[datetime] = None) -> None:
        timestamp = queued_at or datetime.now(timezone.utc)
        job = self.require_job(job_id)
        fields: dict[str, object] = {
            "queued_at": job.queued_at or timestamp,
            "queue_task_id": task_id,
            "queue_name": queue_name,
        }
        if job.status in {MigrationStatus.PENDING, MigrationStatus.QUEUED}:
            fields["status"] = MigrationStatus.QUEUED
            fields["current_step"] = "Queued for worker execution..."
        self.update_job_fields(job_id, **fields)
        self.add_log(job_id, f"Queued migration job for worker execution ({queue_name}, task={task_id})")

    def mark_job_running(
        self,
        job_id: str,
        *,
        worker_id: str,
        current_step: str = "Worker claimed queued migration job",
        heartbeat_at: Optional[datetime] = None,
    ) -> None:
        timestamp = heartbeat_at or datetime.now(timezone.utc)
        current_progress = self.store[job_id].progress_percent if job_id in self.store else 0
        self.update_job_fields(
            job_id,
            status=MigrationStatus.RUNNING,
            current_step=current_step,
            worker_id=worker_id,
            worker_started_at=timestamp,
            last_heartbeat_at=timestamp,
            completed_at=None,
            error_message=None,
            progress_percent=max(current_progress, 1),
        )
        self.add_log(job_id, f"Worker {worker_id} claimed queued migration job")

    def record_worker_heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        heartbeat_at: Optional[datetime] = None,
    ) -> None:
        timestamp = heartbeat_at or datetime.now(timezone.utc)
        job = self.require_job(job_id, include_runtime_detail=True)
        fields: dict[str, object] = {
            "worker_id": worker_id,
            "last_heartbeat_at": timestamp,
        }
        if job.status == MigrationStatus.STALE:
            fields["status"] = MigrationStatus.RUNNING
            fields["completed_at"] = None
            if job.error_message and "Worker heartbeat expired" in job.error_message:
                fields["error_message"] = None
        self.update_job_fields(job_id, **fields)

    def cancel_job(
        self,
        job_id: str,
        *,
        queue_revoke: Optional[Callable[..., None]] = None,
    ) -> MigrationResult:
        job = self.require_job(job_id, include_runtime_detail=True)
        job = self._refresh_stale_job(job)
        now = datetime.now(timezone.utc)

        if job.status in TERMINAL_MIGRATION_JOB_STATUSES:
            return job

        revoke_error: Optional[str] = None
        if job.queue_task_id and queue_revoke is not None:
            try:
                queue_revoke(job.queue_task_id, terminate=False)
            except Exception as exc:
                revoke_error = str(exc)

        if job.status in {MigrationStatus.QUEUED, MigrationStatus.PENDING}:
            self.update_job_fields(
                job_id,
                status=MigrationStatus.CANCELLED,
                current_step="Migration cancelled before worker execution",
                cancel_requested_at=now,
                completed_at=now,
                error_message=None,
            )
            self.add_log(job_id, "Migration cancelled before worker execution.")
        else:
            self.update_job_fields(
                job_id,
                status=MigrationStatus.CANCEL_REQUESTED,
                current_step="Cancellation requested; waiting for worker to stop safely",
                cancel_requested_at=now,
            )
            self.add_log(job_id, "Cancellation requested; worker will stop at the next safe checkpoint.")

        if revoke_error:
            self.add_log(job_id, f"WARNING: Failed to revoke queued task during cancellation: {revoke_error}")

        return self.require_job(job_id, include_runtime_detail=True)

    def add_log(self, job_id: str, message: str) -> None:
        if job_id in self.store:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            job = self.store[job_id]
            entry = f"[{timestamp}] {message}"

            if self.runtime_log_store is not None:
                log_count = self.runtime_log_store.append(
                    job_id,
                    entry,
                    ttl_seconds=_migration_job_status_ttl(job.status),
                )
                job.log_entry_count = log_count
            else:
                detail = self._get_runtime_detail(job_id)
                detail.status = job.status
                detail.migration_log.append(entry)
                self._save_runtime_detail(detail)
                self._apply_runtime_detail_metadata(job, detail)
            self.store[job_id] = job

    def get_job_logs(self, job_id: str, detail: Optional[object] = None) -> list[str]:
        self.require_job(job_id, detail=detail)
        return self._get_runtime_logs(job_id)

    def get_job_file_diffs(self, job_id: str, detail: Optional[object] = None) -> list[FileDiffEntry]:
        self.require_job(job_id, detail=detail)
        return list(self._get_runtime_detail(job_id).file_diffs)
