"""Celery task entrypoint for migration execution."""

from __future__ import annotations

import asyncio
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.job_models import MigrationRequest, MigrationStatus
from services.celery_app import celery_app
from services.job_queue import (
    CeleryMigrationJobQueue,
    MIGRATION_CORE_TASK_NAME,
    MIGRATION_SCANS_TASK_NAME,
    MIGRATION_TESTS_TASK_NAME,
)
from services.job_service import ACTIVE_MIGRATION_JOB_STATUSES, TERMINAL_MIGRATION_JOB_STATUSES
from utils.config import (
    CELERY_TASK_QUEUE_CORE,
    CELERY_TASK_QUEUE_SCANS,
    CELERY_TASK_QUEUE_TESTS,
    JOB_STALE_TIMEOUT_SEC,
)
from services.migration_orchestrator import MigrationCancelledError
from utils.logging_utils import get_job_id, logging_context
from workers.heartbeat import build_worker_heartbeat

import logging

logger = logging.getLogger(__name__)


class JobRuntimeLogHandler(logging.Handler):
    """Mirror selected worker/Celery log records into the per-job runtime log store."""

    def __init__(self, *, job_service: Any, job_id: str) -> None:
        super().__init__(level=logging.INFO)
        self.job_service = job_service
        self.job_id = job_id
        self._emit_lock = threading.Lock()
        self._last_entry: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if get_job_id() != self.job_id:
                return
            if not self._should_capture(record):
                return

            message = record.getMessage().strip()
            if not message:
                return

            entry = f"[CELERY][{record.levelname}] {record.name}: {message}"
            with self._emit_lock:
                if entry == self._last_entry:
                    return
                self._last_entry = entry
            self.job_service.add_log(self.job_id, entry)
        except Exception:
            return

    def _should_capture(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.INFO:
            return False
        if record.name.startswith("celery"):
            return True
        if record.name.startswith("workers.migration_worker"):
            return True
        return False


def _attach_job_runtime_log_handler(job_service: Any, *, job_id: str) -> tuple[logging.Logger, JobRuntimeLogHandler]:
    root_logger = logging.getLogger()
    handler = JobRuntimeLogHandler(job_service=job_service, job_id=job_id)
    root_logger.addHandler(handler)
    return root_logger, handler


def _detach_job_runtime_log_handler(root_logger: logging.Logger, handler: logging.Handler) -> None:
    try:
        root_logger.removeHandler(handler)
    except Exception:
        return


def _task_queue_name(task: Any) -> str:
    delivery_info = getattr(getattr(task, "request", None), "delivery_info", {}) or {}
    return str(delivery_info.get("routing_key") or delivery_info.get("queue") or "").strip()


def _task_id(task: Any) -> str:
    return str(getattr(getattr(task, "request", None), "id", "") or "").strip()


def _should_skip_execution(job: Any, *, task_id: str, now: datetime) -> str | None:
    if task_id and job.queue_task_id and job.queue_task_id != task_id:
        return (
            f"Skipping stale worker task {task_id}: job is assigned to queued task {job.queue_task_id}."
        )

    if job.status in TERMINAL_MIGRATION_JOB_STATUSES:
        return f"Skipping worker task {task_id or 'unknown'}: job is already {job.status.value}."

    if job.status == MigrationStatus.CANCEL_REQUESTED or job.cancel_requested_at is not None:
        return f"Skipping worker task {task_id or 'unknown'}: cancellation has already been requested."

    if (
        task_id
        and job.queue_task_id == task_id
        and job.status in ACTIVE_MIGRATION_JOB_STATUSES
        and job.last_heartbeat_at is not None
    ):
        heartbeat_age_seconds = (now - job.last_heartbeat_at).total_seconds()
        if heartbeat_age_seconds < JOB_STALE_TIMEOUT_SEC:
            return (
                f"Skipping duplicate delivery for task {task_id}: "
                f"job is actively running with a recent heartbeat ({heartbeat_age_seconds:.1f}s ago)."
            )

    return None


def _start_worker_heartbeat(job_service: Any, *, job_id: str, worker_id: str, interval_seconds: int) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()

    def _heartbeat_loop() -> None:
        while not stop_event.wait(interval_seconds):
            try:
                if not job_service.has_job(job_id):
                    logger.warning(
                        "Stopping worker heartbeat because job record is no longer available job_id=%s worker_id=%s",
                        job_id,
                        worker_id,
                    )
                    return
                job_service.record_worker_heartbeat(job_id, worker_id=worker_id)
            except Exception as exc:
                logger.warning(
                    "Failed to record worker heartbeat job_id=%s worker_id=%s: %s",
                    job_id,
                    worker_id,
                    exc,
                )

    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        name=f"migration-heartbeat-{job_id[:8]}",
        daemon=True,
    )
    heartbeat_thread.start()
    return stop_event, heartbeat_thread


