import asyncio
import json
import logging
import os
import re
import shutil
from typing import Any, Dict, List, Optional
from urllib.parse import quote


logger = logging.getLogger(__name__)
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


class FossaError(Exception):
    """Base class for FOSSA-related errors."""


class FossaConfigurationError(FossaError):
    """Raised when FOSSA cannot run due to missing configuration."""


class FossaExecutionError(FossaError):
    """Raised when FOSSA commands fail to execute successfully."""


class FossaService:
    def __init__(self):
        self.fossa_api_key = (os.getenv("FOSSA_API_KEY") or "").strip()
        self.project_locator = (os.getenv("FOSSA_PROJECT_LOCATOR") or "").strip()
        self.project_locator_template = (os.getenv("FOSSA_PROJECT_LOCATOR_TEMPLATE") or "").strip()
        self.fossa_cli_path = (os.getenv("FOSSA_CLI_PATH") or "").strip()
        self.allow_simulated_fallback = (
            os.getenv("FOSSA_ALLOW_SIMULATED_FALLBACK", "false").strip().lower()
            in {"1", "true", "yes"}
        )

        if not self.fossa_api_key:
            logger.warning("FOSSA_API_KEY not set.")

    def get_capabilities(self) -> Dict[str, Any]:
        cli_path = self._resolve_cli_path()
        cli_installed = bool(cli_path)
        api_key_configured = bool(self.fossa_api_key)
        ready = cli_installed and api_key_configured

        if ready:
            message = "FOSSA is configured and ready."
        elif not cli_installed and not api_key_configured:
            message = "FOSSA CLI is not installed and FOSSA_API_KEY is not configured."
        elif not cli_installed:
            message = "FOSSA CLI is not installed."
        else:
            message = "FOSSA_API_KEY is not configured."

        return {
            "ready": ready,
            "cli_installed": cli_installed,
            "cli_path": cli_path,
            "api_key_configured": api_key_configured,
            "allow_simulated_fallback": self.allow_simulated_fallback,
            "project_locator": self.project_locator,
            "project_locator_template": self.project_locator_template,
            "message": message,
        }

    async def analyze_project(
        self,
        project_path: Optional[str] = None,
        allow_simulated: Optional[bool] = None,
        source_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        project_path = project_path or os.getcwd()
        fallback_allowed = self.allow_simulated_fallback if allow_simulated is None else allow_simulated
        dashboard_url = await self._build_dashboard_url(project_path, source_reference)
        logger.info("Starting FOSSA scan on: %s", project_path)

        try:
            self._ensure_ready()
            await self._run_fossa_analyze(project_path)
            test_result = await self._run_fossa_test(project_path)
            if test_result.get("partial_result"):
                result = test_result["partial_result"]
            else:
                result = self._parse_fossa_json(test_result["payload"])
                result["scan_mode"] = "real"
                result["real_scan"] = True
                result["simulated"] = False
                result["ready"] = True
                result["error_message"] = None
            result["analysis_url"] = dashboard_url
            self._display_results(result)
            return result
        except FossaError as exc:
            logger.exception("FOSSA scan failed for %s", project_path)
            if fallback_allowed:
                simulated = self._get_simulated_results(project_path)
                simulated["error_message"] = str(exc)
                simulated["ready"] = False
                simulated["analysis_url"] = dashboard_url
                return simulated
            raise

    def _ensure_ready(self) -> None:
        capabilities = self.get_capabilities()
        if not capabilities["cli_installed"]:
            raise FossaConfigurationError(
                "FOSSA CLI is not installed on the server. Install the FOSSA CLI to enable vulnerability scanning."
            )
        if not capabilities["api_key_configured"]:
            raise FossaConfigurationError(
                "FOSSA_API_KEY is not configured on the server. Configure it to enable vulnerability scanning."
            )

    async def _run_fossa_analyze(self, path: str) -> None:
        logger.info("Running: fossa analyze")
        result = await self._run_command([self._get_cli_command(), "analyze"], cwd=path)
        if result["returncode"] != 0:
            raise FossaExecutionError(
                self._build_command_error("fossa analyze", result)
            )
        logger.info("FOSSA analyze completed")

    async def _run_fossa_test(self, path: str) -> dict:
        logger.info("Running: fossa test --format json")
        result = await self._run_command(
            [self._get_cli_command(), "test", "--format", "json"],
            cwd=path,
        )
        payload = (
            self._load_json_payload(result.get("stdout") or "")
            or self._load_json_payload(result.get("stderr") or "")
            or self._load_json_payload(self._combine_outputs(result))
        )
        if payload is None:
            partial_result = self._extract_partial_result(result)
            if partial_result:
                logger.warning(
                    "FOSSA test did not return machine-readable JSON; exposing a limited real-scan result instead."
                )
                return {"payload": None, "partial_result": partial_result}
            raise FossaExecutionError(self._build_command_error("fossa test --format json", result))

        # FOSSA may return a non-zero exit code when policy violations or vulnerabilities are found.
        # If valid JSON was produced, keep the report instead of treating the scan as a hard failure.
        if result["returncode"] != 0:
            logger.warning(
                "FOSSA test exited with code %s but returned JSON output; treating as a completed scan.",
                result["returncode"],
            )

        return {"payload": payload, "partial_result": None}

    async def _run_command(self, command: List[str], cwd: str) -> Dict[str, Any]:
        env = os.environ.copy()
        if self.fossa_api_key:
            env["FOSSA_API_KEY"] = self.fossa_api_key

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

    def _load_json_payload(self, text: str) -> Optional[dict]:
        if not text:
            return None

        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        match = re.search(r"(\{.*\}|\[.*\])", stripped, re.DOTALL)
        if not match:
            return None

        try:
            payload = json.loads(match.group(1))
            return payload if isinstance(payload, dict) else {"items": payload}
        except json.JSONDecodeError:
            return None

    def _combine_outputs(self, result: Dict[str, Any]) -> str:
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        if stdout and stderr:
            return f"{stdout}\n{stderr}"
        return stdout or stderr

    def _clean_cli_text(self, text: str) -> str:
        without_ansi = ANSI_ESCAPE_RE.sub("", text or "")
        cleaned_lines = [line.strip() for line in without_ansi.splitlines()]
        meaningful = []
        previous = None
        for line in cleaned_lines:
            if not line or line == previous:
                continue
            if line.startswith("[WARN] DEPRECATION NOTICE"):
                previous = line
                continue
            if "--json flag is now deprecated" in line or "Please use:" in line or "--format json" in line:
                previous = line
                continue
            meaningful.append(line)
            previous = line
        return " ".join(meaningful).strip()

    def _extract_issue_count(self, text: str) -> Optional[int]:
        match = re.search(r"Number of issues found:\s*(\d+)", text or "", re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _extract_partial_result(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        combined_output = self._combine_outputs(result)
        normalized_output = self._clean_cli_text(combined_output)
        if not normalized_output:
            return None

        issue_count = self._extract_issue_count(normalized_output)
        push_only_key = "push-only api key was used" in normalized_output.lower()
        details_unavailable = (
            push_only_key
            or "issue details cannot be displayed" in normalized_output.lower()
            or issue_count is not None
        )
        if not details_unavailable:
            return None

        if push_only_key:
            message = (
                "FOSSA completed the scan, but the configured API key is push-only. "
                "Issue details, dependency counts, and severity breakdown are unavailable. "
                "Use a full-access FOSSA API key to retrieve detailed results."
            )
        else:
            message = (
                "FOSSA completed the scan, but the CLI did not return detailed JSON results. "
                "The dashboard may still contain the full findings."
            )

        if issue_count is not None:
            message = f"{message} FOSSA reported {issue_count} issue(s)."

        return {
            "scan_mode": "real_limited",
            "real_scan": True,
            "simulated": False,
            "ready": True,
            "compliance_status": "ISSUES_FOUND" if (issue_count or 0) > 0 else "LIMITED",
            "licenses": {},
            "license_issues": None,
            "vulnerabilities": None,
            "vulnerability_details": [],
            "dependencies": [],
            "analysis_url": None,
            "critical_issues": None,
            "high_issues": None,
            "medium_issues": None,
            "low_issues": None,
            "total_dependencies": None,
            "outdated_dependencies": None,
            "issue_count": issue_count,
            "details_available": False,
            "permission_limited": push_only_key,
            "raw_summary": normalized_output[:2000],
            "error_message": message,
        }

    def _build_command_error(self, command_name: str, result: Dict[str, Any]) -> str:
        details = (result.get("stderr") or result.get("stdout") or "").strip()
        if details:
            return f"{command_name} failed: {details}"
        return f"{command_name} failed with exit code {result.get('returncode')}"

    def _parse_fossa_json(self, data: dict) -> Dict[str, Any]:
        deps = self._extract_dependencies(data)
        license_map = self._extract_licenses(deps)
        vulnerability_details = self._extract_vulnerability_details(data)
        vulnerability_counts = self._count_vulnerabilities(vulnerability_details)
        outdated_dependencies = self._count_outdated_dependencies(deps)

        return {
            "compliance_status": (
                data.get("status")
                or data.get("compliance_status")
                or data.get("policy_status")
                or "UNKNOWN"
            ),
            "licenses": license_map,
            "license_issues": int(data.get("license_issues", license_map.get("UNKNOWN", 0)) or 0),
            "vulnerabilities": vulnerability_counts,
            "vulnerability_details": vulnerability_details,
            "dependencies": deps,
            "analysis_url": None,
            "critical_issues": vulnerability_counts["critical"],
            "high_issues": vulnerability_counts["high"],
            "medium_issues": vulnerability_counts["medium"],
            "low_issues": vulnerability_counts["low"],
            "total_dependencies": len(deps),
            "outdated_dependencies": outdated_dependencies,
        }

    def _extract_dependencies(self, data: dict) -> List[Dict[str, Any]]:
        raw_dependencies = data.get("dependencies", [])
        dependencies: List[Dict[str, Any]] = []
        if not isinstance(raw_dependencies, list):
            return dependencies

        for item in raw_dependencies:
            if not isinstance(item, dict):
                continue
            dependency = {
                "name": item.get("name") or item.get("title") or item.get("package") or item.get("locator") or "unknown",
                "license": item.get("license") or item.get("licenseName") or item.get("declaredLicense") or "UNKNOWN",
                "version": item.get("version") or item.get("resolvedVersion") or item.get("revision"),
                "latest_version": item.get("latestVersion") or item.get("recommendedVersion"),
                "status": item.get("status"),
                "outdated": bool(item.get("outdated")) if "outdated" in item else False,
                "locator": item.get("locator"),
            }
            dependencies.append(dependency)
        return dependencies

    def _extract_licenses(self, dependencies: List[Dict[str, Any]]) -> Dict[str, int]:
        license_map: Dict[str, int] = {}
        for dependency in dependencies:
            license_name = str(dependency.get("license") or "UNKNOWN")
            license_map[license_name] = license_map.get(license_name, 0) + 1
        return license_map

    def _extract_vulnerability_details(self, data: dict) -> List[Dict[str, Any]]:
        raw_vulnerabilities = data.get("vulnerabilities", [])
        vulnerabilities: List[Dict[str, Any]] = []

        if not isinstance(raw_vulnerabilities, list):
            return vulnerabilities

        for item in raw_vulnerabilities:
            if not isinstance(item, dict):
                continue

            severity = str(item.get("severity") or item.get("risk") or "unknown").lower()
            identifier = (
                item.get("id")
                or item.get("cve")
                or item.get("cve_id")
                or item.get("vulnerabilityId")
                or item.get("reference")
                or item.get("title")
                or item.get("name")
                or "unknown-vulnerability"
            )
            package_name = (
                item.get("package")
                or item.get("packageName")
                or item.get("dependency")
                or item.get("component")
                or item.get("artifact")
                or item.get("name")
            )
            vulnerability = {
                "id": str(identifier),
                "title": str(item.get("title") or item.get("name") or identifier),
                "severity": severity,
                "package": package_name,
                "package_version": item.get("version") or item.get("packageVersion") or item.get("currentVersion"),
                "fixed_version": item.get("fixedVersion") or item.get("fixVersion") or item.get("recommendedVersion"),
                "description": item.get("description") or item.get("summary") or item.get("advisory"),
                "reference": item.get("reference") or item.get("url"),
            }
            vulnerabilities.append(vulnerability)

        return vulnerabilities

    def _count_vulnerabilities(self, vulnerability_details: List[Dict[str, Any]]) -> Dict[str, int]:
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for vulnerability in vulnerability_details:
            severity = str(vulnerability.get("severity") or "low").lower()
            if severity in counts:
                counts[severity] += 1
            else:
                counts["low"] += 1
        return counts

    def _count_outdated_dependencies(self, dependencies: List[Dict[str, Any]]) -> int:
        count = 0
        for dependency in dependencies:
            status = str(dependency.get("status") or "").lower()
            outdated = bool(dependency.get("outdated"))
            latest_version = dependency.get("latest_version")
            current_version = dependency.get("version")
            if outdated or status in {"outdated", "out-of-date"}:
                count += 1
            elif latest_version and current_version and str(latest_version) != str(current_version):
                count += 1
        return count

    def _is_fossa_installed(self) -> bool:
        return bool(self._resolve_cli_path())

    def _get_cli_command(self) -> str:
        cli_path = self._resolve_cli_path()
        if not cli_path:
            raise FossaConfigurationError(
                "FOSSA CLI is not installed on the server. Install it or set FOSSA_CLI_PATH to the executable."
            )
        return cli_path

    def _resolve_cli_path(self) -> Optional[str]:
        if self.fossa_cli_path and os.path.isfile(self.fossa_cli_path):
            return self.fossa_cli_path

        discovered = shutil.which("fossa") or shutil.which("fossa.exe")
        if discovered:
            return discovered

        local_appdata = os.getenv("LOCALAPPDATA", "")
        common_locations = [
            os.path.join(local_appdata, "fossa-cli", "fossa.exe"),
            os.path.join(local_appdata, "Programs", "fossa-cli", "fossa.exe"),
            os.path.join(os.path.expanduser("~"), "AppData", "Local", "fossa-cli", "fossa.exe"),
        ]
        for candidate in common_locations:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _normalize_repo_url(self, source_reference: str) -> Optional[str]:
        if not source_reference:
            return None

        value = source_reference.strip()
        if not value or value.startswith("local://"):
            return None

        if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", value):
            value = f"https://github.com/{value}"

        if not re.match(r"^https?://", value, re.IGNORECASE):
            return None

        value = value.rstrip("/")
        value = re.sub(r"\.git$", "", value, flags=re.IGNORECASE)
        return value

    def _extract_repo_context(self, source_reference: Optional[str] = None) -> Dict[str, str]:
        normalized_url = self._normalize_repo_url(source_reference or "")
        if not normalized_url:
            return {}

        match = re.match(r"^https?://([^/]+)/(.+)$", normalized_url, re.IGNORECASE)
        if not match:
            return {}

        host = match.group(1)
        path = match.group(2).strip("/")
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) < 2:
            return {}

        owner = segments[-2]
        repo = segments[-1]
        provider = "github" if "github" in host.lower() else "gitlab" if "gitlab" in host.lower() else "git"
        return {
            "provider": provider,
            "host": host,
            "owner": owner,
            "repo": repo,
            "normalized_url": normalized_url,
        }

    def _derive_project_locator(self, source_reference: Optional[str] = None) -> Optional[str]:
        if self.project_locator and self.project_locator != "github+https://github.com/your-org/your-repo":
            return self.project_locator

        context = self._extract_repo_context(source_reference)
        normalized_url = context.get("normalized_url")
        if not normalized_url:
            return None

        if self.project_locator_template:
            try:
                return self.project_locator_template.format(**context)
            except KeyError:
                logger.warning("FOSSA_PROJECT_LOCATOR_TEMPLATE is invalid: %s", self.project_locator_template)

        lowered = normalized_url.lower()
        if "github.com/" in lowered:
            return f"github+{normalized_url}"
        if "gitlab.com/" in lowered:
            return f"gitlab+{normalized_url}"
        return None

    async def _get_git_revision_context(self, project_path: str) -> Dict[str, str]:
        revision_info: Dict[str, str] = {}
        if not project_path or not os.path.isdir(project_path):
            return revision_info

        branch_result = await self._run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path)
        revision_result = await self._run_command(["git", "rev-parse", "HEAD"], cwd=project_path)

        branch = (branch_result.get("stdout") or "").strip()
        revision = (revision_result.get("stdout") or "").strip()
        if branch and branch != "HEAD":
            revision_info["branch"] = branch
        if revision:
            revision_info["revision"] = revision
        return revision_info

    async def _build_dashboard_url(self, project_path: str, source_reference: Optional[str] = None) -> Optional[str]:
        locator = self._derive_project_locator(source_reference)
        if not locator:
            return None
        encoded_locator = quote(locator, safe="")
        revision_context = await self._get_git_revision_context(project_path)
        branch = revision_context.get("branch")
        revision = revision_context.get("revision")
        if branch and revision:
            encoded_branch = quote(branch, safe="")
            return f"https://app.fossa.com/projects/{encoded_locator}/refs/branch/{encoded_branch}/{revision}"
        return f"https://app.fossa.com/projects/{encoded_locator}/overview"

    def _display_results(self, result: Dict[str, Any]) -> None:
        logger.info("================ FOSSA REPORT ================")
        logger.info("Compliance Status: %s", result.get("compliance_status"))
        logger.info("Total Dependencies: %s", result.get("total_dependencies"))
        logger.info("Licenses: %s", result.get("licenses"))
        logger.info("Vulnerabilities: %s", result.get("vulnerabilities"))
        logger.info("Dashboard: %s", result.get("analysis_url"))
        logger.info("==============================================")

    def _get_simulated_results(self, project_path: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "scan_mode": "simulated",
            "real_scan": False,
            "simulated": True,
            "ready": False,
            "compliance_status": "UNKNOWN",
            "licenses": {},
            "license_issues": 0,
            "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "vulnerability_details": [],
            "dependencies": [],
            "analysis_url": None,
            "critical_issues": 0,
            "high_issues": 0,
            "medium_issues": 0,
            "low_issues": 0,
            "total_dependencies": 0,
            "outdated_dependencies": 0,
            "error_message": None,
        }

        try:
            if project_path and os.path.exists(project_path):
                logger.info("[FOSSA_SIM] simulate for path: %s", project_path)
                dep_count = 0
                pom = os.path.join(project_path, "pom.xml")
                build_gradle = os.path.join(project_path, "build.gradle")

                if os.path.exists(pom):
                    try:
                        with open(pom, "r", encoding="utf-8", errors="ignore") as handle:
                            dep_count += handle.read().count("<dependency>")
                    except Exception:
                        pass

                if os.path.exists(build_gradle):
                    try:
                        with open(build_gradle, "r", encoding="utf-8", errors="ignore") as handle:
                            for line in handle:
                                if "implementation" in line or "compile" in line or "api " in line:
                                    dep_count += 1
                    except Exception:
                        pass

                result["total_dependencies"] = int(dep_count)
                result["licenses"] = {"UNKNOWN": dep_count} if dep_count > 0 else {}
                result["license_issues"] = int(dep_count) if dep_count > 0 else 0
                result["compliance_status"] = "PASSED" if dep_count > 0 else "N/A"

                if dep_count > 10:
                    result["vulnerabilities"] = {"critical": 0, "high": 1, "medium": 2, "low": 0}
                    result["high_issues"] = 1
                    result["medium_issues"] = 2
                    result["vulnerability_details"] = [
                        {
                            "id": "SIM-HIGH-001",
                            "title": "Simulated high severity vulnerability",
                            "severity": "high",
                            "package": "simulated-package",
                            "package_version": None,
                            "fixed_version": None,
                            "description": "Simulated fallback data because real FOSSA scanning was unavailable.",
                            "reference": None,
                        },
                        {
                            "id": "SIM-MEDIUM-001",
                            "title": "Simulated medium severity vulnerability",
                            "severity": "medium",
                            "package": "simulated-package",
                            "package_version": None,
                            "fixed_version": None,
                            "description": "Simulated fallback data because real FOSSA scanning was unavailable.",
                            "reference": None,
                        },
                    ]
                logger.info("[FOSSA_SIM] detected dep_count=%s", dep_count)
        except Exception:
            pass

        return result


if __name__ == "__main__":
    async def main():
        service = FossaService()
        result = await service.analyze_project()
        print(json.dumps(result, indent=4))

    asyncio.run(main())
