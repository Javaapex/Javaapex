import json
import logging
import re
from typing import Any, Dict, List

import httpx

from services.llm_cache_service import build_llm_cache_key, get_cached_llm_response, set_cached_llm_response
from services.llm_context_service import build_version_recommendation_context_pack, context_pack_fingerprint
from utils.config import (
    FORD_LLM_API_ENDPOINT,
    FORD_LLM_API_KEY,
    FORD_LLM_ENABLED,
    FORD_LLM_EXTRA_MODELS,
    FORD_LLM_MAX_TOKENS,
    FORD_LLM_MODEL,
    FORD_LLM_PROXY_URL,
    FORD_LLM_TEMPERATURE,
    FORD_LLM_TIMEOUT,
    FORD_LLM_VERIFY_SSL,
    HF_MODEL,
    HF_RECOMMENDATION_ENDPOINT,
    HF_TOKEN,
    httpx_proxy_kwargs as _proxy_kw,
)


logger = logging.getLogger(__name__)


class HFRecommendationService:
    def __init__(self) -> None:
        # Ford LLM (primary)
        self.ford_llm_enabled = FORD_LLM_ENABLED
        self.ford_llm_api_key = FORD_LLM_API_KEY
        self.ford_llm_api_endpoint = FORD_LLM_API_ENDPOINT
        self.ford_llm_model = FORD_LLM_MODEL
        self.ford_llm_proxy_url = FORD_LLM_PROXY_URL
        self.ford_llm_verify_ssl = FORD_LLM_VERIFY_SSL
        self.ford_llm_timeout = FORD_LLM_TIMEOUT
        self.ford_llm_extra_models = FORD_LLM_EXTRA_MODELS
        # HuggingFace (legacy fallback)
        self.hf_token = HF_TOKEN
        self.endpoint = HF_RECOMMENDATION_ENDPOINT
        self.model = HF_MODEL

    async def recommend_target_version(self, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
        # Use Ford LLM first if available; otherwise fall back to HF_TOKEN
        if not (self.ford_llm_enabled and self.ford_llm_api_key) and not self.hf_token:
            raise ValueError("Neither Ford LLM API key nor HF_TOKEN is configured.")

        prompt_payload = self._build_prompt_payload(analysis_payload)
        cache_key = build_llm_cache_key(
            "hf-recommendation",
            {
                "type": "java_version_recommendation",
                "context": build_version_recommendation_context_pack(prompt_payload),
                "model": self.model,
                "endpoint": self.endpoint,
            },
        )
        cached = get_cached_llm_response(cache_key)
        if cached is not None:
            return cached

        response_data = await self._call_hugging_face(analysis_payload)
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
            raise ValueError("Hugging Face response did not include a valid recommended target version.")
        if not rationale:
            raise ValueError("Hugging Face response did not include rationale.")

        result = {
            "recommended_target_version": recommended_versions[0],
            "recommended_versions": recommended_versions,
            "confidence": str(recommendation.get("confidence", "medium")).lower(),
            "rationale": rationale,
            "alternatives": [option["version"] for option in alternatives],
            "alternative_options": alternatives,
            "raw_recommendation": recommendation,
        }
        set_cached_llm_response(cache_key, result)
        return result

    async def _call_hugging_face(self, analysis_payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt_payload = self._build_prompt_payload(analysis_payload)

        system_content = (
            "You are a Java migration architect. "
            "Recommend one or more target Java versions from the allowed versions in the repository summary. "
            "Recommend only higher versions than the source version. "
            "Prefer LTS versions, minimize migration risk, and return valid JSON only."
        )
        user_content = (
            "Analyze this repository summary and recommend one to three safe target Java versions.\n"
            "Return JSON with keys: recommended_target_version, recommended_versions, confidence, rationale, alternatives.\n"
            "recommended_target_version may be a single version. recommended_versions may be an ordered list.\n"
            "alternatives may be either strings or objects with keys like version, risk, or reason.\n"
            f"Repository summary:\n{json.dumps(prompt_payload, indent=2)}"
        )

        # ── Primary: Ford LLM ──
        if self.ford_llm_enabled and self.ford_llm_api_key:
            try:
                proxy = self.ford_llm_proxy_url or None
                payload: Dict[str, Any] = {
                    "model": self.ford_llm_model,
                    "messages": [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": FORD_LLM_TEMPERATURE,
                    "max_tokens": FORD_LLM_MAX_TOKENS,
                    "response_format": {"type": "json_object"},
                }
                if self.ford_llm_extra_models:
                    payload["extra_body"] = {"models": self.ford_llm_extra_models}

                async with httpx.AsyncClient(
                    timeout=float(self.ford_llm_timeout),
                    **_proxy_kw(proxy),
                    verify=self.ford_llm_verify_ssl,
                ) as client:
                    response = await client.post(
                        self.ford_llm_api_endpoint,
                        headers={
                            "Authorization": f"Bearer {self.ford_llm_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    # Handle models that do not support custom temperature
                    if response.status_code == 400 and "temperature" in (response.text or "").lower():
                        payload.pop("temperature", None)
                        logger.info("Model %s does not support custom temperature; retrying without it", self.ford_llm_model)
                        response = await client.post(
                            self.ford_llm_api_endpoint,
                            headers={
                                "Authorization": f"Bearer {self.ford_llm_api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        )
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                logger.warning("Ford LLM recommendation call failed, falling back to HuggingFace: %s", exc)

        # ── Fallback: HuggingFace ──
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.hf_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            return response.json()

    def _parse_recommendation(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        choices = response_data.get("choices") or []
        if not choices:
            raise ValueError("No choices returned from Hugging Face")

        message = choices[0].get("message") or {}
        content = message.get("content")

        if isinstance(content, list):
            text_chunks = [item.get("text", "") for item in content if isinstance(item, dict)]
            content = "".join(text_chunks)

        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty content returned from Hugging Face")

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
            return re.findall(r"\b(?:8|11|17|21)\b", value)
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

        return [version for version in ["8", "11", "17", "21"] if int(version) > source_number]

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
