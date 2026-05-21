"""
Local filesystem analysis for clone-first repository discovery.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from services.repository_workspace_service import RepositoryPathError, RepositoryWorkspace

logger = logging.getLogger(__name__)


class LocalRepositoryAnalysisService:
    SKIP_DIRS = {
        ".git",
        ".gradle",
        ".idea",
        ".mvn",
        "build",
        "dist",
        "node_modules",
        "out",
        "target",
    }

    def __init__(self) -> None:
        self.max_java_files = int(os.getenv("REPO_ANALYSIS_MAX_JAVA_FILES", "2000"))
        self.max_endpoint_files = int(os.getenv("REPO_ANALYSIS_MAX_ENDPOINT_FILES", "300"))
        self.max_file_content_bytes = int(os.getenv("REPO_FILE_CONTENT_MAX_BYTES", "262144"))

    async def analyze_workspace(self, workspace: RepositoryWorkspace) -> Dict[str, Any]:
        return await asyncio.to_thread(self._analyze_workspace_sync, workspace)

    async def list_files(self, workspace: RepositoryWorkspace, path: str = "") -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_files_sync, workspace, path)

    async def read_file_content(self, workspace: RepositoryWorkspace, file_path: str) -> str:
        return await asyncio.to_thread(self._read_file_content_sync, workspace, file_path)

    def _analyze_workspace_sync(self, workspace: RepositoryWorkspace) -> Dict[str, Any]:
        root = Path(workspace.workspace_path)
        java_files = self._find_java_files(root)
        pom_files = self._find_named_files(root, {"pom.xml"})
        gradle_files = self._find_named_files(root, {"build.gradle", "build.gradle.kts"})

        structure = {
            "has_pom_xml": bool(pom_files),
            "has_build_gradle": bool(gradle_files),
            "has_src_main": self._has_directory(root, ("src", "main")),
            "has_src_test": self._has_directory(root, ("src", "test")),
        }

        build_tool = None
        java_version = None
        java_version_from_build = None
        java_version_detected_from_build = False
        dependencies: List[Dict[str, Any]] = []

        if pom_files:
            build_tool = "maven"
            java_version_from_build = self._detect_java_version_from_pom_files(pom_files)
            java_version_detected_from_build = java_version_from_build is not None
            dependencies = self._collect_maven_dependencies(pom_files)
        elif gradle_files:
            build_tool = "gradle"
            java_version_from_build = self._detect_java_version_from_gradle_files(gradle_files)
            java_version_detected_from_build = java_version_from_build is not None
            dependencies = self._collect_gradle_dependencies(gradle_files)
        elif java_files:
            build_tool = "standalone"

        if java_version_detected_from_build:
            java_version = java_version_from_build
        elif java_files:
            java_version = self._detect_java_version_from_source(java_files)
        else:
            java_version = None

        relative_java_files: List[str] = []
        for file_path in java_files[: self.max_java_files]:
            try:
                relative_java_files.append(self._relative_path(root, file_path))
            except RepositoryPathError:
                logger.warning("Skipping Java file outside workspace boundary during analysis: %s", file_path)
        api_endpoints = self._detect_api_endpoints(root, java_files)
        has_tests = structure["has_src_test"] or any(
            "/test/" in rel.lower() or rel.endswith("Test.java") or rel.endswith("Tests.java")
            for rel in relative_java_files
        )

        analysis: Dict[str, Any] = {
            "name": workspace.repo,
            "full_name": f"{workspace.owner}/{workspace.repo}",
            "default_branch": workspace.default_branch,
            "language": "Java" if java_files or build_tool in {"maven", "gradle", "standalone"} else None,
            "build_tool": build_tool,
            "java_version": java_version,
            "java_version_from_build": java_version_from_build,
            "java_version_detected_from_build": java_version_detected_from_build,
            "java_files": relative_java_files,
            "java_file_count": len(java_files),
            "java_files_truncated": len(java_files) > len(relative_java_files),
            "has_tests": has_tests,
            "dependencies": dependencies,
            "api_endpoints": api_endpoints,
            "structure": structure,
            "all_files": [],
            "business_issues": [],
            "business_logic_issues": [],
            "code_quality_metrics": {
                "java_file_count": len(java_files),
                "dependency_count": len(dependencies),
                "endpoint_count": len(api_endpoints),
            },
            "duplications": [],
            "security_issues": [],
            "performance_issues": [],
            "analysis_limited": False,
            "analysis_source": "clone_first",
            "detected_frameworks": self._detect_frameworks(dependencies),
        }
        return analysis

    def _list_files_sync(self, workspace: RepositoryWorkspace, path: str = "") -> List[Dict[str, Any]]:
        directory = self._resolve_repo_path(workspace, path)
        if not os.path.exists(directory):
            raise RepositoryPathError(f"Path not found: {path}")
        if not os.path.isdir(directory):
            raise RepositoryPathError(f"Path is not a directory: {path}")

        entries: List[Dict[str, Any]] = []
        for item in sorted(os.scandir(directory), key=lambda entry: (entry.is_file(), entry.name.lower())):
            if item.name == ".git":
                continue
            item_path = Path(item.path)
            try:
                relative_path = self._relative_path(Path(workspace.workspace_path), item_path)
            except RepositoryPathError:
                logger.warning("Skipping file-system entry outside workspace boundary: %s", item_path)
                continue
            entries.append(
                {
                    "name": item.name,
                    "path": relative_path,
                    "type": "dir" if item.is_dir() else "file",
                    "size": 0 if item.is_dir() else item.stat().st_size,
                    "url": self._build_browser_url(workspace, relative_path, item.is_dir()),
                }
            )
        return entries

    def _read_file_content_sync(self, workspace: RepositoryWorkspace, file_path: str) -> str:
        resolved = self._resolve_repo_path(workspace, file_path)
        if not os.path.exists(resolved):
            raise RepositoryPathError(f"File not found: {file_path}")
        if os.path.isdir(resolved):
            raise RepositoryPathError(f"Path is a directory, not a file: {file_path}")

        with open(resolved, "rb") as source_file:
            raw = source_file.read(self.max_file_content_bytes + 1)

        if b"\x00" in raw:
            raise RepositoryPathError("Binary file content is not supported.")

        truncated = len(raw) > self.max_file_content_bytes
        if truncated:
            raw = raw[: self.max_file_content_bytes]

        content = raw.decode("utf-8", errors="ignore")
        if truncated:
            content += "\n\n... [truncated by backend]"
        return content

    def _find_java_files(self, root: Path) -> List[Path]:
        java_files: List[Path] = []
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in self.SKIP_DIRS and not name.startswith(".")]
            for file_name in file_names:
                if file_name.endswith(".java"):
                    java_files.append(Path(current_root) / file_name)
        java_files.sort()
        return java_files

    def _find_named_files(self, root: Path, file_names: set[str]) -> List[Path]:
        matches: List[Path] = []
        for current_root, dir_names, files in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in self.SKIP_DIRS and not name.startswith(".")]
            for file_name in files:
                if file_name in file_names:
                    matches.append(Path(current_root) / file_name)
        matches.sort()
        return matches

    def _has_directory(self, root: Path, parts: tuple[str, ...]) -> bool:
        target = root.joinpath(*parts)
        if target.is_dir():
            return True
        for current_root, dir_names, _ in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in self.SKIP_DIRS and not name.startswith(".")]
            current_path = Path(current_root)
            if current_path.parts[-len(parts) :] == parts:
                return True
        return False

    def _collect_maven_dependencies(self, pom_files: Iterable[Path]) -> List[Dict[str, Any]]:
        dependencies: List[Dict[str, Any]] = []
        seen = set()
        pattern = re.compile(
            r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>\s*(?:<version>([^<]+)</version>)?",
            re.DOTALL,
        )

        for pom_file in pom_files:
            try:
                content = pom_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for match in pattern.finditer(content):
                dependency = (
                    match.group(1).strip(),
                    match.group(2).strip(),
                    (match.group(3) or "inherited").strip(),
                )
                if dependency in seen:
                    continue
                seen.add(dependency)
                dependencies.append(
                    {
                        "group_id": dependency[0],
                        "artifact_id": dependency[1],
                        "current_version": dependency[2],
                        "new_version": None,
                        "status": "analyzing",
                    }
                )

        return dependencies

    def _collect_gradle_dependencies(self, gradle_files: Iterable[Path]) -> List[Dict[str, Any]]:
        dependencies: List[Dict[str, Any]] = []
        seen = set()
        scope_pattern = r"(?:api|implementation|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|annotationProcessor|kapt|classpath)"
        dependency_pattern = re.compile(
            rf"(?P<scope>{scope_pattern})\s*\(?\s*['\"](?P<group>[^:'\"\s]+):(?P<artifact>[^:'\"\s]+)(?::(?P<version>[^'\"\n\r)]+))?['\"]\s*\)?"
        )

        for gradle_file in gradle_files:
            try:
                content = gradle_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for match in dependency_pattern.finditer(content):
                dependency = (
                    match.group("group").strip(),
                    match.group("artifact").strip(),
                    (match.group("version") or "unspecified").strip(),
                )
                if dependency in seen:
                    continue
                seen.add(dependency)
                dependencies.append(
                    {
                        "group_id": dependency[0],
                        "artifact_id": dependency[1],
                        "current_version": dependency[2],
                        "new_version": None,
                        "status": f"analyzing ({match.group('scope')})",
                    }
                )

        return dependencies

    def _detect_java_version_from_pom_files(self, pom_files: Iterable[Path]) -> str | None:
        for pom_file in pom_files:
            try:
                content = pom_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            version = self._detect_java_version_from_pom(content)
            if version:
                return version
        return None

    def _detect_java_version_from_gradle_files(self, gradle_files: Iterable[Path]) -> str | None:
        for gradle_file in gradle_files:
            try:
                content = gradle_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            version = self._detect_java_version_from_gradle(content)
            if version:
                return version
        return None

    def _detect_java_version_from_pom(self, pom_content: str) -> str | None:
        def normalize(value: str) -> str:
            value = value.strip()
            return value.replace("1.", "", 1) if value.startswith("1.") else value

        patterns = [
            r"<maven\.compiler\.source>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.source>",
            r"<maven\.compiler\.release>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.release>",
            r"<java\.version>\s*(\d+(?:\.\d+)?)\s*</java\.version>",
            r"<javaVersion>\s*(\d+(?:\.\d+)?)\s*</javaVersion>",
            r"<source>\s*(\d+(?:\.\d+)?)\s*</source>",
        ]
        for pattern in patterns:
            match = re.search(pattern, pom_content)
            if match:
                return normalize(match.group(1))

        property_reference_patterns = [
            r"<maven\.compiler\.source>\s*\$\{([^}]+)\}\s*</maven\.compiler\.source>",
            r"<maven\.compiler\.target>\s*\$\{([^}]+)\}\s*</maven\.compiler\.target>",
            r"<maven\.compiler\.release>\s*\$\{([^}]+)\}\s*</maven\.compiler\.release>",
        ]
        for pattern in property_reference_patterns:
            match = re.search(pattern, pom_content)
            if not match:
                continue
            property_name = match.group(1)
            property_match = re.search(
                rf"<{re.escape(property_name)}>\s*(\d+(?:\.\d+)?)\s*</{re.escape(property_name)}>",
                pom_content,
            )
            if property_match:
                return normalize(property_match.group(1))

        return None

    def _detect_java_version_from_gradle(self, gradle_content: str) -> str | None:
        source_match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+(?:\.\d+)?)['\"]?", gradle_content)
        if source_match:
            version = source_match.group(1)
            return version.replace("1.", "", 1) if version.startswith("1.") else version

        enum_match = re.search(r"JavaVersion\.VERSION_(\d+)(?:_(\d+))?", gradle_content)
        if enum_match:
            major = enum_match.group(1)
            minor = enum_match.group(2)
            if major == "1" and minor:
                return minor
            return major

        return None

    def _detect_java_version_from_source(self, java_files: List[Path]) -> str:
        detected_features = {
            "sealed": False,
            "records": False,
            "text_blocks": False,
            "switch_expr": False,
            "var": False,
            "modules": False,
            "lambdas": False,
            "streams": False,
            "diamond": False,
            "try_resources": False,
        }

        for java_file in java_files[:20]:
            try:
                content = java_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if re.search(r"\bsealed\s+(class|interface)", content) or re.search(r"\bpermits\s+\w+", content):
                detected_features["sealed"] = True
            if re.search(r"\brecord\s+\w+\s*\(", content):
                detected_features["records"] = True
            if '"""' in content:
                detected_features["text_blocks"] = True
            if re.search(r"switch\s*\([^)]+\)\s*\{[^}]*->", content):
                detected_features["switch_expr"] = True
            if re.search(r"\bvar\s+\w+\s*=", content):
                detected_features["var"] = True
            if java_file.name == "module-info.java" or re.search(r"\bmodule\s+\w+", content):
                detected_features["modules"] = True
            if "->" in content and not detected_features["switch_expr"]:
                detected_features["lambdas"] = True
            if ".stream()" in content or ".parallelStream()" in content:
                detected_features["streams"] = True
            if "<>" in content:
                detected_features["diamond"] = True
            if re.search(r"try\s*\([^)]+\)\s*\{", content):
                detected_features["try_resources"] = True

        if detected_features["sealed"]:
            return "17"
        if detected_features["records"]:
            return "16"
        if detected_features["text_blocks"]:
            return "15"
        if detected_features["switch_expr"]:
            return "14"
        if detected_features["var"]:
            return "10"
        if detected_features["modules"]:
            return "9"
        if detected_features["lambdas"] or detected_features["streams"]:
            return "8"
        if detected_features["diamond"] or detected_features["try_resources"]:
            return "7"
        return "8"

    def _detect_api_endpoints(self, root: Path, java_files: List[Path]) -> List[Dict[str, str]]:
        prioritized: List[Path] = []
        fallback: List[Path] = []

        for java_file in java_files:
            try:
                normalized = self._relative_path(root, java_file).lower()
            except RepositoryPathError:
                logger.warning("Skipping endpoint scan for Java file outside workspace boundary: %s", java_file)
                continue
            if any(token in normalized for token in ("controller", "resource", "endpoint", "/api/")):
                prioritized.append(java_file)
            else:
                fallback.append(java_file)

        endpoints: List[Dict[str, str]] = []
        seen = set()
        for java_file in (prioritized + fallback)[: self.max_endpoint_files]:
            try:
                content = java_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for endpoint in self._extract_endpoints_from_java_content(content, java_file.name):
                key = (endpoint["method"], endpoint["path"], endpoint["file"])
                if key in seen:
                    continue
                seen.add(key)
                endpoints.append(endpoint)

        return endpoints

    def _extract_endpoints_from_java_content(self, content: str, file_name: str) -> List[Dict[str, str]]:
        endpoints: List[Dict[str, str]] = []
        class_base_path = ""

        class_request_match = re.search(
            r"@RequestMapping\s*\((.*?)\)\s*(?:public\s+)?(?:class|interface|record)\s+\w+",
            content,
            re.DOTALL,
        )
        if class_request_match:
            class_base_path = self._extract_mapping_path(class_request_match.group(1))

        if not class_base_path:
            class_path_match = re.search(
                r"@Path\s*\(\s*[\"']([^\"']*)[\"']\s*\)\s*(?:public\s+)?(?:class|interface|record)\s+\w+",
                content,
                re.DOTALL,
            )
            if class_path_match:
                class_base_path = class_path_match.group(1)

        spring_patterns = [
            ("GET", r"@GetMapping\s*(?:\((.*?)\))?"),
            ("POST", r"@PostMapping\s*(?:\((.*?)\))?"),
            ("PUT", r"@PutMapping\s*(?:\((.*?)\))?"),
            ("DELETE", r"@DeleteMapping\s*(?:\((.*?)\))?"),
            ("PATCH", r"@PatchMapping\s*(?:\((.*?)\))?"),
        ]

        for method, pattern in spring_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                sub_path = self._extract_mapping_path(match.group(1) or "")
                endpoints.append(
                    {
                        "path": self._join_endpoint_paths(class_base_path, sub_path),
                        "method": method,
                        "file": file_name,
                    }
                )

        for match in re.finditer(r"@RequestMapping\s*\((.*?)\)", content, re.DOTALL):
            annotation_args = match.group(1)
            method_match = re.search(r"RequestMethod\.([A-Z]+)", annotation_args)
            if not method_match:
                continue
            endpoints.append(
                {
                    "path": self._join_endpoint_paths(class_base_path, self._extract_mapping_path(annotation_args)),
                    "method": method_match.group(1),
                    "file": file_name,
                }
            )

        for match in re.finditer(
            r"@(GET|POST|PUT|DELETE|PATCH)\b(?:(?!@(GET|POST|PUT|DELETE|PATCH)\b).)*?(?:@Path\s*\(\s*[\"']([^\"']*)[\"']\s*\))?",
            content,
            re.DOTALL,
        ):
            endpoints.append(
                {
                    "path": self._join_endpoint_paths(class_base_path, match.group(2) or ""),
                    "method": match.group(1),
                    "file": file_name,
                }
            )

        return endpoints

    def _extract_mapping_path(self, annotation_args: str) -> str:
        if not annotation_args:
            return ""

        named_match = re.search(r"(?:value|path)\s*=\s*\{?\s*[\"']([^\"']*)[\"']", annotation_args)
        if named_match:
            return named_match.group(1)

        direct_match = re.search(r"^\s*[\"']([^\"']*)[\"']", annotation_args.strip())
        if direct_match:
            return direct_match.group(1)

        return ""

    def _join_endpoint_paths(self, base_path: str, sub_path: str) -> str:
        parts = [part.strip("/") for part in [base_path, sub_path] if part and part.strip("/")]
        if not parts:
            return "/"
        return "/" + "/".join(parts)

    def _detect_frameworks(self, dependencies: List[Dict[str, Any]]) -> List[str]:
        frameworks = set()
        for dependency in dependencies:
            artifact_id = (dependency.get("artifact_id") or "").lower()
            group_id = (dependency.get("group_id") or "").lower()
            joined = f"{group_id}:{artifact_id}"
            if "spring" in joined:
                frameworks.add("spring")
            if "hibernate" in joined or "jpa" in joined:
                frameworks.add("hibernate")
            if "junit" in joined:
                frameworks.add("junit")
            if "slf4j" in joined or "log4j" in joined:
                frameworks.add("logging")
        return sorted(frameworks)

    def _resolve_repo_path(self, workspace: RepositoryWorkspace, relative_path: str) -> str:
        base_path = Path(workspace.workspace_path).resolve()
        candidate = (base_path / relative_path).resolve()
        if not os.path.exists(candidate):
            candidate = self._resolve_case_insensitive_repo_path(base_path, relative_path) or candidate
        base_canonical = self._canonicalize_path(base_path)
        candidate_canonical = self._canonicalize_path(candidate)
        if not self._is_within_root(base_canonical, candidate_canonical):
            raise RepositoryPathError("Invalid repository path.")
        return candidate_canonical

    def _resolve_case_insensitive_repo_path(self, base_path: Path, relative_path: str) -> Path | None:
        normalized_parts = [part for part in re.split(r"[\\/]+", relative_path or "") if part and part != "."]
        current = base_path
        for part in normalized_parts:
            if part == "..":
                return None
            try:
                entries = {entry.name.lower(): entry.name for entry in os.scandir(current)}
            except OSError:
                return None
            matched_name = entries.get(part.lower())
            if not matched_name:
                return None
            current = current / matched_name
        return current

    def _relative_path(self, root: Path, file_path: Path) -> str:
        root_canonical = self._canonicalize_path(root)
        file_canonical = self._canonicalize_path(file_path)
        if not self._is_within_root(root_canonical, file_canonical):
            raise RepositoryPathError(f"Path '{file_path}' is outside the repository workspace.")
        try:
            return os.path.relpath(file_canonical, root_canonical).replace("\\", "/")
        except ValueError as exc:
            raise RepositoryPathError(f"Path '{file_path}' is outside the repository workspace.") from exc

    def _canonicalize_path(self, path: Path | str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(str(path))))

    def _is_within_root(self, root_canonical: str, candidate_canonical: str) -> bool:
        try:
            return os.path.commonpath([root_canonical, candidate_canonical]) == root_canonical
        except ValueError:
            return False

    def _build_browser_url(self, workspace: RepositoryWorkspace, relative_path: str, is_dir: bool) -> str:
        if workspace.repo_url.startswith("local://"):
            return relative_path
        repo_url = workspace.normalized_repo_url.removesuffix(".git")
        route = "tree" if is_dir else "blob"
        return f"{repo_url}/{route}/{workspace.default_branch}/{relative_path}"
