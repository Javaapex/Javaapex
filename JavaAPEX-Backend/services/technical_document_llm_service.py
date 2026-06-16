import copy
import logging
from typing import Any, Dict, List, Optional

from services.llm_context_service import build_repository_context_pack, context_pack_fingerprint
from services.preferred_llm_service import preferred_llm_service


logger = logging.getLogger(__name__)


class TechnicalDocumentLLMService:
    async def enrich_document(
        self,
        base_document: Dict[str, Any],
        analysis_data: Dict[str, Any],
        *,
        repo_name: str,
        repo_url: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        document = copy.deepcopy(base_document)
        summary_payload = build_repository_context_pack(
            repo_name=repo_name,
            repo_url=repo_url,
            analysis_data=analysis_data,
            base_document=document,
        )
        cache_key = context_pack_fingerprint(
            {
                "type": "technical_document_enrichment",
                "context": summary_payload,
            }
        )

        system_prompt = (
            "You are a senior software architect preparing a repository-grounded technical document. "
            "Use only the provided repository summary. Do not invent runtime behavior, business rules, "
            "database schemas, or integrations that are not supported by the input. "
            "When evidence is weak, stay conservative and summarize at a high level. "
            "Return valid JSON only."
        )
        user_prompt = (
            "Enrich this Java repository technical document using the provided analysis summary.\n"
            "Return a JSON object with any of these keys when you can improve them with repository-grounded detail:\n"
            "executive_summary,\n"
            "business_objectives,\n"
            "modules,\n"
            "use_cases,\n"
            "capabilities,\n"
            "external_api_calls,\n"
            "risks,\n"
            "glossary.\n\n"
            "Shape requirements:\n"
            "- business_objectives: array of objects with id, objective, target\n"
            "- modules: array of objects with name, description, files\n"
            "- use_cases: array of objects with id, name, actor, main_flow, post_condition\n"
            "- capabilities: array of objects with name, overview, business_value, features, processes\n"
            "- external_api_calls: array of objects with name, protocol, technology, format, endpoint, purpose, notes\n"
            "- risks: array of objects with category, title, description, mitigation\n"
            "- glossary: array of objects with term, definition\n"
            "- Keep counts modest and high-signal.\n"
            "- Omit keys you cannot improve responsibly.\n\n"
            f"Repository summary:\n{summary_payload}"
        )

        try:
            llm_result = await preferred_llm_service.request_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=1800,
                temperature=0.15,
                cache_key=cache_key,
            )
            enriched_document = self._merge_document(document, llm_result["parsed"])
            metadata = {
                "llm_enriched": True,
                "llm_provider": llm_result["provider"],
                "llm_model": llm_result["model"],
            }
            doc_info = enriched_document.get("document_info")
            if isinstance(doc_info, dict):
                doc_info["llm_provider"] = llm_result["provider"]
                doc_info["llm_model"] = llm_result["model"]
                enriched_document["document_info"] = doc_info
            return enriched_document, metadata
        except Exception as exc:
            logger.warning("Technical document LLM enrichment failed, using heuristic document: %s", exc)
            return document, {
                "llm_enriched": False,
                "llm_error": str(exc),
            }

    def _build_summary_payload(
        self,
        *,
        repo_name: str,
        repo_url: str,
        analysis_data: Dict[str, Any],
        base_document: Dict[str, Any],
    ) -> Dict[str, Any]:
        dependencies = analysis_data.get("dependencies", []) or []
        vulnerable_dependencies = analysis_data.get("vulnerable_dependencies", []) or []
        api_endpoints = analysis_data.get("api_endpoints", []) or []
        all_files = analysis_data.get("all_files", []) or []
        frameworks = analysis_data.get("detected_frameworks", []) or []
        build_files_info = analysis_data.get("build_files_info", {}) or {}
        modules = base_document.get("modules", []) or []

        file_paths: List[str] = []
        java_class_names: List[str] = []
        for item in all_files[:60]:
            path = ""
            if isinstance(item, dict):
                path = str(item.get("path") or item.get("name") or "").strip()
            else:
                path = str(item).strip()
            if not path:
                continue
            normalized = path.replace("\\", "/")
            file_paths.append(normalized)
            if normalized.endswith(".java"):
                java_class_names.append(normalized.rsplit("/", 1)[-1].replace(".java", ""))

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

        return {
            "repo_name": repo_name,
            "repo_url": repo_url,
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
            "java_class_samples": java_class_names[:25],
            "file_samples": file_paths[:40],
            "build_files": {
                "pom_files": build_files_info.get("pom_files", [])[:8],
                "gradle_files": build_files_info.get("gradle_files", [])[:8],
                "build_tool_version": build_files_info.get("build_tool_version"),
            },
            "existing_document_summary": {
                "executive_summary": base_document.get("executive_summary"),
                "business_objectives": (base_document.get("business_objectives") or [])[:4],
                "use_cases": (base_document.get("use_cases") or [])[:4],
                "capabilities": (base_document.get("capabilities") or [])[:4],
                "risks": (base_document.get("risks") or [])[:4],
            },
        }

    def _merge_document(self, base_document: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(base_document)

        if isinstance(llm_payload.get("executive_summary"), str) and llm_payload["executive_summary"].strip():
            merged["executive_summary"] = llm_payload["executive_summary"].strip()

        list_specs = {
            "business_objectives": {"max_items": 6, "required": ["id", "objective", "target"]},
            "modules": {"max_items": 8, "required": ["name", "description", "files"]},
            "use_cases": {"max_items": 6, "required": ["id", "name", "actor", "main_flow", "post_condition"]},
            "capabilities": {"max_items": 6, "required": ["name", "overview", "business_value"]},
            "external_api_calls": {"max_items": 6, "required": ["name"]},
            "risks": {"max_items": 8, "required": ["category", "title", "description", "mitigation"]},
            "glossary": {"max_items": 16, "required": ["term", "definition"]},
        }

        for key, spec in list_specs.items():
            normalized_items = self._normalize_object_list(llm_payload.get(key), required_keys=spec["required"])
            if normalized_items:
                merged[key] = normalized_items[: spec["max_items"]]

        return merged

    def _normalize_object_list(self, value: Any, *, required_keys: List[str]) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            cleaned: Dict[str, Any] = {}
            for key, raw in item.items():
                if isinstance(raw, str):
                    text = raw.strip()
                    if text:
                        cleaned[key] = text
                elif isinstance(raw, list):
                    cleaned[key] = [str(entry).strip() for entry in raw if str(entry).strip()]
                elif raw is not None:
                    cleaned[key] = raw
            if all(cleaned.get(required_key) for required_key in required_keys):
                normalized.append(cleaned)
        return normalized


technical_document_llm_service = TechnicalDocumentLLMService()
