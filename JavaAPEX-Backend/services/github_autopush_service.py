"""
GitHub Auto-Push Service
========================
Creates a new GitHub repository and pushes a local directory to it.
Supports both public GitHub and GitHub Enterprise.

Usage (as a module):
    from services.github_autopush_service import github_autopush
    result = github_autopush.push(
        local_path="C:/path/to/generated/output",
        repo_name="petclinic-microservices",
    )

Environment variables (all optional – falls back to .env):
    GITHUB_TOKEN          – PAT with repo scope
    GITHUB_OWNER          – org or user (default: authenticated user)
    GITHUB_ENTERPRISE_URL – e.g. https://github.ford.com  (omit for github.com)
"""

from __future__ import annotations

import logging
import os
import subprocess
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("github_autopush")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class PushResult:
    repo_url: str = ""
    branch: str = "main"
    commit_sha: str = ""
    files_pushed: int = 0
    success: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class GitHubAutoPushService:
    """Creates a new repo on GitHub and pushes a local directory into it."""

    def __init__(self):
        self.proxy = os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", ""))

    # ---- public API -------------------------------------------------------
    def push(
        self,
        local_path: str,
        repo_name: Optional[str] = None,
        token: Optional[str] = None,
        owner: Optional[str] = None,
        private: bool = False,
        branch: str = "main",
        commit_message: str = "Initial commit – auto-generated microservices",
        description: str = "Auto-generated microservices project by JavaAPEX",
        enterprise_url: Optional[str] = None,
    ) -> PushResult:
        """
        Push *local_path* to a **new** GitHub repository.

        Parameters
        ----------
        local_path : str
            Absolute path to the folder whose contents should be pushed.
        repo_name : str, optional
            Name for the new repo (default: folder name + timestamp).
        token : str, optional
            GitHub PAT (falls back to GITHUB_TOKEN env var).
        owner : str, optional
            GitHub org / user (falls back to GITHUB_OWNER or authenticated user).
        private : bool
            Whether the new repo should be private.
        branch : str
            Branch name (default ``main``).
        commit_message : str
            First commit message.
        description : str
            Repo description on GitHub.
        enterprise_url : str, optional
            GitHub Enterprise base URL (e.g. ``https://github.ford.com``).
        """
        result = PushResult(branch=branch)
        try:
            local = Path(local_path).resolve()
            if not local.is_dir():
                raise FileNotFoundError(f"Directory not found: {local}")

            effective_token = (token or "").strip() or os.getenv("GITHUB_TOKEN", "").strip()
            if not effective_token:
                raise ValueError("No GitHub token provided. Set GITHUB_TOKEN env var or pass token=.")

            effective_owner = (owner or "").strip() or os.getenv("GITHUB_OWNER", "").strip()
            ent_url = (enterprise_url or "").strip() or os.getenv("GITHUB_ENTERPRISE_URL", "").strip()

            # Determine repo name
            if not repo_name:
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                repo_name = f"{local.name}-{ts}"
            repo_name = _sanitize_repo_name(repo_name)

            # 1. Create the repo via GitHub API
            api_base, html_base = _github_urls(ent_url)
            owner_resolved = effective_owner or _whoami(api_base, effective_token, self.proxy)
            repo_full = f"{owner_resolved}/{repo_name}"

            logger.info("Creating GitHub repo %s …", repo_full)
            _create_repo_api(
                api_base=api_base,
                token=effective_token,
                owner=owner_resolved,
                repo_name=repo_name,
                description=description,
                private=private,
                proxy=self.proxy,
            )
            repo_html_url = f"{html_base}/{repo_full}"
            result.repo_url = repo_html_url
            logger.info("Repo created: %s", repo_html_url)

            # 2. git init + add + commit + push
            auth_remote = f"https://{effective_token}@{html_base.split('://',1)[1]}/{repo_full}.git"
            n_files = _git_init_and_push(
                local_path=str(local),
                remote_url=auth_remote,
                branch=branch,
                commit_message=commit_message,
                proxy=self.proxy,
            )
            result.files_pushed = n_files
            result.success = True
            logger.info("Pushed %d files to %s", n_files, repo_html_url)

        except Exception as exc:
            logger.error("Auto-push failed: %s", exc, exc_info=True)
            result.error = str(exc)

        return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _sanitize_repo_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "-", name)
    return name.strip("-").lower() or "generated-project"


