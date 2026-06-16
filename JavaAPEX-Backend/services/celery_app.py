"""Celery application bootstrap for Phase 2 worker execution."""

from __future__ import annotations

from typing import Any

try:
    from celery import Celery
except Exception:  # pragma: no cover
    Celery = None  # type: ignore[assignment]

from utils.config import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    CELERY_TASK_QUEUE,
    CELERY_TASK_QUEUE_CORE,
    CELERY_TASK_QUEUE_SCANS,
    CELERY_TASK_QUEUE_TESTS,
    CELERY_TASK_SOFT_TIME_LIMIT_SEC,
    CELERY_TASK_TIME_LIMIT_SEC,
    MIGRATION_MAX_CONCURRENT_JOBS,
)
from services.job_queue import (
    MIGRATION_CORE_TASK_NAME,
    MIGRATION_SCANS_TASK_NAME,
    MIGRATION_TESTS_TASK_NAME,
)


def create_celery_app() -> Any:
    if Celery is None:
        return None
    app = Celery(
        "javaapex_backend",
        broker=CELERY_BROKER_URL or None,
        backend=CELERY_RESULT_BACKEND or None,
        include=["workers.migration_worker"],
    )
    app.conf.update(
        task_default_queue=CELERY_TASK_QUEUE,
        task_routes={
            MIGRATION_CORE_TASK_NAME: {"queue": CELERY_TASK_QUEUE_CORE},
            MIGRATION_TESTS_TASK_NAME: {"queue": CELERY_TASK_QUEUE_TESTS},
            MIGRATION_SCANS_TASK_NAME: {"queue": CELERY_TASK_QUEUE_SCANS},
        },
        task_track_started=True,
        task_time_limit=CELERY_TASK_TIME_LIMIT_SEC,
        task_soft_time_limit=CELERY_TASK_SOFT_TIME_LIMIT_SEC,
        worker_prefetch_multiplier=1,
        worker_concurrency=MIGRATION_MAX_CONCURRENT_JOBS,
        task_acks_late=True,
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = create_celery_app()
