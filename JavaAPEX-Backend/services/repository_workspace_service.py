"""
Managed repository workspaces for clone-first analysis.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class RepositoryWorkspaceError(Exception):
    """Base error for managed repository workspaces."""


class RepositoryNotFoundError(RepositoryWorkspaceError):
    """Raised when the repository cannot be found."""


class RepositoryAuthenticationError(RepositoryWorkspaceError):
    """Raised when the repository requires authentication or the token is invalid."""


class RepositoryCloneTimeoutError(RepositoryWorkspaceError):
    """Raised when git clone exceeds the configured timeout."""


class RepositoryPathError(RepositoryWorkspaceError):
    """Raised when a requested path is invalid for the workspace."""


@dataclass(frozen=True)
class RepositoryWorkspace:
    repo_url: str
    normalized_repo_url: str
    owner: str
    repo: str
    workspace_path: str
    default_branch: str
    cache_key: str
    auth_scope_key: str


class RepositoryWorkspaceService:
    def __init__(self) -> None:
        work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
        self.workspace_root = os.path.join(work_dir, "repo_workspaces")
        self.workspace_ttl_seconds = int(os.getenv("REPO_WORKSPACE_TTL_SEC", "21600"))
        self.clone_timeout_seconds = int(os.getenv("REPO_CLONE_TIMEOUT_SEC", "900"))
        self.workspace_replace_retries = int(os.getenv("REPO_WORKSPACE_REPLACE_RETRIES", "8"))
        self.workspace_replace_retry_delay_seconds = float(os.getenv("REPO_WORKSPACE_RETRY_DELAY_SEC", "0.35"))
        self.workspace_artifact_ttl_seconds = int(
            os.getenv("REPO_WORKSPACE_ARTIFACT_TTL_SEC", str(max(self.workspace_ttl_seconds, 21600)))
        )
        self.workspace_cleanup_interval_seconds = float(os.getenv("REPO_WORKSPACE_CLEANUP_INTERVAL_SEC", "300"))
        self.workspace_artifact_cleanup_retries = int(os.getenv("REPO_WORKSPACE_ARTIFACT_RETRIES", "2"))
        self._locks: Dict[str, asyncio.Lock] = {}
        self._cleanup_state_lock = threading.Lock()
        self._cleanup_in_progress = False
        self._last_cleanup_started_at = 0.0
        os.makedirs(self.workspace_root, exist_ok=True)

    async def prepare_workspace(
        self,
        repo_reference: str,
        token: str = "",
        force_refresh: bool = False,
    ) -> RepositoryWorkspace:
        normalized_repo_url, owner, repo = self.parse_repo_reference(repo_reference)
        auth_scope_key = self._build_auth_scope_key(token)
        cache_key = self._build_workspace_cache_key(normalized_repo_url, auth_scope_key)
        workspace_path = os.path.join(self.workspace_root, cache_key)
        lock = self._locks.setdefault(cache_key, asyncio.Lock())

        async with lock:
            self._schedule_cleanup_if_due()
            if force_refresh or not self._is_ready_workspace(workspace_path):
                await asyncio.to_thread(
                    self._recreate_workspace_sync,
                    normalized_repo_url,
                    workspace_path,
                    owner,
                    repo,
                    token,
                )

            metadata = await asyncio.to_thread(self._load_metadata_sync, workspace_path)
            await asyncio.to_thread(self._touch_workspace_sync, workspace_path, metadata)

        return RepositoryWorkspace(
            repo_url=repo_reference,
            normalized_repo_url=normalized_repo_url,
            owner=owner,
            repo=repo,
            workspace_path=workspace_path,
            default_branch=metadata.get("default_branch", "main"),
            cache_key=cache_key,
            auth_scope_key=auth_scope_key,
        )

    def parse_repo_reference(self, repo_reference: str) -> tuple[str, str, str]:
        cleaned = (repo_reference or "").strip()
        if not cleaned:
            raise RepositoryWorkspaceError("Repository URL is required.")

        owner_repo_match = re.fullmatch(r"(?P<owner>[^/\s:]+)/(?P<repo>[^/\s]+)", cleaned)
        if owner_repo_match:
            owner = owner_repo_match.group("owner")
            repo = owner_repo_match.group("repo").removesuffix(".git")
            return f"https://github.com/{owner}/{repo}.git", owner, repo

        ssh_match = re.fullmatch(r"git@(?P<host>[^:]+):(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?", cleaned)
        if ssh_match:
            host = ssh_match.group("host")
            owner = ssh_match.group("owner")
            repo = ssh_match.group("repo")
            return f"https://{host}/{owner}/{repo}.git", owner, repo

        https_match = re.fullmatch(
            r"https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?",
            cleaned,
        )
        if https_match:
            host = https_match.group("host")
            owner = https_match.group("owner")
            repo = https_match.group("repo")
            return f"https://{host}/{owner}/{repo}.git", owner, repo

        raise RepositoryWorkspaceError(
            "Invalid GitHub repository reference. Use owner/repo, https://host/owner/repo, or git@host:owner/repo.git"
        )

    def resolve_workspace_path(self, workspace: RepositoryWorkspace, relative_path: str = "") -> str:
        base_path = Path(workspace.workspace_path).resolve()
        candidate = (base_path / relative_path).resolve()
        base_canonical = self._canonicalize_path(base_path)
        candidate_canonical = self._canonicalize_path(candidate)
        if not self._is_within_root(base_canonical, candidate_canonical):
            raise RepositoryPathError("Invalid repository path.")
        return candidate_canonical

    def _is_ready_workspace(self, workspace_path: str) -> bool:
        return os.path.isdir(workspace_path) and os.path.isdir(os.path.join(workspace_path, ".git"))

    def _build_auth_scope_key(self, token: str) -> str:
        normalized_token = (token or "").strip()
        if not normalized_token:
            return "public"
        return hashlib.sha256(normalized_token.encode("utf-8")).hexdigest()[:12]

    def _build_workspace_cache_key(self, normalized_repo_url: str, auth_scope_key: str) -> str:
        raw_key = f"{normalized_repo_url.lower()}::{auth_scope_key}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]

    def _canonicalize_path(self, path: Path | str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))

    def _is_within_root(self, root_canonical: str, candidate_canonical: str) -> bool:
        try:
            return os.path.commonpath([root_canonical, candidate_canonical]) == root_canonical
        except ValueError:
            return False

    def _recreate_workspace_sync(
        self,
        normalized_repo_url: str,
        workspace_path: str,
        owner: str,
        repo: str,
        token: str,
    ) -> None:
        temp_path = self._allocate_staging_workspace_path(workspace_path)
        os.makedirs(os.path.dirname(workspace_path), exist_ok=True)

        clone_args = [
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--no-tags",
            "-c",
            "core.longpaths=true",
            "-c",
            "core.protectNTFS=false",
            normalized_repo_url,
            temp_path,
        ]

        logger.info("Cloning repository %s into managed workspace %s", normalized_repo_url, workspace_path)
        self._run_git(clone_args, cwd=self.workspace_root, token=token, timeout_seconds=self.clone_timeout_seconds)

        default_branch = self._resolve_default_branch_sync(temp_path)
        metadata = {
            "normalized_repo_url": normalized_repo_url,
            "owner": owner,
            "repo": repo,
            "default_branch": default_branch,
            "last_synced_at": time.time(),
        }
        self._write_metadata_sync(temp_path, metadata)
        self._promote_workspace_sync(temp_path, workspace_path)

    def _resolve_default_branch_sync(self, workspace_path: str) -> str:
        result = self._run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace_path,
            timeout_seconds=30,
        )
        branch = result.stdout.strip()
        return branch or "main"

    def _metadata_path(self, workspace_path: str) -> str:
        return os.path.join(workspace_path, ".repo_workspace.json")

    def _load_metadata_sync(self, workspace_path: str) -> Dict[str, object]:
        metadata_path = self._metadata_path(workspace_path)
        if not os.path.exists(metadata_path):
            return {}
        with open(metadata_path, "r", encoding="utf-8") as metadata_file:
            return json.load(metadata_file)

    def _write_metadata_sync(self, workspace_path: str, metadata: Dict[str, object]) -> None:
        metadata_path = self._metadata_path(workspace_path)
        with open(metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, indent=2)

    def _touch_workspace_sync(self, workspace_path: str, metadata: Dict[str, object]) -> None:
        if not metadata:
            return
        metadata["last_accessed_at"] = time.time()
        self._write_metadata_sync(workspace_path, metadata)

    def _cleanup_expired_workspaces_sync(self) -> None:
        now = time.time()
        for entry in os.scandir(self.workspace_root):
            if not entry.is_dir():
                continue

            metadata_path = self._metadata_path(entry.path)
            if not os.path.exists(metadata_path):
                continue

            try:
                with open(metadata_path, "r", encoding="utf-8") as metadata_file:
                    metadata = json.load(metadata_file)
            except Exception:
                logger.warning("Failed to read workspace metadata for %s", entry.path)
                continue

            last_accessed_at = float(metadata.get("last_accessed_at", metadata.get("last_synced_at", 0)))
            if now - last_accessed_at <= self.workspace_ttl_seconds:
                continue

            logger.info("Removing expired managed workspace %s", entry.path)
            self._remove_path_if_exists(entry.path)

        self._cleanup_stale_workspace_artifacts_sync(now)

    def _schedule_cleanup_if_due(self) -> None:
        now = time.time()
        with self._cleanup_state_lock:
            if self._cleanup_in_progress:
                return
            if self.workspace_cleanup_interval_seconds > 0 and (
                now - self._last_cleanup_started_at < self.workspace_cleanup_interval_seconds
            ):
                return
            self._cleanup_in_progress = True
            self._last_cleanup_started_at = now

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._run_cleanup_background())
        except RuntimeError:
            try:
                self._cleanup_expired_workspaces_sync()
            finally:
                with self._cleanup_state_lock:
                    self._cleanup_in_progress = False

    async def _run_cleanup_background(self) -> None:
        try:
            await asyncio.to_thread(self._cleanup_expired_workspaces_sync)
        except Exception:
            logger.exception("Managed workspace cleanup failed")
        finally:
            with self._cleanup_state_lock:
                self._cleanup_in_progress = False

    def _promote_workspace_sync(self, temp_path: str, workspace_path: str) -> None:
        last_error: Exception | None = None
        backup_path = self._allocate_backup_workspace_path(workspace_path)
        for attempt in range(1, self.workspace_replace_retries + 1):
            try:
                if os.path.exists(workspace_path):
                    try:
                        os.replace(workspace_path, backup_path)
                    except OSError as exc:
                        last_error = exc
                        if os.path.isdir(workspace_path) and os.path.isdir(os.path.join(workspace_path, ".git")):
                            logger.warning(
                                "Using existing repository workspace because refreshed activation is blocked for %s: %s",
                                workspace_path,
                                exc,
                            )
                            self._retire_workspace_artifact(temp_path, "stale-stage")
                            return
                        raise

                os.replace(temp_path, workspace_path)
                self._remove_path_if_exists(backup_path, must_succeed=False)
                return
            except FileNotFoundError:
                if os.path.isdir(workspace_path) and os.path.isdir(os.path.join(workspace_path, ".git")):
                    return
                last_error = RepositoryWorkspaceError(
                    "Temporary workspace disappeared before activation."
                )
            except PermissionError as exc:
                last_error = exc
            except OSError as exc:
                last_error = exc

            logger.warning(
                "Workspace promotion attempt %s/%s failed for %s: %s",
                attempt,
                self.workspace_replace_retries,
                workspace_path,
                last_error,
            )
            time.sleep(self.workspace_replace_retry_delay_seconds * attempt)

        self._retire_workspace_artifact(temp_path, "stale-stage")
        if os.path.isdir(workspace_path) and os.path.isdir(os.path.join(workspace_path, ".git")):
            logger.warning(
                "Returning existing repository workspace after refresh activation failed for %s: %s",
                workspace_path,
                last_error,
            )
            return
        raise RepositoryWorkspaceError(
            f"Failed to activate refreshed repository workspace at {workspace_path}: {last_error}"
        )

    def _run_git(
        self,
        args: list[str],
        cwd: str,
        token: str = "",
        timeout_seconds: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        command = ["git"]
        if os.name == "nt":
            command.extend(["-c", "core.longpaths=true"])
        if token.strip():
            command.extend(
                [
                    "-c",
                    f"http.extraHeader=AUTHORIZATION: Basic {self._build_basic_auth_header(token.strip())}",
                ]
            )
        command.extend(args)

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"

        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RepositoryCloneTimeoutError(
                f"Repository operation timed out after {timeout_seconds} seconds."
            ) from exc

        if result.returncode == 0:
            return result

        stderr = (result.stderr or "").strip()
        stderr_lower = stderr.lower()
        if (
            "authentication failed" in stderr_lower
            or "could not read username" in stderr_lower
            or "bad credentials" in stderr_lower
            or "http basic: access denied" in stderr_lower
            or "invalid username or password" in stderr_lower
        ):
            raise RepositoryAuthenticationError("Invalid PAT token.")
        if "access denied" in stderr_lower or "permission denied" in stderr_lower:
            raise RepositoryAuthenticationError("The GitHub token is valid but does not have access to this repository. Ensure it has repo scope and repository access.")
        if "repository not found" in stderr_lower or "not found" in stderr_lower:
            if token.strip():
                raise RepositoryAuthenticationError(
                    "Repository not found or not accessible with the provided GitHub token. "
                    "If this is a private repository, verify that the token is valid and has repo scope/access."
                )
            raise RepositoryNotFoundError(
                "Repository not found or requires authentication. If this is a private repository, provide a GitHub Personal Access Token with repo scope."
            )
        raise RepositoryWorkspaceError(stderr or "Git operation failed.")

    def _build_basic_auth_header(self, token: str) -> str:
        raw = f"x-access-token:{token}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _remove_path_if_exists(self, path: str, must_succeed: bool = False) -> None:
        if not os.path.exists(path):
            return

        retries = self.workspace_replace_retries
        if not must_succeed and self._is_workspace_artifact_path(path):
            retries = min(retries, max(1, self.workspace_artifact_cleanup_retries))

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, onerror=self._handle_remove_error)
                else:
                    os.chmod(path, 0o666)
                    os.remove(path)

                if not os.path.exists(path):
                    return
            except FileNotFoundError:
                return
            except OSError as exc:
                last_error = exc

            logger.warning(
                "Workspace cleanup attempt %s/%s failed for %s: %s",
                attempt,
                retries,
                path,
                last_error,
            )
            time.sleep(self.workspace_replace_retry_delay_seconds * attempt)

        if must_succeed and os.path.exists(path):
            raise RepositoryWorkspaceError(f"Failed to remove workspace path {path}: {last_error}")

    def _handle_remove_error(self, func, path, exc_info) -> None:
        try:
            os.chmod(path, 0o666)
            func(path)
        except Exception:
            raise exc_info[1]

    def _allocate_staging_workspace_path(self, workspace_path: str) -> str:
        cache_key = os.path.basename(workspace_path)
        return os.path.join(self.workspace_root, f"{cache_key}.stage-{uuid.uuid4().hex[:8]}")

    def _allocate_backup_workspace_path(self, workspace_path: str) -> str:
        cache_key = os.path.basename(workspace_path)
        return os.path.join(self.workspace_root, f"{cache_key}.old-{uuid.uuid4().hex[:8]}")

    def _retire_workspace_artifact(self, path: str, artifact_kind: str) -> None:
        if not os.path.exists(path):
            return

        retired_path = os.path.join(
            self.workspace_root,
            f"{os.path.basename(path)}.{artifact_kind}-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        )
        try:
            os.replace(path, retired_path)
            path = retired_path
        except OSError as exc:
            logger.warning("Failed to retire workspace artifact %s: %s", path, exc)

        self._remove_path_if_exists(path, must_succeed=False)

    def _cleanup_stale_workspace_artifacts_sync(self, now: float) -> None:
        artifact_markers = (".stage-", ".old-", ".stale-stage-", ".stale-delete-")
        for entry in os.scandir(self.workspace_root):
            if not entry.is_dir():
                continue
            if not any(marker in entry.name for marker in artifact_markers):
                continue
            try:
                age_seconds = now - entry.stat().st_mtime
            except OSError:
                age_seconds = self.workspace_artifact_ttl_seconds + 1
            if age_seconds <= self.workspace_artifact_ttl_seconds:
                continue
            logger.info("Removing stale workspace artifact %s", entry.path)
            self._remove_path_if_exists(entry.path, must_succeed=False)

    def _is_workspace_artifact_path(self, path: str) -> bool:
        artifact_markers = (".stage-", ".old-", ".stale-stage-", ".stale-delete-")
        name = os.path.basename(path)
        return any(marker in name for marker in artifact_markers)
