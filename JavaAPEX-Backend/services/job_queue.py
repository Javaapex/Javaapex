"""Queue abstraction for migration job dispatch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from models.job_models import MigrationRequest
from utils.config import CELERY_TASK_QUEUE, CELERY_TASK_QUEUE_CORE, CELERY_TASK_QUEUE_SCANS, CELERY_TASK_QUEUE_TESTS


MIGRATION_CORE_TASK_NAME = "workers.migration_worker.run_migration_core_job"
MIGRATION_TESTS_TASK_NAME = "workers.migration_worker.run_migration_tests_job"
MIGRATION_SCANS_TASK_NAME = "workers.migration_worker.run_migration_scans_job"


def _parse_positive_float_env(name: str, default: float) -> float:
    raw_value = (os.environ.get(name) or "").strip()
    if not raw_value:
        return default
    try:
        parsed = float(raw_value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


class MigrationJobQueue(Protocol):
    def is_available(self) -> bool:
        """Return whether queue-backed execution is available."""

    def availability_error(self) -> Optional[str]:
        """Return an explanatory error when queue-backed execution is unavailable."""

    def enqueue_migration(self, job_id: str, request: MigrationRequest) -> Any:
        """Submit a migration job and return the queue task id."""

    def revoke(self, task_id: str, *, terminate: bool = False) -> None:
        """Request cancellation for a previously enqueued task."""


class QueueUnavailableError(RuntimeError):
    """Raised when queue-backed execution is requested but unavailable."""


@dataclass(frozen=True)
class QueuedMigrationTask:
    task_id: str
    queue_name: str


@dataclass
class CeleryMigrationJobQueue:
    queue_name: str = CELERY_TASK_QUEUE_CORE
    require_live_worker: bool = (
        (os.environ.get("CELERY_REQUIRE_LIVE_WORKER") or "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    worker_ping_timeout_sec: float = max(0.25, _parse_positive_float_env("CELERY_WORKER_PING_TIMEOUT_SEC", 1.5))

    def _load_celery_app(self) -> Any:
        from services.celery_app import celery_app

        return celery_app

    def _has_live_worker(self, celery_app: Any) -> bool:
        if celery_app is None:
            return False
        if not self.require_live_worker:
            return True

        try:
            inspector = celery_app.control.inspect(timeout=self.worker_ping_timeout_sec)
            if inspector is None:
                return False
            ping_result = inspector.ping()
            return bool(ping_result)
        except Exception:
            return False

    def is_available(self) -> bool:
        celery_app = self._load_celery_app()
        if celery_app is None:
            return False
        return self._has_live_worker(celery_app)

    def availability_error(self) -> Optional[str]:
        if self.is_available():
            return None
        celery_app = self._load_celery_app()
        if celery_app is None:
            return "Celery is not installed or the worker queue is not configured for this environment."
        if self.require_live_worker:
            return "Celery is configured, but no live worker responded to the broker ping."
        return "Celery queue is unavailable."

    def enqueue_migration(self, job_id: str, request: MigrationRequest) -> QueuedMigrationTask:
        return self.enqueue_task(
            task_name=MIGRATION_CORE_TASK_NAME,
            job_id=job_id,
            request_payload=request.model_dump(mode="json"),
            queue_name=self.queue_name,
        )

    def enqueue_task(
        self,
        *,
        task_name: str,
        job_id: str,
        request_payload: dict[str, Any],
        queue_name: str,
        skip_worker_availability_check: bool = False,
    ) -> QueuedMigrationTask:
        celery_app = self._load_celery_app()
        if celery_app is None:
            raise QueueUnavailableError(self.availability_error() or "Celery queue is unavailable.")
        if not skip_worker_availability_check and not self._has_live_worker(celery_app):
            raise QueueUnavailableError(self.availability_error() or "Celery queue is unavailable.")
        async_result = celery_app.send_task(
            task_name,
            kwargs={
                "job_id": job_id,
                "request_payload": request_payload,
            },
            queue=queue_name,
        )
        return QueuedMigrationTask(task_id=async_result.id, queue_name=queue_name)

    def revoke(self, task_id: str, *, terminate: bool = False) -> None:
        celery_app = self._load_celery_app()
        if celery_app is None:
            raise QueueUnavailableError(self.availability_error() or "Celery queue is unavailable.")
        celery_app.control.revoke(task_id, terminate=terminate)


def build_queue_metadata(task_id: str, queue_name: str = CELERY_TASK_QUEUE) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "queue": queue_name,
    }


def default_worker_queues() -> tuple[str, str, str]:
    return (
        CELERY_TASK_QUEUE_CORE,
        CELERY_TASK_QUEUE_TESTS,
        CELERY_TASK_QUEUE_SCANS,
    )
