from __future__ import annotations

import logging
from typing import Any, Dict

from analyzers.microservice_readiness_analyzer import MicroserviceReadinessAnalyzer
from models.microservice_readiness import MicroserviceReadinessReport
from services.repository_workspace_service import RepositoryWorkspace

logger = logging.getLogger(__name__)


class MicroserviceReadinessService:
    def __init__(self) -> None:
        self._analyzer = MicroserviceReadinessAnalyzer()

    async def analyze_repository(
        self,
        workspace: RepositoryWorkspace,
        analysis_data: Dict[str, Any],
    ) -> MicroserviceReadinessReport:
        logger.info("Running microservice readiness service for %s", workspace.repo_url)
        return self._analyzer.analyze(workspace, analysis_data)


microservice_readiness_service = MicroserviceReadinessService()

