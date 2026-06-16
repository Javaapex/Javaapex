"""Migration analysis and preview endpoints."""

from __future__ import annotations

import difflib
import logging
import os
import traceback
from typing import Any, Awaitable, Callable, Dict, List

from fastapi import APIRouter, HTTPException

from models.job_models import GitPlatform, MigrationRequest

logger = logging.getLogger(__name__)


def create_migration_router(
    *,
    github_service: Any,
    gitlab_service: Any,
    migration_service: Any,
    effective_github_token: Callable[..., str],
    resolve_source_project_path: Callable[[str, Any, str], Awaitable[str]],
) -> APIRouter:
    router = APIRouter(tags=["migration"])

    @router.post("/migration/preview")
    async def preview_migration_changes(request: MigrationRequest):
        """Preview what changes will be made during migration without actually applying them."""
        try:
            logger.info("Starting migration preview for source=%s", request.source_repo_url)

            if request.platform == GitPlatform.GITLAB:
                repo_service = gitlab_service
                source_token = (request.token or "").strip()
            else:
                repo_service = github_service
                source_token = effective_github_token(
                    token=request.token or "",
                    github_token=request.github_token or "",
                )

            clone_path = await resolve_source_project_path(
                request.source_repo_url,
                repo_service,
                source_token,
            )
            logger.info("Prepared migration preview source path=%s", clone_path)

            current_analysis = await migration_service.analyze_project(clone_path)
            preview_changes = await migration_service.preview_migration_changes(
                clone_path,
                request.source_java_version,
                request.target_java_version.value,
                request.conversion_types,
                request.fix_business_logic,
            )
            file_diffs = await _generate_file_diffs(clone_path, preview_changes)

            return {
                "repository": request.source_repo_url,
                "platform": request.platform.value,
                "source_version": request.source_java_version,
                "target_version": request.target_java_version.value,
                "conversions": request.conversion_types,
                "business_logic_fixes": request.fix_business_logic,
                "summary": {
                    "files_to_modify": len(preview_changes.get("files_to_modify", [])),
                    "files_to_create": len(preview_changes.get("files_to_create", [])),
                    "files_to_remove": len(preview_changes.get("files_to_remove", [])),
                    "total_changes": sum(
                        len(changes) for changes in preview_changes.get("file_changes", {}).values()
                    ),
                },
                "changes": preview_changes,
                "file_diffs": file_diffs[:10],
                "dependencies": {
                    "current": current_analysis.get("dependencies", []),
                    "upgrades": [
                        dependency
                        for dependency in current_analysis.get("dependencies", [])
                        if dependency.get("status") == "upgraded"
                    ],
                },
            }
        except Exception as exc:
            logger.exception("Migration preview failed for source=%s", request.source_repo_url)
            raise HTTPException(status_code=500, detail=f"Preview failed: {str(exc)}") from exc

    return router


async def _generate_file_diffs(clone_path: str, changes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate git-style diffs for changed files."""
    diffs: List[Dict[str, Any]] = []

    files_to_check = changes.get("files_to_modify", [])[:5]
    for file_path in files_to_check:
        full_path = os.path.join(clone_path, file_path)
        if not os.path.exists(full_path):
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as handle:
                current_content = handle.readlines()

            new_content = _simulate_file_changes(
                current_content,
                changes.get("file_changes", {}).get(file_path, []),
            )
            diff = list(
                difflib.unified_diff(
                    current_content,
                    new_content,
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    lineterm="",
                )
            )
            if diff:
                diffs.append(
                    {
                        "file_path": file_path,
                        "diff": "\n".join(diff[:50]),
                        "change_count": len([line for line in diff if line.startswith(("+", "-"))]),
                    }
                )
        except Exception as exc:
            logger.warning("Failed to generate preview diff for %s: %s", file_path, exc)

    return diffs


def _simulate_file_changes(lines: List[str], changes: List[Dict[str, Any]]) -> List[str]:
    """Simulate applying preview changes to file content."""
    new_lines = lines.copy()
    for change in changes:
        if change.get("type") != "replace":
            continue

        old_text = change.get("old", "")
        new_text = change.get("new", "")
        for index, line in enumerate(new_lines):
            if old_text in line:
                new_lines[index] = line.replace(old_text, new_text)
                break
    return new_lines
