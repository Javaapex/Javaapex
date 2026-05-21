from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse


class RenderDeploymentService:
    """Single deployment implementation for Render.com."""

    def _backend_deploy_allowed(self) -> bool:
        deploy_mode = os.getenv("DEPLOYMENT_MODE", "github_actions").strip().lower()
        allow_backend_render = os.getenv("ALLOW_BACKEND_RENDER_DEPLOY", "0").strip().lower() in {"1", "true", "yes", "on"}
        return deploy_mode in {"render_api", "render-api", "render"} and allow_backend_render

    def _is_enabled(self) -> bool:
        return os.getenv("AUTO_DEPLOY", "false").lower() in ("true", "1", "yes")

    def _sanitize_service_name(self, value: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9-]+", "-", (value or "")).strip("-").lower()
        base = re.sub(r"-{2,}", "-", base)
        return base[:63] or "javaapex-generated-service"

    def _extract_repo_full_name(self, repo_reference: str) -> str:
        value = (repo_reference or "").strip()
        if not value or value.startswith("local://"):
            return ""
        if re.match(r"^[^/\s]+/[^/\s]+$", value):
            return value.replace(".git", "")

        parsed = urlparse(value if "://" in value else f"https://{value}")
        if "github.com" not in parsed.netloc.lower():
            return ""
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 2:
            return ""
        return f"{parts[0]}/{parts[1].replace('.git', '')}"

    def _is_timeout_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "timed out" in text or "timeout" in text

    def _create_service(self, payload: Dict[str, Any], api_key: str) -> Dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                req = urllib_request.Request(
                    "https://api.render.com/v1/services",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
                with urllib_request.urlopen(req, timeout=120) as response:
                    body = response.read().decode("utf-8", errors="ignore")
                return json.loads(body) if body else {}
            except Exception as exc:
                last_error = exc
                if attempt >= 3 or not self._is_timeout_error(exc):
                    raise
                # Render API can be slow intermittently; retry transient timeout failures.
                time.sleep(min(2 * attempt, 5))
        if last_error:
            raise last_error
        return {}

    def _resolve_owner_id(self, api_key: str) -> str:
        configured = (os.getenv("RENDER_OWNER_ID", "") or os.getenv("RENDER_OWNERID", "")).strip()
        if configured:
            return configured

        req = urllib_request.Request(
            "https://api.render.com/v1/owners",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib_request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8", errors="ignore")
        data = json.loads(body) if body else []

        if isinstance(data, dict):
            # Some responses may nest items.
            candidates = data.get("owners") or data.get("items") or []
        else:
            candidates = data

        if not candidates:
            return ""
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        return str(first.get("owner", {}).get("id") or first.get("id") or "").strip()

    def deploy_services(
        self,
        deployment_config: Dict[str, Any],
        project_name: str,
        github_repo: str = "",
        branch: str = "main",
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_executed",
            "reason": "",
            "output": "",
            "services_deployed": [],
            "service_urls": [],
            "accessible_url": "",
            "dashboard_url": "https://dashboard.render.com/services",
            "errors": [],
        }

        if not self._backend_deploy_allowed():
            result["status"] = "queued_via_github_actions"
            result["reason"] = "Backend Render API deploy is disabled. Deployment is handled via GitHub Actions."
            return result

        if not self._is_enabled():
            result["status"] = "skipped"
            result["reason"] = "AUTO_DEPLOY not enabled. Set AUTO_DEPLOY=true to enable automatic deployment."
            return result

        render_api_key = os.getenv("RENDER_API_KEY", "").strip()
        if not render_api_key:
            result["status"] = "failed"
            result["reason"] = "RENDER_API_KEY environment variable not set"
            result["errors"].append("RENDER_API_KEY is required for deployment")
            return result

        repo_name = self._extract_repo_full_name(github_repo or os.getenv("GITHUB_REPOSITORY", "").strip())
        if not repo_name:
            result["status"] = "failed"
            result["reason"] = "GITHUB_REPOSITORY environment variable not set or invalid"
            result["errors"].append("A valid GitHub owner/repo is required for deployment")
            return result

        deployed: List[str] = []
        service_urls: List[str] = []
        output_lines: List[str] = [f"Deploying {project_name} using repo {repo_name}"]

        try:
            owner_id = self._resolve_owner_id(render_api_key)
            if not owner_id:
                result["status"] = "failed"
                result["reason"] = "Unable to resolve Render owner ID"
                result["errors"].append(
                    "Set RENDER_OWNER_ID in environment, or ensure the API key has access to at least one owner/workspace."
                )
                return result

            services = deployment_config.get("services", {}) if isinstance(deployment_config, dict) else {}
            for service_id, service_cfg in services.items():
                branch_candidates = [branch, "main", "master"]
                branch_candidates = [b for i, b in enumerate(branch_candidates) if b and b.strip() and b not in branch_candidates[:i]]
                response_data = None
                last_error: Exception | None = None
                for selected_branch in branch_candidates:
                    env_vars = [
                        {"key": k, "value": str(v)}
                        for k, v in (service_cfg.get("environment", {}) or {}).items()
                    ]
                    build_command = service_cfg.get("build_command", "mvn clean package -DskipTests")
                    start_command = service_cfg.get("start_command", "java -jar target/*.jar")
                    runtime = (
                        str(
                            service_cfg.get("runtime")
                            or os.getenv("RENDER_RUNTIME")
                            or "docker"
                        )
                        .strip()
                        .lower()
                    )
                    service_type = str(service_cfg.get("service_type", "web_service")).strip().lower()
                    if service_type not in {"web_service", "background_worker"}:
                        service_type = "web_service"
                    payload = {
                        "type": service_type,
                        "ownerId": owner_id,
                        "name": self._sanitize_service_name(service_id),
                        "repo": f"https://github.com/{repo_name}",
                        "branch": selected_branch,
                        "plan": "free",
                        "autoDeploy": "yes",
                        # Render's service-creation API for non-static services expects serviceDetails.
                        # Keep top-level fields that may be accepted in older payload shapes.
                        "serviceDetails": {
                            "runtime": runtime,
                            "buildCommand": build_command,
                            "startCommand": start_command,
                            "envVars": env_vars,
                            "plan": "free",
                            "pullRequestPreviewsEnabled": "no",
                        },
                        "runtime": runtime,
                        "buildCommand": build_command,
                        "startCommand": start_command,
                        "envVars": env_vars,
                    }
                    try:
                        response_data = self._create_service(payload, render_api_key)
                        output_lines.append(f"Created using branch: {selected_branch}")
                        break
                    except urllib_error.HTTPError as err:
                        last_error = err
                        continue
                if response_data is None and last_error:
                    raise last_error
                service_name = response_data.get("service", {}).get("name") or response_data.get("name") or service_id
                deployed.append(service_name)
                output_lines.append(f"Created service: {service_name}")
                service_url = (
                    response_data.get("service", {}).get("serviceDetails", {}).get("url")
                    or response_data.get("serviceDetails", {}).get("url")
                    or response_data.get("url")
                    or ""
                )
                if service_url:
                    service_urls.append(service_url)
                    output_lines.append(f"Service URL: {service_url}")

            result["status"] = "success"
            result["services_deployed"] = deployed
            result["service_urls"] = service_urls
            result["accessible_url"] = service_urls[0] if service_urls else ""
            result["output"] = "\n".join(output_lines)
            return result
        except urllib_error.HTTPError as http_err:
            body = http_err.read().decode("utf-8", errors="ignore")
            result["status"] = "failed"
            result["reason"] = f"Render API returned HTTP {http_err.code}"
            result["errors"].append(body or str(http_err))
        except Exception as exc:
            result["status"] = "failed"
            result["reason"] = f"Unexpected error during deployment: {exc}"
            result["errors"].append(str(exc))

        result["output"] = "\n".join(output_lines)
        return result

    def deploy_repository(self, repo_reference: str, service_name: str, branch: str = "main") -> Dict[str, Any]:
        config = {
            "services": {
                self._sanitize_service_name(service_name): {
                    "build_command": "mvn clean package -DskipTests",
                    "start_command": "java -jar target/*.jar",
                    "environment": {
                        "SPRING_PROFILES_ACTIVE": "production",
                    },
                }
            }
        }
        return self.deploy_services(config, service_name, github_repo=repo_reference, branch=branch)


render_deployment_service = RenderDeploymentService()
