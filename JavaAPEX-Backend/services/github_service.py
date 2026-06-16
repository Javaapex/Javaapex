def get_github_client(token: str, repo_url: str = None):
    """Return a Github client for public or enterprise GitHub."""
    from github import Github
    import re
    if repo_url and "github.com" in repo_url and not "github." in repo_url.replace("github.com", ""):
        # Public GitHub
        if token and len(token.strip()) > 0:
            return Github(token)
        else:
            return Github()  # No token for public access
    elif repo_url:
        # Enterprise (extract base domain)
        m = re.match(r"https?://([^/]+)/", repo_url)
        if m:
            base_url = f"https://{m.group(1)}/api/v3"
            if token and len(token.strip()) > 0:
                return Github(base_url=base_url, login_or_token=token)
            else:
                return Github(base_url=base_url)  # No token for enterprise
        else:
            raise Exception("Invalid GitHub Enterprise URL")
    else:
        if token and len(token.strip()) > 0:
            return Github(token)
        else:
            return Github()  # No token
"""
Git Service - Handles GitHub and GitLab API interactions
"""
import os
import tempfile
import shutil
import time
import re
import base64
import subprocess
import logging
from typing import List, Dict, Any, Optional
from github import Github, GithubException, RateLimitExceededException
import git
import httpx

from utils.config import DEFAULT_WORK_DIR
from utils.logging_utils import redact_url_credentials

logger = logging.getLogger(__name__)

# Simple in-memory cache for rate limit handling
_cache = {}
_cache_ttl = 300  # 5 minutes cache TTL


