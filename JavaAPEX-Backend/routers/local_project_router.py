"""
Local project analysis endpoints.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from services.local_project_service import local_project_service
from services.repository_workspace_service import RepositoryPathError, RepositoryWorkspaceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["local-project"])


class LocalProjectAnalyzeRequest(BaseModel):
    project_path: str = Field(description="Absolute path to the local project directory accessible by the backend.")


def _to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, RepositoryPathError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RepositoryWorkspaceError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Internal server error: {exc}")


@router.get("/local-project/capabilities")
async def get_local_project_capabilities():
    return local_project_service.get_capabilities()


@router.post("/local-project/analyze")
async def analyze_local_project(request: LocalProjectAnalyzeRequest):
    try:
        workspace, analysis = await local_project_service.analyze_project(request.project_path)
        return {
            "project_path": workspace.workspace_path,
            "project_name": workspace.repo,
            "repo_url": workspace.repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "analysis": analysis,
        }
    except Exception as exc:
        logger.exception("Local project analysis failed for %s", request.project_path)
        raise _to_http_exception(exc) from exc


@router.post("/local-project/upload")
async def upload_local_project(
    files: list[UploadFile] = File(...),
    project_name: str | None = Form(None),
):
    try:
        workspace, analysis = await local_project_service.upload_project(files, project_name)
        return {
            "project_path": workspace.workspace_path,
            "project_name": workspace.repo,
            "repo_url": workspace.repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "analysis": analysis,
        }
    except Exception as exc:
        logger.exception("Local project upload failed")
        raise _to_http_exception(exc) from exc


@router.post("/local-project/upload-chunk")
async def upload_local_project_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk_count: int = Form(0),
    total_chunks: int = Form(0),
    file: UploadFile = File(...),
    file_name: str | None = Form(None),
    project_name: str | None = Form(None),
):
    try:
        chunk_count = chunk_count or total_chunks
        if chunk_index < 1 or chunk_count < 1 or chunk_index > chunk_count:
            raise ValueError("Invalid chunk index or chunk count")

        result = await local_project_service.upload_project_chunk(
            upload_id,
            chunk_index,
            chunk_count,
            file,
            file_name,
            project_name,
        )

        if result is None:
            return {
                "status": "chunk_received",
                "upload_id": upload_id,
                "chunk_index": chunk_index,
                "total_chunks": chunk_count,
            }

        workspace, analysis = result
        return {
            "project_path": workspace.workspace_path,
            "project_name": workspace.repo,
            "repo_url": workspace.repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "analysis": analysis,
        }
    except Exception as exc:
        logger.exception("Local project chunk upload failed")
        raise _to_http_exception(exc) from exc


@router.get("/local-project/list-files")
async def list_local_project_files(project_path: str, path: str = ""):
    try:
        workspace, files = await local_project_service.list_files(project_path, path=path)
        return {
            "repo_url": workspace.repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "project_path": workspace.workspace_path,
            "project_name": workspace.repo,
            "path": path,
            "files": files,
        }
    except Exception as exc:
        logger.exception("Local project file listing failed for %s", project_path)
        raise _to_http_exception(exc) from exc


@router.get("/local-project/file-content")
async def get_local_project_file_content(project_path: str, file_path: str):
    try:
        workspace, content = await local_project_service.get_file_content(project_path, file_path=file_path)
        return {
            "repo_url": workspace.repo_url,
            "owner": workspace.owner,
            "repo": workspace.repo,
            "project_path": workspace.workspace_path,
            "project_name": workspace.repo,
            "file_path": file_path,
            "content": content,
        }
    except Exception as exc:
        logger.exception("Local project file content read failed for %s:%s", project_path, file_path)
        raise _to_http_exception(exc) from exc
