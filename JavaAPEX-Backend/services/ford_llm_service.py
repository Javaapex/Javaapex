"""
Groq LLM Service - Direct integration with Groq's API (replaces Ford LLM).
Uses the OpenAI-compatible /chat/completions endpoint provided by Groq.
Simple API key auth — no OAuth needed.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from services.llm_cache_service import build_llm_cache_key, get_cached_llm_response, set_cached_llm_response
from utils.config import (
    FORD_LLM_API_ENDPOINT,
    FORD_LLM_API_KEY,
    FORD_LLM_ENABLED,
    FORD_LLM_EXTRA_MODELS,
    FORD_LLM_FALLBACK_MODELS,
    FORD_LLM_MAX_RETRIES,
    FORD_LLM_MAX_TOKENS,
    FORD_LLM_MODEL,
    FORD_LLM_PROXY_URL,
    FORD_LLM_TEMPERATURE,
    FORD_LLM_TIMEOUT,
    FORD_LLM_VERIFY_SSL,
    httpx_proxy_kwargs as _proxy_kw,
)

logger = logging.getLogger(__name__)


class FordLLMService:
    """Groq API client using OpenAI-compatible chat/completions endpoint (replaces Ford LLM)."""

    def __init__(self) -> None:
        self.enabled = FORD_LLM_ENABLED
        self.api_endpoint = FORD_LLM_API_ENDPOINT
        self.api_key = FORD_LLM_API_KEY
        self.model = FORD_LLM_MODEL
        self.extra_models = FORD_LLM_EXTRA_MODELS
        self.fallback_models = FORD_LLM_FALLBACK_MODELS
        self.timeout = FORD_LLM_TIMEOUT
        self.max_retries = FORD_LLM_MAX_RETRIES
        self.temperature = FORD_LLM_TEMPERATURE
        self.max_tokens = FORD_LLM_MAX_TOKENS
        self.proxy_url = FORD_LLM_PROXY_URL
        self.verify_ssl = FORD_LLM_VERIFY_SSL

        if self.enabled:
            logger.info(
                "Groq LLM Service initialized (model=%s, fallbacks=%s, endpoint=%s)",
                self.model, self.fallback_models, self.api_endpoint,
            )
        else:
            logger.info("Groq LLM Service is DISABLED via FORD_LLM_ENABLED=false")

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Call Groq chat/completions with automatic model-fallback chain."""
        if not self.enabled:
            raise ValueError("Groq LLM Service is disabled.")

        primary = model or self.model
        models_to_try = [primary] + [m for m in self.fallback_models if m != primary]

        last_exc: Optional[Exception] = None
        for idx, try_model in enumerate(models_to_try):
            try:
                result = await self._chat_completion_single(
                    messages,
                    model=try_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
                text = result.get("text", "")
                if text and text.strip():
                    if idx > 0:
                        logger.info(
                            "Groq LLM fallback succeeded on model=%s (primary %s failed)",
                            try_model, primary,
                        )
                    return result

                logger.warning(
                    "Groq LLM model %s returned empty content (%d/%d), trying next fallback",
                    try_model, idx + 1, len(models_to_try),
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Groq LLM model %s failed (%d/%d): %s — trying next fallback",
                    try_model, idx + 1, len(models_to_try), exc,
                )

        raise last_exc or ValueError(
            f"Groq LLM: all models exhausted ({', '.join(models_to_try)}), none returned content"
        )

    async def _chat_completion_single(
        self,
        messages: List[Dict[str, str]],
        *,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Call Groq chat/completions for a single model with retries."""
        if not self.api_key:
            raise ValueError("Groq API key is not available. Set GROQ_API_KEY in .env.")

        use_temp = temperature if temperature is not None else self.temperature
        use_max_tokens = max_tokens or self.max_tokens
        url = self.api_endpoint

        headers = self._build_headers()
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": use_max_tokens,
            "temperature": use_temp,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        proxy = self.proxy_url or None
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=float(self.timeout),
                    **_proxy_kw(proxy),
                    verify=self.verify_ssl,
                ) as client:
                    response = await client.post(url, headers=headers, json=payload)

                    if response.status_code == 400:
                        body_text = (response.text or "").lower()
                        if "temperature" in body_text:
                            payload.pop("temperature", None)
                            logger.info(
                                "Model %s does not support custom temperature; retrying without it",
                                model,
                            )
                            continue

                    if response.status_code == 422:
                        use_max_tokens = max(512, use_max_tokens // 2)
                        payload["max_tokens"] = use_max_tokens
                        logger.warning("Groq LLM 422 — reducing max_tokens to %d", use_max_tokens)
                        continue

                    response.raise_for_status()
                    data = response.json()

                    text = self._extract_text(data)
                    return {
                        "provider": "groq",
                        "model": model,
                        "text": text,
                        "usage": self._extract_usage(data),
                        "data": data,
                    }
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                logger.warning(
                    "Groq LLM [%s] attempt %d/%d failed (HTTP %d): %s",
                    model, attempt, self.max_retries, status, exc.response.text[:300],
                )
                if status in (504, 502, 503, 429):
                    await asyncio.sleep(min(2 ** attempt, 10))
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning("Groq LLM [%s] attempt %d/%d failed: %s", model, attempt, self.max_retries, exc)
                await asyncio.sleep(min(2 ** attempt, 10))

        raise last_exc or ValueError(f"Groq LLM [{model}]: all retry attempts exhausted")

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        model: Optional[str] = None,
    ) -> Any:
        """High-level generate interface (backwards-compatible with FordLLMServiceBridge)."""
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        cache_key = build_llm_cache_key("groq", {"prompt": prompt, "system": system_prompt, "model": model or self.model})
        cached = get_cached_llm_response(cache_key)
        if cached is not None:
            class CachedResponse:
                def __init__(self, content):
                    self.content = content
                    self.success = True
            return CachedResponse(cached)

        try:
            result = await self.chat_completion(
                messages, model=model, temperature=temperature, max_tokens=max_tokens,
            )

            class LLMResponse:
                def __init__(self, content):
                    self.content = content
                    self.success = True if content else False

            text = result.get("text", "")
            try:
                set_cached_llm_response(cache_key, text)
            except Exception:
                pass
            return LLMResponse(text)
        except Exception as e:
            logger.error("GroqLLMService.generate error: %s", e)
            class FailedResponse:
                def __init__(self):
                    self.content = ""
                    self.success = False
            return FailedResponse()

    def _extract_text(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message") if isinstance(choice, dict) else None

            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

                rc = message.get("reasoning_content")
                if isinstance(rc, str) and rc.strip():
                    logger.info("Extracted text from reasoning_content field")
                    return rc.strip()

                parts = message.get("parts") or message.get("content_parts")
                if isinstance(parts, list):
                    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
                    if texts:
                        logger.info("Extracted text from parts field (%d parts)", len(texts))
                        return "\n".join(texts)

                refusal = message.get("refusal")
                if isinstance(refusal, str) and refusal.strip():
                    logger.warning("Model refused request: %s", refusal[:200])
                    return ""

            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict):
                dc = delta.get("content")
                if isinstance(dc, str) and dc.strip():
                    return dc.strip()

        output = data.get("output")
        if isinstance(output, str) and output.strip():
            logger.info("Extracted text from top-level output field")
            return output.strip()

        text = data.get("text")
        if isinstance(text, str) and text.strip():
            logger.info("Extracted text from top-level text field")
            return text.strip()

        logger.warning("Groq LLM response contained no extractable text. Keys: %s", list(data.keys()))
        return ""

    def _extract_usage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        usage = data.get("usage")
        if isinstance(usage, dict):
            return {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        return {}


ford_llm_service = FordLLMService()
