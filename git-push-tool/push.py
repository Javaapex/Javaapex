#!/usr/bin/env python3
"""
JavaAPEX Git Push Tool
======================
Standalone CLI to push any local folder to a new (or existing) GitHub repo.

Usage:
    python push.py                                       # push entire JavaAPEX root
    python push.py C:\some\other\folder                  # push a custom path
    python push.py --name my-repo --owner qlikaccel      # specify repo name & owner
    python push.py --private                             # create private repo
    python push.py --branch develop                      # push to a specific branch

Config is read from  ../JavaAPEX-Backend/.env  automatically
(GITHUB_TOKEN, HTTP_PROXY, HTTPS_PROXY).
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env from the backend folder (sibling directory)
# ---------------------------------------------------------------------------
TOOL_DIR = Path(__file__).resolve().parent
ROOT_DIR = TOOL_DIR.parent                          # c:\jabacx\JavaAPEX
BACKEND_ENV = ROOT_DIR / "JavaAPEX-Backend" / ".env"

def _load_env(env_path: Path):
    """Minimal .env loader (no external deps required)."""
    if not env_path.is_file():
        return
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if not os.environ.get(key):        # don't overwrite explicit env
                os.environ[key] = val

_load_env(BACKEND_ENV)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
PROXY        = os.environ.get("HTTPS_PROXY", os.environ.get("HTTP_PROXY", ""))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("git-push")


# ---------------------------------------------------------------------------
# GitHub API helpers (pure stdlib + subprocess – zero pip deps)
# ---------------------------------------------------------------------------

def _api_request(method: str, url: str, token: str, body: dict = None):
    """Make a GitHub REST API call using urllib (no httpx/requests needed)."""
    import urllib.request
    import urllib.error

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "JavaAPEX-Git-Push-Tool",
    }
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    # Handle proxy
    if PROXY:
        handler = urllib.request.ProxyHandler({
            "http": PROXY,
            "https": PROXY,
        })
        opener = urllib.request.build_opener(handler)
    else:
        opener = urllib.request.build_opener()

    try:
        resp = opener.open(req, timeout=30)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        return e.code, body_text


def _whoami(token: str) -> str:
    code, data = _api_request("GET", "https://api.github.com/user", token)
    if code != 200:
        raise RuntimeError(f"Cannot authenticate with GitHub (HTTP {code})")
    return data["login"]


def _create_repo(token: str, owner: str, name: str, desc: str, private: bool) -> dict:
    """Create repo under org first, fall back to user."""
    payload = {"name": name, "description": desc, "private": private, "auto_init": False}

    # Try org
    code, data = _api_request("POST", f"https://api.github.com/orgs/{owner}/repos", token, payload)
    if code in (200, 201):
        return data

    # 404 = not an org → create under user
    if code == 404:
        code2, data2 = _api_request("POST", "https://api.github.com/user/repos", token, payload)
        if code2 in (200, 201):
            return data2
        # 422 = already exists
        if code2 == 422 and "already exists" in str(data2).lower():
            log.warning("Repo %s/%s already exists – will push into it", owner, name)
            return {"already_exists": True}
        raise RuntimeError(f"Failed to create repo (user): {code2} – {data2}")

    if code == 422 and "already exists" in str(data).lower():
        log.warning("Repo %s/%s already exists – will push into it", owner, name)
        return {"already_exists": True}

    raise RuntimeError(f"Failed to create repo (org): {code} – {data}")


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if PROXY:
        env["http_proxy"] = PROXY
        env["https_proxy"] = PROXY
    cmd = ["git", "-c", "core.longpaths=true"] + args
    return subprocess.run(
        cmd, cwd=cwd,
        capture_output=True, text=True,
        encoding="utf-8", errors="ignore",
        env=env,
    )


def _push_directory(
    local_path: str,
    remote_url: str,
    branch: str,
    commit_msg: str,
) -> int:
    """Init, commit, push.  Returns number of files."""
    cwd = local_path

    # If already a git repo, just add + commit + push
    is_existing = (Path(cwd) / ".git").is_dir()

    if not is_existing:
        _git(["init", "-b", branch], cwd)

    _git(["config", "user.email", "javaapex@auto.gen"], cwd)
    _git(["config", "user.name", "JavaAPEX Auto-Push"], cwd)

    _git(["add", "-A"], cwd)

    ls = _git(["ls-files"], cwd)
    n = len([l for l in (ls.stdout or "").splitlines() if l.strip()])

    _git(["commit", "-m", commit_msg, "--allow-empty"], cwd)

    _git(["remote", "remove", "origin"], cwd)  # ignore error
    _git(["remote", "add", "origin", remote_url], cwd)

    r = _git(["push", "-u", "origin", branch, "--force"], cwd)
    if r.returncode != 0:
        raise RuntimeError(f"git push failed:\n{r.stderr}")

    return n


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Push a local folder to a new GitHub repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "local_path", nargs="?", default=str(ROOT_DIR),
        help=f"Path to push (default: {ROOT_DIR})",
    )
    parser.add_argument("--name",    dest="repo_name", default=None, help="Repo name (default: folder-YYYYMMDD)")
    parser.add_argument("--owner",   default=None,     help="GitHub org or user")
    parser.add_argument("--token",   default=None,     help="GitHub PAT (default: from .env)")
    parser.add_argument("--private", action="store_true", help="Create private repo")
    parser.add_argument("--branch",  default="main",   help="Branch (default: main)")
    parser.add_argument("--message", default="Auto-push by JavaAPEX git-push-tool", help="Commit message")

    args = parser.parse_args()

    token = (args.token or "").strip() or GITHUB_TOKEN
    if not token:
        print("❌  No GITHUB_TOKEN found. Set it in .env or pass --token.")
        sys.exit(1)

    local = Path(args.local_path).resolve()
    if not local.is_dir():
        print(f"❌  Directory not found: {local}")
        sys.exit(1)

    # Resolve owner
    owner = (args.owner or "").strip()
    if not owner:
        log.info("Detecting GitHub username …")
        owner = _whoami(token)
    log.info("GitHub owner: %s", owner)

    # Resolve repo name
    repo_name = args.repo_name or f"{local.name}-{datetime.now():%Y%m%d-%H%M%S}"
    repo_name = re.sub(r"[^a-zA-Z0-9._-]", "-", repo_name).strip("-")

    print(f"\n📦  Pushing:  {local}")
    print(f"📍  Target:   github.com/{owner}/{repo_name}")
    print(f"🌿  Branch:   {args.branch}")
    print(f"🔒  Private:  {args.private}\n")

    # 1. Create repo
    log.info("Creating repo %s/%s …", owner, repo_name)
    _create_repo(token, owner, repo_name, "Auto-pushed by JavaAPEX", args.private)

    # 2. Push
    remote = f"https://{token}@github.com/{owner}/{repo_name}.git"
    log.info("Pushing files …")
    n = _push_directory(str(local), remote, args.branch, args.message)

    print(f"\n✅  Done!  {n} files pushed.")
    print(f"🔗  https://github.com/{owner}/{repo_name}")


if __name__ == "__main__":
    main()
