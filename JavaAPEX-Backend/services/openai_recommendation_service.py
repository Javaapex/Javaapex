import json
import logging
import re
from typing import Any, Dict, List

from services.llm_context_service import build_version_recommendation_context_pack, context_pack_fingerprint
from services.preferred_llm_service import preferred_llm_service


logger = logging.getLogger(__name__)


class OpenAIRecommendationService:
    def __init__(self) -> None:
        self.primary_provider = "groq"
        self.secondary_provider = "openai"
        self.fallback_provider = "openai"

    async def recommend_target_version(self, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_versions = self._get_allowed_versions(analysis_payload)
        if not allowed_versions:
            raise ValueError("No higher Java target versions are available for recommendation.")

        llm_result = await self._call_llm(analysis_payload, allowed_versions)
        recommendation = self._parse_recommendation(llm_result["text"])

        recommended_versions = self._normalize_versions(
            recommendation.get("recommended_target_version")
            or recommendation.get("recommended_versions")
            or recommendation.get("target_versions"),
            allowed_versions,
        )
        alternatives = self._normalize_option_objects(
            recommendation.get("alternatives")
            or recommendation.get("alternative_versions")
            or recommendation.get("alternative_options"),
            allowed_versions,
        )
        rationale = self._normalize_rationale(recommendation)

        if not recommended_versions:
            raise ValueError("LLM response did not include a valid recommended target version.")
        if not rationale:
            raise ValueError("LLM response did not include rationale.")

        return {
            "recommended_target_version": recommended_versions[0],
            "recommended_versions": recommended_versions,
            "confidence": str(recommendation.get("confidence", "medium")).lower(),
            "rationale": rationale,
            "alternatives": [option["version"] for option in alternatives],
            "alternative_options": alternatives,
            "provider_used": llm_result["provider"],
            "raw_recommendation": recommendation,
        }

    async def _call_llm(self, analysis_payload: Dict[str, Any], allowed_versions: List[str]) -> Dict[str, str]:
        prompt_payload = self._build_prompt_payload(analysis_payload, allowed_versions)
        context_key = context_pack_fingerprint(
            {
                "type": "java_version_recommendation",
                "context": build_version_recommendation_context_pack(prompt_payload),
            }
        )
        system_prompt = (
            "You are a Java migration architect. "
            "Recommend one to three safe target Java versions. "
            "Only recommend higher versions than the source version. "
            "Prefer LTS versions when possible, minimize migration risk, "
            "and return valid JSON only."
        )
        user_prompt = (
            "Analyze this repository summary and recommend safe Java upgrade targets.\n"
            "Return JSON with keys: recommended_target_version, recommended_versions, "
            "confidence, rationale, alternatives.\n"
            "alternatives may be strings or objects with version, risk, and reason.\n"
            f"Repository summary:\n{json.dumps(prompt_payload, indent=2)}"
        )
        return await preferred_llm_service.request_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1500,
            temperature=0.2,
            json_mode=True,
            cache_key=context_key,
        )

    def _parse_recommendation(self, response_text: str) -> Dict[str, Any]:
        stripped = (response_text or "").strip()
        if not stripped:
            raise ValueError("OpenAI returned an empty recommendation.")

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            json_match = re.search(r"\{.*\}", stripped, re.DOTALL)
            if not json_match:
                raise ValueError("LLM response did not contain valid JSON.") from None
            return json.loads(json_match.group(0))

    def _normalize_rationale(self, recommendation: Dict[str, Any]) -> List[str]:
        candidates = [
            recommendation.get("rationale"),
            recommendation.get("reasons"),
            recommendation.get("explanation"),
            recommendation.get("reasoning"),
        ]
        normalized: List[str] = []
        for candidate in candidates:
            if isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, str) and item.strip():
                        normalized.append(item.strip())
                    elif isinstance(item, dict):
                        text = item.get("reason") or item.get("text") or item.get("description")
                        if isinstance(text, str) and text.strip():
                            normalized.append(text.strip())
            elif isinstance(candidate, str) and candidate.strip():
                normalized.extend(
                    [line.strip("- ").strip() for line in candidate.splitlines() if line.strip()]
                )

        deduped: List[str] = []
        for item in normalized:
            if item and item not in deduped:
                deduped.append(item)
        return deduped

    def _extract_version_tokens(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return re.findall(r"\b(?:8|11|17|21|22|23|24)\b", value)
        if isinstance(value, (int, float)):
            return [str(int(value))]
        if isinstance(value, list):
            tokens: List[str] = []
            for item in value:
                tokens.extend(self._extract_version_tokens(item))
            return tokens
        if isinstance(value, dict):
            tokens: List[str] = []
            for key in ("version", "target_version", "value", "recommended_target_version"):
                if key in value:
                    tokens.extend(self._extract_version_tokens(value.get(key)))
            return tokens
        return []

    def _normalize_versions(self, value: Any, allowed_versions: List[str]) -> List[str]:
        normalized: List[str] = []
        for token in self._extract_version_tokens(value):
            if token in allowed_versions and token not in normalized:
                normalized.append(token)
        return normalized

    def _normalize_option_objects(self, value: Any, allowed_versions: List[str]) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: List[Dict[str, Any]] = []
        seen_versions = set()
        for item in value:
            versions = self._normalize_versions(item, allowed_versions)
            if not versions:
                continue
            version = versions[0]
            if version in seen_versions:
                continue
            seen_versions.add(version)

            option: Dict[str, Any] = {"version": version}
            if isinstance(item, dict):
                risk = item.get("risk")
                reason = item.get("reason") or item.get("description") or item.get("text")
                if isinstance(risk, str) and risk.strip():
                    option["risk"] = risk.strip()
                if isinstance(reason, str) and reason.strip():
                    option["reason"] = reason.strip()
            normalized.append(option)
        return normalized

    def _get_allowed_versions(self, analysis_payload: Dict[str, Any]) -> List[str]:
        source_version = str(
            analysis_payload.get("source_java_version")
            or analysis_payload.get("detected_java_version")
            or ""
        ).strip()
        try:
            source_number = int(source_version)
        except ValueError:
            source_number = 0
        return [version for version in ["8", "11", "17", "21", "22", "23", "24"] if int(version) > source_number]

    def _build_prompt_payload(self, analysis_payload: Dict[str, Any], allowed_versions: List[str]) -> Dict[str, Any]:
        dependencies = analysis_payload.get("dependencies") or []
        return {
            "source_java_version": analysis_payload.get("source_java_version"),
            "detected_java_version": analysis_payload.get("detected_java_version"),
            "build_tool": analysis_payload.get("build_tool"),
            "risk_level": analysis_payload.get("risk_level"),
            "has_tests": analysis_payload.get("has_tests"),
            "api_endpoint_count": analysis_payload.get("api_endpoint_count"),
            "allowed_target_versions": allowed_versions,
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


openai_recommendation_service = OpenAIRecommendationService()
