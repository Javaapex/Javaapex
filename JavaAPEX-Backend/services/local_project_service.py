"""
Local project analysis and staging support.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from services.local_repository_analysis_service import LocalRepositoryAnalysisService
from services.repository_workspace_service import (
    RepositoryPathError,
    RepositoryWorkspace,
    RepositoryWorkspaceError,
)


def _enable_long_path_on_windows() -> None:
    """Enable long path support on Windows (>260 chars)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetDefaultDllDirectories(0x0800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
        except Exception:
            pass  # Long paths may not be available; continue without enabling


def _to_long_path(path: str) -> str:
    """Convert Windows path to long path format (\\?\...) for absolute paths."""
    if sys.platform == "win32":
        abs_path = os.path.abspath(path)
        if not abs_path.startswith("\\\\?\\"):
            if abs_path.startswith("\\\\"):
                return f"\\\\?\\UNC\\{abs_path[2:]}"
            return f"\\\\?\\{abs_path}"
        return abs_path
    return path


class _SimpleUploadFile:
    def __init__(self, filename: str, file_obj):
        self.filename = filename
        self.file = file_obj


_enable_long_path_on_windows()


def _parse_allowed_roots(value: str) -> List[str]:
    roots: List[str] = []
    seen = set()
    for raw_root in (value or "").split(","):
        root = raw_root.strip()
        if not root:
            continue
        canonical = os.path.normcase(os.path.realpath(os.path.abspath(root)))
        if canonical in seen:
            continue
        seen.add(canonical)
        roots.append(canonical)
    return roots


class LocalProjectService:
    def __init__(self) -> None:
        work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
        self.analysis_service = LocalRepositoryAnalysisService()
        self.hosted_mode = bool(os.getenv("RENDER"))
        enabled_default = "false" if self.hosted_mode else "true"
        self.local_projects_enabled = os.getenv("LOCAL_PROJECTS_ENABLED", enabled_default).strip().lower() not in {"0", "false", "no"}

        allow_any_env = os.getenv("LOCAL_PROJECT_ALLOW_ANY_PATH", "").strip().lower()
        if allow_any_env:
            self.allow_any_path = allow_any_env in {"1", "true", "yes"}
        else:
            self.allow_any_path = not self.hosted_mode

        configured_roots = _parse_allowed_roots(os.getenv("LOCAL_PROJECT_ALLOWED_ROOTS", ""))
        if configured_roots:
            self.allowed_roots = configured_roots
        elif self.allow_any_path:
            self.allowed_roots = []
        else:
            self.allowed_roots = []

        self.local_stage_root = os.path.join(work_dir, "local_project_staging")
        os.makedirs(self.local_stage_root, exist_ok=True)

        self.chunked_upload_root = os.path.join(self.local_stage_root, "chunked_uploads")
        os.makedirs(self.chunked_upload_root, exist_ok=True)

    def get_capabilities(self) -> Dict[str, object]:
        if not self.local_projects_enabled:
            if self.hosted_mode:
                message = (
                    "Local project analysis is disabled on this hosted deployment. "
                    "Set LOCAL_PROJECTS_ENABLED=true and configure server-accessible roots using LOCAL_PROJECT_ALLOWED_ROOTS to enable this. "
                    "Note: this works only for paths that are accessible from the backend container, not files on your local computer."
                )
            else:
                message = "Local project analysis is disabled by server configuration."
        elif self.hosted_mode and not self.allow_any_path and not self.allowed_roots:
            message = (
                "Hosted deployments can analyze only server-accessible local paths. "
                "Configure LOCAL_PROJECT_ALLOWED_ROOTS or LOCAL_PROJECT_ALLOW_ANY_PATH to enable this. "
                "The provided path must exist inside the backend environment, not on your local machine."
            )
        elif self.hosted_mode and not self.allow_any_path:
            message = (
                "Upload local projects using the file uploader. Your uploaded files will be extracted and analyzed on the backend."
            )
        else:
            message = "Local project analysis is enabled."

        return {
            "enabled": self.local_projects_enabled,
            "hosted_mode": self.hosted_mode,
            "allow_any_path": self.allow_any_path,
            "allowed_roots": self.allowed_roots,
            "supports_upload": True,
            "message": message,
        }

    async def upload_project(self, uploaded_files: List[Any], project_name: str | None = None) -> tuple[RepositoryWorkspace, Dict[str, object]]:
        project_path = await asyncio.to_thread(self.stage_uploaded_project_files, uploaded_files, project_name)
        workspace = self.prepare_workspace(project_path)
        analysis = await self.analysis_service.analyze_workspace(workspace)
        return workspace, analysis

    async def upload_project_chunk(
        self,
        upload_id: str,
        chunk_index: int,
        total_chunks: int,
        chunk_file: Any,
        file_name: str | None = None,
        project_name: str | None = None,
    ) -> tuple[RepositoryWorkspace, Dict[str, object]] | None:
        await self.stage_uploaded_project_chunk(upload_id, chunk_index, total_chunks, chunk_file)
        if chunk_index < total_chunks:
            return None
        return await self.combine_uploaded_project_chunks(upload_id, total_chunks, chunk_file, project_name, file_name)

    async def stage_uploaded_project_chunk(
        self,
        upload_id: str,
        chunk_index: int,
        chunk_count: int,
        chunk_file: Any,
    ) -> None:
        if chunk_index < 1 or chunk_count < 1 or chunk_index > chunk_count:
            raise RepositoryPathError("Invalid chunk index or chunk count")

        upload_dir = os.path.join(self.local_stage_root, "chunked_uploads", upload_id)
        os.makedirs(_to_long_path(upload_dir), exist_ok=True)

        chunk_file.file.seek(0)
        chunk_path = os.path.join(upload_dir, f"{chunk_index:04d}")
        with open(_to_long_path(chunk_path), "wb") as dest:
            shutil.copyfileobj(chunk_file.file, dest)

    async def combine_uploaded_project_chunks(
        self,
        upload_id: str,
        chunk_count: int,
        final_chunk_file: Any,
        project_name: str | None = None,
        file_name: str | None = None,
    ) -> tuple[RepositoryWorkspace, Dict[str, object]]:
        upload_dir = os.path.join(self.local_stage_root, "chunked_uploads", upload_id)
        zip_path = os.path.join(upload_dir, "upload.zip")

        with open(_to_long_path(zip_path), "wb") as target:
            for index in range(1, chunk_count + 1):
                chunk_path = os.path.join(upload_dir, f"{index:04d}")
                if not os.path.exists(chunk_path):
                    raise RepositoryPathError("Missing upload chunk for local project")
                with open(_to_long_path(chunk_path), "rb") as source:
                    shutil.copyfileobj(source, target)

        with open(_to_long_path(zip_path), "rb") as zip_file:
            upload_file = SimpleNamespace(filename=file_name or final_chunk_file.filename or "local-project.zip", file=zip_file)
            project_path = self.stage_uploaded_project_files([upload_file], project_name)

        workspace = self.prepare_workspace(project_path)
        analysis = await self.analysis_service.analyze_workspace(workspace)
        return workspace, analysis

    def stage_uploaded_project_files(self, uploaded_files: List[Any], project_name: str | None = None) -> str:
        target_path = os.path.join(self.local_stage_root, str(uuid.uuid4()))
        target_path_long = _to_long_path(target_path)
        os.makedirs(target_path_long, exist_ok=True)

        if len(uploaded_files) == 1 and uploaded_files[0].filename.lower().endswith(".zip"):
            upload_file = uploaded_files[0]
            upload_file.file.seek(0)
            with zipfile.ZipFile(upload_file.file) as archive:
                for member in archive.namelist():
                    normalized = os.path.normpath(member)
                    if normalized.startswith("..") or os.path.isabs(normalized):
                        raise RepositoryPathError("Uploaded ZIP archive contains invalid path entries.")
                    if normalized.endswith("/") or normalized.endswith("\\"):
                        continue
                    destination = os.path.join(target_path, normalized)
                    destination_long = _to_long_path(destination)
                    
                    try:
                        parent_dir_long = _to_long_path(os.path.dirname(destination))
                        os.makedirs(parent_dir_long, exist_ok=True)
                    except FileExistsError:
                        dir_path = os.path.dirname(destination)
                        if not os.path.isdir(dir_path):
                            raise RepositoryPathError(
                                f"Cannot create directory '{os.path.basename(dir_path)}': a file with this name already exists."
                            )
                    
                    if os.path.exists(destination) and os.path.isdir(destination):
                        raise RepositoryPathError(f"Cannot write file to '{normalized}': a directory with this name already exists.")
                    
                    try:
                        with archive.open(member) as source, open(destination_long, "wb") as dest:
                            shutil.copyfileobj(source, dest)
                    except Exception as e:
                        raise RepositoryPathError(f"Failed to extract file '{normalized}': {str(e)}")
        else:
            for upload_file in uploaded_files:
                raw_filename = upload_file.filename or ""
                if raw_filename.endswith("/") or raw_filename.endswith("\\"):
                    # Skip directory placeholders that may be included in some multi-file uploads.
                    continue

                filename = os.path.normpath(raw_filename)
                if not filename:
                    continue
                if filename.startswith("/") or filename.startswith("\\") or filename.replace("\\", "/").split("/")[0] == "..":
                    raise RepositoryPathError("Uploaded file contains invalid path segments.")
                destination = os.path.join(target_path, filename)
                destination = os.path.abspath(destination)
                if os.path.commonpath([target_path, destination]) != target_path:
                    raise RepositoryPathError("Uploaded file path is not allowed.")

                parent_dir = os.path.dirname(destination)
                parent_dir_long = _to_long_path(parent_dir)
                if os.path.exists(parent_dir) and os.path.isfile(parent_dir):
                    raise RepositoryPathError(
                        f"Cannot create directory '{os.path.basename(parent_dir)}': a file with this name already exists."
                    )

                try:
                    os.makedirs(parent_dir_long, exist_ok=True)
                except FileExistsError:
                    if not os.path.isdir(parent_dir):
                        raise RepositoryPathError(
                            f"Cannot create directory '{os.path.basename(parent_dir)}': a file with this name already exists."
                        )

                if os.path.exists(destination) and os.path.isdir(destination):
                    raise RepositoryPathError(f"Cannot write file: a directory already exists at '{filename}'.")

                destination_long = _to_long_path(destination)
                try:
                    with open(destination_long, "wb") as dest:
                        shutil.copyfileobj(upload_file.file, dest)
                except Exception as e:
                    raise RepositoryPathError(f"Failed to write file '{filename}': {str(e)}")

        return target_path

    async def analyze_project(self, project_path: str) -> tuple[RepositoryWorkspace, Dict[str, object]]:
        workspace = self.prepare_workspace(project_path)
        analysis = await self.analysis_service.analyze_workspace(workspace)
        return workspace, analysis

    async def list_files(self, project_path: str, path: str = "") -> tuple[RepositoryWorkspace, List[Dict[str, object]]]:
        workspace = self.prepare_workspace(project_path)
        files = await self.analysis_service.list_files(workspace, path)
        return workspace, files

    async def get_file_content(self, project_path: str, file_path: str) -> tuple[RepositoryWorkspace, str]:
        workspace = self.prepare_workspace(project_path)
        content = await self.analysis_service.read_file_content(workspace, file_path)
        return workspace, content

    async def stage_project_copy(self, project_path: str) -> str:
        source_path = self.resolve_local_project_path(project_path)
        target_path = os.path.join(self.local_stage_root, str(uuid.uuid4()))
        await asyncio.to_thread(shutil.copytree, source_path, target_path)
        return target_path

    def prepare_workspace(self, project_path: str) -> RepositoryWorkspace:
        source_path = self.resolve_local_project_path(project_path)
        repo_name = Path(source_path).name or "local-project"
        cache_key = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:24]
        return RepositoryWorkspace(
            repo_url=f"local://{source_path}",
            normalized_repo_url=f"local://{source_path}",
            owner="local",
            repo=repo_name,
            workspace_path=source_path,
            default_branch="local",
            cache_key=cache_key,
            auth_scope_key="local",
        )

    def resolve_local_project_path(self, project_path: str) -> str:
        capabilities = self.get_capabilities()
        if not capabilities["enabled"]:
            raise RepositoryWorkspaceError(str(capabilities["message"]))

        cleaned = (project_path or "").strip()
        if cleaned.startswith("local://"):
            cleaned = cleaned[len("local://") :]

        if not cleaned:
            raise RepositoryPathError("Local project path is required.")

        resolved = os.path.normcase(os.path.realpath(os.path.abspath(cleaned)))
        if not os.path.exists(resolved):
            raise RepositoryPathError(f"Local project path not found: {cleaned}")
        if not os.path.isdir(resolved):
            raise RepositoryPathError(f"Local project path is not a directory: {cleaned}")

        if self.allow_any_path:
            return resolved

        for allowed_root in self.allowed_roots:
            try:
                if os.path.commonpath([allowed_root, resolved]) == allowed_root:
                    return resolved
            except ValueError:
                continue

        allowed_roots_text = ", ".join(self.allowed_roots) if self.allowed_roots else "configured server roots"
        raise RepositoryPathError(
            f"Local project path is not allowed by server configuration. Allowed roots: {allowed_roots_text}"
        )


local_project_service = LocalProjectService()
