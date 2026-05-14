import json
import logging
import os
import re
import asyncio
from typing import Any, Dict, List

import httpx
from openai import OpenAI


logger = logging.getLogger(__name__)


class HFRecommendationService:
    def __init__(self) -> None:
        from services.fordllm_auth_service import fordllm_auth
        self._auth = fordllm_auth
        self.base_url = os.getenv("FORDLLM_BASE_URL", "https://api.pivpn.core.ford.com/fordllmapi/api/v1")
        self.model = os.getenv("FORDLLM_MODEL", "fordllm-coding-model")
        self.sub_model = os.getenv("FORDLLM_SUB_MODEL", "gemini-2.5-pro")

    def _get_client(self) -> OpenAI:
        return OpenAI(api_key=self._auth.token, base_url=self.base_url)

    async def recommend_target_version(self, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._auth.client_id:
            raise ValueError("FORDLLM_CLIENT_ID is not configured.")

        response_data = await self._call_fordllm(analysis_payload)
        recommendation = self._parse_recommendation(response_data)

        allowed_versions = self._get_allowed_versions(analysis_payload)
        recommended_versions = self._normalize_versions(
            recommendation.get("recommended_target_version")
            or recommendation.get("recommended_versions")
            or recommendation.get("recommendedTargets")
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
            raise ValueError("FordLLM response did not include a valid recommended target version.")
        if not rationale:
            raise ValueError("FordLLM response did not include rationale.")

        return {
            "recommended_target_version": recommended_versions[0],
            "recommended_versions": recommended_versions,
            "confidence": str(recommendation.get("confidence", "medium")).lower(),
            "rationale": rationale,
            "alternatives": [option["version"] for option in alternatives],
            "alternative_options": alternatives,
            "raw_recommendation": recommendation,
        }

    async def _call_fordllm(self, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt_payload = self._build_prompt_payload(analysis_payload)
        client = self._get_client()

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Java migration architect. "
                    "Recommend one or more target Java versions from the allowed versions in the repository summary. "
                    "Recommend only higher versions than the source version. "
                    "Prefer LTS versions, minimize migration risk, and return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this repository summary and recommend one to three safe target Java versions.\n"
                    "Return JSON with keys: recommended_target_version, recommended_versions, confidence, rationale, alternatives.\n"
                    "recommended_target_version may be a single version. recommended_versions may be an ordered list.\n"
                    "alternatives may be either strings or objects with keys like version, risk, or reason.\n"
                    f"Repository summary:\n{json.dumps(prompt_payload, indent=2)}"
                ),
            },
        ]

        loop = asyncio.get_event_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                extra_body={"models": [self.sub_model]},
            ),
        )

        # Convert to dict format matching the old response structure
        return {
            "choices": [
                {
                    "message": {
                        "content": completion.choices[0].message.content or ""
                    }
                }
            ]
        }

    def _parse_recommendation(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        choices = response_data.get("choices") or []
        if not choices:
            raise ValueError("No choices returned from FordLLM")

        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, list):
            text_chunks = [item.get("text", "") for item in content if isinstance(item, dict)]
            content = "".join(text_chunks)

        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty content returned from FordLLM")

        return json.loads(content)

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
                split_lines = [line.strip("- ").strip() for line in candidate.splitlines() if line.strip()]
                normalized.extend([line for line in split_lines if line])
            elif isinstance(candidate, dict):
                text = candidate.get("reason") or candidate.get("text") or candidate.get("description")
                if isinstance(text, str) and text.strip():
                    normalized.append(text.strip())

        deduped: List[str] = []
        for item in normalized:
            if item not in deduped:
                deduped.append(item)

        return deduped

    def _extract_version_tokens(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return re.findall(r"\b(?:8|11|17|21|25)\b", value)
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

        return [version for version in ["8", "11", "17", "21", "25"] if int(version) > source_number]

    def _build_prompt_payload(self, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
        dependencies = analysis_payload.get("dependencies") or []
        allowed_versions = self._get_allowed_versions(analysis_payload)

        return {
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
                for dep in dependencies[:20]
                if isinstance(dep, dict)
            ],
        }