def _enqueue_follow_up_task(
    job_service: Any,
    *,
    job_id: str,
    request_payload: dict[str, Any],
    task_name: str,
    queue_name: str,
    current_step: str,
) -> dict[str, Any]:
    # We are already executing inside a live worker process, so a broker send is
    # the real requirement here; re-running inspect().ping() can fail spuriously.
    queue = CeleryMigrationJobQueue(require_live_worker=False)
    queued_task = queue.enqueue_task(
        task_name=task_name,
        job_id=job_id,
        request_payload=request_payload,
        queue_name=queue_name,
        skip_worker_availability_check=True,
    )
    job_service.update_job_fields(
        job_id,
        status=MigrationStatus.QUEUED,
        queue_task_id=queued_task.task_id,
        queue_name=queued_task.queue_name,
        queued_at=datetime.now(timezone.utc),
        current_step=current_step,
    )
    job_service.add_log(
        job_id,
        f"[CELERY] Queued follow-up stage on {queued_task.queue_name} (task={queued_task.task_id})",
    )
    return {
        "status": "queued",
        "next_task_id": queued_task.task_id,
        "next_queue": queued_task.queue_name,
    }


def _run_worker_stage(
    self: Any,
    job_id: str,
    request_payload: dict[str, Any],
    *,
    stage_name: str,
    stage_runner: Any,
) -> dict[str, Any]:
    """Execute one migration stage inside a Celery worker process."""
    request = MigrationRequest.model_validate(request_payload)

    heartbeat = build_worker_heartbeat(job_id)
    heartbeat_stop_event: threading.Event | None = None
    heartbeat_thread: threading.Thread | None = None
    runtime_log_root: logging.Logger | None = None
    runtime_log_handler: JobRuntimeLogHandler | None = None
    try:
        with logging_context(job_id=job_id, worker_id=heartbeat.worker_id):
            try:
                from services.migration_runtime import get_migration_orchestrator, job_service

                runtime_log_root, runtime_log_handler = _attach_job_runtime_log_handler(job_service, job_id=job_id)
                current_task_id = _task_id(self)
                current_queue_name = _task_queue_name(self)
                current_job = job_service.require_job(job_id)
                logger.info(
                    "Celery worker picked up %s stage task task_id=%s queue=%s",
                    stage_name,
                    current_task_id or "-",
                    current_queue_name or "-",
                )
                skip_reason = _should_skip_execution(current_job, task_id=current_task_id, now=heartbeat.emitted_at)
                if skip_reason:
                    job_service.add_log(job_id, skip_reason)
                    logger.info("Skipping Celery migration execution reason=%s", skip_reason)
                    return {
                        "job_id": job_id,
                        "worker_id": heartbeat.worker_id,
                        "task_id": current_task_id,
                        "status": "ignored",
                        "reason": skip_reason,
                    }

                claim_fields: dict[str, object] = {}
                if current_task_id and current_job.queue_task_id != current_task_id:
                    claim_fields["queue_task_id"] = current_task_id
                if current_queue_name and current_job.queue_name != current_queue_name:
                    claim_fields["queue_name"] = current_queue_name
                if claim_fields:
                    job_service.update_job_fields(job_id, **claim_fields)

                job_service.mark_job_running(
                    job_id,
                    worker_id=heartbeat.worker_id,
                    current_step=f"Worker claimed queued migration {stage_name} stage",
                    heartbeat_at=heartbeat.emitted_at,
                )
                job_service.add_log(
                    job_id,
                    f"[CELERY] Worker started {stage_name} stage task {current_task_id or '-'} on queue {current_queue_name or '-'} (worker={heartbeat.worker_id})",
                )
                heartbeat_stop_event, heartbeat_thread = _start_worker_heartbeat(
                    job_service,
                    job_id=job_id,
                    worker_id=heartbeat.worker_id,
                    interval_seconds=heartbeat.interval_seconds,
                )
                self.update_state(
                    state="STARTED",
                    meta={
                        "job_id": job_id,
                        "stage": stage_name,
                        "worker_id": heartbeat.worker_id,
                        "task_id": current_task_id,
                        "heartbeat_at": heartbeat.emitted_at.isoformat(),
                    },
                )

                stage_result = asyncio.run(stage_runner(get_migration_orchestrator(), job_service, request))
                job_service.record_worker_heartbeat(
                    job_id,
                    worker_id=heartbeat.worker_id,
                )
                if stage_result.get("status") == "completed":
                    job_service.add_log(
                        job_id,
                        f"[CELERY] Worker completed {stage_name} stage task {current_task_id or '-'} successfully",
                    )
                    logger.info("Celery worker completed %s stage successfully", stage_name)
                else:
                    logger.info("Celery worker completed %s stage and queued follow-up work", stage_name)

                return {
                    "job_id": job_id,
                    "stage": stage_name,
                    "worker_id": heartbeat.worker_id,
                    "task_id": current_task_id,
                    **stage_result,
                }
            except MigrationCancelledError:
                if "job_service" in locals() and job_service.has_job(job_id):
                    job_service.record_worker_heartbeat(
                        job_id,
                        worker_id=heartbeat.worker_id,
                    )
                    job_service.add_log(
                        job_id,
                        f"[CELERY] Worker observed cancellation for {stage_name} stage task {current_task_id or '-'}",
                    )
                logger.info("Celery worker observed %s stage cancellation", stage_name)
                return {
                    "job_id": job_id,
                    "stage": stage_name,
                    "worker_id": heartbeat.worker_id,
                    "task_id": current_task_id,
                    "status": "cancelled",
                }
            except Exception as exc:
                failure_message = f"Celery worker failed: {exc}"
                if "job_service" in locals():
                    current_job = None
                    if job_service.has_job(job_id):
                        current_job = job_service.get_job(job_id)
                    if current_job is None or current_job.status != MigrationStatus.FAILED:
                        job_service.add_log(job_id, failure_message)
                        job_service.add_log(
                            job_id,
                            f"[CELERY] Worker failed {stage_name} stage task {current_task_id or '-'} on queue {current_queue_name or '-'}",
                        )
                        job_service.add_log(job_id, "TRACEBACK: See backend logs for the full worker stack trace.")
                        if current_job is not None:
                            job_service.update_job_fields(
                                job_id,
                                status=MigrationStatus.FAILED,
                                current_step=failure_message,
                            )
                logger.exception("Celery worker execution failed")
                raise
    finally:
        if runtime_log_root is not None and runtime_log_handler is not None:
            _detach_job_runtime_log_handler(runtime_log_root, runtime_log_handler)
        if heartbeat_stop_event is not None:
            heartbeat_stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)