def _parse_positive_int_env(name: str, default: int) -> int:
    raw_value = (os.environ.get(name) or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
        return parsed if parsed > 0 else default
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %s", name, raw_value, default)
        return default


_cache_max_entries = _parse_positive_int_env("GITHUB_SERVICE_CACHE_MAX_ENTRIES", 1024)


def _prune_cache() -> None:
    """Keep the in-memory cache bounded and clear expired entries proactively."""
    now = time.time()
    expired_keys = [key for key, (_, timestamp) in list(_cache.items()) if now - timestamp >= _cache_ttl]
    for key in expired_keys:
        _cache.pop(key, None)

    overflow = len(_cache) - _cache_max_entries
    if overflow > 0:
        oldest_keys = sorted(_cache.items(), key=lambda item: item[1][1])[:overflow]
        for key, _ in oldest_keys:
            _cache.pop(key, None)


def get_cached(key: str) -> Optional[Any]:
    """Get cached value if not expired"""
    _prune_cache()
    if key in _cache:
        value, timestamp = _cache[key]
        if time.time() - timestamp < _cache_ttl:
            return value
        del _cache[key]
    return None


def set_cached(key: str, value: Any):
    """Set cached value with current timestamp"""
    _cache[key] = (value, time.time())
    _prune_cache()


def _summarize_push_result(push_result: Any) -> str:
    push_infos = list(push_result or [])
    if not push_infos:
        return "no push result returned"
    return "; ".join((getattr(info, "summary", "") or str(info)).strip() for info in push_infos)


def _ensure_push_succeeded(push_result: Any, provider: str, branch_name: str) -> None:
    push_infos = list(push_result or [])
    if not push_infos:
        raise Exception(f"{provider} push returned no result for branch '{branch_name}'")

    push_info_cls = git.remote.PushInfo
    error_mask = (
        getattr(push_info_cls, "ERROR", 0)
        | getattr(push_info_cls, "REJECTED", 0)
        | getattr(push_info_cls, "REMOTE_REJECTED", 0)
        | getattr(push_info_cls, "REMOTE_FAILURE", 0)
    )

    failures: list[str] = []
    for info in push_infos:
        summary = (getattr(info, "summary", "") or str(info)).strip()
        flags = getattr(info, "flags", 0)
        lowered = summary.lower()
        if flags & error_mask or "[rejected]" in lowered or "error" in lowered or "failed" in lowered:
            failures.append(summary or f"push failed with flags={flags}")

    if failures:
        raise Exception(f"{provider} push failed for branch '{branch_name}': {'; '.join(failures)}")


class GitHubService:
    def __init__(self):
        self.work_dir = DEFAULT_WORK_DIR
        os.makedirs(self.work_dir, exist_ok=True)

    def validate_token(self, token: str, repo_url: str = None):
        """Validate that a GitHub token is well-formed and accepted by GitHub."""
        normalized_token = (token or "").strip()
        if not normalized_token:
            raise Exception("Invalid PAT token.")
        if len(normalized_token) < 10:
            raise Exception("Invalid PAT token.")

        try:
            g = get_github_client(normalized_token, repo_url)
            user = g.get_user()
            _ = user.login
            return g
        except GithubException as e:
            status_code = getattr(e, 'status', None)
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            lowered = error_msg.lower()
            if status_code in {401, 403} or 'bad credentials' in lowered:
                raise Exception("Invalid PAT token.")
            raise Exception(f"Failed to validate GitHub token: {error_msg}")

    def validate_repository_access(self, token: str, owner: str, repo: str, repo_url: str = None):
        """Validate that a token can access the requested repository."""
        normalized_token = (token or "").strip()
        if not normalized_token:
            return

        g = self.validate_token(normalized_token, repo_url)
        try:
            repository = g.get_repo(f"{owner}/{repo}")
            _ = repository.full_name
        except GithubException as e:
            status_code = getattr(e, 'status', None)
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            lowered = error_msg.lower()
            if status_code == 401 or 'bad credentials' in lowered:
                raise Exception("Invalid PAT token.")
            if status_code in {403, 404}:
                raise Exception(
                    "The GitHub token is valid but does not have access to this repository. "
                    "For private repositories, ensure the token has repo scope and repository access."
                )
            raise Exception(f"Failed to verify repository access: {error_msg}")
    
    async def list_repositories(self, token: str, repo_url: str = None) -> List[Dict[str, Any]]:
        """List all repositories accessible with the token"""
        try:
            g = self.validate_token(token, repo_url)
            user = g.get_user()
            
            repos = []
            
            # Get user's own repos
            for repo in user.get_repos():
                repos.append({
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "url": repo.html_url,
                    "default_branch": repo.default_branch,
                    "language": repo.language,
                    "description": repo.description or ""
                })
            
            return repos
        except GithubException as e:
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            raise Exception(f"GitHub API error: {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to connect to GitHub: {str(e)}")
    
    async def analyze_repository(
        self,
        token: str,
        owner: str,
        repo: str,
        repo_url: str = None,
        force_refresh: bool = False,
        include_deep_analysis: bool = False
    ) -> Dict[str, Any]:
        """Analyze a repository via the clone-first analysis flow."""
        from services.github_clone_analysis_service import github_clone_analysis_service

        repo_reference = repo_url or f"{owner}/{repo}"
        _, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=repo_reference,
            token=token,
            force_refresh=force_refresh,
        )

        if not (token or "").strip():
            cache_key = f"analysis:v2:{owner}/{repo}:deep={include_deep_analysis}"
            set_cached(cache_key, analysis)
        return analysis
    
    async def parse_repo_url(self, repo_url: str) -> tuple:
        """Parse GitHub URL to extract owner and repo name"""
        import re
        # Strip URL fragment (#...) and query string (?...) before parsing
        cleaned = re.split(r'[#?]', repo_url, maxsplit=1)[0].rstrip('/')
        # Accept github.com, github.<enterprise>.com, and owner/repo
        patterns = [
            r'github(\.[^/]+)?\.com[:/]+([^/]+)/([^/\s]+)',  # https://github.com/owner/repo or github.enterprise.com/owner/repo
            r'^([^/]+)/([^/]+)$',  # owner/repo format
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned)
            if match:
                # For enterprise, owner/repo is always last two groups
                if 'github' in pattern:
                    return match.group(2), match.group(3).replace('.git', '')
                else:
                    return match.group(1), match.group(2).replace('.git', '')
        raise Exception("Invalid GitHub repository URL. Use format: owner/repo, https://github.com/owner/repo, or https://github.<enterprise>.com/owner/repo")
    
    async def get_repo_info(self, token: str, owner: str, repo: str, repo_url: str = None) -> Dict[str, Any]:
        """Get repository information (works with or without token for public repos)"""
        try:
            if token and token.strip():
                self.validate_token(token.strip(), repo_url)
                g = get_github_client(token.strip(), repo_url)
            else:
                g = get_github_client(None, repo_url)
            
            repository = g.get_repo(f"{owner}/{repo}")
            
            return {
                "name": repository.name,
                "full_name": repository.full_name,
                "url": repository.html_url,
                "default_branch": repository.default_branch,
                "language": repository.language,
                "description": repository.description or "",
                "is_private": repository.private,
                "owner": repository.owner.login,
            }
        except GithubException as e:
            # Check the HTTP status code for better error messages
            status_code = getattr(e, 'status', None)
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            
            if status_code == 404:
                if token and token.strip():
                    raise Exception(
                        "Repository not found or not accessible with the provided GitHub token. "
                        "If this is a private repository, verify that the token is valid and has repo scope/access."
                    )
                raise Exception(f"Repository not found: {owner}/{repo}")
            elif status_code == 403:
                if token and token.strip():
                    raise Exception(
                        "The GitHub token is valid but does not have access to this repository. "
                        "For private repositories, ensure the token has repo scope and repository access."
                    )
                raise Exception("Access denied. The repository may be private or you may not have permission to access it.")
            elif status_code == 401:
                raise Exception("Invalid PAT token.")
            elif 'rate limit' in error_msg.lower():
                raise Exception("GitHub API rate limit exceeded. Please wait a few minutes or provide a different GitHub token.")
            else:
                raise Exception(f"GitHub API error ({status_code}): {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to get repository info: {str(e)}")
    
    async def list_repo_files(self, token: str, owner: str, repo: str, path: str = "", repo_url: str = None) -> List[Dict[str, Any]]:
        """List all files and directories in a repository"""
        cache_key = f"files:{owner}/{repo}:{path}"
        
        # Check cache first
        cached = get_cached(cache_key)
        if cached:
            logger.debug("GitHub cache hit owner=%s repo=%s path=%s", owner, repo, path)
            return cached
        
        try:
            if token and len(token.strip()) > 0:
                g = get_github_client(token.strip(), repo_url)
            else:
                g = get_github_client(None, repo_url)
            
            # Check rate limit
            rate_limit = g.get_rate_limit()
            if rate_limit.core.remaining < 5:
                reset_time = rate_limit.core.reset.timestamp() - time.time()
                raise Exception(f"GitHub API rate limit nearly exhausted ({rate_limit.core.remaining} remaining). Resets in {reset_time/60:.1f} minutes.")
            
            repository = g.get_repo(f"{owner}/{repo}")
            contents = repository.get_contents(path)
            
            files = []
            for item in contents:
                files.append({
                    "name": item.name,
                    "path": item.path,
                    "type": "file" if not item.type == "dir" else "dir",
                    "size": item.size if hasattr(item, 'size') else 0,
                    "url": item.html_url,
                })
            
            # Cache the result
            set_cached(cache_key, files)
            return files
        except RateLimitExceededException:
            raise Exception("GitHub API rate limit exceeded. Please wait a few minutes or provide a different GitHub token.")
        except GithubException as e:
            # Check the HTTP status code for better error messages
            status_code = getattr(e, 'status', None)
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            
            if status_code == 404:
                raise Exception(f"Repository not found. Please check that the repository URL is correct and the repository exists: {repo_url}")
            elif status_code == 403:
                raise Exception("Access denied. The repository may be private or you may not have permission to access it.")
            elif status_code == 401:
                raise Exception("Authentication failed. Please check your GitHub token.")
            elif 'rate limit' in error_msg.lower():
                raise Exception("GitHub API rate limit exceeded. Please wait a few minutes or provide a different GitHub token.")
            else:
                raise Exception(f"GitHub API error ({status_code}): {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to list files: {str(e)}")
    
    async def get_file_content(self, token: str, owner: str, repo: str, path: str) -> str:
        """Get the content of a file from the repository"""
        try:
            if token:
                g = Github(token)
            else:
                g = Github()
            
            repository = g.get_repo(f"{owner}/{repo}")
            file_content = repository.get_contents(path)
            
            if hasattr(file_content, 'decoded_content'):
                return file_content.decoded_content.decode('utf-8')
            return ""
        except GithubException as e:
            # Check the HTTP status code for better error messages
            status_code = getattr(e, 'status', None)
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            
            if status_code == 404:
                raise Exception(f"File or repository not found: {path}")
            elif status_code == 403:
                raise Exception("Access denied. The repository may be private or you may not have permission to access it.")
            elif status_code == 401:
                raise Exception("Authentication failed. Please check your GitHub token.")
            elif 'rate limit' in error_msg.lower():
                raise Exception("GitHub API rate limit exceeded. Please wait a few minutes or provide a different GitHub token.")
            else:
                raise Exception(f"GitHub API error ({status_code}): {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to get file content: {str(e)}")
    
    async def clone_repository(self, token: str, repo_url: str) -> str:
        """Clone a repository to local filesystem"""
        normalized_token = (token or "").strip()
        if normalized_token:
            owner, repo = await self.parse_repo_url(repo_url)
            self.validate_repository_access(normalized_token, owner, repo, repo_url)

        # Create unique directory for this clone
        import uuid
        clone_dir = os.path.join(self.work_dir, str(uuid.uuid4()))
        os.makedirs(clone_dir, exist_ok=True)

        try:
            # Clone with config to handle Windows Zone.Identifier files
            result = self._run_git_command(
                [
                    'clone',
                    '-c', 'core.longpaths=true',  # Allow long paths on Windows
                    '-c', 'core.protectNTFS=false',  # Allow files with colons in names
                    repo_url, clone_dir
                ],
                cwd=os.path.dirname(clone_dir),
                token=normalized_token,
            )

            if result.returncode == 0:
                return clone_dir
            else:
                # If clone fails due to Zone.Identifier files, try recovery
                error_msg = result.stderr
                if "Zone.Identifier" in error_msg and "invalid path" in error_msg:
                    # Try clone with --no-checkout first
                    result2 = self._run_git_command(
                        ['clone', '-c', 'core.longpaths=true', '--no-checkout', repo_url, clone_dir],
                        cwd=os.path.dirname(clone_dir),
                        token=normalized_token,
                    )

                    if result2.returncode == 0:
                        # Configure the repo and try checkout
                        result3 = subprocess.run([
                            'git', 'config', 'core.protectNTFS', 'false'
                        ], capture_output=True, text=True, encoding="utf-8", errors="ignore", cwd=clone_dir)
                        result3b = subprocess.run([
                            'git', 'config', 'core.longpaths', 'true'
                        ], capture_output=True, text=True, encoding="utf-8", errors="ignore", cwd=clone_dir)

                        # Try checkout
                        result4 = subprocess.run([
                            'git', 'checkout'
                        ], capture_output=True, text=True, encoding="utf-8", errors="ignore", cwd=clone_dir)

                        # Even if checkout fails, return the directory
                        # The migration service can work with partial checkouts
                        return clone_dir
                    else:
                        raise Exception(f"Failed to clone repository (recovery): {result2.stderr}")
                else:
                    raise Exception(f"Failed to clone repository: {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to clone repository: {str(e)}")

    def _run_git_command(self, args: List[str], cwd: str, token: str = "") -> subprocess.CompletedProcess[str]:
        command = ["git"]
        if os.name == "nt":
            command.extend(["-c", "core.longpaths=true"])
        normalized_token = (token or "").strip()
        if normalized_token:
            command.extend(
                [
                    "-c",
                    f"http.extraHeader=AUTHORIZATION: Basic {self._build_basic_auth_header(normalized_token)}",
                ]
            )
        command.extend(args)

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            cwd=cwd,
            env=env,
        )

    def _build_basic_auth_header(self, token: str) -> str:
        raw = f"x-access-token:{token}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _prepare_publish_snapshot_repo(self, source_path: str) -> tuple[git.Repo, str]:
        publish_path = tempfile.mkdtemp(prefix="publish_snapshot_", dir=self.work_dir)
        shutil.copytree(
            source_path,
            publish_path,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git"),
        )
        repo = git.Repo.init(publish_path)
        return repo, publish_path
    

    async def create_and_push_repo(
        self,
        token: str,
        repo_name: str,
        local_path: str,
        description: str,
        owner: str | None = None,
        job_marker: str | None = None,
    ) -> str:
        """Create a new repository and push the migrated code"""
        publish_repo_path: str | None = None
        try:
            logger.info(
                "Starting GitHub repository creation repo_name=%s local_path=%s local_path_exists=%s token_provided=%s token_length=%s",
                repo_name,
                local_path,
                os.path.exists(local_path),
                bool(token),
                len(token) if token else 0,
            )

            if not token or len(token.strip()) == 0:
                raise Exception("GitHub token is required to create and push repositories. Please provide a valid Personal Access Token with repo or public_repo scope.")

            g = Github(token)
            user = g.get_user()
            logger.debug("Authenticated GitHub user login=%s", user.login)
            owner_name = (owner or user.login).strip()
            repo_container = user

            if owner_name.lower() != user.login.lower():
                logger.debug("GitHub target owner requested owner=%s", owner_name)
                try:
                    repo_container = g.get_organization(owner_name)
                    logger.debug("Using GitHub organization owner owner=%s", owner_name)
                except GithubException as e:
                    error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
                    raise Exception(
                        f"Unable to access GitHub owner '{owner_name}'. Make sure the token has permission to create repositories there. {error_msg}"
                    )

            new_repo = None
            # Check if repo already exists
            try:
                existing = repo_container.get_repo(repo_name)
                existing_description = existing.description or ""
                if job_marker and job_marker in existing_description:
                    logger.info("Reusing existing GitHub repo full_name=%s job_marker=%s", existing.full_name, job_marker)
                    new_repo = existing
                else:
                    logger.info("GitHub repo name already exists; generating unique name repo_name=%s", repo_name)
                    repo_name = f"{repo_name}-{int(__import__('time').time())}"
                    logger.debug("GitHub repo retry name=%s", repo_name)
            except GithubException as e:
                logger.debug("GitHub repo does not exist yet repo_name=%s proceeding_to_create=true", repo_name)

            # Create new repository
            if new_repo is None:
                try:
                    logger.info("Creating GitHub repo full_name=%s/%s", owner_name, repo_name)
                    new_repo = repo_container.create_repo(
                        name=repo_name,
                        description=description,
                        private=False,
                        auto_init=False
                    )
                    logger.info("Created GitHub repo url=%s", new_repo.html_url)
                except GithubException as e:
                    error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
                    logger.warning("GitHub repo creation failed repo_name=%s error=%s", repo_name, error_msg)
                    if 'name already exists' in error_msg.lower():
                        try:
                            existing = repo_container.get_repo(repo_name)
                            existing_description = existing.description or ""
                            if job_marker and job_marker in existing_description:
                                logger.info("Reusing GitHub repo created by same job full_name=%s", existing.full_name)
                                new_repo = existing
                            else:
                                repo_name = f"{repo_name}-{int(__import__('time').time())}"
                                logger.info("Retrying GitHub repo creation with new name repo_name=%s", repo_name)
                                new_repo = repo_container.create_repo(
                                    name=repo_name,
                                    description=description,
                                    private=False,
                                    auto_init=False
                                )
                                logger.info("Created GitHub repo on retry url=%s", new_repo.html_url)
                        except GithubException:
                            repo_name = f"{repo_name}-{int(__import__('time').time())}"
                            logger.info("Retrying GitHub repo creation after duplicate conflict repo_name=%s", repo_name)
                            new_repo = repo_container.create_repo(
                                name=repo_name,
                                description=description,
                                private=False,
                                auto_init=False
                            )
                            logger.info("Created GitHub repo on retry url=%s", new_repo.html_url)
                    else:
                        raise Exception(f"Repository creation failed: {error_msg}")

            logger.info(
                "Preparing standalone publish snapshot from %s to avoid shallow-history push failures",
                local_path,
            )
            repo, publish_repo_path = self._prepare_publish_snapshot_repo(local_path)
            logger.debug("Prepared publish snapshot repository path=%s", publish_repo_path)

            # Remove old remote if exists
            if "origin" in [remote.name for remote in repo.remotes]:
                logger.debug("Removing existing Git remote origin")
                repo.delete_remote("origin")

            # Add new remote with token
            auth_url = new_repo.clone_url.replace("https://", f"https://{token}@")
            logger.debug("Adding GitHub remote origin url=%s", redact_url_credentials(auth_url))
            origin = repo.create_remote("origin", auth_url)

            # Check git status before staging
            logger.debug("Checking Git status before staging")
            status = repo.git.status(porcelain=True)
            logger.debug("Git status porcelain=%s", status)

            if not status.strip():
                logger.info("No local changes detected; creating placeholder commit state")
                # Create a .gitkeep file if directory is empty
                gitkeep_path = os.path.join(repo.working_tree_dir or local_path, ".gitkeep")
                with open(gitkeep_path, 'w') as f:
                    f.write("# Migration placeholder\n")
                repo.git.add(A=True)

            # Stage and commit all changes
            logger.debug("Staging Git changes")
            repo.git.add(A=True)

            # Check if there are staged changes
            staged = repo.git.diff("--cached", "--name-only")
            logger.debug("Staged files=%s", staged)

            if staged.strip():
                try:
                    logger.info("Creating Git commit for migrated repository")
                    commit_msg = "Java migration completed - upgraded Java version, dependencies, and code quality"
                    repo.index.commit(commit_msg)
                    logger.info("Git commit created message=%s", commit_msg)

                    # Show commit details
                    commit = repo.head.commit
                    logger.debug("Git commit details hash=%s files_changed=%s totals=%s", commit.hexsha, len(commit.stats.files), commit.stats.total)

                except git.GitCommandError as e:
                    logger.warning("Git commit failed error=%s status=%s", e, repo.git.status())
                    raise Exception(f"Git commit failed: {str(e)}")
            else:
                logger.info("No staged Git changes detected; attempting empty commit")
                # Still create an empty commit to establish the repo
                try:
                    repo.index.commit("Migration setup - no source changes detected")
                    logger.debug("Created empty Git commit for migration setup")
                except git.GitCommandError:
                    logger.debug("Empty Git commit was not created")

            # Push to new repo - try main first, then master
            try:
                logger.debug("Checking current Git branch before push")
                current_branch = repo.active_branch.name if repo.heads else None
                logger.debug("Current Git branch=%s", current_branch)

                if not repo.heads:
                    logger.debug("No Git branches found; creating main branch")
                    repo.git.checkout('-b', 'main')
                    current_branch = 'main'
                    logger.debug("Created Git branch main")
                else:
                    current_branch = repo.active_branch.name

                logger.info("Pushing migrated GitHub repository branch=%s", current_branch)
                push_result = origin.push(refspec=f"HEAD:{current_branch}", set_upstream=True, force=True)
                _ensure_push_succeeded(push_result, "GitHub", current_branch)
                logger.info("GitHub push completed branch=%s", current_branch)
                logger.debug("GitHub push result=%s", _summarize_push_result(push_result))

            except Exception as e:
                logger.warning("GitHub push failed branch=%s error=%s", current_branch, e)

                # Try alternative branch names
                for alt_branch in ['main', 'master']:
                    if alt_branch != current_branch:
                        try:
                            logger.info("Retrying GitHub push alternate_branch=%s", alt_branch)
                            push_result = origin.push(refspec=f"HEAD:{alt_branch}", force=True)
                            _ensure_push_succeeded(push_result, "GitHub", alt_branch)
                            logger.info("GitHub push completed on alternate branch=%s", alt_branch)
                            break
                        except Exception as alt_error:
                            logger.warning("GitHub push failed on alternate branch=%s error=%s", alt_branch, alt_error)
                            continue
                else:
                    # All push attempts failed
                    raise Exception(f"Failed to push to repository on any branch: {str(e)}")

            logger.info("GitHub repository creation and push completed url=%s", new_repo.html_url)
            return new_repo.html_url

        except GithubException as e:
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            logger.error("GitHub API error during repository creation: %s", error_msg)
            raise Exception(f"GitHub API error: {error_msg}")
        except Exception as e:
            error_msg = str(e)
            logger.exception("Unexpected GitHub repository creation error: %s", error_msg)

            # Provide more specific error messages for common issues
            if "Bad credentials" in error_msg or "401" in error_msg:
                raise Exception("GitHub authentication failed. Please check your token is valid and has the required permissions (repo or public_repo scope).")
            elif "403" in error_msg or "Forbidden" in error_msg:
                raise Exception("GitHub API access forbidden. Your token may not have permission to create repositories. Please check token scopes.")
            elif "name already exists" in error_msg.lower():
                raise Exception("Repository name already exists. The system tried to create a unique name but it still conflicts.")
            elif "Validation Failed" in error_msg:
                raise Exception("Repository validation failed. The repository name may be invalid or you may have reached GitHub's repository limits.")
            elif "git" in error_msg.lower() and ("push" in error_msg.lower() or "remote" in error_msg.lower()):
                raise Exception(f"Git operation failed during repository push: {error_msg}")
            else:
                raise Exception(f"Repository creation failed: {error_msg}")
        finally:
            if publish_repo_path and os.path.exists(publish_repo_path):
                shutil.rmtree(publish_repo_path, ignore_errors=True)

    async def push_to_branch(self, token: str, repo_url: str, local_path: str, branch_name: str) -> str:
        """Push migrated code to a new branch in the existing repository."""
        try:
            if not token or len(token.strip()) == 0:
                raise Exception("GitHub token is required to push to a branch. Please provide a valid Personal Access Token with repo or public_repo scope.")

            repo = git.Repo(local_path)

            if "origin" not in [remote.name for remote in repo.remotes]:
                raise Exception("Existing repository remote 'origin' was not found.")

            origin = repo.remotes.origin
            auth_url = repo_url.replace("https://", f"https://{token}@")
            origin.set_url(auth_url)

            repo.git.add(A=True)
            staged = repo.git.diff("--cached", "--name-only")

            if staged.strip():
                repo.index.commit("Java migration completed - upgraded Java version, dependencies, and code quality")
            else:
                try:
                    repo.index.commit("Migration setup - no source changes detected")
                except git.GitCommandError:
                    pass

            repo.git.checkout("-B", branch_name)
            push_result = origin.push(refspec=f"HEAD:{branch_name}", set_upstream=True, force=True)
            _ensure_push_succeeded(push_result, "GitHub", branch_name)

            clean_repo_url = repo_url.replace(".git", "").rstrip("/")
            return f"{clean_repo_url}/tree/{branch_name}"

        except Exception as e:
            raise Exception(f"Failed to push migrated code to branch '{branch_name}': {str(e)}")
    
    def _detect_java_version_from_pom(self, pom_content: str) -> dict:
        """Detect Java version from pom.xml"""
        import re

        def normalize(version: str) -> str:
            version = version.strip()
            return version.replace("1.", "", 1) if version.startswith("1.") else version

        def lookup_property(property_name: str) -> str | None:
            property_match = re.search(
                rf'<{re.escape(property_name)}>\s*(\d+(?:\.\d+)?)\s*</{re.escape(property_name)}>',
                pom_content
            )
            if property_match:
                return normalize(property_match.group(1))
            return None

        # Check for maven.compiler.source
        match = re.search(r'<maven\.compiler\.source>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.source>', pom_content)
        if match:
            return {"version": normalize(match.group(1)), "detected": True}

        # Check for maven.compiler.release
        match = re.search(r'<maven\.compiler\.release>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.release>', pom_content)
        if match:
            return {"version": normalize(match.group(1)), "detected": True}

        # Check for java.version property
        match = re.search(r'<java\.version>\s*(\d+(?:\.\d+)?)\s*</java\.version>', pom_content)
        if match:
            return {"version": normalize(match.group(1)), "detected": True}

        # Check for javaVersion property
        match = re.search(r'<javaVersion>\s*(\d+(?:\.\d+)?)\s*</javaVersion>', pom_content)
        if match:
            return {"version": normalize(match.group(1)), "detected": True}

        # Resolve property references like ${javaVersion} or ${java.version}
        property_reference_patterns = [
            r'<maven\.compiler\.source>\s*\$\{([^}]+)\}\s*</maven\.compiler\.source>',
            r'<maven\.compiler\.target>\s*\$\{([^}]+)\}\s*</maven\.compiler\.target>',
            r'<maven\.compiler\.release>\s*\$\{([^}]+)\}\s*</maven\.compiler\.release>',
            r'<source>\s*\$\{([^}]+)\}\s*</source>',
        ]
        for pattern in property_reference_patterns:
            match = re.search(pattern, pom_content)
            if match:
                resolved = lookup_property(match.group(1))
                if resolved:
                    return {"version": resolved, "detected": True}

        # Check for source in compiler plugin
        match = re.search(r'<source>\s*(\d+\.?\d*)\s*</source>', pom_content)
        if match:
            return {"version": normalize(match.group(1)), "detected": True}

        # No Java version specified in build file
        return {"version": "not_specified", "detected": False}
    
    def _detect_java_version_from_gradle(self, gradle_content: str) -> dict:
        """Detect Java version from build.gradle"""
        import re

        # Check for sourceCompatibility
        match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+(?:\.\d+)?)['\"]?", gradle_content)
        if match:
            version = match.group(1)
            if version.startswith("1."):
                version = version.replace("1.", "")
            return {"version": version, "detected": True}

        # Check for JavaVersion enum
        match = re.search(r"JavaVersion\.VERSION_(\d+)(?:_(\d+))?", gradle_content)
        if match:
            major = match.group(1)
            minor = match.group(2)
            if major == "1" and minor:
                version = minor
            else:
                version = major
            return {"version": version, "detected": True}

        # No Java version specified in build file
        return {"version": "not_specified", "detected": False}
    
    def _parse_pom_dependencies(self, pom_content: str) -> List[Dict[str, str]]:
        """Parse dependencies from pom.xml"""
        import re

        dependencies = []
        dep_pattern = re.compile(
            r'<dependency>\s*'
            r'<groupId>([^<]+)</groupId>\s*'
            r'<artifactId>([^<]+)</artifactId>\s*'
            r'(?:<version>([^<]+)</version>)?',
            re.DOTALL
        )

        for match in dep_pattern.finditer(pom_content):
            dependencies.append({
                "group_id": match.group(1),
                "artifact_id": match.group(2),
                "current_version": match.group(3) or "inherited",
                "new_version": None,
                "status": "analyzing"
            })

        return dependencies

    def _parse_gradle_dependencies(self, gradle_content: str) -> List[Dict[str, str]]:
        """Parse common dependency declarations from build.gradle/build.gradle.kts."""
        import re

        dependencies = []
        seen = set()

        def add_dependency(group_id: str, artifact_id: str, version: str, scope: str):
            key = (group_id, artifact_id, version, scope)
            if key in seen:
                return
            seen.add(key)
            dependencies.append({
                "group_id": group_id,
                "artifact_id": artifact_id,
                "current_version": version or "unspecified",
                "new_version": None,
                "status": f"analyzing ({scope})"
            })

        scope_pattern = r"(?:api|implementation|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|annotationProcessor|kapt|classpath)"

        # Matches forms like:
        # implementation "group:artifact:version"
        # implementation("group:artifact:version")
        # testRuntimeOnly 'group:artifact'
        direct_dependency_pattern = re.compile(
            rf"(?P<scope>{scope_pattern})\s*\(?\s*['\"](?P<group>[^:'\"\s]+):(?P<artifact>[^:'\"\s]+)(?::(?P<version>[^'\"\n\r)]+))?['\"]\s*\)?"
        )

        for match in direct_dependency_pattern.finditer(gradle_content):
            add_dependency(
                match.group("group"),
                match.group("artifact"),
                (match.group("version") or "unspecified").strip(),
                match.group("scope")
            )

        # Matches custom helper declarations like:
        # implementation arcModule("extensions:flabel")
        # classpath arcModule(':extensions:packer')
        helper_dependency_pattern = re.compile(
            rf"(?P<scope>{scope_pattern})\s+(?P<helper>\w+)\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)"
        )

        for match in helper_dependency_pattern.finditer(gradle_content):
            helper_name = match.group("helper")
            module_name = match.group("module").lstrip(":")
            artifact_name = module_name.split(":")[-1]

            if helper_name == "project":
                add_dependency("project", artifact_name, "module", match.group("scope"))
                continue

            if helper_name == "arcModule":
                add_dependency("com.github.Anuken.Arc", artifact_name, "$arcHash", match.group("scope"))
                continue

            add_dependency(helper_name, module_name, "dynamic", match.group("scope"))

        return dependencies

    async def _count_java_files_recursive(self, repository, path: str, max_depth: int = 10) -> int:
        """Recursively count Java files in a directory path"""
        try:
            contents = repository.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]
            java_count = 0

            for item in contents:
                if item.type == "file" and item.name.endswith('.java'):
                    java_count += 1
                elif item.type == "dir" and max_depth > 0:
                    if item.name.startswith('.') or item.name in {"target", "build", "out", "node_modules"}:
                        continue
                    java_count += await self._count_java_files_recursive(repository, item.path, max_depth - 1)

            return java_count
        except:
            return 0

    async def _collect_java_files_recursive(self, repository, path: str, max_depth: int = 4, max_files: int = 500) -> List[str]:
        """Recursively collect Java file paths from a repository path."""
        java_files = []
        try:
            contents = repository.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]

            for item in contents:
                if item.type == "file" and item.name.endswith('.java'):
                    java_files.append(item.path)
                    if len(java_files) >= max_files:
                        return java_files
                elif item.type == "dir" and max_depth > 0:
                    if item.name.startswith('.') or item.name in {"target", "build", "out", "node_modules"}:
                        continue
                    java_files.extend(await self._collect_java_files_recursive(repository, item.path, max_depth - 1, max_files - len(java_files)))
                    if len(java_files) >= max_files:
                        return java_files
            return java_files
        except:
            return java_files

    async def _scan_repo_for_java_files(self, repository) -> List[str]:
        """Scan entire repository for Java files (limited to avoid rate limits)"""
        java_files = []
        try:
            contents = repository.get_contents("")
            if not isinstance(contents, list):
                contents = [contents]

            java_files.extend([item.path for item in contents if item.type == "file" and item.name.endswith('.java')])

            for item in contents:
                if item.type == "dir":
                    java_files.extend(await self._collect_java_files_recursive(repository, item.path, 10, 1000 - len(java_files)))
                    if len(java_files) >= 1000:
                        break

            return java_files
        except:
            return java_files

    async def _detect_api_endpoints_in_repo(self, repository) -> List[Dict[str, str]]:
        """Detect REST API endpoints in a connected repository."""
        candidate_files = await self._collect_endpoint_candidate_files(repository)
        endpoints: List[Dict[str, str]] = []
        seen = set()

        for file_path in candidate_files:
            try:
                content = repository.get_contents(file_path).decoded_content.decode("utf-8", errors="ignore")
                for endpoint in self._extract_endpoints_from_java_content(content, file_path):
                    key = (endpoint["method"], endpoint["path"], endpoint["file"])
                    if key in seen:
                        continue
                    seen.add(key)
                    endpoints.append(endpoint)
            except Exception:
                continue

        return endpoints

    async def _collect_endpoint_candidate_files(self, repository, max_depth: int = 6, max_files: int = 200) -> List[str]:
        """Collect Java source files that are likely to declare API endpoints."""
        candidate_paths: List[str] = []
        queue: List[tuple[str, int]] = []
        visited = set()

        for base_path in ["src/main/java", "src"]:
            try:
                repository.get_contents(base_path)
                queue.append((base_path, max_depth))
            except Exception:
                continue

        # Always include root fallback so nonstandard layouts are scanned too
        queue.append(("", 3))

        while queue and len(candidate_paths) < max_files:
            current_path, depth = queue.pop(0)
            if current_path in visited or depth < 0:
                continue
            visited.add(current_path)

            try:
                contents = repository.get_contents(current_path)
            except Exception:
                continue

            if not isinstance(contents, list):
                contents = [contents]

            for item in contents:
                if item.type == "file" and item.name.endswith(".java"):
                    candidate_paths.append(item.path)
                    if len(candidate_paths) >= max_files:
                        break
                elif item.type == "dir" and depth > 0:
                    if item.name.startswith(".") or item.name in {"target", "build", "out", "node_modules"}:
                        continue
                    queue.append((item.path, depth - 1))

        prioritized = []
        fallback = []
        for path in candidate_paths:
            normalized = path.lower()
            if any(token in normalized for token in ["controller", "resource", "endpoint", "api"]):
                prioritized.append(path)
            else:
                fallback.append(path)

        return prioritized + fallback

    def _extract_endpoints_from_java_content(self, content: str, file_path: str) -> List[Dict[str, str]]:
        """Extract Spring-style and JAX-RS endpoints from a Java file."""
        endpoints: List[Dict[str, str]] = []
        file_name = os.path.basename(file_path)

        class_base_path = ""
        class_request_match = re.search(r'@RequestMapping\s*\((.*?)\)\s*(?:public\s+)?(?:class|interface|record)\s+\w+', content, re.DOTALL)
        if class_request_match:
            class_base_path = self._extract_mapping_path(class_request_match.group(1))

        if not class_base_path:
            class_path_match = re.search(r'@Path\s*\(\s*["\']([^"\']*)["\']\s*\)\s*(?:public\s+)?(?:class|interface|record)\s+\w+', content, re.DOTALL)
            if class_path_match:
                class_base_path = class_path_match.group(1)

        spring_patterns = [
            ("GET", r'@GetMapping\s*(?:\((.*?)\))?'),
            ("POST", r'@PostMapping\s*(?:\((.*?)\))?'),
            ("PUT", r'@PutMapping\s*(?:\((.*?)\))?'),
            ("DELETE", r'@DeleteMapping\s*(?:\((.*?)\))?'),
            ("PATCH", r'@PatchMapping\s*(?:\((.*?)\))?'),
        ]

        for method, pattern in spring_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                sub_path = self._extract_mapping_path(match.group(1) or "")
                endpoints.append({
                    "path": self._join_endpoint_paths(class_base_path, sub_path),
                    "method": method,
                    "file": file_name,
                })

        for match in re.finditer(r'@RequestMapping\s*\((.*?)\)', content, re.DOTALL):
            annotation_args = match.group(1)
            method_match = re.search(r'RequestMethod\.([A-Z]+)', annotation_args)
            sub_path = self._extract_mapping_path(annotation_args)
            if method_match:
                endpoints.append({
                    "path": self._join_endpoint_paths(class_base_path, sub_path),
                    "method": method_match.group(1),
                    "file": file_name,
                })

        jaxrs_class_base = class_base_path
        for match in re.finditer(r'@(GET|POST|PUT|DELETE|PATCH)\b(?:(?!@(GET|POST|PUT|DELETE|PATCH)\b).)*?(?:@Path\s*\(\s*["\']([^"\']*)["\']\s*\))?', content, re.DOTALL):
            method = match.group(1)
            sub_path = match.group(3) or ""
            endpoints.append({
                "path": self._join_endpoint_paths(jaxrs_class_base, sub_path),
                "method": method,
                "file": file_name,
            })

        return endpoints

    def _extract_mapping_path(self, annotation_args: str) -> str:
        """Extract a route path from Java mapping annotation arguments."""
        if not annotation_args:
            return ""

        named_match = re.search(r'(?:value|path)\s*=\s*\{?\s*["\']([^"\']*)["\']', annotation_args)
        if named_match:
            return named_match.group(1)

        direct_match = re.search(r'^\s*["\']([^"\']*)["\']', annotation_args.strip())
        if direct_match:
            return direct_match.group(1)

        return ""

    def _join_endpoint_paths(self, base_path: str, sub_path: str) -> str:
        """Join class-level and method-level endpoint paths."""
        parts = [part.strip("/") for part in [base_path, sub_path] if part and part.strip("/")]
        if not parts:
            return "/"
        return "/" + "/".join(parts)

    async def _detect_java_version_from_repo(self, repository) -> str:
        """Detect Java version by analyzing source files using automation packages (javalang, pylint, etc.)"""
        try:
            # Get a sample of Java files to analyze
            java_files = await self._scan_repo_for_java_files(repository)
            if not java_files:
                return "8"  # Default

            # Find actual Java files (not just counts)
            actual_files = []
            for java_info in java_files[:20]:
                path = java_info
                try:
                    contents = repository.get_contents(path)
                    if not isinstance(contents, list):
                        contents = [contents]

                    for item in contents:
                        if item.type == "file" and item.name.endswith('.java'):
                            actual_files.append(item)
                            if len(actual_files) >= 10:
                                break
                    if len(actual_files) >= 10:
                        break
                except Exception:
                    try:
                        file_obj = repository.get_contents(path)
                        if hasattr(file_obj, 'path') and file_obj.path.endswith('.java'):
                            actual_files.append(file_obj)
                    except Exception:
                        continue
                    if len(actual_files) >= 10:
                        break

            # Use javalang for AST-based Java version detection
            detected_features = await self._analyze_java_files_with_javalang(actual_files, repository)

            # Determine the minimum Java version required based on detected features
            # Check in reverse order (newest to oldest) to find the minimum required version

            logger.debug("Java version detection features=%s basic_java=%s", detected_features, detected_features.get("basic_java", False))

            # Java 21+
            if (detected_features.get("virtual_threads", False) or
                detected_features.get("pattern_matching_instanceof", False) or
                detected_features.get("record_patterns", False)):
                logger.debug("Java version detection selected version=21")
                return "21"

            # Java 17-20
            elif (detected_features.get("sealed_classes", False) or
                  detected_features.get("records", False)):
                logger.debug("Java version detection selected version=17")
                return "17"

            # Java 14-16
            elif (detected_features.get("text_blocks", False) or
                  detected_features.get("switch_expressions", False) or
                  detected_features.get("pattern_matching_switch", False)):
                logger.debug("Java version detection selected version=14")
                return "14"

            # Java 9-13
            elif (detected_features.get("modules", False) or
                  detected_features.get("var_keyword", False)):
                logger.debug("Java version detection selected version=9")
                return "9"

            # Java 8
            elif (detected_features.get("lambdas", False) or
                  detected_features.get("streams", False) or
                  detected_features.get("default_methods", False)):
                logger.debug("Java version detection selected version=8")
                return "8"

            # Java 7
            elif (detected_features.get("diamond_operator", False) or
                  detected_features.get("try_with_resources", False) or
                  detected_features.get("strings_in_switch", False)):
                logger.debug("Java version detection selected version=7")
                return "7"

            # Java 6
            elif (detected_features.get("annotations", False) or
                  detected_features.get("generics", False)):
                logger.debug("Java version detection selected version=6")
                return "6"

            # Java 5
            elif (detected_features.get("enums", False) or
                  detected_features.get("autoboxing", False) or
                  detected_features.get("enhanced_for", False)):
                logger.debug("Java version detection selected version=5")
                return "5"

            # Java 1.4
            elif detected_features.get("assertions", False):
                logger.debug("Java version detection selected version=1.4")
                return "4"

            # Java 1.3
            elif detected_features.get("dynamic_proxy", False):
                logger.debug("Java version detection selected version=1.3")
                return "3"

            # Java 1.2
            elif detected_features.get("collections", False):
                logger.debug("Java version detection selected version=1.2")
                return "2"

            # Java 1.1
            elif detected_features.get("inner_classes", False):
                logger.debug("Java version detection selected version=1.1")
                return "1.1"

            # Java 1.0 - Any valid Java code that doesn't use advanced features
            if detected_features.get("basic_java", False):
                logger.debug("Java version detection selected version=1.0")
                return "1.0"

            # Fallback - if we get here, something went wrong with feature detection
            logger.debug("Java version detection found no advanced markers; defaulting to version=8")
            return "8"

        except Exception as e:
            logger.warning("Error in Java version detection error=%s", e)
            return "8"  # Safe default

    async def _analyze_java_files_with_javalang(self, java_files: list, repository) -> dict:
        """Analyze Java files using javalang AST parser for accurate feature detection"""
        detected_features = {
            # Java 21+ (preview features)
            "virtual_threads": False, "pattern_matching_instanceof": False, "record_patterns": False,
            # Java 17-20
            "sealed_classes": False, "records": False, "pattern_matching_switch": False,
            # Java 14-16
            "text_blocks": False, "switch_expressions": False, "instanceof_pattern_matching": False,
            # Java 9-13
            "modules": False, "var_keyword": False, "text_blocks_preview": False,
            # Java 8
            "lambdas": False, "streams": False, "default_methods": False,
            # Java 7
            "diamond_operator": False, "try_with_resources": False, "strings_in_switch": False,
            # Java 6
            "annotations": False, "generics": False,
            # Java 5
            "enums": False, "autoboxing": False, "enhanced_for": False,
            # Java 1.4
            "assertions": False,
            # Java 1.3
            "dynamic_proxy": False,
            # Java 1.2
            "collections": False,
            # Java 1.1
            "inner_classes": False,
            # Java 1.0
            "basic_java": False  # Will be set to True if we find basic Java syntax
        }

        try:
            import javalang
        except ImportError:
            logger.info("javalang is not available; falling back to regex-based Java version analysis")
            # Fallback to regex analysis if javalang is not available
            return await self._fallback_regex_analysis(java_files, repository)

        # Analyze each Java file using javalang AST parser
        for file_item in java_files[:10]:  # Limit to 10 files for performance
            try:
                content = file_item.decoded_content.decode('utf-8', errors='ignore')

                # Skip files that are too large or too small
                if len(content) > 1000000 or len(content) < 10:  # 1MB limit, 10 char minimum
                    continue

                try:
                    # Parse Java source code into AST
                    tree = javalang.parse.parse(content)

                    # First check if this is valid Java code (sets basic_java to True)
                    if tree and hasattr(tree, 'types'):
                        detected_features["basic_java"] = True

                    # Analyze AST for Java language features
                    await self._analyze_ast_for_features(tree, detected_features, file_item.name)

                    # For basic Java syntax detection, check for fundamental constructs
                    detected_features["basic_java"] = True  # Any successfully parsed Java file is at least Java 1.0

                except javalang.parser.JavaSyntaxError as e:
                    logger.warning("Java syntax error during AST analysis file=%s error=%s", file_item.name, e)
                    # Even with syntax errors, check for basic Java patterns with regex
                    detected_features["basic_java"] = True  # Assume it's Java if it has .java extension
                    await self._fallback_regex_for_file(content, detected_features)
                except Exception as e:
                    logger.warning("Error parsing Java file with javalang file=%s error=%s", file_item.name, e)
                    # Fall back to regex analysis for this file
                    detected_features["basic_java"] = True  # Assume it's Java if parsing fails
                    await self._fallback_regex_for_file(content, detected_features)

            except Exception as e:
                logger.warning("Error processing Java file for version detection file=%s error=%s", file_item.name, e)
                continue

        # Ensure basic_java is True if we found any Java files
        if len(java_files) > 0:
            detected_features["basic_java"] = True

        return detected_features

    async def _analyze_ast_for_features(self, tree, detected_features: dict, filename: str):
        """Analyze AST tree for Java language features using javalang"""

        # First, ensure we have basic Java syntax (classes, methods, etc.)
        if hasattr(tree, 'types') and tree.types:
            detected_features["basic_java"] = True

        # Walk through all nodes in the AST
        for path, node in tree:

            # Basic Java 1.0+ features - any class/method/variable is Java 1.0+
            if hasattr(node, 'name') and node.name:
                detected_features["basic_java"] = True

            # Java 21+ features
            if hasattr(node, 'name') and node.name and 'Thread.ofVirtual' in str(node):
                detected_features["virtual_threads"] = True

            # Check for instanceof pattern matching (Java 16+)
            if hasattr(node, 'pattern') and node.pattern:
                detected_features["pattern_matching_instanceof"] = True

            # Java 17+ features - Records
            if hasattr(node, 'modifiers') and 'record' in str(node.modifiers).lower():
                detected_features["records"] = True

            # Sealed classes (Java 17+)
            if hasattr(node, 'modifiers') and ('sealed' in str(node.modifiers).lower() or
                                              'non-sealed' in str(node.modifiers).lower()):
                detected_features["sealed_classes"] = True

            # Java 14+ features - Switch expressions
            if hasattr(node, 'cases') and node.cases:
                for case in node.cases:
                    if hasattr(case, 'body') and '->' in str(case.body):
                        detected_features["switch_expressions"] = True
                        break

            # Java 9+ features - Modules
            if filename == 'module-info.java':
                detected_features["modules"] = True

            # Var keyword (Java 10+)
            if hasattr(node, 'type') and str(node.type) == 'var':
                detected_features["var_keyword"] = True

            # Lambda expressions (Java 8+)
            if hasattr(node, 'parameters') and hasattr(node, 'body') and '->' in str(node):
                detected_features["lambdas"] = True

            # Stream API (Java 8+)
            if hasattr(node, 'member') and 'stream' in str(node.member).lower():
                detected_features["streams"] = True

            # Default methods (Java 8+)
            if hasattr(node, 'modifiers') and 'default' in str(node.modifiers).lower():
                detected_features["default_methods"] = True

            # Diamond operator (Java 7+) - disabled for now due to false positives
            # if (hasattr(node, 'type_arguments') and
            #     node.type_arguments is not None and
            #     len(node.type_arguments) == 0 and
            #     hasattr(node, 'qualifier') and
            #     str(node.qualifier).startswith('new ')):
            #     detected_features["diamond_operator"] = True

            # Try-with-resources (Java 7+)
            if hasattr(node, 'resources') and node.resources:
                detected_features["try_with_resources"] = True

            # Strings in switch (Java 7+)
            if hasattr(node, 'expression') and isinstance(node.expression, str):
                detected_features["strings_in_switch"] = True

            # Annotations (Java 6+)
            if hasattr(node, 'annotations') and node.annotations:
                detected_features["annotations"] = True

            # Generics (Java 5+)
            if hasattr(node, 'type_arguments') and node.type_arguments:
                detected_features["generics"] = True

            # Enums (Java 5+)
            if hasattr(node, 'modifiers') and 'enum' in str(node.modifiers).lower():
                detected_features["enums"] = True

            # Enhanced for loop (Java 5+)
            if hasattr(node, 'control') and hasattr(node.control, 'iterable'):
                detected_features["enhanced_for"] = True

            # Assertions (Java 1.4+)
            if hasattr(node, 'expression') and 'assert' in str(node.expression).lower():
                detected_features["assertions"] = True

            # Collections (Java 1.2+)
            if hasattr(node, 'type') and 'ArrayList' in str(node.type):
                detected_features["collections"] = True
            if hasattr(node, 'type') and 'HashMap' in str(node.type):
                detected_features["collections"] = True

            # Inner classes (Java 1.1+)
            if hasattr(node, 'enclosing_type') and node.enclosing_type:
                detected_features["inner_classes"] = True

    async def _fallback_regex_analysis(self, java_files: list, repository) -> dict:
        """Fallback regex-based analysis when javalang is not available"""
        logger.info("Using regex fallback for Java version detection")

        detected_features = {
            "virtual_threads": False, "pattern_matching_instanceof": False, "record_patterns": False,
            "sealed_classes": False, "records": False, "pattern_matching_switch": False,
            "text_blocks": False, "switch_expressions": False, "instanceof_pattern_matching": False,
            "modules": False, "var_keyword": False, "text_blocks_preview": False,
            "lambdas": False, "streams": False, "default_methods": False,
            "diamond_operator": False, "try_with_resources": False, "strings_in_switch": False,
            "annotations": False, "generics": False,
            "enums": False, "autoboxing": False, "enhanced_for": False,
            "assertions": False, "dynamic_proxy": False, "collections": False, "inner_classes": False,
            "basic_java": True
        }

        # Use regex patterns to detect features
        for file_item in java_files[:10]:
            try:
                content = file_item.decoded_content.decode('utf-8', errors='ignore')
                await self._fallback_regex_for_file(content, detected_features)
            except Exception as e:
                logger.warning("Error in regex fallback analysis file=%s error=%s", file_item.name, e)
                continue

        return detected_features

    async def _fallback_regex_for_file(self, content: str, detected_features: dict):
        """Apply regex patterns to detect Java features in a single file"""
        import re

        # Java 21+ features
        if re.search(r'Thread\.ofVirtual\(\)', content):
            detected_features["virtual_threads"] = True
        if re.search(r'instanceof.*->', content):
            detected_features["pattern_matching_instanceof"] = True
        if re.search(r'record\s+\w+\s*\([^}]*\)\s*\{', content):
            detected_features["record_patterns"] = True

        # Java 17+ features
        if re.search(r'\bsealed\s+(class|interface)', content):
            detected_features["sealed_classes"] = True
        if re.search(r'\brecord\s+\w+\s*\(', content):
            detected_features["records"] = True

        # Java 14-16 features
        if '"""' in content or '```' in content:
            detected_features["text_blocks"] = True
        if re.search(r'switch\s*\([^)]+\)\s*\{[^}]*->[^}]*\}', content):
            detected_features["switch_expressions"] = True

        # Java 9-13 features
        if 'module-info.java' in content or re.search(r'\bmodule\s+\w+', content):
            detected_features["modules"] = True
        if re.search(r'\bvar\s+\w+\s*=', content):
            detected_features["var_keyword"] = True

        # Java 8 features
        if re.search(r'->\s*\{', content):
            detected_features["lambdas"] = True
        if re.search(r'\.stream\(\)|\.parallelStream\(\)', content):
            detected_features["streams"] = True
        if re.search(r'\bdefault\s+\w+', content):
            detected_features["default_methods"] = True

        # Java 7 features - Diamond operator (more specific pattern)
        if re.search(r'new\s+\w+\s*<\s*>', content):
            detected_features["diamond_operator"] = True
        if re.search(r'try\s*\([^)]+\)', content):
            detected_features["try_with_resources"] = True
        if re.search(r'case\s+"[^"]+"\s*:', content):
            detected_features["strings_in_switch"] = True

        # Java 6 features
        if re.search(r'@\w+', content):
            detected_features["annotations"] = True
        if re.search(r'List<\w+>|Map<\w+,\w+>', content):
            detected_features["generics"] = True

        # Java 5 features
        if re.search(r'\benum\s+\w+', content):
            detected_features["enums"] = True
        if re.search(r'Integer\.valueOf|Integer\.parseInt', content):
            detected_features["autoboxing"] = True
        if re.search(r'for\s*\(\w+\s+\w+\s*:\s*\w+\)', content):
            detected_features["enhanced_for"] = True

        # Java 1.4 features
        if re.search(r'\bassert\s+', content):
            detected_features["assertions"] = True

        # Java 1.3 features
        if re.search(r'Proxy\.|InvocationHandler', content):
            detected_features["dynamic_proxy"] = True

        # Java 1.2 features
        if re.search(r'ArrayList|HashMap|Collections\.', content):
            detected_features["collections"] = True

        # Java 1.1 features
        if re.search(r'class\s+\w+\s*\.\s*\w+', content):
            detected_features["inner_classes"] = True

    async def _analyze_all_repository_files(self, repository, analysis: dict, remaining_requests: int = 100) -> dict:
        """Comprehensive analysis of ALL files in repository for business logic issues, duplications, and code quality"""
        result = {
            "files": [],
            "business_issues": [],
            "quality_metrics": {},
            "duplications": [],
            "security_issues": [],
            "performance_issues": []
        }

        try:
            # Get all files recursively (with depth limit to avoid rate limits)
            all_files = await self._get_all_files_recursive(repository, "", max_depth=5)
            result["files"] = all_files

            logger.info("Repository file analysis discovered total_files=%s", len(all_files))

            # Categorize files by type
            file_types = {}
            code_files = []
            text_files = []

            for file_info in all_files:
                file_name = file_info["name"]
                file_path = file_info["path"]

                # Categorize by extension
                if file_name.endswith(('.java', '.py', '.js', '.ts', '.cpp', '.c', '.cs', '.php', '.rb', '.go')):
                    code_files.append(file_info)
                    ext = file_name.split('.')[-1]
                    file_types[ext] = file_types.get(ext, 0) + 1
                elif file_name.endswith(('.txt', '.md', '.xml', '.json', '.yml', '.yaml', '.properties', '.sql')):
                    text_files.append(file_info)

            result["quality_metrics"]["total_files"] = len(all_files)
            result["quality_metrics"]["code_files"] = len(code_files)
            result["quality_metrics"]["text_files"] = len(text_files)
            result["quality_metrics"]["file_types"] = file_types

            # Analyze Java files for business logic issues
            java_files = [f for f in code_files if f["name"].endswith('.java')]

            # Analyze business logic issues
            business_issues = await self._analyze_business_logic_issues(java_files, repository)
            result["business_issues"] = business_issues

            # Analyze code duplications
            duplications = await self._analyze_code_duplications(java_files, repository)
            result["duplications"] = duplications

            # Analyze security issues
            security_issues = await self._analyze_security_issues(java_files, repository)
            result["security_issues"] = security_issues

            # Analyze performance issues
            performance_issues = await self._analyze_performance_issues(java_files, repository)
            result["performance_issues"] = performance_issues

            # Calculate code quality metrics
            result["quality_metrics"]["cyclomatic_complexity"] = await self._calculate_complexity_metrics(java_files, repository)
            result["quality_metrics"]["maintainability_index"] = await self._calculate_maintainability_index(java_files, repository)
            result["quality_metrics"]["technical_debt"] = await self._estimate_technical_debt(business_issues, duplications, security_issues)

        except Exception as e:
            logger.warning("Error in comprehensive repository file analysis error=%s", e)
            # Return basic result if analysis fails
            pass

        return result

    async def _get_all_files_recursive(self, repository, path: str, max_depth: int = 5, current_depth: int = 0) -> list:
        """Recursively get all files in repository with depth limit"""
        files = []

        try:
            if current_depth >= max_depth:
                return files

            contents = repository.get_contents(path)

            for item in contents:
                # Skip common directories that shouldn't be analyzed
                skip_dirs = ['.git', 'node_modules', 'target', 'build', 'out', '.gradle', '.idea', '.vscode',
                           'dist', 'bin', 'obj', '__pycache__', '.next', '.nuxt', 'coverage']

                if item.type == "dir":
                    if item.name not in skip_dirs and not item.name.startswith('.'):
                        # Recursively get files from subdirectory
                        sub_files = await self._get_all_files_recursive(repository, item.path, max_depth, current_depth + 1)
                        files.extend(sub_files)
                else:
                    # Add file info
                    files.append({
                        "name": item.name,
                        "path": item.path,
                        "size": getattr(item, 'size', 0),
                        "type": "file"
                    })

        except Exception as e:
            logger.warning("Error getting repository files path=%s error=%s", path, e)

        return files

    async def _analyze_business_logic_issues(self, java_files: list, repository) -> list:
        """Analyze Java files for business logic issues, duplications, and code quality problems"""
        issues = []

        for file_info in java_files[:20]:  # Limit to avoid rate limits
            try:
                file_content = repository.get_contents(file_info["path"]).decoded_content.decode('utf-8', errors='ignore')
                file_issues = await self._analyze_single_file_business_logic(file_info["path"], file_content)
                issues.extend(file_issues)
            except Exception as e:
                logger.warning("Error analyzing business logic path=%s error=%s", file_info["path"], e)
                continue

        return issues

    async def _analyze_single_file_business_logic(self, file_path: str, content: str) -> list:
        """Analyze a single file for business logic issues"""
        issues = []
        lines = content.split('\n')

        # Business Logic Issue Detection Patterns
        patterns = [
            # Null pointer exceptions
            {
                "type": "null_pointer_risk",
                "pattern": r'\.equals\([^)]*\)\s*(?:\|\||&&)',
                "severity": "high",
                "message": "Potential null pointer exception in chained equals() calls",
                "auto_fix": True
            },
            # Empty catch blocks
            {
                "type": "empty_catch",
                "pattern": r'catch\s*\([^)]*\)\s*\{\s*\}',
                "severity": "medium",
                "message": "Empty catch block - exceptions are being silently ignored",
                "auto_fix": False
            },
            # Magic numbers
            {
                "type": "magic_number",
                "pattern": r'\b\d{2,}\b(?!\s*[;),])',
                "severity": "low",
                "message": "Magic number detected - consider using named constants",
                "auto_fix": True
            },
            # Long methods (>50 lines)
            {
                "type": "long_method",
                "pattern": r'public\s+.*\{[^}]*\n(?:.*\n){50,}[^}]*\}',
                "severity": "medium",
                "message": "Method is too long - consider breaking it down",
                "auto_fix": False
            },
            # Missing null checks
            {
                "type": "missing_null_check",
                "pattern": r'(\w+)\.(\w+)\(\)',
                "severity": "medium",
                "message": "Potential null pointer exception - method called on variable that might be null",
                "auto_fix": True
            },
            # Inefficient string concatenation in loops
            {
                "type": "string_concat_loop",
                "pattern": r'for\s*\([^}]*\{[^}]*\+\s*=.*[^}]*\}',
                "severity": "high",
                "message": "Inefficient string concatenation in loop - use StringBuilder",
                "auto_fix": True
            },
            # Hard-coded credentials
            {
                "type": "hardcoded_credentials",
                "pattern": r'(?i)(password|pwd|secret|key|token)\s*[=:]\s*["\'][^"\']+["\']',
                "severity": "critical",
                "message": "Hard-coded credentials detected - security risk",
                "auto_fix": True
            },
            # SQL injection risk
            {
                "type": "sql_injection",
                "pattern": r'(?:select|insert|update|delete).*\+\s*\w+',
                "severity": "critical",
                "message": "Potential SQL injection vulnerability",
                "auto_fix": True
            },
            # Resource leaks
            {
                "type": "resource_leak",
                "pattern": r'(?:FileInputStream|FileOutputStream|BufferedReader|BufferedWriter|Connection)\s+\w+\s*=.*new',
                "severity": "high",
                "message": "Resource not properly closed - potential memory leak",
                "auto_fix": True
            }
        ]

        import re

        for i, line in enumerate(lines, 1):
            for pattern_info in patterns:
                if re.search(pattern_info["pattern"], line):
                    issues.append({
                        "file": file_path,
                        "line": i,
                        "type": pattern_info["type"],
                        "severity": pattern_info["severity"],
                        "message": pattern_info["message"],
                        "code": line.strip(),
                        "auto_fix": pattern_info["auto_fix"]
                    })

        return issues

    async def _analyze_code_duplications(self, java_files: list, repository) -> list:
        """Analyze code for duplications"""
        duplications = []

        # Simple duplication detection - compare method bodies
        methods = {}

        for file_info in java_files[:10]:  # Limit files for performance
            try:
                content = repository.get_contents(file_info["path"]).decoded_content.decode('utf-8', errors='ignore')

                # Extract method signatures and bodies
                import re
                method_pattern = r'(?:public|private|protected)?\s*\w+\s+\w+\s*\([^)]*\)\s*\{([^}]*)\}'
                matches = re.findall(method_pattern, content, re.DOTALL)

                for method_body in matches:
                    # Create a hash of the method body (simplified)
                    body_hash = hash(method_body.strip())
                    if body_hash in methods:
                        # Found duplication
                        duplications.append({
                            "type": "method_duplication",
                            "files": [methods[body_hash]["file"], file_info["path"]],
                            "method_signature": methods[body_hash]["signature"],
                            "severity": "medium",
                            "message": "Duplicate method implementation found"
                        })
                    else:
                        # Store method info
                        methods[body_hash] = {
                            "file": file_info["path"],
                            "signature": method_body[:100] + "..." if len(method_body) > 100 else method_body,
                            "body": method_body
                        }

            except Exception as e:
                logger.warning("Error analyzing code duplication path=%s error=%s", file_info["path"], e)

        return duplications

    async def _analyze_security_issues(self, java_files: list, repository) -> list:
        """Analyze code for security vulnerabilities"""
        security_issues = []

        security_patterns = [
            {
                "type": "command_injection",
                "pattern": r'Runtime\.getRuntime\(\)\.exec\([^)]*\+\s*\w+',
                "severity": "critical",
                "message": "Command injection vulnerability"
            },
            {
                "type": "xpath_injection",
                "pattern": r'XPath.*compile.*\+',
                "severity": "high",
                "message": "XPath injection vulnerability"
            },
            {
                "type": "xml_external_entity",
                "pattern": r'DocumentBuilderFactory.*setFeature.*false',
                "severity": "high",
                "message": "XML external entity vulnerability"
            },
            {
                "type": "weak_cryptography",
                "pattern": r'DesCipher|MD5|SHA-1',
                "severity": "medium",
                "message": "Weak cryptography algorithm detected"
            }
        ]

        import re

        for file_info in java_files[:15]:
            try:
                content = repository.get_contents(file_info["path"]).decoded_content.decode('utf-8', errors='ignore')
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    for pattern_info in security_patterns:
                        if re.search(pattern_info["pattern"], line):
                            security_issues.append({
                                "file": file_info["path"],
                                "line": i,
                                "type": pattern_info["type"],
                                "severity": pattern_info["severity"],
                                "message": pattern_info["message"],
                                "code": line.strip()
                            })

            except Exception as e:
                logger.warning("Error analyzing security issues path=%s error=%s", file_info["path"], e)

        return security_issues

    async def _analyze_performance_issues(self, java_files: list, repository) -> list:
        """Analyze code for performance issues"""
        performance_issues = []

        performance_patterns = [
            {
                "type": "inefficient_collection",
                "pattern": r'new\s+(?:Vector|Hashtable|Stack)\(',
                "severity": "medium",
                "message": "Using legacy synchronized collection - consider ArrayList/HashMap"
            },
            {
                "type": "string_concatenation",
                "pattern": r'\w+\s*\+\s*\w+\s*\+\s*\w+\s*\+\s*\w+',
                "severity": "low",
                "message": "Multiple string concatenations - consider StringBuilder"
            },
            {
                "type": "expensive_operation_loop",
                "pattern": r'for\s*\([^}]*\{[^}]*\.(?:size|length)\(\)[^}]*\}',
                "severity": "medium",
                "message": "Calling size()/length() in loop condition - cache the value"
            },
            {
                "type": "autoboxing_overhead",
                "pattern": r'Long\.|Integer\.|Double\.|Float\.',
                "severity": "low",
                "message": "Potential autoboxing overhead - consider primitive types"
            }
        ]

        import re

        for file_info in java_files[:15]:
            try:
                content = repository.get_contents(file_info["path"]).decoded_content.decode('utf-8', errors='ignore')
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    for pattern_info in performance_patterns:
                        if re.search(pattern_info["pattern"], line):
                            performance_issues.append({
                                "file": file_info["path"],
                                "line": i,
                                "type": pattern_info["type"],
                                "severity": pattern_info["severity"],
                                "message": pattern_info["message"],
                                "code": line.strip()
                            })

            except Exception as e:
                logger.warning("Error analyzing performance issues path=%s error=%s", file_info["path"], e)

        return performance_issues

    async def _calculate_complexity_metrics(self, java_files: list, repository) -> dict:
        """Calculate cyclomatic complexity and other code metrics"""
        metrics = {
            "average_complexity": 0,
            "max_complexity": 0,
            "complex_methods": 0,
            "total_methods": 0
        }

        total_complexity = 0
        method_count = 0

        for file_info in java_files[:10]:
            try:
                content = repository.get_contents(file_info["path"]).decoded_content.decode('utf-8', errors='ignore')

                # Simple complexity calculation based on control flow statements
                import re
                complexity_keywords = ['if', 'while', 'for', 'case', 'catch', '&&', '||']
                methods = re.findall(r'(?:public|private|protected)?\s*\w+\s+\w+\s*\([^)]*\)\s*\{([^}]*)\}', content, re.DOTALL)

                for method in methods:
                    method_count += 1
                    complexity = 1  # Base complexity

                    for keyword in complexity_keywords:
                        complexity += len(re.findall(r'\b' + keyword + r'\b', method))

                    total_complexity += complexity
                    metrics["max_complexity"] = max(metrics["max_complexity"], complexity)

                    if complexity > 10:
                        metrics["complex_methods"] += 1

            except Exception as e:
                logger.warning("Error calculating complexity metrics path=%s error=%s", file_info["path"], e)

        if method_count > 0:
            metrics["average_complexity"] = round(total_complexity / method_count, 2)
        metrics["total_methods"] = method_count

        return metrics

    async def _calculate_maintainability_index(self, java_files: list, repository) -> float:
        """Calculate maintainability index (simplified version)"""
        try:
            total_lines = 0
            total_comments = 0

            for file_info in java_files[:10]:
                try:
                    content = repository.get_contents(file_info["path"]).decoded_content.decode('utf-8', errors='ignore')
                    lines = content.split('\n')
                    total_lines += len(lines)

                    # Count comment lines
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith('//') or stripped.startswith('/*') or '*/' in stripped:
                            total_comments += 1

                except Exception as e:
                    logger.warning("Error calculating maintainability index path=%s error=%s", file_info["path"], e)

            if total_lines > 0:
                comment_ratio = total_comments / total_lines
                # Simplified maintainability index calculation
                return round((comment_ratio * 50) + 20, 2)  # Scale to 0-70 range
            else:
                return 0.0

        except:
            return 0.0

    async def _estimate_technical_debt(self, business_issues: list, duplications: list, security_issues: list) -> dict:
        """Estimate technical debt based on found issues"""
        debt_hours = {
            "business_logic": len(business_issues) * 2,  # 2 hours per business logic issue
            "duplications": len(duplications) * 4,  # 4 hours per duplication
            "security": len(security_issues) * 8,  # 8 hours per security issue
        }

        total_hours = sum(debt_hours.values())

        return {
            "estimated_hours": total_hours,
            "breakdown": debt_hours,
            "severity": "low" if total_hours < 40 else "medium" if total_hours < 100 else "high"
        }

    def _is_java_makefile(self, repository) -> bool:
        """Check if a Makefile is for Java compilation"""
        try:
            makefile_content = repository.get_contents("Makefile").decoded_content.decode('utf-8')
            # Check for Java-related commands
            java_indicators = ['javac', '.class', '.java', 'java ', 'jar ']
            return any(indicator in makefile_content.lower() for indicator in java_indicators)
        except:
            return False
