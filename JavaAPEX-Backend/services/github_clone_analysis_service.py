"""
Clone-first repository analysis for GitHub repositories.
"""
from __future__ import annotations

from typing import Any, Dict, List

from services.github_service import GitHubService
from services.github_service import get_cached, set_cached
from services.local_repository_analysis_service import LocalRepositoryAnalysisService
from services.repository_workspace_service import RepositoryWorkspace, RepositoryWorkspaceService


class GitHubCloneAnalysisService:
    def __init__(self) -> None:
        self.workspace_service = RepositoryWorkspaceService()
        self.analysis_service = LocalRepositoryAnalysisService()
        self.github_service = GitHubService()

    async def prepare_workspace(
        self,
        repo_reference: str,
        token: str = "",
        force_refresh: bool = False,
    ) -> RepositoryWorkspace:
        normalized_repo_url, owner, repo = self.workspace_service.parse_repo_reference(repo_reference)
        if token.strip():
            self.github_service.validate_repository_access(token, owner, repo, normalized_repo_url)
        return await self.workspace_service.prepare_workspace(
            repo_reference=repo_reference,
            token=token,
            force_refresh=force_refresh,
        )

    async def read_workspace_file_content(self, workspace: RepositoryWorkspace, file_path: str) -> str:
        return await self.analysis_service.read_file_content(workspace, file_path=file_path)

    async def analyze_repository(
        self,
        repo_reference: str,
        token: str = "",
        force_refresh: bool = False,
    ) -> tuple[RepositoryWorkspace, Dict[str, Any]]:
        workspace = await self.prepare_workspace(
            repo_reference=repo_reference,
            token=token,
            force_refresh=force_refresh,
        )

        cache_key = f"analysis:clone:{workspace.cache_key}"
        if not force_refresh:
            cached = get_cached(cache_key)
            if cached:
                return workspace, cached

        analysis = await self.analysis_service.analyze_workspace(workspace)
        set_cached(cache_key, analysis)
        if workspace.auth_scope_key == "public":
            set_cached(f"analysis:{workspace.owner}/{workspace.repo}", analysis)
            set_cached(f"analysis:v2:{workspace.owner}/{workspace.repo}:deep=False", analysis)
        return workspace, analysis

    async def list_files(self, repo_reference: str, token: str = "", path: str = "") -> tuple[RepositoryWorkspace, List[Dict[str, Any]]]:
        workspace = await self.prepare_workspace(repo_reference=repo_reference, token=token)
        files = await self.analysis_service.list_files(workspace, path=path)
        return workspace, files

    async def get_file_content(self, repo_reference: str, file_path: str, token: str = "") -> tuple[RepositoryWorkspace, str]:
        workspace = await self.prepare_workspace(repo_reference=repo_reference, token=token)
        content = await self.read_workspace_file_content(workspace, file_path=file_path)
        return workspace, content


github_clone_analysis_service = GitHubCloneAnalysisService()
