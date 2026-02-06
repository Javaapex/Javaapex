def get_github_client(token: str, repo_url: str = None):
    """Return a Github client for public or enterprise GitHub."""
    from github import Github
    import re
    if repo_url and "github.com" in repo_url and not "github." in repo_url.replace("github.com", ""):
        # Public GitHub
        return Github(token)
    elif repo_url:
        # Enterprise (extract base domain)
        m = re.match(r"https?://([^/]+)/", repo_url)
        if m:
            base_url = f"https://{m.group(1)}/api/v3"
            return Github(base_url=base_url, login_or_token=token)
        else:
            raise Exception("Invalid GitHub Enterprise URL")
    else:
        return Github(token)
"""
Git Service - Handles GitHub and GitLab API interactions
"""
import os
import tempfile
import shutil
import time
from typing import List, Dict, Any, Optional
from github import Github, GithubException, RateLimitExceededException
import git
import httpx

# Simple in-memory cache for rate limit handling
_cache = {}
_cache_ttl = 300  # 5 minutes cache TTL


def get_cached(key: str) -> Optional[Any]:
    """Get cached value if not expired"""
    if key in _cache:
        value, timestamp = _cache[key]
        if time.time() - timestamp < _cache_ttl:
            return value
        del _cache[key]
    return None


def set_cached(key: str, value: Any):
    """Set cached value with current timestamp"""
    _cache[key] = (value, time.time())


