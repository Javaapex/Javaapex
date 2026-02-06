"""
GitLab Service - Handles GitLab API interactions
"""
import os
import tempfile
import shutil
from typing import List, Dict, Any
import git
import httpx


class GitLabService:
    def __init__(self):
        self.work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
        self.gitlab_url = os.getenv("GITLAB_URL", "https://gitlab.com")
        self.api_base_url = f"{self.gitlab_url}/api/v4"
        os.makedirs(self.work_dir, exist_ok=True)

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
            ], capture_output=True, text=True, cwd=os.path.dirname(clone_dir))

            if result.returncode == 0:
                return clone_dir
            else:
                raise Exception(f"Failed to clone repository: {result.stderr}")
        except Exception as e:
            raise Exception(f"Failed to clone repository: {str(e)}")

    async def create_and_push_repo(self, token: str, repo_name: str, local_path: str, description: str) -> str:
        """Create a new repository and push the migrated code"""
        try:
            print(f"DEBUG: Starting GitLab repository creation process")
            headers = {"Authorization": f"Bearer {token}"}

            # Create new repository
            async with httpx.AsyncClient() as client:
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
                    print(f"DEBUG: GitLab repo created successfully: {new_repo['web_url']}")
                elif create_response.status_code == 400:
                    # Try with timestamp suffix if name exists
                    repo_name = f"{repo_name}-{int(__import__('time').time())}"
                    print(f"DEBUG: Retrying with name: {repo_name}")

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
                        print(f"DEBUG: GitLab repo created on retry: {new_repo['web_url']}")
                    else:
                        raise Exception(f"Repository creation failed: {create_response.status_code} - {create_response.text}")
                else:
                    raise Exception(f"Repository creation failed: {create_response.status_code} - {create_response.text}")

            # Initialize git in local path and push
            try:
                print(f"DEBUG: Initializing git repo in {local_path}")
                repo = git.Repo(local_path)
                print("DEBUG: Git repo initialized")
            except git.InvalidGitRepositoryError:
                print("DEBUG: Local path not a git repo, initializing...")
                repo = git.Repo.init(local_path)
                print("DEBUG: Git repo initialized from scratch")

            # Remove old remote if exists
            if "origin" in [remote.name for remote in repo.remotes]:
                print("DEBUG: Removing old origin remote")
                repo.delete_remote("origin")

            # Add new remote with token
            auth_url = new_repo["http_url_to_repo"].replace("https://", f"https://oauth2:{token}@")
            print(f"DEBUG: Adding remote origin: {auth_url[:50]}...")
            origin = repo.create_remote("origin", auth_url)

            # Check git status before staging
            print("DEBUG: Checking git status...")
            status = repo.git.status(porcelain=True)
            print(f"DEBUG: Git status: {status}")

            if not status.strip():
                print("DEBUG: No changes to commit - creating initial commit")
                # Create a .gitkeep file if directory is empty
                gitkeep_path = os.path.join(local_path, ".gitkeep")
                with open(gitkeep_path, 'w') as f:
                    f.write("# Migration placeholder\n")
                repo.git.add(A=True)

            # Stage and commit all changes
            print("DEBUG: Staging changes...")
            repo.git.add(A=True)

            # Check if there are staged changes
            staged = repo.git.diff("--cached", "--name-only")
            print(f"DEBUG: Staged files: {staged}")

            if staged.strip():
                try:
                    print("DEBUG: Committing changes...")
                    commit_msg = "Java migration completed - upgraded Java version, dependencies, and code quality"
                    repo.index.commit(commit_msg)
                    print(f"DEBUG: Commit successful: {commit_msg}")

                    # Show commit details
                    commit = repo.head.commit
                    print(f"DEBUG: Commit hash: {commit.hexsha}")
                    print(f"DEBUG: Files changed: {len(commit.stats.files)}")
                    print(f"DEBUG: Commit stats: {commit.stats.total}")

                except git.GitCommandError as e:
                    print(f"DEBUG: Commit failed: {str(e)}")
                    raise Exception(f"Git commit failed: {str(e)}")
            else:
                print("DEBUG: No staged changes to commit")
                # Still create an empty commit to establish the repo
                try:
                    repo.index.commit("Migration setup - no source changes detected")
                    print("DEBUG: Empty commit created")
                except git.GitCommandError:
                    print("DEBUG: Could not create empty commit")

            # Push to new repo - try main first, then master
            try:
                print("DEBUG: Checking current branch...")
                current_branch = repo.active_branch.name if repo.heads else None
                print(f"DEBUG: Current branch: {current_branch}")

                if not repo.heads:
                    print("DEBUG: No branches exist, creating main...")
                    repo.git.checkout('-b', 'main')
                    current_branch = 'main'
                    print("DEBUG: Created main branch")
                else:
                    current_branch = repo.active_branch.name

                print(f"DEBUG: Pushing to {current_branch} branch...")
                push_result = origin.push(refspec=f"HEAD:{current_branch}", set_upstream=True, force=True)
                print(f"DEBUG: Push to {current_branch} successful")

            except git.GitCommandError as e:
                print(f"DEBUG: Push to {current_branch} failed: {str(e)}")

                # Try alternative branch names
                for alt_branch in ['main', 'master']:
                    if alt_branch != current_branch:
                        try:
                            print(f"DEBUG: Retrying push to {alt_branch}...")
                            push_result = origin.push(refspec=f"HEAD:{alt_branch}", force=True)
                            print(f"DEBUG: Push to {alt_branch} successful")
                            break
                        except git.GitCommandError as alt_error:
                            print(f"DEBUG: Push to {alt_branch} also failed: {str(alt_error)}")
                            continue
                else:
                    raise Exception(f"Failed to push to repository on any branch: {str(e)}")

            print(f"DEBUG: GitLab migration completed successfully: {new_repo['web_url']}")
            return new_repo["web_url"]

        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"DEBUG: GitLab error: {error_msg}")
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")

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

    def _detect_java_version_from_pom(self, pom_content: str) -> str:
        """Detect Java version from pom.xml"""
        import re

        # Check for maven.compiler.source
        match = re.search(r'<maven\.compiler\.source>(\d+)</maven\.compiler\.source>', pom_content)
        if match:
            return match.group(1)

        # Check for java.version property
        match = re.search(r'<java\.version>(\d+)</java\.version>', pom_content)
        if match:
            return match.group(1)

        # Check for source in compiler plugin
        match = re.search(r'<source>(\d+\.?\d*)</source>', pom_content)
        if match:
            version = match.group(1)
            return version.replace("1.", "") if version.startswith("1.") else version

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