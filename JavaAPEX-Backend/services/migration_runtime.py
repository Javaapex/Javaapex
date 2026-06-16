"""Shared migration runtime bootstrap for web and worker processes."""

from __future__ import annotations

import logging
import os
from typing import Optional

from services import job_service as job_service_module
from services.artifact_service import ArtifactService
from services.email_service import EmailService
from services.fossa_service import FossaService
from services.github_service import GitHubService
from services.gitlab_service import GitLabService
from services.job_queue import CeleryMigrationJobQueue
from services.persistent_job_store import PersistentListStore
from services.migration_orchestrator import MigrationOrchestrator
from services.migration_runtime_support import (
    effective_github_token,
    first_nonempty_token,
    generate_migration_issues,
    generate_repository_file_diffs,
    generate_testcase_doc_markdown,
    infer_local_project_name,
    is_local_project_reference,
    parse_target_repository_destination,
    prepare_source_working_copy,
    publish_migrated_project_locally,
    sanitize_local_publish_folder_name,
)
from services.migration_service import MigrationService
from services.sonarqube_service import SonarQubeService

logger = logging.getLogger(__name__)


def _create_migration_job_log_store() -> PersistentListStore[str]:
    factory = getattr(job_service_module, "create_migration_job_log_store", None)
    if callable(factory):
        return factory()

    logger.warning(
        "services.job_service.create_migration_job_log_store is unavailable; "
        "falling back to inline migration log store bootstrap."
    )
    return PersistentListStore(
        serializer=lambda entry: entry,
        deserializer=lambda data: str(data),
        redis_url=(
            os.environ.get("REDIS_URL", "").strip()
            or os.environ.get("CELERY_BROKER_URL", "").strip()
            or os.environ.get("CELERY_RESULT_BACKEND", "").strip()
        ),
        namespace=os.environ.get("MIGRATION_JOB_LOG_STORE_NAMESPACE", "migration_logs"),
        cache_in_memory_when_redis=False,
        max_cached_items=16,
    )


github_service = GitHubService()
gitlab_service = GitLabService()
migration_service = MigrationService()
email_service = EmailService()
sonarqube_service = SonarQubeService()
fossa_service = FossaService()
migration_jobs = job_service_module.create_migration_job_store()
migration_job_runtime_details = job_service_module.create_migration_job_runtime_detail_store()
migration_job_logs = _create_migration_job_log_store()
job_service = job_service_module.MigrationJobService(
    migration_jobs,
    migration_job_runtime_details,
    migration_job_logs,
)
artifact_service = ArtifactService(job_service=job_service)
job_queue = CeleryMigrationJobQueue()

_migration_orchestrator: Optional[MigrationOrchestrator] = None


def get_migration_orchestrator() -> MigrationOrchestrator:
    global _migration_orchestrator
    if _migration_orchestrator is None:
        _migration_orchestrator = MigrationOrchestrator(
            job_service=job_service,
            artifact_service=artifact_service,
            github_service=github_service,
            gitlab_service=gitlab_service,
            migration_service=migration_service,
            sonarqube_service=sonarqube_service,
            fossa_service=fossa_service,
            email_service=email_service,
            prepare_source_working_copy=prepare_source_working_copy,
            generate_migration_issues=generate_migration_issues,
            is_local_project_reference=is_local_project_reference,
            infer_local_project_name=infer_local_project_name,
            parse_target_repository_destination=parse_target_repository_destination,
            sanitize_local_publish_folder_name=sanitize_local_publish_folder_name,
            effective_github_token=effective_github_token,
            first_nonempty_token=first_nonempty_token,
            publish_migrated_project_locally=publish_migrated_project_locally,
            generate_repository_file_diffs=generate_repository_file_diffs,
            generate_testcase_doc_markdown=generate_testcase_doc_markdown,
        )
    return _migration_orchestrator

