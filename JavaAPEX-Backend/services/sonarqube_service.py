"""
SonarQube / SonarCloud service.

Production-oriented behavior:
- validates configuration explicitly
- supports Maven and Gradle builds
- compiles Java bytecode before scanning
- runs SonarScanner CLI with explicit parameters
- polls compute-engine task completion before reading results
- returns real/unavailable/simulated states instead of silently masking failures
"""
import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


logger = logging.getLogger(__name__)


class SonarQubeError(Exception):
    """Base class for Sonar-related failures."""


class SonarQubeConfigurationError(SonarQubeError):
    """Raised when Sonar cannot run due to missing configuration."""


class SonarQubeExecutionError(SonarQubeError):
    """Raised when scanner execution or result collection fails."""


class SonarQubeService:
    def __init__(self):
        self.sonar_url = (
            os.getenv("SONAR_HOST_URL")
            or os.getenv("SONARQUBE_URL")
            or "https://sonarcloud.io"
        ).strip().rstrip("/")
        self.sonar_token = (
            os.getenv("SONAR_TOKEN")
            or os.getenv("SONARQUBE_TOKEN")
            or ""
        ).strip()
        self.sonar_organization = (
            os.getenv("SONAR_ORGANIZATION")
            or os.getenv("SONARCLOUD_ORGANIZATION")
            or ""
        ).strip()
        self.java_home = (os.getenv("JAVA_HOME") or "").strip()
        self.sonar_scanner_path = (os.getenv("SONAR_SCANNER_PATH") or "").strip()
        self.project_key_prefix = (os.getenv("SONAR_PROJECT_KEY_PREFIX") or "").strip()
        self.allow_simulated_fallback = (
            os.getenv("SONAR_ALLOW_SIMULATED_FALLBACK", "false").strip().lower()
            in {"1", "true", "yes"}
        )

    def get_capabilities(self) -> Dict[str, Any]:
        scanner_path = self._resolve_scanner_path()
        scanner_installed = bool(scanner_path)
        token_configured = bool(self.sonar_token)
        is_sonarcloud = self._is_sonarcloud()
        organization_configured = bool(self.sonar_organization) if is_sonarcloud else True
        ready = scanner_installed and token_configured and organization_configured

        if ready:
            message = "Sonar is configured and ready."
        elif not scanner_installed:
            message = "SonarScanner CLI is not installed on the server."
        elif not token_configured:
            message = "SONAR_TOKEN / SONARQUBE_TOKEN is not configured."
        else:
            message = "SONAR_ORGANIZATION is required for SonarCloud analyses."

        return {
            "ready": ready,
            "scanner_installed": scanner_installed,
            "scanner_path": scanner_path,
            "token_configured": token_configured,
            "host_url": self.sonar_url,
            "provider": "sonarcloud" if is_sonarcloud else "sonarqube",
            "organization": self.sonar_organization or None,
            "organization_configured": organization_configured,
            "allow_simulated_fallback": self.allow_simulated_fallback,
            "message": message,
        }

    async def analyze_project(
        self,
        project_path: str,
        project_key: Optional[str] = None,
        source_reference: Optional[str] = None,
        build_tool: Optional[str] = None,
        allow_simulated: Optional[bool] = None,
    ) -> Dict[str, Any]:
        fallback_allowed = self.allow_simulated_fallback if allow_simulated is None else allow_simulated
        logger.info("Starting Sonar analysis on: %s", project_path)

        try:
            self._ensure_ready()
            build_tool_name = build_tool or self._detect_build_tool(project_path)
            project_key_value = project_key or self._derive_project_key(source_reference, project_path)
            project_name = self._derive_project_name(source_reference, project_path)

            compile_result = await self._compile_project(project_path, build_tool_name)
            report_task_path = await self._run_scanner(
                project_path=project_path,
                build_tool=build_tool_name,
                project_key=project_key_value,
                project_name=project_name,
            )
            task_metadata = self._load_report_task(report_task_path)
            ce_task = await self._await_compute_engine(task_metadata)
            result = await self._fetch_analysis_results(
                project_key=project_key_value,
                task_metadata=task_metadata,
            )
            result.update(
                {
                    "scan_mode": "real",
                    "real_scan": True,
                    "simulated": False,
                    "ready": True,
                    "error_message": None,
                    "provider": "sonarcloud" if self._is_sonarcloud() else "sonarqube",
                    "organization": self.sonar_organization or None,
                    "project_key": project_key_value,
                    "project_name": project_name,
                    "build_tool": build_tool_name,
                    "ce_task_id": ce_task.get("id"),
                    "ce_task_status": ce_task.get("status"),
                    "compile_stdout": self._truncate_output(compile_result.get("stdout", "")),
                    "compile_stderr": self._truncate_output(compile_result.get("stderr", "")),
                }
            )
            return result
        except SonarQubeError as exc:
            logger.exception("Sonar analysis failed for %s", project_path)
            if fallback_allowed:
                simulated = self._get_simulated_results(project_path)
                simulated["error_message"] = str(exc)
                simulated["ready"] = False
                return simulated
            raise

    def _ensure_ready(self) -> None:
        capabilities = self.get_capabilities()
        if not capabilities["scanner_installed"]:
            raise SonarQubeConfigurationError(
                "SonarScanner CLI is not installed on the server. Install it to enable Sonar analysis."
            )
        if not capabilities["token_configured"]:
            raise SonarQubeConfigurationError(
                "SONAR_TOKEN / SONARQUBE_TOKEN is not configured on the server."
            )
        if self._is_sonarcloud() and not capabilities["organization_configured"]:
            raise SonarQubeConfigurationError(
                "SONAR_ORGANIZATION is required for SonarCloud analysis."
            )

    def _is_sonarcloud(self) -> bool:
        return "sonarcloud.io" in self.sonar_url.lower()

    def _detect_build_tool(self, project_path: str) -> str:
        root = Path(project_path)
        if (root / "pom.xml").exists():
            return "maven"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return "gradle"
        raise SonarQubeConfigurationError(
            "Sonar analysis currently supports Maven and Gradle Java projects only."
        )

    def _derive_project_name(self, source_reference: Optional[str], project_path: str) -> str:
        if source_reference and not source_reference.startswith("local://"):
            normalized = source_reference.rstrip("/").split("/")[-1]
            return re.sub(r"\.git$", "", normalized, flags=re.IGNORECASE) or Path(project_path).name
        return Path(project_path).name or "project"

    def _derive_project_key(self, source_reference: Optional[str], project_path: str) -> str:
        base_parts: List[str] = []
        if source_reference and not source_reference.startswith("local://"):
            normalized = source_reference.strip().rstrip("/")
            normalized = re.sub(r"\.git$", "", normalized, flags=re.IGNORECASE)
            match = re.match(r"^https?://[^/]+/(.+)$", normalized, re.IGNORECASE)
            if match:
                base_parts.extend([part for part in match.group(1).split("/") if part])
            else:
                base_parts.extend([part for part in normalized.split("/") if part])
        else:
            base_parts.append(Path(project_path).name or "project")

        base_key = "_".join(base_parts[-2:]) if len(base_parts) >= 2 else "_".join(base_parts)
        prefix = self.project_key_prefix or (self.sonar_organization if self._is_sonarcloud() else "java_apex")
        key = f"{prefix}_{base_key}" if prefix else base_key
        sanitized = re.sub(r"[^A-Za-z0-9._:-]+", "_", key).strip("._:-")
        return sanitized or "java_apex_project"

    async def _compile_project(self, project_path: str, build_tool: str) -> Dict[str, Any]:
        command = self._build_compile_command(project_path, build_tool)
        logger.info("Compiling project for Sonar analysis: %s", command)
        result = await self._run_command(command, cwd=project_path)

        if result["returncode"] != 0 and not self._discover_binaries(project_path):
            raise SonarQubeExecutionError(
                self._build_command_error(
                    f"{build_tool} compile",
                    result,
                    extra_hint="Sonar Java analysis requires compiled classes. Fix the build or provide the required dependencies.",
                )
            )

        if result["returncode"] != 0:
            logger.warning(
                "Build command returned non-zero exit code, but compiled classes were found; continuing with Sonar scan."
            )
        return result

    def _build_compile_command(self, project_path: str, build_tool: str) -> List[str]:
        root = Path(project_path)
        if build_tool == "maven":
            if os.name == "nt" and (root / "mvnw.cmd").exists():
                return [str(root / "mvnw.cmd"), "-B", "-DskipTests", "-DskipITs", "-Dmaven.test.skip=true", "compile"]
            if (root / "mvnw").exists():
                return ["sh", str(root / "mvnw"), "-B", "-DskipTests", "-DskipITs", "-Dmaven.test.skip=true", "compile"]
            return ["mvn", "-B", "-DskipTests", "-DskipITs", "-Dmaven.test.skip=true", "compile"]

        if build_tool == "gradle":
            if os.name == "nt" and (root / "gradlew.bat").exists():
                return [str(root / "gradlew.bat"), "--no-daemon", "classes", "-x", "test"]
            if (root / "gradlew").exists():
                return ["sh", str(root / "gradlew"), "--no-daemon", "classes", "-x", "test"]
            return ["gradle", "--no-daemon", "classes", "-x", "test"]

        raise SonarQubeConfigurationError(f"Unsupported build tool for Sonar analysis: {build_tool}")

    async def _run_scanner(
        self,
        project_path: str,
        build_tool: str,
        project_key: str,
        project_name: str,
    ) -> str:
        scanner = self._get_scanner_command()
        binaries = self._discover_binaries(project_path)
        if not binaries:
            raise SonarQubeExecutionError(
                "No compiled Java binaries were found after the build step. Sonar analysis requires compiled classes."
            )

        scanner_settings_path = self._write_scanner_settings(
            project_path=project_path,
            project_key=project_key,
            project_name=project_name,
            binaries=binaries,
        )
        command = [
            scanner,
            f"-Dproject.settings={scanner_settings_path}",
        ]

        logger.info("Running Sonar scanner: %s", command)
        result = await self._run_command(command, cwd=project_path)
        if result["returncode"] != 0:
            raise SonarQubeExecutionError(self._build_command_error("sonar-scanner", result))

        report_task_path = self._find_report_task_path(project_path, build_tool)
        if not report_task_path:
            raise SonarQubeExecutionError(
                "Sonar analysis completed without generating report-task.txt, so results could not be retrieved."
            )
        return report_task_path

    def _discover_source_dirs(self, project_path: str, candidates: List[str]) -> List[str]:
        root = Path(project_path)
        discovered: List[str] = []
        for candidate in candidates:
            path = root / candidate
            if path.exists():
                discovered.append(candidate.replace("\\", "/"))

            pattern = candidate.replace("\\", "/")
            for nested in root.rglob(pattern):
                if not nested.exists() or not nested.is_dir():
                    continue
                relative = nested.relative_to(root).as_posix()
                if relative not in discovered:
                    discovered.append(relative)
        if discovered:
            return discovered
        return ["."]

    def _discover_binaries(self, project_path: str) -> List[str]:
        root = Path(project_path)
        candidate_dirs = [
            root / "target" / "classes",
            root / "build" / "classes" / "java" / "main",
            root / "build" / "classes" / "kotlin" / "main",
        ]
        binaries = [str(path) for path in candidate_dirs if path.exists() and path.is_dir()]

        recursive_patterns = [
            "target/classes",
            "build/classes/java/main",
            "build/classes/kotlin/main",
        ]
        for pattern in recursive_patterns:
            for path in root.rglob(pattern):
                if not path.exists() or not path.is_dir():
                    continue
                value = str(path)
                if value not in binaries:
                    binaries.append(value)

        gradle_classes_root = root / "build" / "classes"
        if gradle_classes_root.exists():
            for path in gradle_classes_root.rglob("*"):
                if path.is_dir() and any(path.iterdir()):
                    value = str(path)
                    if value not in binaries:
                        binaries.append(value)

        return binaries

    def _find_report_task_path(self, project_path: str, build_tool: str) -> Optional[str]:
        root = Path(project_path)
        candidates = [
            root / ".scannerwork" / "report-task.txt",
            root / "target" / "sonar" / "report-task.txt",
            root / "build" / "sonar" / "report-task.txt",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        for candidate in root.rglob("report-task.txt"):
            candidate_str = str(candidate)
            if ".scannerwork" in candidate_str or "sonar" in candidate_str:
                return candidate_str
        return None

    def _write_scanner_settings(
        self,
        project_path: str,
        project_key: str,
        project_name: str,
        binaries: List[str],
    ) -> str:
        root = Path(project_path)
        source_dirs = self._discover_source_dirs(project_path, ["src/main/java"])
        test_dirs = self._discover_source_dirs(project_path, ["src/test/java"])
        settings_dir = root / ".scannerwork"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_path = settings_dir / "generated-sonar-project.properties"
        binary_paths = self._normalize_scanner_paths(root, binaries)

        properties = {
            "sonar.host.url": self.sonar_url,
            "sonar.token": self.sonar_token,
            "sonar.projectKey": project_key,
            "sonar.projectName": project_name,
            "sonar.sourceEncoding": "UTF-8",
            "sonar.sources": ",".join(source_dirs),
            "sonar.java.binaries": ",".join(binary_paths),
        }
        if test_dirs:
            properties["sonar.tests"] = ",".join(test_dirs)
        if self._is_sonarcloud():
            properties["sonar.organization"] = self.sonar_organization

        lines = [f"{key}={value}" for key, value in properties.items() if value]
        settings_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return settings_path.relative_to(root).as_posix()

    def _normalize_scanner_paths(self, root: Path, paths: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for raw_path in paths:
            value = self._normalize_scanner_path(root, raw_path)
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    def _normalize_scanner_path(self, root: Path, raw_path: str) -> str:
        path = Path(raw_path)
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except Exception:
            return path.resolve().as_posix()

    def _load_report_task(self, report_task_path: str) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        with open(report_task_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if "=" not in line:
                    continue
                key, value = line.strip().split("=", 1)
                metadata[key] = value
        return metadata

    async def _await_compute_engine(self, task_metadata: Dict[str, str]) -> Dict[str, Any]:
        ce_task_url = task_metadata.get("ceTaskUrl")
        if not ce_task_url:
            logger.warning("report-task.txt did not contain ceTaskUrl; skipping compute-engine polling.")
            return {}

        timeout_seconds = 180
        interval_seconds = 5
        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(timeout_seconds // interval_seconds):
                response = await client.get(ce_task_url, auth=(self.sonar_token, ""))
                response.raise_for_status()
                task = response.json().get("task", {})
                status = str(task.get("status") or "").upper()
                if status == "SUCCESS":
                    return task
                if status in {"FAILED", "CANCELED"}:
                    raise SonarQubeExecutionError(
                        f"Sonar compute-engine task ended with status {status}."
                    )
                await asyncio.sleep(interval_seconds)

        raise SonarQubeExecutionError(
            "Timed out while waiting for Sonar analysis to complete."
        )

    async def _fetch_analysis_results(
        self,
        project_key: str,
        task_metadata: Dict[str, str],
    ) -> Dict[str, Any]:
        dashboard_url = self._normalize_analysis_url(task_metadata.get("dashboardUrl"), project_key)
        vulnerability_details: List[Dict[str, Any]] = []
        code_smell_details: List[Dict[str, Any]] = []
        bug_details: List[Dict[str, Any]] = []
        security_hotspot_details: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            measures_response = await client.get(
                f"{self.sonar_url}/api/measures/component",
                params={
                    "component": project_key,
                    "metricKeys": "bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,security_hotspots",
                },
                auth=(self.sonar_token, ""),
            )
            measures_response.raise_for_status()
            measures_data = measures_response.json()
            measures = {
                item["metric"]: item.get("value", "0")
                for item in measures_data.get("component", {}).get("measures", [])
            }

            gate_params: Dict[str, Any] = {"projectKey": project_key}
            if self._is_sonarcloud() and self.sonar_organization:
                gate_params["organization"] = self.sonar_organization

            gate_response = await client.get(
                f"{self.sonar_url}/api/qualitygates/project_status",
                params=gate_params,
                auth=(self.sonar_token, ""),
            )
            gate_response.raise_for_status()
            gate_payload = gate_response.json()
            quality_gate = self._normalize_quality_gate(
                gate_payload.get("projectStatus", {}).get("status")
            )

            try:
                bug_details = await self._fetch_issue_details(client, project_key, "BUG")
                vulnerability_details = await self._fetch_issue_details(client, project_key, "VULNERABILITY")
                code_smell_details = await self._fetch_issue_details(client, project_key, "CODE_SMELL")
                security_hotspot_details = await self._fetch_security_hotspot_details(client, project_key)
            except Exception as detail_error:
                logger.warning("Failed to fetch detailed Sonar issues for %s: %s", project_key, detail_error)

        return {
            "quality_gate": quality_gate,
            "bugs": int(float(measures.get("bugs", 0) or 0)),
            "vulnerabilities": int(float(measures.get("vulnerabilities", 0) or 0)),
            "code_smells": int(float(measures.get("code_smells", 0) or 0)),
            "coverage": float(measures.get("coverage", 0) or 0.0),
            "duplications": float(measures.get("duplicated_lines_density", 0) or 0.0),
            "security_hotspots": int(float(measures.get("security_hotspots", 0) or 0)),
            "analysis_url": dashboard_url,
            "bug_details": bug_details,
            "vulnerability_details": vulnerability_details,
            "code_smell_details": code_smell_details,
            "security_hotspot_details": security_hotspot_details,
        }

    def _normalize_quality_gate(self, status: Optional[str]) -> str:
        normalized = str(status or "").upper()
        if normalized == "OK":
            return "PASSED"
        if normalized == "ERROR":
            return "FAILED"
        if normalized == "WARN":
            return "WARN"
        if normalized in {"NONE", ""}:
            return "N/A"
        return normalized

    def _build_dashboard_url(self, project_key: str) -> str:
        if self._is_sonarcloud() and self.sonar_organization:
            return f"{self.sonar_url}/project/overview?id={project_key}&organization={self.sonar_organization}"
        return f"{self.sonar_url}/dashboard?id={project_key}"

    def _normalize_analysis_url(self, url: Optional[str], project_key: str) -> str:
        if not url:
            return self._build_dashboard_url(project_key)

        if self._is_sonarcloud() and self.sonar_organization and "organization=" not in url:
            separator = "&" if "?" in url else "?"
            return f"{url}{separator}organization={self.sonar_organization}"
        return url

    async def _fetch_issue_details(
        self,
        client: httpx.AsyncClient,
        project_key: str,
        issue_type: str,
        page_size: int = 100,
        max_items: int = 100,
    ) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        page = 1

        while len(issues) < max_items:
            response = await client.get(
                f"{self.sonar_url}/api/issues/search",
                params={
                    "componentKeys": project_key,
                    "types": issue_type,
                    "ps": min(page_size, max_items - len(issues)),
                    "p": page,
                    "additionalFields": "_all",
                },
                auth=(self.sonar_token, ""),
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("issues", [])
            if not batch:
                break

            issues.extend(self._format_issue_detail(project_key, issue) for issue in batch)

            paging_total = int(payload.get("paging", {}).get("total", 0) or 0)
            if len(issues) >= max_items or page * page_size >= paging_total:
                break
            page += 1

        return issues

    async def _fetch_security_hotspot_details(
        self,
        client: httpx.AsyncClient,
        project_key: str,
        page_size: int = 100,
        max_items: int = 100,
    ) -> List[Dict[str, Any]]:
        hotspots: List[Dict[str, Any]] = []
        page = 1

        while len(hotspots) < max_items:
            params: Dict[str, Any] = {
                "projectKey": project_key,
                "ps": min(page_size, max_items - len(hotspots)),
                "p": page,
            }
            if self._is_sonarcloud() and self.sonar_organization:
                params["organization"] = self.sonar_organization

            response = await client.get(
                f"{self.sonar_url}/api/hotspots/search",
                params=params,
                auth=(self.sonar_token, ""),
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("hotspots", [])
            if not batch:
                break

            hotspots.extend(self._format_hotspot_detail(project_key, hotspot) for hotspot in batch)

            paging_total = int(payload.get("paging", {}).get("total", 0) or 0)
            if len(hotspots) >= max_items or page * page_size >= paging_total:
                break
            page += 1

        return hotspots

    def _format_issue_detail(self, project_key: str, issue: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "key": issue.get("key"),
            "type": issue.get("type"),
            "severity": issue.get("severity"),
            "component": self._normalize_component_path(project_key, issue.get("component")),
            "line": issue.get("line"),
            "message": issue.get("message"),
            "rule": issue.get("rule"),
            "status": issue.get("status"),
            "resolution": issue.get("resolution"),
            "effort": issue.get("effort"),
            "debt": issue.get("debt"),
            "author": issue.get("author"),
            "tags": issue.get("tags", []),
            "creation_date": issue.get("creationDate"),
            "update_date": issue.get("updateDate"),
        }

    def _format_hotspot_detail(self, project_key: str, hotspot: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "key": hotspot.get("key"),
            "component": self._normalize_component_path(project_key, hotspot.get("component")),
            "line": hotspot.get("line"),
            "message": hotspot.get("message"),
            "rule": hotspot.get("rule"),
            "status": hotspot.get("status"),
            "security_category": hotspot.get("securityCategory"),
            "vulnerability_probability": hotspot.get("vulnerabilityProbability"),
            "author": hotspot.get("author"),
            "creation_date": hotspot.get("creationDate"),
            "update_date": hotspot.get("updateDate"),
        }

    def _normalize_component_path(self, project_key: str, component: Optional[str]) -> Optional[str]:
        if not component:
            return None
        prefix = f"{project_key}:"
        if component.startswith(prefix):
            return component[len(prefix):]
        return component

    def _resolve_scanner_path(self) -> Optional[str]:
        if self.sonar_scanner_path and os.path.isfile(self.sonar_scanner_path):
            return self.sonar_scanner_path

        discovered = (
            shutil.which("sonar-scanner")
            or shutil.which("sonar-scanner.bat")
            or shutil.which("sonar-scanner.cmd")
        )
        if discovered:
            return discovered

        common_locations = [
            "/usr/local/bin/sonar-scanner",
            "/opt/sonar-scanner/bin/sonar-scanner",
            os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "sonar-scanner", "bin", "sonar-scanner.bat"),
        ]
        for candidate in common_locations:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _get_scanner_command(self) -> str:
        scanner_path = self._resolve_scanner_path()
        if not scanner_path:
            raise SonarQubeConfigurationError(
                "SonarScanner CLI is not installed. Install it or set SONAR_SCANNER_PATH."
            )
        return scanner_path

    async def _run_command(self, command: List[str], cwd: str) -> Dict[str, Any]:
        env = os.environ.copy()
        resolved_java_home = self._resolve_java_home()
        if resolved_java_home:
            env["JAVA_HOME"] = resolved_java_home
            java_bin = os.path.join(resolved_java_home, "bin")
            current_path = env.get("PATH", "")
            path_entries = current_path.split(os.pathsep) if current_path else []
            if java_bin not in path_entries:
                env["PATH"] = os.pathsep.join([java_bin, current_path]) if current_path else java_bin
        if self.sonar_token:
            env["SONAR_TOKEN"] = self.sonar_token
        env["SONAR_HOST_URL"] = self.sonar_url

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout, stderr = await process.communicate()
        return {
            "returncode": process.returncode,
            "stdout": stdout.decode("utf-8", errors="ignore"),
            "stderr": stderr.decode("utf-8", errors="ignore"),
        }

    def _build_command_error(
        self,
        command_name: str,
        result: Dict[str, Any],
        extra_hint: Optional[str] = None,
    ) -> str:
        details = (result.get("stderr") or result.get("stdout") or "").strip()
        base = f"{command_name} failed with exit code {result.get('returncode')}"
        if details:
            base = f"{command_name} failed: {self._truncate_output(details)}"
        if extra_hint:
            return f"{base} {extra_hint}"
        return base

    def _truncate_output(self, text: str, limit: int = 3000) -> str:
        normalized = (text or "").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + "...(truncated)"

    def _get_simulated_results(self, project_path: str) -> Dict[str, Any]:
        java_file_count = 0
        if project_path and os.path.isdir(project_path):
            java_file_count = sum(1 for _ in Path(project_path).rglob("*.java"))
        java_file_count = max(java_file_count, 10)

        return {
            "scan_mode": "simulated",
            "real_scan": False,
            "simulated": True,
            "ready": False,
            "provider": "sonarcloud" if self._is_sonarcloud() else "sonarqube",
            "organization": self.sonar_organization or None,
            "project_key": None,
            "project_name": Path(project_path).name if project_path else "project",
            "build_tool": None,
            "quality_gate": "PASSED",
            "bugs": max(0, java_file_count // 6 - 1),
            "vulnerabilities": max(0, java_file_count // 12),
            "code_smells": java_file_count * 2,
            "coverage": 72.5,
            "duplications": 3.2,
            "security_hotspots": max(0, java_file_count // 15),
            "analysis_url": None,
            "error_message": None,
            "bug_details": [],
            "vulnerability_details": [],
            "code_smell_details": [],
            "security_hotspot_details": [],
        }

    def _resolve_java_home(self) -> Optional[str]:
        configured = self._normalize_java_home_candidate(self.java_home)
        if configured:
            return configured

        javac_path = shutil.which("javac")
        detected = self._java_home_from_executable(javac_path)
        if detected:
            return detected

        java_path = shutil.which("java")
        detected = self._java_home_from_executable(java_path)
        if detected:
            return detected

        common_candidates = [
            os.path.join(os.getenv("ProgramFiles", r"C:\Program Files"), "Java", "jdk-25.0.2"),
            os.path.join(os.getenv("ProgramFiles", r"C:\Program Files"), "Java", "latest", "jdk-25"),
            os.path.join(os.getenv("ProgramFiles", r"C:\Program Files"), "Java", "latest"),
            os.path.join(os.getenv("ProgramFiles", r"C:\Program Files"), "Java"),
        ]
        for candidate in common_candidates:
            detected = self._normalize_java_home_candidate(candidate)
            if detected:
                return detected
        return None

    def _java_home_from_executable(self, executable: Optional[str]) -> Optional[str]:
        if not executable:
            return None

        executable_path = Path(executable).resolve()
        detected = self._normalize_java_home_candidate(str(executable_path.parent.parent))
        if detected:
            return detected

        if "javapath" in executable_path.as_posix().lower():
            program_files = Path(os.getenv("ProgramFiles", r"C:\Program Files"))
            java_root = program_files / "Java"
            if java_root.exists():
                preferred_dirs = sorted(
                    [path for path in java_root.glob("jdk-*") if path.is_dir()],
                    reverse=True,
                )
                latest_dir = java_root / "latest"
                if latest_dir.exists():
                    preferred_dirs = [path for path in latest_dir.glob("jdk*") if path.is_dir()] + preferred_dirs
                for candidate in preferred_dirs:
                    detected = self._normalize_java_home_candidate(str(candidate))
                    if detected:
                        return detected
        return None

    def _normalize_java_home_candidate(self, candidate: Optional[str]) -> Optional[str]:
        if not candidate:
            return None

        path = Path(candidate).expanduser()
        if not path.exists():
            return None

        if (path / "bin" / "javac.exe").exists() or (path / "bin" / "javac").exists():
            return str(path)

        nested_jdks = sorted([nested for nested in path.glob("jdk*") if nested.is_dir()], reverse=True)
        for nested in nested_jdks:
            if (nested / "bin" / "javac.exe").exists() or (nested / "bin" / "javac").exists():
                return str(nested)
        return None
