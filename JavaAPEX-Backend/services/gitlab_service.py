"""
GitLab Service - Handles GitLab API interactions
"""
import logging
import os
import tempfile
import shutil
from typing import List, Dict, Any
import git
import httpx

from utils.config import DEFAULT_WORK_DIR
from utils.logging_utils import redact_url_credentials

logger = logging.getLogger(__name__)


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


class GitLabService:
    def __init__(self):
        self.work_dir = DEFAULT_WORK_DIR
        self.gitlab_url = os.getenv("GITLAB_URL", "https://gitlab.com")
        self.api_base_url = f"{self.gitlab_url}/api/v4"
        os.makedirs(self.work_dir, exist_ok=True)

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

    async def list_repositories(self, token: str) -> List[Dict[str, Any]]:
        """List all repositories accessible with the token"""
        try:
            if not token or len(token) < 10:
                raise Exception("Invalid GitLab token format")

            headers = {"Authorization": f"Bearer {token}"}

            # Get user's projects
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/projects",
                    headers=headers,
                    params={"membership": "true", "per_page": "100"}
                )

                if response.status_code == 200:
                    projects = response.json()
                    repos = []

                    for project in projects:
                        repos.append({
                            "name": project["name"],
                            "full_name": project["path_with_namespace"],
                            "url": project["web_url"],
                            "default_branch": project.get("default_branch", "main"),
                            "language": None,  # GitLab doesn't expose primary language easily
                            "description": project.get("description", "")
                        })

                    return repos
                else:
                    raise Exception(f"GitLab API error: {response.status_code} - {response.text}")

        except Exception as e:
            raise Exception(f"Failed to connect to GitLab: {str(e)}")

    async def analyze_repository(self, token: str, owner: str, repo: str) -> Dict[str, Any]:
        """Analyze a repository to detect Java version, build tool, and structure"""
        try:
            if not token or len(token.strip()) == 0:
                raise Exception("GitLab token is required for repository analysis.")

            headers = {"Authorization": f"Bearer {token}"}

            # Get project info
            project_path = f"{owner}/{repo}"
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/projects/{project_path.replace('/', '%2F')}",
                    headers=headers
                )

                if response.status_code != 200:
                    raise Exception(f"GitLab API error: {response.status_code} - {response.text}")

                project = response.json()

                analysis = {
                    "name": project["name"],
                    "full_name": project["path_with_namespace"],
                    "default_branch": project.get("default_branch", "main"),
                    "language": None,
                    "build_tool": None,
                    "java_version": None,
                    "has_tests": False,
                    "dependencies": [],
                    "api_endpoints": [],
                    "structure": {
                        "has_pom_xml": False,
                        "has_build_gradle": False,
                        "has_src_main": False,
                        "has_src_test": False
                    }
                }

                # Check for build files in repository
                files_response = await client.get(
                    f"{self.api_base_url}/projects/{project['id']}/repository/tree",
                    headers=headers,
                    params={"ref": project.get("default_branch", "main"), "per_page": "100"}
                )

                if files_response.status_code == 200:
                    files = files_response.json()
                    file_names = [f["name"] for f in files]

                    if "pom.xml" in file_names:
                        analysis["build_tool"] = "maven"
                        analysis["structure"]["has_pom_xml"] = True

                        # Get pom.xml content
                        pom_response = await client.get(
                            f"{self.api_base_url}/projects/{project['id']}/repository/files/pom.xml/raw",
                            headers=headers,
                            params={"ref": project.get("default_branch", "main")}
                        )

                        if pom_response.status_code == 200:
                            pom_content = pom_response.text
                            analysis["java_version"] = self._detect_java_version_from_pom(pom_content)
                            analysis["dependencies"] = self._parse_pom_dependencies(pom_content)

                    elif "build.gradle" in file_names:
                        analysis["build_tool"] = "gradle"
                        analysis["structure"]["has_build_gradle"] = True

                        # Get build.gradle content
                        gradle_response = await client.get(
                            f"{self.api_base_url}/projects/{project['id']}/repository/files/build.gradle/raw",
                            headers=headers,
                            params={"ref": project.get("default_branch", "main")}
                        )

                        if gradle_response.status_code == 200:
                            gradle_content = gradle_response.text
                            analysis["java_version"] = self._detect_java_version_from_gradle(gradle_content)

                    # Check for src directory structure
                    if any(f["name"] == "src" and f["type"] == "tree" for f in files):
                        analysis["structure"]["has_src_main"] = True  # Assume if src exists, main exists
                        analysis["structure"]["has_src_test"] = True  # Assume if src exists, test exists
                        analysis["has_tests"] = True

                return analysis

        except Exception as e:
            raise Exception(f"GitLab API error: {str(e)}")

    async def parse_repo_url(self, repo_url: str) -> tuple:
        """Parse GitLab URL to extract owner and repo name"""
        import re
        # Handle various GitLab URL formats
        patterns = [
            r'gitlab\.com[:/]+([^/]+)/([^/\s]+)',  # https://gitlab.com/owner/repo or gitlab.com/owner/repo
            r'^([^/]+)/([^/]+)$',  # owner/repo format
        ]
        for pattern in patterns:
            match = re.search(pattern, repo_url)
            if match:
                return match.group(1), match.group(2).replace('.git', '')
        raise Exception("Invalid GitLab repository URL. Use format: owner/repo or https://gitlab.com/owner/repo")

    async def get_repo_info(self, token: str, owner: str, repo: str) -> Dict[str, Any]:
        """Get repository information"""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            project_path = f"{owner}/{repo}"

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/projects/{project_path.replace('/', '%2F')}",
                    headers=headers
                )

                if response.status_code == 200:
                    project = response.json()
                    return {
                        "name": project["name"],
                        "full_name": project["path_with_namespace"],
                        "url": project["web_url"],
                        "default_branch": project.get("default_branch", "main"),
                        "language": None,
                        "description": project.get("description", ""),
                        "is_private": project["visibility"] != "public",
                        "owner": project["namespace"]["path"],
                    }
                else:
                    raise Exception(f"GitLab API error: {response.status_code} - {response.text}")

        except Exception as e:
            raise Exception(f"Failed to get repository info: {str(e)}")

    async def list_repo_files(self, token: str, owner: str, repo: str, path: str = "") -> List[Dict[str, Any]]:
        """List all files and directories in a repository"""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            project_path = f"{owner}/{repo}"

            # First get project ID
            async with httpx.AsyncClient() as client:
                project_response = await client.get(
                    f"{self.api_base_url}/projects/{project_path.replace('/', '%2F')}",
                    headers=headers
                )

                if project_response.status_code != 200:
                    raise Exception(f"Failed to get project: {project_response.status_code}")

                project = project_response.json()
                project_id = project["id"]

                # Get repository tree
                tree_response = await client.get(
                    f"{self.api_base_url}/projects/{project_id}/repository/tree",
                    headers=headers,
                    params={
                        "path": path,
                        "ref": project.get("default_branch", "main"),
                        "per_page": "100"
                    }
                )

                if tree_response.status_code == 200:
                    items = tree_response.json()
                    files = []
                    for item in items:
                        files.append({
                            "name": item["name"],
                            "path": item["path"],
                            "type": "file" if item["type"] == "blob" else "dir",
                            "size": 0,  # GitLab doesn't provide size in tree API
                            "url": f"{project['web_url']}/-/blob/{project.get('default_branch', 'main')}/{item['path']}",
                        })

                    return files
                else:
                    raise Exception(f"GitLab API error: {tree_response.status_code} - {tree_response.text}")

        except Exception as e:
            raise Exception(f"Failed to list files: {str(e)}")

    async def get_file_content(self, token: str, owner: str, repo: str, path: str) -> str:
        """Get the content of a file from the repository"""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            project_path = f"{owner}/{repo}"

            # First get project ID
            async with httpx.AsyncClient() as client:
                project_response = await client.get(
                    f"{self.api_base_url}/projects/{project_path.replace('/', '%2F')}",
                    headers=headers
                )

                if project_response.status_code != 200:
                    raise Exception(f"Failed to get project: {project_response.status_code}")

                project = project_response.json()
                project_id = project["id"]

                # Get file content
                file_response = await client.get(
                    f"{self.api_base_url}/projects/{project_id}/repository/files/{path.replace('/', '%2F')}/raw",
                    headers=headers,
                    params={"ref": project.get("default_branch", "main")}
                )

                if file_response.status_code == 200:
                    return file_response.text
                else:
                    raise Exception(f"GitLab API error: {file_response.status_code} - {file_response.text}")

        except Exception as e:
            raise Exception(f"Failed to get file content: {str(e)}")

    async def clone_repository(self, token: str, repo_url: str) -> str:
        """Clone a repository to local filesystem"""
        # Create unique directory for this clone
        import uuid
        clone_dir = os.path.join(self.work_dir, str(uuid.uuid4()))
        os.makedirs(clone_dir, exist_ok=True)

        # Add token to URL for authentication
        if "gitlab.com" in repo_url:
            auth_url = repo_url.replace("https://", f"https://oauth2:{token}@")
        else:
            auth_url = repo_url

        try:
            # Use subprocess for better control over git clone
            import subprocess

            result = subprocess.run([
                'git', 'clone',
                '-c', 'core.protectNTFS=false',
                auth_url, clone_dir
            ], capture_output=True, text=True, encoding="utf-8", errors="ignore", cwd=os.path.dirname(clone_dir))

            if result.returncode == 0:
                return clone_dir
            else:
                raise Exception(f"Failed to clone repository: {result.stderr}")
        except Exception as e:
            raise Exception(f"Failed to clone repository: {str(e)}")

    async def create_and_push_repo(
        self,
        token: str,
        repo_name: str,
        local_path: str,
        description: str,
        job_marker: str | None = None,
    ) -> str:
        """Create a new repository and push the migrated code"""
        publish_repo_path: str | None = None
        try:
            logger.info(
                "Starting GitLab repository creation repo_name=%s local_path=%s local_path_exists=%s",
                repo_name,
                local_path,
                os.path.exists(local_path),
            )
            headers = {"Authorization": f"Bearer {token}"}

            # Create new repository
            async with httpx.AsyncClient() as client:
                async def _get_existing_project() -> Dict[str, Any] | None:
                    try:
                        user_response = await client.get(f"{self.api_base_url}/user", headers=headers)
                        if user_response.status_code != 200:
                            return None
                        username = (user_response.json() or {}).get("username")
                        if not username:
                            return None
                        project_path = f"{username}/{repo_name}"
                        project_response = await client.get(
                            f"{self.api_base_url}/projects/{project_path.replace('/', '%2F')}",
                            headers=headers,
                        )
                        if project_response.status_code == 200:
                            return project_response.json()
                    except Exception:
                        return None
                    return None

                new_repo = None
                create_response = await client.post(
                    f"{self.api_base_url}/projects",
                    headers=headers,
                    json={
                        "name": repo_name,
                        "description": description,
                        "visibility": "public",
                        "initialize_with_readme": False
                    }
                )

                if create_response.status_code == 201:
                    new_repo = create_response.json()
                    logger.info("Created GitLab repository url=%s", new_repo["web_url"])
                elif create_response.status_code == 400:
                    existing = await _get_existing_project()
                    if existing and job_marker and job_marker in (existing.get("description") or ""):
                        new_repo = existing
                        logger.info("Reusing existing GitLab repository url=%s job_marker=%s", new_repo["web_url"], job_marker)
                    else:
                        repo_name = f"{repo_name}-{int(__import__('time').time())}"
                        logger.info("Retrying GitLab repository creation with new name repo_name=%s", repo_name)

                        create_response = await client.post(
                            f"{self.api_base_url}/projects",
                            headers=headers,
                            json={
                                "name": repo_name,
                                "description": description,
                                "visibility": "public",
                                "initialize_with_readme": False
                            }
                        )

                        if create_response.status_code == 201:
                            new_repo = create_response.json()
                            logger.info("Created GitLab repository on retry url=%s", new_repo["web_url"])
                        else:
                            raise Exception(f"Repository creation failed: {create_response.status_code} - {create_response.text}")
                else:
                    raise Exception(f"Repository creation failed: {create_response.status_code} - {create_response.text}")

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
            auth_url = new_repo["http_url_to_repo"].replace("https://", f"https://oauth2:{token}@")
            logger.debug("Adding GitLab remote origin url=%s", redact_url_credentials(auth_url))
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
                    logger.warning("Git commit failed error=%s", e)
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

                logger.info("Pushing migrated GitLab repository branch=%s", current_branch)
                push_result = origin.push(refspec=f"HEAD:{current_branch}", set_upstream=True, force=True)
                _ensure_push_succeeded(push_result, "GitLab", current_branch)
                logger.info("GitLab push completed branch=%s", current_branch)
                logger.debug("GitLab push result=%s", _summarize_push_result(push_result))

            except Exception as e:
                logger.warning("GitLab push failed branch=%s error=%s", current_branch, e)

                # Try alternative branch names
                for alt_branch in ['main', 'master']:
                    if alt_branch != current_branch:
                        try:
                            logger.info("Retrying GitLab push alternate_branch=%s", alt_branch)
                            push_result = origin.push(refspec=f"HEAD:{alt_branch}", force=True)
                            _ensure_push_succeeded(push_result, "GitLab", alt_branch)
                            logger.info("GitLab push completed on alternate branch=%s", alt_branch)
                            break
                        except Exception as alt_error:
                            logger.warning("GitLab push failed on alternate branch=%s error=%s", alt_branch, alt_error)
                            continue
                else:
                    raise Exception(f"Failed to push to repository on any branch: {str(e)}")

            logger.info("GitLab repository creation and push completed url=%s", new_repo["web_url"])
            return new_repo["web_url"]

        except Exception as e:
            error_msg = str(e)
            logger.exception("Unexpected GitLab repository creation error: %s", error_msg)

            # Provide more specific error messages
            if "401" in error_msg or "Unauthorized" in error_msg:
                raise Exception("GitLab authentication failed. Please check your token is valid and has the required permissions (api scope).")
            elif "403" in error_msg or "Forbidden" in error_msg:
                raise Exception("GitLab API access forbidden. Your token may not have permission to create repositories.")
            elif "has already been taken" in error_msg.lower():
                raise Exception("Repository name already exists. The system tried to create a unique name but it still conflicts.")
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
                raise Exception("GitLab token is required to push to a branch.")

            repo = git.Repo(local_path)

            if "origin" not in [remote.name for remote in repo.remotes]:
                raise Exception("Existing repository remote 'origin' was not found.")

            origin = repo.remotes.origin
            auth_url = repo_url.replace("https://", f"https://oauth2:{token}@")
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
            _ensure_push_succeeded(push_result, "GitLab", branch_name)

            clean_repo_url = repo_url.replace(".git", "").rstrip("/")
            return f"{clean_repo_url}/-/tree/{branch_name}"

        except Exception as e:
            raise Exception(f"Failed to push migrated code to branch '{branch_name}': {str(e)}")

    def _detect_java_version_from_pom(self, pom_content: str) -> str:
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
            return normalize(match.group(1))

        # Check for maven.compiler.release
        match = re.search(r'<maven\.compiler\.release>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.release>', pom_content)
        if match:
            return normalize(match.group(1))

        # Check for java.version property
        match = re.search(r'<java\.version>\s*(\d+(?:\.\d+)?)\s*</java\.version>', pom_content)
        if match:
            return normalize(match.group(1))

        # Check for javaVersion property
        match = re.search(r'<javaVersion>\s*(\d+(?:\.\d+)?)\s*</javaVersion>', pom_content)
        if match:
            return normalize(match.group(1))

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
                    return resolved

        # Check for source in compiler plugin
        match = re.search(r'<source>\s*(\d+\.?\d*)\s*</source>', pom_content)
        if match:
            return normalize(match.group(1))

        return "unknown"

    def _detect_java_version_from_gradle(self, gradle_content: str) -> str:
        """Detect Java version from build.gradle"""
        import re

        # Check for sourceCompatibility
        match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+)['\"]?", gradle_content)
        if match:
            return match.group(1)

        # Check for JavaVersion enum
        match = re.search(r"JavaVersion\.VERSION_(\d+)", gradle_content)
        if match:
            return match.group(1)

        return "unknown"

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
