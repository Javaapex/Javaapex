"""Helpers for migration artifact path resolution and persistence."""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from utils.config import (
    DEFAULT_JMETER_BASE_URL,
    DEFAULT_WORK_DIR,
    WORKSPACE_ARTIFACT_ROOT,
    WORKSPACE_RESTORE_ROOT,
)

WORKSPACE_ARTIFACT_URI_PREFIX = "workspace://"
SNAPSHOT_EXCLUDED_DIR_NAMES = {
    ".javaapex-cache",
    ".scannerwork",
    ".gradle",
    "build",
    "dist",
    "node_modules",
    "out",
    "target",
    "__pycache__",
}


class ArtifactService:
    def __init__(
        self,
        *,
        job_service: Any,
        work_dir: str = DEFAULT_WORK_DIR,
        workspace_artifact_root: str = WORKSPACE_ARTIFACT_ROOT,
        workspace_restore_root: str = WORKSPACE_RESTORE_ROOT,
        default_jmeter_base_url: str = DEFAULT_JMETER_BASE_URL,
    ) -> None:
        self.job_service = job_service
        self.work_dir = work_dir
        self.workspace_artifact_root = workspace_artifact_root
        self.workspace_restore_root = workspace_restore_root
        self.default_jmeter_base_url = default_jmeter_base_url

    def resolve_clone_path(self, job: Any) -> Optional[str]:
        clone_path = getattr(job, "clone_path", None)
        if clone_path and os.path.isdir(clone_path):
            return clone_path
        if not clone_path and getattr(job, "target_repo", None) and str(job.target_repo).startswith("local://"):
            clone_path = str(job.target_repo).replace("local://", "")
            if os.path.isdir(clone_path):
                return clone_path
        return None

    def _workspace_artifact_uri(self, job_id: str, filename: str) -> str:
        return f"{WORKSPACE_ARTIFACT_URI_PREFIX}{job_id}/{filename}"

    def _workspace_artifact_local_path(self, artifact_uri: str) -> str:
        raw_uri = str(artifact_uri or "").strip()
        if not raw_uri:
            return ""

        if raw_uri.startswith(WORKSPACE_ARTIFACT_URI_PREFIX):
            relative_path = raw_uri[len(WORKSPACE_ARTIFACT_URI_PREFIX):].lstrip("/\\")
            normalized_path = os.path.normpath(relative_path)
            if normalized_path in {"", "."} or normalized_path.startswith("..") or os.path.isabs(normalized_path):
                raise HTTPException(status_code=400, detail="Workspace artifact URI is invalid.")
            return os.path.join(self.workspace_artifact_root, normalized_path)

        if raw_uri.startswith("file://"):
            parsed = urlparse(raw_uri)
            local_path = unquote(parsed.path or "")
            if os.name == "nt" and len(local_path) >= 3 and local_path[0] == "/" and local_path[2] == ":":
                local_path = local_path[1:]
            if parsed.netloc and not local_path.startswith("//"):
                local_path = f"//{parsed.netloc}{local_path}"
            return os.path.normpath(local_path)

        return raw_uri

    def _job_artifact_dir(self, job_id: str) -> str:
        return os.path.join(self.workspace_artifact_root, job_id)

    def _safe_cleanup_path(self, path: str) -> None:
        target = os.path.abspath(path)
        managed_roots = [
            os.path.abspath(self.work_dir),
            os.path.abspath(self.workspace_restore_root),
        ]
        if not any(target == root or target.startswith(root + os.sep) for root in managed_roots):
            return
        shutil.rmtree(target, ignore_errors=True)

    def _compute_sha256(self, file_path: str) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _should_exclude_snapshot_path(self, relative_path: str) -> bool:
        normalized = str(relative_path or "").replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized:
            return False
        parts = [part.lower() for part in normalized.split("/") if part and part != "."]
        return any(part in SNAPSHOT_EXCLUDED_DIR_NAMES for part in parts)

    def _build_workspace_snapshot_archive(self, clone_path: str, archive_path: str) -> tuple[int, int]:
        archived_entries = 0
        skipped_missing_entries = 0
        clone_root = os.path.abspath(clone_path)

        with tarfile.open(archive_path, "w:gz") as archive:
            for current_root, dir_names, file_names in os.walk(clone_root, topdown=True):
                current_relative = os.path.relpath(current_root, clone_root)
                if current_relative == ".":
                    current_relative = ""

                dir_names[:] = [
                    directory_name
                    for directory_name in dir_names
                    if not self._should_exclude_snapshot_path(
                        os.path.join(current_relative, directory_name) if current_relative else directory_name
                    )
                ]

                if current_relative and not self._should_exclude_snapshot_path(current_relative):
                    try:
                        archive.add(current_root, arcname=current_relative.replace("\\", "/"), recursive=False)
                        archived_entries += 1
                    except FileNotFoundError:
                        skipped_missing_entries += 1
                        continue

                for file_name in file_names:
                    relative_path = os.path.join(current_relative, file_name) if current_relative else file_name
                    if self._should_exclude_snapshot_path(relative_path):
                        continue
                    full_path = os.path.join(current_root, file_name)
                    try:
                        archive.add(full_path, arcname=relative_path.replace("\\", "/"), recursive=False)
                        archived_entries += 1
                    except FileNotFoundError:
                        skipped_missing_entries += 1
                        continue

        return archived_entries, skipped_missing_entries

    def create_workspace_snapshot(self, job_id: str, job: Any, clone_path: str, *, stage: str) -> str:
        if not clone_path or not os.path.isdir(clone_path):
            raise FileNotFoundError(f"Workspace directory not found for snapshot creation: {clone_path}")

        os.makedirs(self._job_artifact_dir(job_id), exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archive_filename = f"workspace-{stage}-{timestamp}.tar.gz"
        archive_base = os.path.join(self._job_artifact_dir(job_id), f"workspace-{stage}-{timestamp}")
        archive_path = f"{archive_base}.tar.gz"
        archived_entries, skipped_missing_entries = self._build_workspace_snapshot_archive(clone_path, archive_path)
        artifact_uri = self._workspace_artifact_uri(job_id, archive_filename)
        checksum = self._compute_sha256(archive_path)

        previous_artifact = getattr(job, "workspace_artifact_uri", None)
        previous_local_path = self._workspace_artifact_local_path(previous_artifact) if previous_artifact else ""
        if previous_local_path and os.path.abspath(previous_local_path) != os.path.abspath(archive_path):
            try:
                if os.path.isfile(previous_local_path):
                    os.remove(previous_local_path)
            except Exception:
                pass

        artifact_created_at = datetime.now(timezone.utc)
        if hasattr(job, "workspace_artifact_uri"):
            job.workspace_artifact_uri = artifact_uri
            job.workspace_artifact_checksum = checksum
            job.workspace_artifact_stage = stage
            job.workspace_artifact_created_at = artifact_created_at
        if hasattr(job, "has_workspace_artifact"):
            job.has_workspace_artifact = True
        self.job_service.update_job_fields(
            job_id,
            workspace_artifact_uri=artifact_uri,
            workspace_artifact_checksum=checksum,
            workspace_artifact_stage=stage,
            workspace_artifact_created_at=artifact_created_at,
            has_workspace_artifact=True,
        )
        self.job_service.add_log(
            job_id,
            f"Persisted workspace snapshot for stage '{stage}' at {artifact_uri} ({archive_path}); archived {archived_entries} entries.",
        )
        if skipped_missing_entries:
            self.job_service.add_log(
                job_id,
                f"Skipped {skipped_missing_entries} transient workspace entries while creating the '{stage}' snapshot.",
            )
        return artifact_uri

    def materialize_workspace_snapshot(
        self,
        job_id: str,
        job: Any,
        *,
        purpose: str,
        detail: str = "Workspace snapshot is not available for this job",
    ) -> str:
        artifact_uri = getattr(job, "workspace_artifact_uri", None)
        if not artifact_uri:
            raise HTTPException(status_code=404, detail=detail)

        archive_path = self._workspace_artifact_local_path(artifact_uri)
        if not archive_path or not os.path.isfile(archive_path):
            raise HTTPException(
                status_code=404,
                detail=f"{detail}. Snapshot path is unavailable: {artifact_uri}",
            )

        os.makedirs(self.workspace_restore_root, exist_ok=True)
        restore_dir = os.path.join(
            self.workspace_restore_root,
            job_id,
            f"{purpose}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
        )
        os.makedirs(restore_dir, exist_ok=True)
        shutil.unpack_archive(archive_path, restore_dir)
        if hasattr(job, "clone_path"):
            job.clone_path = restore_dir
        self.job_service.update_job_fields(job_id, clone_path=restore_dir)
        self.job_service.add_log(job_id, f"Restored workspace snapshot for {purpose} at {restore_dir}")
        return restore_dir

    def externalize_workspace(
        self,
        job_id: str,
        job: Any,
        clone_path: str,
        *,
        stage: str,
        cleanup_source: bool = True,
    ) -> str:
        artifact_uri = self.create_workspace_snapshot(job_id, job, clone_path, stage=stage)
        if cleanup_source:
            self._safe_cleanup_path(clone_path)
            if hasattr(job, "clone_path"):
                job.clone_path = None
            self.job_service.update_job_fields(job_id, clone_path=None)
            self.job_service.add_log(job_id, f"Released local workspace after '{stage}' stage externalization.")
        return artifact_uri

    def require_clone_path(self, job: Any, detail: str = "Local migration directory not found for this job") -> str:
        clone_path = self.resolve_clone_path(job)
        if not clone_path and getattr(job, "workspace_artifact_uri", None):
            clone_path = self.materialize_workspace_snapshot(job.job_id, job, purpose="artifact-access", detail=detail)
        if not clone_path or not os.path.isdir(clone_path):
            raise HTTPException(status_code=404, detail=detail)
        return clone_path

    def maybe_restore_clone_path(self, job: Any, *, purpose: str) -> Optional[str]:
        clone_path = self.resolve_clone_path(job)
        if clone_path:
            return clone_path
        if not getattr(job, "workspace_artifact_uri", None):
            return None
        try:
            return self.materialize_workspace_snapshot(job.job_id, job, purpose=purpose)
        except HTTPException:
            return None
        except Exception as exc:
            try:
                self.job_service.add_log(job.job_id, f"WARNING: Failed to restore workspace snapshot for {purpose}: {exc}")
            except Exception:
                pass
            return None

    def create_zip_archive(self, job_id: str, job: Any) -> str:
        clone_path = self.require_clone_path(job, detail="Migration files not found")

        zip_filename = f"migration-{job_id}"
        zip_path = os.path.join(tempfile.gettempdir(), zip_filename)

        try:
            shutil.make_archive(zip_path, "zip", clone_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error creating ZIP: {str(exc)}") from exc

        zip_file = f"{zip_path}.zip"
        if not os.path.exists(zip_file):
            raise HTTPException(status_code=500, detail="Failed to create ZIP file")
        return zip_file

    def persist_testcase_markdown(self, job_id: str, job: Any, clone_path: str, markdown: str) -> str:
        doc_path = getattr(job, "testcase_doc_path", None) or os.path.join(clone_path, "TESTCASE_AND_CHANGES.md")
        try:
            with open(doc_path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            job.testcase_doc_path = doc_path
        except Exception:
            tmp_path = os.path.join(tempfile.gettempdir(), f"TESTCASE_AND_CHANGES-{job_id}.md")
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            job.testcase_doc_path = tmp_path
            doc_path = tmp_path

        self.job_service.save_job(job)
        return doc_path

    def set_jmeter_base_url(self, job: Any, base_url: Optional[str] = None) -> str:
        effective_base_url = (base_url or getattr(job, "jmeter_base_url", None) or self.default_jmeter_base_url).strip()
        try:
            job.jmeter_base_url = effective_base_url
        except Exception:
            pass
        self.job_service.save_job(job)
        return effective_base_url