if celery_app is not None:
    def _run_migration_core_job_impl(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        async def _runner(orchestrator: Any, job_service: Any, request: MigrationRequest) -> dict[str, Any]:
            await orchestrator.run_core_phase(job_id, request)
            if request.run_tests:
                return _enqueue_follow_up_task(
                    job_service,
                    job_id=job_id,
                    request_payload=request_payload,
                    task_name=MIGRATION_TESTS_TASK_NAME,
                    queue_name=CELERY_TASK_QUEUE_TESTS,
                    current_step="Queued test stage for worker execution...",
                )
            return _enqueue_follow_up_task(
                job_service,
                job_id=job_id,
                request_payload=request_payload,
                task_name=MIGRATION_SCANS_TASK_NAME,
                queue_name=CELERY_TASK_QUEUE_SCANS,
                current_step="Queued scan/finalization stage for worker execution...",
            )

        return _run_worker_stage(
            self,
            job_id,
            request_payload,
            stage_name="core",
            stage_runner=_runner,
        )

    def _run_migration_tests_job_impl(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        async def _runner(orchestrator: Any, job_service: Any, request: MigrationRequest) -> dict[str, Any]:
            await orchestrator.run_test_phase(job_id, request)
            return _enqueue_follow_up_task(
                job_service,
                job_id=job_id,
                request_payload=request_payload,
                task_name=MIGRATION_SCANS_TASK_NAME,
                queue_name=CELERY_TASK_QUEUE_SCANS,
                current_step="Queued scan/finalization stage for worker execution...",
            )

        return _run_worker_stage(
            self,
            job_id,
            request_payload,
            stage_name="tests",
            stage_runner=_runner,
        )

    def _run_migration_scans_job_impl(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        async def _runner(orchestrator: Any, job_service: Any, request: MigrationRequest) -> dict[str, Any]:
            await orchestrator.run_scan_and_finalize_phase(job_id, request)
            return {"status": "completed"}

        return _run_worker_stage(
            self,
            job_id,
            request_payload,
            stage_name="scans",
            stage_runner=_runner,
        )

    run_migration_core_job = celery_app.task(name=MIGRATION_CORE_TASK_NAME, bind=True)(_run_migration_core_job_impl)
    run_migration_tests_job = celery_app.task(name=MIGRATION_TESTS_TASK_NAME, bind=True)(_run_migration_tests_job_impl)
    run_migration_scans_job = celery_app.task(name=MIGRATION_SCANS_TASK_NAME, bind=True)(_run_migration_scans_job_impl)
    run_migration_job = celery_app.task(name="workers.migration_worker.run_migration_job", bind=True)(_run_migration_core_job_impl)
else:
    def run_migration_core_job(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Celery is not installed in this environment.")

    def run_migration_tests_job(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Celery is not installed in this environment.")

    def run_migration_scans_job(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Celery is not installed in this environment.")

    def run_migration_job(self: Any, job_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Celery is not installed in this environment.")