class GitHubService:
    def __init__(self):
        self.work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
        os.makedirs(self.work_dir, exist_ok=True)
    
    async def list_repositories(self, token: str, repo_url: str = None) -> List[Dict[str, Any]]:
        """List all repositories accessible with the token"""
        try:
            if not token or len(token) < 10:
                raise Exception("Invalid GitHub token format")
            
            g = get_github_client(token, repo_url)
            user = g.get_user()
            
            # Test authentication by accessing login
            _ = user.login
            
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
    
    async def analyze_repository(self, token: str, owner: str, repo: str, repo_url: str = None, force_refresh: bool = False) -> Dict[str, Any]:
        """Analyze a repository to detect Java version, build tool, and structure"""
        cache_key = f"analysis:{owner}/{repo}"

        # Check cache first to avoid rate limits (unless force refresh is requested)
        if not force_refresh:
            cached = get_cached(cache_key)
            if cached:
                print(f"[CACHE HIT] Using cached analysis for {owner}/{repo}")
                return cached
        else:
            print(f"[CACHE BYPASS] Forcing fresh analysis for {owner}/{repo}")
        
        try:
            # Allow public repo analysis without token
            if token and len(token.strip()) > 0:
                g = get_github_client(token.strip(), repo_url)
            else:
                g = get_github_client(None, repo_url)
            
            # Check rate limit before making requests
            rate_limit = g.get_rate_limit()
            if rate_limit.core.remaining < 10:
                reset_time = rate_limit.core.reset.timestamp() - time.time()
                print(f"[RATE LIMIT] Only {rate_limit.core.remaining} requests remaining. Reset in {reset_time:.0f}s")
                if rate_limit.core.remaining < 5:
                    raise Exception(f"GitHub API rate limit nearly exhausted. Resets in {reset_time/60:.1f} minutes. Please wait or use a different token.")
            
            repository = g.get_repo(f"{owner}/{repo}")
            
            analysis = {
                "name": repository.name,
                "full_name": repository.full_name,
                "default_branch": repository.default_branch,
                "language": repository.language,
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
            
            # Comprehensive repository analysis - read ALL files
            print(f"[ANALYSIS] Starting comprehensive analysis of {repository.full_name}")

            # Initialize analysis structure
            analysis["all_files"] = []
            analysis["business_logic_issues"] = []
            analysis["code_quality_metrics"] = {}
            analysis["duplications"] = []
            analysis["security_issues"] = []
            analysis["performance_issues"] = []

            # Enhanced Java project detection
            is_java_project = False
            java_files_found = []

            # Check for build files in root and subdirectories
            try:
                contents = repository.get_contents("")
                file_names = [c.name for c in contents]

                # Check for standard build files
                if "pom.xml" in file_names:
                    analysis["build_tool"] = "maven"
                    analysis["structure"]["has_pom_xml"] = True
                    # Parse pom.xml for Java version
                    pom_content = repository.get_contents("pom.xml").decoded_content.decode()
                    java_version_result = self._detect_java_version_from_pom(pom_content)
                    analysis["java_version_from_build"] = java_version_result["version"]
                    analysis["java_version_detected_from_build"] = java_version_result["detected"]
                    analysis["dependencies"] = self._parse_pom_dependencies(pom_content)
                    is_java_project = True

                elif "build.gradle" in file_names or "build.gradle.kts" in file_names:
                    analysis["build_tool"] = "gradle"
                    analysis["structure"]["has_build_gradle"] = True
                    gradle_content = repository.get_contents("build.gradle").decoded_content.decode()
                    java_version_result = self._detect_java_version_from_gradle(gradle_content)
                    analysis["java_version_from_build"] = java_version_result["version"]
                    analysis["java_version_detected_from_build"] = java_version_result["detected"]
                    is_java_project = True

                # Check for other build systems
                elif "build.xml" in file_names:  # Ant
                    analysis["build_tool"] = "ant"
                    is_java_project = True
                elif "Makefile" in file_names and self._is_java_makefile(repository):
                    analysis["build_tool"] = "make"
                    is_java_project = True

                # Check for src directory structure
                try:
                    repository.get_contents("src/main")
                    analysis["structure"]["has_src_main"] = True
                    is_java_project = True
                except:
                    pass

                try:
                    repository.get_contents("src/test")
                    analysis["structure"]["has_src_test"] = True
                    analysis["has_tests"] = True
                    is_java_project = True
                except:
                    pass

                # Check for common Java project directories
                java_dirs = ["src", "java", "main", "com", "org", "net"]
                for item in contents:
                    if item.type == "dir" and item.name in java_dirs:
                        # Recursively check for Java files
                        java_count = await self._count_java_files_recursive(repository, item.path)
                        if java_count > 0:
                            java_files_found.append(f"{item.path}: {java_count} files")
                            is_java_project = True

                # If no standard structure found, scan entire repo for Java files
                if not is_java_project:
                    java_files_found = await self._scan_repo_for_java_files(repository)
                    if java_files_found:
                        is_java_project = True
                        analysis["build_tool"] = "standalone"
                        # Detect Java version from source files
                        analysis["java_version"] = await self._detect_java_version_from_repo(repository)

                # COMPREHENSIVE FILE ANALYSIS - Full analysis of all files and folders
                print("[ANALYSIS] Starting comprehensive analysis of ALL files and folders...")
                try:
                    # Check remaining rate limit before heavy analysis
                    rate_limit = g.get_rate_limit()
                    remaining_requests = rate_limit.core.remaining
                    print(f"[RATE LIMIT] {remaining_requests} requests remaining before analysis")

                    # Always perform full comprehensive analysis (user requested complete analysis)
                    print(f"[ANALYSIS] Performing complete analysis of all files and folders...")
                    all_files_data = await self._analyze_all_repository_files(repository, analysis, remaining_requests)

                    analysis["all_files"] = all_files_data["files"]
                    analysis["business_issues"] = all_files_data["business_issues"]
                    analysis["code_quality_metrics"] = all_files_data["quality_metrics"]
                    analysis["duplications"] = all_files_data["duplications"]
                    analysis["security_issues"] = all_files_data["security_issues"]
                    analysis["performance_issues"] = all_files_data["performance_issues"]
                    analysis["analysis_limited"] = False
                    analysis["rate_limit_warning"] = f"Complete analysis finished ({remaining_requests} requests remaining)"

                    print(f"[ANALYSIS]  SUCCESS: Analyzed {len(analysis.get('all_files', []))} files total")
                    print(f"[ANALYSIS] Found {len(analysis.get('business_issues', []))} business logic issues")
                    print(f"[ANALYSIS] Found {len(analysis.get('security_issues', []))} security issues")
                    print(f"[ANALYSIS] Found {len(analysis.get('performance_issues', []))} performance issues")

                except Exception as e:
                    print(f"[ANALYSIS] L ERROR in comprehensive analysis: {str(e)}")
                    import traceback
                    traceback.print_exc()

                    # Don't fail completely - provide basic analysis
                    print("[ANALYSIS] Providing basic analysis due to error...")
                    analysis["all_files"] = []
                    analysis["business_logic_issues"] = []
                    analysis["code_quality_metrics"] = {
                        "total_files": len(file_names),
                        "code_files": len([f for f in file_names if f.endswith(('.java', '.py', '.js', '.ts'))]),
                        "text_files": len([f for f in file_names if f.endswith(('.md', '.txt', '.xml', '.json'))]),
                        "file_types": {},
                        "cyclomatic_complexity": {"average_complexity": 0, "max_complexity": 0, "complex_methods": 0, "total_methods": 0},
                        "maintainability_index": 0.0,
                        "technical_debt": {"estimated_hours": 0, "breakdown": {"business_logic": 0, "duplications": 0, "security": 0}, "severity": "low"}
                    }
                    analysis["duplications"] = []
                    analysis["security_issues"] = []
                    analysis["performance_issues"] = []
                    analysis["analysis_limited"] = True
                    analysis["error_message"] = f"Analysis failed: {str(e)}"

                print(f"[ANALYSIS] Completed analysis: {len(analysis['all_files'])} files analyzed")
                print(f"[ANALYSIS] Found {len(analysis['business_logic_issues'])} business logic issues")
                print(f"[ANALYSIS] Found {len(analysis['duplications'])} code duplications")
                print(f"[ANALYSIS] Found {len(analysis['security_issues'])} security issues")
                print(f"[ANALYSIS] Found {len(analysis['performance_issues'])} performance issues")
                
            except GithubException:
                pass
            
            # Cache the result
            set_cached(cache_key, analysis)
            print(f"[CACHE SET] Cached analysis for {owner}/{repo}")
            return analysis
            
        except RateLimitExceededException as e:
            reset_time = e.headers.get('X-RateLimit-Reset', 0)
            wait_time = int(reset_time) - int(time.time()) if reset_time else 3600
            raise Exception(f"GitHub API rate limit exceeded. Resets in {wait_time/60:.1f} minutes. Please wait or provide a different GitHub token.")
        except GithubException as e:
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            if 'rate limit' in error_msg.lower():
                raise Exception(f"GitHub API rate limit exceeded. Please wait a few minutes or provide a different GitHub token.")
            raise Exception(f"GitHub API error: {error_msg}")
    
    async def parse_repo_url(self, repo_url: str) -> tuple:
        """Parse GitHub URL to extract owner and repo name"""
        import re
        # Accept github.com, github.<enterprise>.com, and owner/repo
        patterns = [
            r'github(\.[^/]+)?\.com[:/]+([^/]+)/([^/\s]+)',  # https://github.com/owner/repo or github.enterprise.com/owner/repo
            r'^([^/]+)/([^/]+)$',  # owner/repo format
        ]
        for pattern in patterns:
            match = re.search(pattern, repo_url)
            if match:
                # For enterprise, owner/repo is always last two groups
                if 'github' in pattern:
                    return match.group(2), match.group(3).replace('.git', '')
                else:
                    return match.group(1), match.group(2).replace('.git', '')
        raise Exception("Invalid GitHub repository URL. Use format: owner/repo, https://github.com/owner/repo, or https://github.<enterprise>.com/owner/repo")
    
    async def get_repo_info(self, token: str, owner: str, repo: str) -> Dict[str, Any]:
        """Get repository information (works with or without token for public repos)"""
        try:
            if token:
                g = Github(token)
            else:
                g = Github()
            
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
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            raise Exception(f"GitHub API error: {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to get repository info: {str(e)}")
    
    async def list_repo_files(self, token: str, owner: str, repo: str, path: str = "", repo_url: str = None) -> List[Dict[str, Any]]:
        """List all files and directories in a repository"""
        cache_key = f"files:{owner}/{repo}:{path}"
        
        # Check cache first
        cached = get_cached(cache_key)
        if cached:
            print(f"[CACHE HIT] Using cached file list for {owner}/{repo}/{path}")
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
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            if 'rate limit' in error_msg.lower():
                raise Exception("GitHub API rate limit exceeded. Please wait a few minutes or provide a different GitHub token.")
            raise Exception(f"GitHub API error: {error_msg}")
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
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            raise Exception(f"GitHub API error: {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to get file content: {str(e)}")
    
    async def clone_repository(self, token: str, repo_url: str) -> str:
        """Clone a repository to local filesystem"""
        # Create unique directory for this clone
        import uuid
        clone_dir = os.path.join(self.work_dir, str(uuid.uuid4()))
        os.makedirs(clone_dir, exist_ok=True)

        # Add token to URL for authentication
        if "github.com" in repo_url:
            auth_url = repo_url.replace("https://", f"https://{token}@")
        else:
            auth_url = repo_url

        try:
            # Use subprocess for better control over git clone with config
            import subprocess

            # Clone with config to handle Windows Zone.Identifier files
            result = subprocess.run([
                'git', 'clone',
                '-c', 'core.protectNTFS=false',  # Allow files with colons in names
                auth_url, clone_dir
            ], capture_output=True, text=True, cwd=os.path.dirname(clone_dir))

            if result.returncode == 0:
                return clone_dir
            else:
                # If clone fails due to Zone.Identifier files, try recovery
                error_msg = result.stderr
                if "Zone.Identifier" in error_msg and "invalid path" in error_msg:
                    # Try clone with --no-checkout first
                    result2 = subprocess.run([
                        'git', 'clone', '--no-checkout', auth_url, clone_dir
                    ], capture_output=True, text=True, cwd=os.path.dirname(clone_dir))

                    if result2.returncode == 0:
                        # Configure the repo and try checkout
                        result3 = subprocess.run([
                            'git', 'config', 'core.protectNTFS', 'false'
                        ], capture_output=True, text=True, cwd=clone_dir)

                        # Try checkout
                        result4 = subprocess.run([
                            'git', 'checkout'
                        ], capture_output=True, text=True, cwd=clone_dir)

                        # Even if checkout fails, return the directory
                        # The migration service can work with partial checkouts
                        return clone_dir
                    else:
                        raise Exception(f"Failed to clone repository (recovery): {result2.stderr}")
                else:
                    raise Exception(f"Failed to clone repository: {error_msg}")
        except Exception as e:
            raise Exception(f"Failed to clone repository: {str(e)}")
    

    async def create_and_push_repo(self, token: str, repo_name: str, local_path: str, description: str) -> str:
        """Create a new repository and push the migrated code"""
        try:
            print(f"DEBUG: Starting repository creation process")
            print(f"DEBUG: Token provided: {'Yes' if token else 'No'} (length: {len(token) if token else 0})")
            print(f"DEBUG: Repo name: {repo_name}")
            print(f"DEBUG: Local path exists: {os.path.exists(local_path)}")

            if not token or len(token.strip()) == 0:
                raise Exception("GitHub token is required to create and push repositories. Please provide a valid Personal Access Token with repo or public_repo scope.")

            g = Github(token)
            user = g.get_user()
            print(f"DEBUG: Authenticated as user: {user.login}")

            # Check if repo already exists
            try:
                existing = user.get_repo(repo_name)
                print(f"DEBUG: Repo {repo_name} already exists, renaming...")
                # If exists, delete it first or use a different name
                repo_name = f"{repo_name}-{int(__import__('time').time())}"
                print(f"DEBUG: New repo name: {repo_name}")
            except GithubException as e:
                print(f"DEBUG: Repo {repo_name} does not exist, proceeding with creation")

            # Create new repository
            try:
                print(f"DEBUG: Creating repo {repo_name}...")
                new_repo = user.create_repo(
                    name=repo_name,
                    description=description,
                    private=False,
                    auto_init=False
                )
                print(f"DEBUG: Repo created successfully: {new_repo.html_url}")
            except GithubException as e:
                error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
                print(f"DEBUG: Repo creation failed: {error_msg}")
                if 'name already exists' in error_msg.lower():
                    # Try with timestamp suffix
                    repo_name = f"{repo_name}-{int(__import__('time').time())}"
                    print(f"DEBUG: Retrying with name: {repo_name}")
                    new_repo = user.create_repo(
                        name=repo_name,
                        description=description,
                        private=False,
                        auto_init=False
                    )
                    print(f"DEBUG: Repo created on retry: {new_repo.html_url}")
                else:
                    raise Exception(f"Repository creation failed: {error_msg}")

            # Initialize git in local path and push
            try:
                print(f"DEBUG: Initializing git repo in {local_path}")
                repo = git.Repo(local_path)
                print("DEBUG: Git repo initialized")
            except git.InvalidGitRepositoryError:
                # Initialize new repo if not already a git repo
                print("DEBUG: Local path not a git repo, initializing...")
                repo = git.Repo.init(local_path)
                print("DEBUG: Git repo initialized from scratch")

            # Remove old remote if exists
            if "origin" in [remote.name for remote in repo.remotes]:
                print("DEBUG: Removing old origin remote")
                repo.delete_remote("origin")

            # Add new remote with token
            auth_url = new_repo.clone_url.replace("https://", f"https://{token}@")
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
                    print(f"DEBUG: Git status: {repo.git.status()}")
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
                print(f"DEBUG: Push result: {push_result}")

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
                    # All push attempts failed
                    raise Exception(f"Failed to push to repository on any branch: {str(e)}")

            print(f"DEBUG: Migration completed successfully: {new_repo.html_url}")
            return new_repo.html_url

        except GithubException as e:
            error_msg = e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)
            print(f"DEBUG: GitHub API error: {error_msg}")
            raise Exception(f"GitHub API error: {error_msg}")
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"DEBUG: Unexpected error: {error_msg}")
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")

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
    
    def _detect_java_version_from_pom(self, pom_content: str) -> dict:
        """Detect Java version from pom.xml"""
        import re

        # Check for maven.compiler.source
        match = re.search(r'<maven\.compiler\.source>(\d+)</maven\.compiler\.source>', pom_content)
        if match:
            return {"version": match.group(1), "detected": True}

        # Check for java.version property
        match = re.search(r'<java\.version>(\d+)</java\.version>', pom_content)
        if match:
            return {"version": match.group(1), "detected": True}

        # Check for source in compiler plugin
        match = re.search(r'<source>(\d+\.?\d*)</source>', pom_content)
        if match:
            version = match.group(1)
            final_version = version.replace("1.", "") if version.startswith("1.") else version
            return {"version": final_version, "detected": True}

        # No Java version specified in build file
        return {"version": "not_specified", "detected": False}
    
    def _detect_java_version_from_gradle(self, gradle_content: str) -> dict:
        """Detect Java version from build.gradle"""
        import re

        # Check for sourceCompatibility
        match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+)['\"]?", gradle_content)
        if match:
            return {"version": match.group(1), "detected": True}

        # Check for JavaVersion enum
        match = re.search(r"JavaVersion\.VERSION_(\d+)", gradle_content)
        if match:
            return {"version": match.group(1), "detected": True}

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

    async def _count_java_files_recursive(self, repository, path: str, max_depth: int = 3) -> int:
        """Recursively count Java files in a directory path"""
        try:
            contents = repository.get_contents(path)
            java_count = 0

            for item in contents:
                if item.type == "file" and item.name.endswith('.java'):
                    java_count += 1
                elif item.type == "dir" and max_depth > 0:
                    # Recursively check subdirectories (with depth limit to avoid rate limits)
                    java_count += await self._count_java_files_recursive(repository, item.path, max_depth - 1)

            return java_count
        except:
            return 0

    async def _scan_repo_for_java_files(self, repository) -> List[str]:
        """Scan entire repository for Java files (limited to avoid rate limits)"""
        java_files = []
        try:
            # Get root contents
            contents = repository.get_contents("")

            # Check common Java directories first
            java_dirs = ["src", "java", "main", "com", "org", "net", "app", "core"]

            for item in contents:
                if item.type == "dir":
                    # Check if this is a known Java directory
                    if item.name in java_dirs or item.name.endswith('.java'):
                        java_count = await self._count_java_files_recursive(repository, item.path, 2)
                        if java_count > 0:
                            java_files.append(f"{item.path}: {java_count} Java files")
                    # Also check for Java files directly in root-level directories
                    elif not item.name.startswith('.') and item.name not in ['node_modules', 'target', 'build', '.git']:
                        try:
                            sub_contents = repository.get_contents(item.path)
                            java_in_dir = sum(1 for sub_item in sub_contents if sub_item.type == "file" and sub_item.name.endswith('.java'))
                            if java_in_dir > 0:
                                java_files.append(f"{item.path}: {java_in_dir} Java files")
                        except:
                            pass

            # Check for Java files in root directory
            root_java = [item.name for item in contents if item.type == "file" and item.name.endswith('.java')]
            if root_java:
                java_files.append(f"root: {len(root_java)} Java files")

            return java_files
        except:
            return java_files

    async def _detect_java_version_from_repo(self, repository) -> str:
        """Detect Java version by analyzing source files using automation packages (javalang, pylint, etc.)"""
        try:
            # Get a sample of Java files to analyze
            java_files = await self._scan_repo_for_java_files(repository)
            if not java_files:
                return "8"  # Default

            # Find actual Java files (not just counts)
            actual_files = []
            for java_info in java_files[:5]:  # Check first 5 directories for better sampling
                path = java_info.split(':')[0]
                if path == "root":
                    path = ""

                try:
                    if path:
                        contents = repository.get_contents(path)
                    else:
                        contents = repository.get_contents("")

                    for item in contents:
                        if item.type == "file" and item.name.endswith('.java'):
                            actual_files.append(item)
                            if len(actual_files) >= 10:  # Analyze more files for better detection
                                break
                    if len(actual_files) >= 10:
                        break
                except:
                    continue

            # Use javalang for AST-based Java version detection
            detected_features = await self._analyze_java_files_with_javalang(actual_files, repository)

            # Determine the minimum Java version required based on detected features
            # Check in reverse order (newest to oldest) to find the minimum required version

            print(f"[VERSION DETECTION] Detected features: {detected_features}")
            print(f"[VERSION DETECTION] Basic Java detected: {detected_features.get('basic_java', False)}")

            # Java 21+
            if (detected_features.get("virtual_threads", False) or
                detected_features.get("pattern_matching_instanceof", False) or
                detected_features.get("record_patterns", False)):
                print("[VERSION DETECTION] Detected Java 21+ features")
                return "21"

            # Java 17-20
            elif (detected_features.get("sealed_classes", False) or
                  detected_features.get("records", False)):
                print("[VERSION DETECTION] Detected Java 17+ features")
                return "17"

            # Java 14-16
            elif (detected_features.get("text_blocks", False) or
                  detected_features.get("switch_expressions", False) or
                  detected_features.get("pattern_matching_switch", False)):
                print("[VERSION DETECTION] Detected Java 14+ features")
                return "14"

            # Java 9-13
            elif (detected_features.get("modules", False) or
                  detected_features.get("var_keyword", False)):
                print("[VERSION DETECTION] Detected Java 9+ features")
                return "9"

            # Java 8
            elif (detected_features.get("lambdas", False) or
                  detected_features.get("streams", False) or
                  detected_features.get("default_methods", False)):
                print("[VERSION DETECTION] Detected Java 8+ features")
                return "8"

            # Java 7
            elif (detected_features.get("diamond_operator", False) or
                  detected_features.get("try_with_resources", False) or
                  detected_features.get("strings_in_switch", False)):
                print("[VERSION DETECTION] Detected Java 7+ features")
                return "7"

            # Java 6
            elif (detected_features.get("annotations", False) or
                  detected_features.get("generics", False)):
                print("[VERSION DETECTION] Detected Java 6+ features")
                return "6"

            # Java 5
            elif (detected_features.get("enums", False) or
                  detected_features.get("autoboxing", False) or
                  detected_features.get("enhanced_for", False)):
                print("[VERSION DETECTION] Detected Java 5+ features")
                return "5"

            # Java 1.4
            elif detected_features.get("assertions", False):
                print("[VERSION DETECTION] Detected Java 1.4+ features")
                return "4"

            # Java 1.3
            elif detected_features.get("dynamic_proxy", False):
                print("[VERSION DETECTION] Detected Java 1.3+ features")
                return "3"

            # Java 1.2
            elif detected_features.get("collections", False):
                print("[VERSION DETECTION] Detected Java 1.2+ features")
                return "2"

            # Java 1.1
            elif detected_features.get("inner_classes", False):
                print("[VERSION DETECTION] Detected Java 1.1+ features")
                return "1.1"

            # Java 1.0 - Any valid Java code that doesn't use advanced features
            if detected_features.get("basic_java", False):
                print("[VERSION DETECTION] No advanced features detected - returning Java 1.0")
                return "1.0"

            # Fallback - if we get here, something went wrong with feature detection
            print("[VERSION DETECTION] No features detected at all - defaulting to Java 8")
            return "8"

        except Exception as e:
            print(f"Error in Java version detection: {e}")
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
            print("javalang not available, falling back to regex analysis")
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
                    print(f"Java syntax error in {file_item.name}: {e}")
                    # Even with syntax errors, check for basic Java patterns with regex
                    detected_features["basic_java"] = True  # Assume it's Java if it has .java extension
                    await self._fallback_regex_for_file(content, detected_features)
                except Exception as e:
                    print(f"Error parsing {file_item.name} with javalang: {e}")
                    # Fall back to regex analysis for this file
                    detected_features["basic_java"] = True  # Assume it's Java if parsing fails
                    await self._fallback_regex_for_file(content, detected_features)

            except Exception as e:
                print(f"Error processing file {file_item.name}: {e}")
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
        print("Using regex fallback for Java version detection")

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
                print(f"Error in regex fallback for {file_item.name}: {e}")
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

            print(f"[ANALYSIS] Found {len(all_files)} total files to analyze")

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
            print(f"[ANALYSIS] Error in comprehensive file analysis: {e}")
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
            print(f"[ANALYSIS] Error getting files from {path}: {e}")

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
                print(f"[ANALYSIS] Error analyzing {file_info['path']}: {e}")
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
                print(f"[DUPLICATION] Error analyzing {file_info['path']}: {e}")

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
                print(f"[SECURITY] Error analyzing {file_info['path']}: {e}")

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
                print(f"[PERFORMANCE] Error analyzing {file_info['path']}: {e}")

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
                print(f"[COMPLEXITY] Error analyzing {file_info['path']}: {e}")

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
                    print(f"[MAINTAINABILITY] Error analyzing {file_info['path']}: {e}")

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