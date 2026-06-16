from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional


def _coerce_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, ()):
        return []
    return [value]


def _first_nonempty(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text or default
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _sample_file_paths(all_files: List[Any], limit: int = 40) -> List[str]:
    samples: List[str] = []
    for item in all_files[:limit]:
        if isinstance(item, dict):
            path = _first_nonempty(item.get("path") or item.get("name"))
        else:
            path = _first_nonempty(item)
        if path:
            samples.append(path.replace("\\", "/"))
    return samples


def _sample_java_class_names(file_samples: List[str], limit: int = 25) -> List[str]:
    class_names: List[str] = []
    for path in file_samples:
        if path.endswith(".java"):
            class_name = path.rsplit("/", 1)[-1].replace(".java", "")
            if class_name:
                class_names.append(class_name)
        if len(class_names) >= limit:
            break
    return class_names


def _normalize_dependency_signature(dependencies: List[Any], limit: int = 25) -> List[Dict[str, Any]]:
    signature: List[Dict[str, Any]] = []
    for dep in dependencies[:limit]:
        if isinstance(dep, dict):
            signature.append(
                {
                    "group_id": dep.get("group_id"),
                    "artifact_id": dep.get("artifact_id"),
                    "current_version": dep.get("current_version") or dep.get("version"),
                    "status": dep.get("status"),
                }
            )
    return signature


def derive_repo_snapshot_id(
    *,
    repo_name: str,
    repo_url: str,
    analysis_data: Dict[str, Any],
    base_document: Optional[Dict[str, Any]] = None,
) -> str:
    existing_candidates = [
        analysis_data.get("repo_snapshot_id"),
        analysis_data.get("snapshot_id"),
        analysis_data.get("workspace_snapshot_id"),
        analysis_data.get("workspace_revision"),
        analysis_data.get("git_revision"),
        analysis_data.get("commit_sha"),
        analysis_data.get("head_commit"),
        analysis_data.get("revision"),
    ]
    for candidate in existing_candidates:
        text = _first_nonempty(candidate)
        if text:
            return text

    dependencies = analysis_data.get("dependencies", []) or []
    vulnerable_dependencies = analysis_data.get("vulnerable_dependencies", []) or []
    api_endpoints = analysis_data.get("api_endpoints", []) or []
    all_files = analysis_data.get("all_files", []) or []
    build_files_info = analysis_data.get("build_files_info", {}) or {}
    build_tool = analysis_data.get("build_tool")
    java_version = analysis_data.get("java_version") or analysis_data.get("java_version_from_build")
    file_samples = _sample_file_paths(all_files)

    snapshot_payload = {
        "repo_name": repo_name,
        "repo_url": repo_url,
        "build_tool": build_tool,
        "java_version": java_version,
        "frameworks": analysis_data.get("detected_frameworks", [])[:20],
        "dependency_count": len(dependencies),
        "vulnerability_count": len(vulnerable_dependencies),
        "api_endpoint_count": len(api_endpoints),
        "file_count": len(all_files),
        "file_samples": file_samples[:40],
        "dependencies": _normalize_dependency_signature(dependencies),
        "build_files": {
            "pom_files": build_files_info.get("pom_files", [])[:8],
            "gradle_files": build_files_info.get("gradle_files", [])[:8],
        },
        "existing_document_summary": {
            "executive_summary": _first_nonempty((base_document or {}).get("executive_summary")),
            "business_objectives": len(_coerce_list((base_document or {}).get("business_objectives"))),
            "use_cases": len(_coerce_list((base_document or {}).get("use_cases"))),
            "capabilities": len(_coerce_list((base_document or {}).get("capabilities"))),
            "risks": len(_coerce_list((base_document or {}).get("risks"))),
        },
    }
    return hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def build_repository_context_pack(
    *,
    repo_name: str,
    repo_url: str,
    analysis_data: Dict[str, Any],
    base_document: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dependencies = analysis_data.get("dependencies", []) or []
    vulnerable_dependencies = analysis_data.get("vulnerable_dependencies", []) or []
    api_endpoints = analysis_data.get("api_endpoints", []) or []
    all_files = analysis_data.get("all_files", []) or []
    frameworks = analysis_data.get("detected_frameworks", []) or []
    build_files_info = analysis_data.get("build_files_info", {}) or {}
    modules = (base_document or {}).get("modules", []) or []
    repo_snapshot_id = derive_repo_snapshot_id(
        repo_name=repo_name,
        repo_url=repo_url,
        analysis_data=analysis_data,
        base_document=base_document,
    )

    file_samples = _sample_file_paths(all_files)
    module_payload = []
    for module in modules[:8]:
        if isinstance(module, dict):
            module_payload.append(
                {
                    "name": module.get("name"),
                    "description": module.get("description"),
                    "files": module.get("files"),
                }
            )

    endpoint_payload = []
    for item in api_endpoints[:15]:
        if isinstance(item, dict):
            endpoint_payload.append(
                {
                    "method": item.get("method") or "GET",
                    "endpoint": item.get("endpoint") or item.get("path") or "",
                    "description": item.get("description") or "",
                }
            )

    dependency_payload = []
    for dep in dependencies[:25]:
        if isinstance(dep, dict):
            dependency_payload.append(
                {
                    "group_id": dep.get("group_id"),
                    "artifact_id": dep.get("artifact_id"),
                    "version": dep.get("current_version") or dep.get("version"),
                    "status": dep.get("status"),
                }
            )

    vulnerable_payload = []
    for dep in vulnerable_dependencies[:10]:
        if isinstance(dep, dict):
            vulnerable_payload.append(
                {
                    "dependency": dep.get("dependency") or dep.get("artifact_id") or dep.get("package"),
                    "severity": dep.get("severity"),
                    "reason": dep.get("reason") or dep.get("title") or dep.get("description"),
                }
            )

    existing_document_summary = {
        "executive_summary": (base_document or {}).get("executive_summary"),
        "business_objectives": _coerce_list((base_document or {}).get("business_objectives"))[:4],
        "use_cases": _coerce_list((base_document or {}).get("use_cases"))[:4],
        "capabilities": _coerce_list((base_document or {}).get("capabilities"))[:4],
        "risks": _coerce_list((base_document or {}).get("risks"))[:4],
    }

    return {
        "repo_name": repo_name,
        "repo_url": repo_url,
        "repo_snapshot_id": repo_snapshot_id,
        "build_tool": analysis_data.get("build_tool"),
        "java_version": analysis_data.get("java_version") or analysis_data.get("java_version_from_build"),
        "frameworks": frameworks[:20],
        "dependency_count": len(dependencies),
        "vulnerability_count": len(vulnerable_dependencies),
        "api_endpoint_count": len(api_endpoints),
        "file_count": len(all_files),
        "module_hints": module_payload,
        "api_endpoints": endpoint_payload,
        "dependencies": dependency_payload,
        "vulnerable_dependencies": vulnerable_payload,
        "java_class_samples": _sample_java_class_names(file_samples),
        "file_samples": file_samples,
        "build_files": {
            "pom_files": build_files_info.get("pom_files", [])[:8],
            "gradle_files": build_files_info.get("gradle_files", [])[:8],
            "build_tool_version": build_files_info.get("build_tool_version"),
        },
        "existing_document_summary": existing_document_summary,
    }


def build_version_recommendation_context_pack(analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
    dependencies = analysis_payload.get("dependencies") or []
    allowed_versions = analysis_payload.get("allowed_target_versions") or []
    repo_name = _first_nonempty(analysis_payload.get("repo_name"))
    repo_url = _first_nonempty(analysis_payload.get("repo_url"))
    repo_snapshot_id = _first_nonempty(analysis_payload.get("repo_snapshot_id")) or derive_repo_snapshot_id(
        repo_name=repo_name,
        repo_url=repo_url,
        analysis_data=analysis_payload,
        base_document=None,
    )
    return {
        "repo_name": repo_name,
        "repo_url": repo_url,
        "repo_snapshot_id": repo_snapshot_id,
        "source_java_version": str(analysis_payload.get("source_java_version", "")),
        "detected_java_version": analysis_payload.get("detected_java_version"),
        "allowed_target_versions": allowed_versions,
        "build_tool": analysis_payload.get("build_tool"),
        "has_tests": bool(analysis_payload.get("has_tests")),
        "api_endpoint_count": int(analysis_payload.get("api_endpoint_count", 0)),
        "risk_level": analysis_payload.get("risk_level", "unknown"),
        "dependency_count": len(dependencies),
        "dependencies": [
            {
                "group_id": dep.get("group_id"),
                "artifact_id": dep.get("artifact_id"),
                "current_version": dep.get("current_version"),
                "status": dep.get("status"),
            }
            for dep in dependencies
            if isinstance(dep, dict)
        ][:40],
    }


def context_pack_fingerprint(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def summarize_context_for_prompt(context: Dict[str, Any], *, dep_limit: int = 8, sample_limit: int = 6) -> Dict[str, Any]:
    """Produce a compact summary of the repository context suitable for prompt interpolation.

    Returns a small dict with counts and top items to keep token usage low.
    """
    java_version = context.get("java_version") or context.get("detected_java_version") or context.get("source_java_version")
    build_tool = context.get("build_tool")
    dep_count = int(context.get("dependency_count") or len(context.get("dependencies") or []))
    vuln_count = int(context.get("vulnerability_count") or len(context.get("vulnerable_dependencies") or []))
    file_count = int(context.get("file_count") or 0)

    # top dependencies as short signatures
    deps = []
    for d in (context.get("dependencies") or [])[:dep_limit]:
        if isinstance(d, dict):
            gid = d.get("group_id") or d.get("group") or ""
            aid = d.get("artifact_id") or d.get("artifact") or ""
            ver = d.get("version") or d.get("current_version") or ""
            deps.append(f"{gid}:{aid}:{ver}".strip(":"))

    # critical vulnerabilities
    criticals = []
    for v in (context.get("vulnerable_dependencies") or [])[:dep_limit]:
        if isinstance(v, dict):
            name = v.get("dependency") or v.get("artifact_id") or v.get("package") or ""
            sev = v.get("severity")
            reason = (v.get("reason") or v.get("title") or v.get("description") or "")
            criticals.append({"dependency": name, "severity": sev, "reason": reason})

    frameworks = (context.get("frameworks") or [])[:6]
    samples = (context.get("file_samples") or [])[:sample_limit]

    return {
        "java_version": java_version,
        "build_tool": build_tool,
        "dependency_count": dep_count,
        "vulnerability_count": vuln_count,
        "file_count": file_count,
        "top_dependencies": deps,
        "top_vulnerabilities": criticals,
        "frameworks": frameworks,
        "sample_files": samples,
    }