def _github_urls(enterprise_url: str):
    """Return (api_base, html_base) for public or enterprise GitHub."""
    if enterprise_url:
        base = enterprise_url.rstrip("/")
        return f"{base}/api/v3", base
    return "https://api.github.com", "https://github.com"


def _whoami(api_base: str, token: str, proxy: str) -> str:
    """Get the authenticated user's login."""
    import httpx

    proxies = {"https://": proxy, "http://": proxy} if proxy else None
    r = httpx.get(
        f"{api_base}/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        proxies=proxies,
        timeout=15,
    )
    r.raise_for_status()
    login = r.json().get("login")
    if not login:
        raise RuntimeError("Could not determine GitHub username from token")
    return login


def _create_repo_api(
    api_base: str,
    token: str,
    owner: str,
    repo_name: str,
    description: str,
    private: bool,
    proxy: str,
):
    """Create a new repository via the GitHub REST API."""
    import httpx

    proxies = {"https://": proxy, "http://": proxy} if proxy else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    # Check if it's a user or org.  Try org first, fall back to user.
    payload = {
        "name": repo_name,
        "description": description,
        "private": private,
        "auto_init": False,
    }

    # Try creating under an org
    r = httpx.post(
        f"{api_base}/orgs/{owner}/repos",
        json=payload,
        headers=headers,
        proxies=proxies,
        timeout=30,
    )
    if r.status_code in (201, 200):
        return r.json()

    # If 404 (org not found) → user repo
    if r.status_code == 404:
        r2 = httpx.post(
            f"{api_base}/user/repos",
            json=payload,
            headers=headers,
            proxies=proxies,
            timeout=30,
        )
        if r2.status_code in (201, 200):
            return r2.json()
        raise RuntimeError(
            f"Failed to create repo (user): {r2.status_code} – {r2.text}"
        )

    # 422 = repo already exists → that's OK, we'll push into it
    if r.status_code == 422 and "already exists" in r.text.lower():
        logger.warning("Repo %s/%s already exists – will push into it", owner, repo_name)
        return {"already_exists": True}

    raise RuntimeError(
        f"Failed to create repo (org): {r.status_code} – {r.text}"
    )


def _git_init_and_push(
    local_path: str,
    remote_url: str,
    branch: str,
    commit_message: str,
    proxy: str,
) -> int:
    """Initialise a git repo in *local_path*, commit everything, push."""
    env = os.environ.copy()
    if proxy:
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy

    def _run(args, **kw):
        kw.setdefault("cwd", local_path)
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        kw.setdefault("encoding", "utf-8")
        kw.setdefault("errors", "ignore")
        kw.setdefault("env", env)
        r = subprocess.run(["git", "-c", "core.longpaths=true"] + args, **kw)
        if r.returncode != 0 and "already exists" not in (r.stderr or ""):
            logger.debug("git %s → rc=%d stderr=%s", args, r.returncode, r.stderr)
        return r

    # Init
    _run(["init", "-b", branch])

    # Config
    _run(["config", "user.email", "javaapex@auto.gen"])
    _run(["config", "user.name", "JavaAPEX Auto-Push"])

    # Add all
    _run(["add", "-A"])

    # Count files
    ls_result = _run(["ls-files"])
    n_files = len([l for l in (ls_result.stdout or "").splitlines() if l.strip()])

    # Commit
    _run(["commit", "-m", commit_message])

    # Remote
    _run(["remote", "remove", "origin"])  # ignore errors
    _run(["remote", "add", "origin", remote_url])

    # Push
    push_result = _run(["push", "-u", "origin", branch, "--force"])
    if push_result.returncode != 0:
        raise RuntimeError(f"git push failed: {push_result.stderr}")

    return n_files


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
github_autopush = GitHubAutoPushService()
