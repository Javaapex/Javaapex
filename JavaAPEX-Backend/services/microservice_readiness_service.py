from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from analyzers.microservice_readiness_analyzer import MicroserviceReadinessAnalyzer
from services.microservice_eligibility_pasted import _assess_microservice_eligibility
from services.repository_workspace_service import RepositoryWorkspace

logger = logging.getLogger(__name__)


class MicroserviceReadinessService:
    def __init__(self) -> None:
        self._fallback_analyzer = MicroserviceReadinessAnalyzer()
        self._max_file_content_bytes = int(os.getenv("REPO_FILE_CONTENT_MAX_BYTES", "262144"))
        self._max_java_content_files = max(24, int(os.getenv("MICROSERVICE_ELIGIBILITY_MAX_FILE_INSPECTIONS", "160")))

    async def analyze_repository(
        self,
        workspace: RepositoryWorkspace,
        analysis_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.info("Running microservice readiness service for %s", workspace.repo_url)
        enriched_analysis = self._enrich_analysis_with_content(workspace, analysis_data)

        try:
            assessment = await _assess_microservice_eligibility(
                owner=workspace.owner,
                repo=workspace.repo,
                analysis=enriched_analysis,
            )
            if not isinstance(assessment, dict):
                raise ValueError("Pasted eligibility function returned a non-dict payload.")
            compatibility = self._build_compatibility_payload(workspace, enriched_analysis, assessment)
            return {**compatibility, **assessment}
        except Exception:
            logger.exception(
                "Pasted microservice eligibility assessment failed for %s; using fallback analyzer.",
                workspace.repo_url,
            )
            fallback_report = self._fallback_analyzer.analyze(workspace, analysis_data)
            return fallback_report.model_dump()

    def _enrich_analysis_with_content(
        self,
        workspace: RepositoryWorkspace,
        analysis_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        enriched = dict(analysis_data or {})
        root = Path(workspace.workspace_path).resolve()
        all_files_raw = analysis_data.get("all_files") or []
        normalized_entries: List[Dict[str, Any]] = []
        seen_paths = set()

        for item in all_files_raw:
            if isinstance(item, dict):
                entry = dict(item)
                path = str(entry.get("path") or entry.get("name") or "").strip()
            else:
                path = str(item or "").strip()
                entry = {}

            if not path:
                continue
            normalized_path = path.replace("\\", "/")
            key = normalized_path.lower()
            if key in seen_paths:
                continue
            seen_paths.add(key)
            entry["path"] = normalized_path
            entry.setdefault("name", os.path.basename(normalized_path))
            normalized_entries.append(entry)

        for item in (analysis_data.get("java_files") or []):
            if isinstance(item, dict):
                path = str(item.get("path") or item.get("name") or item.get("file") or "").strip()
            else:
                path = str(item or "").strip()
            if not path:
                continue
            normalized_path = path.replace("\\", "/")
            key = normalized_path.lower()
            if key in seen_paths:
                continue
            seen_paths.add(key)
            normalized_entries.append({"name": os.path.basename(normalized_path), "path": normalized_path, "type": "file"})

        if not normalized_entries:
            normalized_entries = self._collect_workspace_file_entries(root)
            seen_paths = {str(entry.get("path") or "").lower() for entry in normalized_entries if entry.get("path")}

        java_files_loaded = 0
        for entry in normalized_entries:
            file_path = str(entry.get("path") or "")
            if not file_path.lower().endswith(".java"):
                continue
            if java_files_loaded >= self._max_java_content_files:
                break
            content = self._safe_read_workspace_file(root, file_path)
            if content is None:
                continue
            entry["content"] = content
            java_files_loaded += 1

        enriched["all_files"] = normalized_entries
        return enriched

    def _collect_workspace_file_entries(self, root: Path) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        skip_dirs = {
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
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in skip_dirs and not name.startswith(".")]
            current = Path(current_root)
            for file_name in sorted(file_names):
                full_path = current / file_name
                try:
                    rel_path = full_path.relative_to(root).as_posix()
                except Exception:
                    continue
                entries.append(
                    {
                        "name": file_name,
                        "path": rel_path,
                        "type": "file",
                    }
                )
        return entries

    def _safe_read_workspace_file(self, root: Path, relative_path: str) -> str | None:
        try:
            candidate = (root / relative_path).resolve()
            if os.path.commonpath([str(root), str(candidate)]) != str(root):
                return None
            if not candidate.is_file():
                return None
            with open(candidate, "rb") as source_file:
                raw = source_file.read(self._max_file_content_bytes + 1)
            truncated = len(raw) > self._max_file_content_bytes
            if truncated:
                raw = raw[: self._max_file_content_bytes]
            text = raw.decode("utf-8", errors="ignore")
            if truncated:
                text += "\n\n... [truncated by backend]"
            return text
        except Exception:
            return None

    def _build_compatibility_payload(
        self,
        workspace: RepositoryWorkspace,
        analysis_data: Dict[str, Any],
        assessment: Dict[str, Any],
    ) -> Dict[str, Any]:
        score = int(assessment.get("score") or 0)
        eligible = bool(assessment.get("eligible"))
        eligibility_label = str(assessment.get("eligibility_label") or "").strip()
        suggested_services = assessment.get("suggested_services") or []
        evaluation_criteria = assessment.get("evaluation_criteria") or []

        recommended_architecture = (
            "Microservices"
            if score >= 70
            else "Modular Monolith with Refactoring"
            if score >= 51
            else "Monolith (Refactor First)"
        )

        strengths = [
            item.get("description", "")
            for item in (assessment.get("benefits_if_converted") or [])
            if isinstance(item, dict) and item.get("description")
        ]
        risks = [
            item.get("description", "")
            for item in (assessment.get("risks_if_not_converted") or [])
            if isinstance(item, dict) and item.get("description")
        ]
        if not strengths:
            strengths = [value for value in (assessment.get("signals_for") or []) if isinstance(value, str)]
        if not risks:
            risks = [value for value in (assessment.get("signals_against") or []) if isinstance(value, str)]

        service_candidates = []
        for svc in suggested_services:
            if isinstance(svc, dict):
                name = str(svc.get("name") or "Service").strip()
                evidence = [str(svc.get("description") or "").strip()] if svc.get("description") else []
                packages = [str(value).strip() for value in (svc.get("components") or []) if str(value).strip()]
            else:
                name = str(svc).strip()
                evidence = []
                packages = []
            if not name:
                continue
            service_candidates.append(
                {
                    "name": name,
                    "packages": packages[:6],
                    "evidence": evidence[:3],
                    "scaling_signals": [],
                    "external_integrations": [],
                    "transactional": False,
                }
            )

        score_breakdown = []
        for criterion in evaluation_criteria:
            if not isinstance(criterion, dict):
                continue
            score_breakdown.append(
                {
                    "name": str(criterion.get("name") or "Criteria"),
                    "score": int(criterion.get("score_percent") or 0),
                    "weight": int(criterion.get("max_score") or 0),
                    "summary": str(criterion.get("justification") or ""),
                }
            )

        domains_detected = assessment.get("domains_detected") or []
        scan_count = int(assessment.get("java_files_count") or 0)
        return {
            "projectName": workspace.repo,
            "score": score,
            "eligibility": eligibility_label or ("ELIGIBLE" if eligible else "NOT ELIGIBLE"),
            "recommendedArchitecture": recommended_architecture,
            "summary": str(assessment.get("reasoning") or ""),
            "strengths": strengths[:8],
            "risks": risks[:10],
            "serviceCandidates": service_candidates[:8],
            "couplingIssues": [value for value in (assessment.get("signals_against") or []) if isinstance(value, str)][:10],
            "databaseConcerns": [],
            "scalingCandidates": [entry["name"] for entry in service_candidates[:6]],
            "recommendedMigrationStrategy": [
                str(item.get("description"))
                for item in (assessment.get("changes_needed") or [])
                if isinstance(item, dict) and item.get("description")
            ][:8],
            "observations": [
                f"Criteria option: {assessment.get('criteria_option', 'N/A')}",
                f"Detected domains: {', '.join(domains_detected[:5])}" if domains_detected else "Detected domains: none",
            ],
            "scoreBreakdown": score_breakdown,
            "detailedEligibilityReport": {
                "project_structure": [f"Build tool: {analysis_data.get('build_tool') or 'unknown'}", f"Java files scanned: {scan_count}"],
                "package_structure": [],
                "module_boundaries": [value for value in domains_detected[:8]],
                "dependency_coupling": [value for value in (assessment.get("signals_against") or []) if isinstance(value, str)][:8],
                "database_access_patterns": [],
                "communication_analysis": [value for value in (assessment.get("signals_for") or []) if isinstance(value, str)][:8],
                "deployment_independence": [],
                "scalability_indicators": [entry["name"] for entry in service_candidates[:8]],
            },
            "architecturalObservations": [str(assessment.get("reasoning") or "")],
            "analysisDiagnostics": {
                "java_files_total": scan_count,
                "java_files_scanned": scan_count,
                "package_count": len(domains_detected),
                "detected_modules": len(assessment.get("chunk_results") or []),
                "cross_module_dependencies": 0,
                "circular_dependencies": 0,
                "external_integration_count": 0,
                "scan_truncated": False,
            },
            "reportGeneratedAt": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "springBootDetected": any(
                    "spring" in str(item).lower()
                    for item in (
                        analysis_data.get("detected_frameworks")
                        or [dependency.get("artifact_id") for dependency in (analysis_data.get("dependencies") or []) if isinstance(dependency, dict)]
                    )
                ),
                "databaseTechnologies": [],
            },
        }


microservice_readiness_service = MicroserviceReadinessService()

