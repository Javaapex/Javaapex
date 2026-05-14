"""
GitHub repository endpoints backed by clone-first local analysis.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from services.github_clone_analysis_service import github_clone_analysis_service
from services.repository_workspace_service import (
    RepositoryAuthenticationError,
    RepositoryCloneTimeoutError,
    RepositoryNotFoundError,
    RepositoryPathError,
    RepositoryWorkspaceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github-repository"])
DEFAULT_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


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


@router.get("/github/repo/{owner}/{repo}/analyze")
async def analyze_repository(owner: str, repo: str, token: str = ""):
    try:
        workspace, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=f"{owner}/{repo}",
            token=_effective_token(token),
        )
        return {
            **analysis,
            "name": analysis.get("name") or workspace.repo,
            "full_name": analysis.get("full_name") or f"{workspace.owner}/{workspace.repo}",
        }
    except Exception as exc:
        raise _to_http_exception(exc) from exc


@router.get("/github/analyze-url")
async def analyze_repo_url(repo_url: str, token: str = "", force_refresh: bool = False):
    try:
        workspace, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=repo_url,
            token=_effective_token(token),
            force_refresh=force_refresh,
        )
        return {
            "repo_url": repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "analysis": analysis,
        }
    except Exception as exc:
        logger.exception("Clone-first repository analysis failed for %s", repo_url)
        raise _to_http_exception(exc) from exc


@router.get("/github/list-files")
async def list_repo_files(repo_url: str, token: str = "", path: str = ""):
    try:
        workspace, files = await github_clone_analysis_service.list_files(
            repo_reference=repo_url,
            token=_effective_token(token),
            path=path,
        )
        return {
            "repo_url": repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "path": path,
            "files": files,
        }
    except Exception as exc:
        logger.exception("Clone-first repository file listing failed for %s", repo_url)
        raise _to_http_exception(exc) from exc


@router.get("/github/file-content")
async def get_file_content(repo_url: str, file_path: str, token: str = ""):
    try:
        workspace, content = await github_clone_analysis_service.get_file_content(
            repo_reference=repo_url,
            file_path=file_path,
            token=_effective_token(token),
        )
        return {
            "repo_url": repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "file_path": file_path,
            "content": content,
        }
    except Exception as exc:
        logger.exception("Clone-first file content read failed for %s:%s", repo_url, file_path)
        raise _to_http_exception(exc) from exc
