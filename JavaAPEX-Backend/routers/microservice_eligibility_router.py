"""
Microservice readiness endpoints using a dedicated analyzer stack.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.config import DEFAULT_GITHUB_TOKEN
from services.github_clone_analysis_service import github_clone_analysis_service
from services.local_project_service import local_project_service
from services.microservice_readiness_service import microservice_readiness_service
from services.repository_workspace_service import (
    RepositoryAuthenticationError,
    RepositoryCloneTimeoutError,
    RepositoryNotFoundError,
    RepositoryPathError,
    RepositoryWorkspaceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["microservice-readiness"])


class LocalMicroserviceReadinessRequest(BaseModel):
    project_path: str = Field(description="Absolute path to the local project directory accessible by the backend.")
    analysis: Dict[str, Any] = Field(default_factory=dict)


class GithubMicroserviceReadinessRequest(BaseModel):
    repo_url: str = Field(description="GitHub repository URL or owner/repository reference.")
    token: str = Field(default="", description="Optional GitHub Personal Access Token.")
    analysis: Dict[str, Any] = Field(default_factory=dict)


def _effective_token(token: str) -> str:
    return token.strip() if token and token.strip() else DEFAULT_GITHUB_TOKEN


def _to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, RepositoryNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RepositoryAuthenticationError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, RepositoryPathError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RepositoryCloneTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, RepositoryWorkspaceError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Internal server error: {exc}")


def _has_prefetched_analysis(analysis: Dict[str, Any]) -> bool:
    if not isinstance(analysis, dict):
        return False
    return any(
        key in analysis
        for key in ("java_file_count", "dependencies", "build_tool", "has_tests", "structure")
    )


@router.get("/github/microservice-eligibility", response_model=Dict[str, Any])
async def get_microservice_eligibility(repo_url: str, token: str = ""):
    try:
        workspace, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=repo_url,
            token=_effective_token(token),
            force_refresh=False,
        )
        return await microservice_readiness_service.analyze_repository(workspace, analysis)
    except Exception as exc:
        logger.exception("Microservice readiness analysis failed for %s", repo_url)
        raise _to_http_exception(exc) from exc


@router.post("/github/microservice-eligibility", response_model=Dict[str, Any])
async def post_microservice_eligibility(request: GithubMicroserviceReadinessRequest):
    try:
        effective_token = _effective_token(request.token)
        workspace = await github_clone_analysis_service.prepare_workspace(
            repo_reference=request.repo_url,
            token=effective_token,
            force_refresh=False,
        )
        analysis = request.analysis if _has_prefetched_analysis(request.analysis) else None
        if analysis is None:
            _, analysis = await github_clone_analysis_service.analyze_repository(
                repo_reference=request.repo_url,
                token=effective_token,
                force_refresh=False,
            )
        return await microservice_readiness_service.analyze_repository(workspace, analysis)
    except Exception as exc:
        logger.exception("Microservice readiness analysis failed for %s", request.repo_url)
        raise _to_http_exception(exc) from exc


@router.post("/local-project/microservice-eligibility", response_model=Dict[str, Any])
async def get_local_project_microservice_eligibility(request: LocalMicroserviceReadinessRequest):
    try:
        workspace = local_project_service.prepare_workspace(request.project_path)
        analysis = request.analysis if _has_prefetched_analysis(request.analysis) else None
        if analysis is None:
            _, analysis = await local_project_service.analyze_project(request.project_path)
        return await microservice_readiness_service.analyze_repository(workspace, analysis)
    except Exception as exc:
        logger.exception("Local project microservice readiness analysis failed for %s", request.project_path)
        raise _to_http_exception(exc) from exc
