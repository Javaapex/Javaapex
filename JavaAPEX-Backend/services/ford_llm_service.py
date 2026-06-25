"""
Ford LLM Service - Direct integration with Ford's internal LLM API.
Uses the OpenAI-compatible /chat/completions endpoint provided by Ford LLM gateway.
Handles OAuth2 token refresh and proxy configuration for Ford's internal network.
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from services.llm_cache_service import build_llm_cache_key, get_cached_llm_response, set_cached_llm_response
from utils.config import (
    FORD_LLM_API_ENDPOINT,
    FORD_LLM_API_KEY,
    FORD_LLM_AUTH_TYPE,
    FORD_LLM_BASE_URL,
    FORD_LLM_ENABLED,
    FORD_LLM_EXTRA_MODELS,
    FORD_LLM_FALLBACK_MODELS,
    FORD_LLM_MAX_RETRIES,
    FORD_LLM_MAX_TOKENS,
    FORD_LLM_MODEL,
    FORD_LLM_OAUTH_CLIENT_ID,
    FORD_LLM_OAUTH_CLIENT_SECRET,
    FORD_LLM_OAUTH_SCOPE,
    FORD_LLM_OAUTH_TOKEN_URL,
    FORD_LLM_PROXY_URL,
    FORD_LLM_TEMPERATURE,
    FORD_LLM_TIMEOUT,
    FORD_LLM_VERIFY_SSL,
    httpx_proxy_kwargs as _proxy_kw,
)

logger = logging.getLogger(__name__)


class FordLLMService:
    """Direct Ford LLM API client using OpenAI-compatible chat/completions endpoint."""

    def __init__(self) -> None:
        self.enabled = FORD_LLM_ENABLED
        self.api_endpoint = FORD_LLM_API_ENDPOINT
        self.base_url = FORD_LLM_BASE_URL
        self.api_key = FORD_LLM_API_KEY
        self.auth_type = FORD_LLM_AUTH_TYPE
        self.model = FORD_LLM_MODEL
        self.extra_models = FORD_LLM_EXTRA_MODELS
        self.fallback_models = FORD_LLM_FALLBACK_MODELS
        self.timeout = FORD_LLM_TIMEOUT
        self.max_retries = FORD_LLM_MAX_RETRIES
        self.temperature = FORD_LLM_TEMPERATURE
        self.max_tokens = FORD_LLM_MAX_TOKENS
        self.proxy_url = FORD_LLM_PROXY_URL
        self.verify_ssl = FORD_LLM_VERIFY_SSL
        # OAuth2 token cache
        self._oauth_token: Optional[str] = None
        self._oauth_token_expiry: float = 0.0

        if self.enabled:
            logger.info(
                "Ford LLM Service initialized (model=%s, fallbacks=%s, endpoint=%s, auth=%s)",
                self.model, self.fallback_models, self.api_endpoint, self.auth_type,
            )
        else:
            logger.info("Ford LLM Service is DISABLED via FORD_LLM_ENABLED=false")

    async def _get_auth_token(self) -> str:
        """Get a valid auth token.

        Uses the centralized token_manager for automatic refresh.
        Falls back to local OAuth2 refresh or static API key if manager is unavailable.
        """
        # Try centralized token manager first (handles auto-refresh)
        try:
            from services.token_manager import ford_token_manager
            if ford_token_manager.is_configured:
                token = ford_token_manager.ensure_fresh_token()
                if token:
                    self.api_key = token  # keep local copy in sync
                    return token
        except Exception:
            pass

        # Fallback: local OAuth2 refresh
        has_oauth = bool(FORD_LLM_OAUTH_TOKEN_URL and FORD_LLM_OAUTH_CLIENT_ID and FORD_LLM_OAUTH_CLIENT_SECRET)
        if has_oauth:
            now = time.time()
            if self._oauth_token and now < self._oauth_token_expiry - 60:
                return self._oauth_token
            return await self._refresh_oauth_token()
        # Static bearer / api_key (no auto-refresh)
        return self.api_key

    async def _refresh_oauth_token(self) -> str:
        """Fetch a new OAuth2 token from Microsoft Entra ID (Azure AD)."""
        if not FORD_LLM_OAUTH_TOKEN_URL:
            raise ValueError("FORD_LLM_OAUTH_TOKEN_URL is not configured for OAuth2 auth.")
        data = {
            "grant_type": "client_credentials",
            "client_id": FORD_LLM_OAUTH_CLIENT_ID,
            "client_secret": FORD_LLM_OAUTH_CLIENT_SECRET,
            "scope": FORD_LLM_OAUTH_SCOPE,
        }
        proxy = self.proxy_url or None
        async with httpx.AsyncClient(timeout=30.0, **_proxy_kw(proxy), verify=self.verify_ssl) as client:
            resp = await client.post(FORD_LLM_OAUTH_TOKEN_URL, data=data)
            resp.raise_for_status()
            token_data = resp.json()
        self._oauth_token = token_data["access_token"]
        self._oauth_token_expiry = time.time() + token_data.get("expires_in", 3600)
        logger.info("Ford LLM OAuth2 token refreshed (expires_in=%s)", token_data.get("expires_in"))
        return self._oauth_token

    def _build_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
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
        """Call Ford LLM chat/completions with automatic model-fallback chain.

        Tries the primary model first; on empty response or hard failure,
        falls through each model in ``self.fallback_models`` before raising.
        """
        if not self.enabled:
            raise ValueError("Ford LLM Service is disabled.")

        # Build ordered list: explicit model (or primary) → fallback models
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
                            "Ford LLM fallback succeeded on model=%s (primary %s failed)",
                            try_model, primary,
                        )
                    return result

                logger.warning(
                    "Ford LLM model %s returned empty content (%d/%d), trying next fallback",
                    try_model, idx + 1, len(models_to_try),
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Ford LLM model %s failed (%d/%d): %s — trying next fallback",
                    try_model, idx + 1, len(models_to_try), exc,
                )

        raise last_exc or ValueError(
            f"Ford LLM: all models exhausted ({', '.join(models_to_try)}), none returned content"
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
        """Call Ford LLM chat/completions for a single model with retries."""
        token = await self._get_auth_token()
        if not token:
            raise ValueError("Ford LLM API key / OAuth token is not available.")

        use_temp = temperature if temperature is not None else self.temperature
        use_max_tokens = max_tokens or self.max_tokens
        url = self.api_endpoint

        headers = self._build_headers(token)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": use_max_tokens,
            "temperature": use_temp,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # Ford LLM gateway uses extra_body for model routing
        if self.extra_models:
            payload["extra_body"] = {"models": self.extra_models}

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

                    if response.status_code == 401:
                        # Token expired — force-refresh via token manager and retry
                        try:
                            from services.token_manager import ford_token_manager
                            if ford_token_manager.is_configured:
                                token = ford_token_manager.force_refresh()
                            else:
                                token = await self._refresh_oauth_token()
                        except Exception:
                            token = await self._refresh_oauth_token()
                        headers = self._build_headers(token)
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
                        # max_tokens might be too high — auto-reduce and retry
                        use_max_tokens = max(512, use_max_tokens // 2)
                        payload["max_tokens"] = use_max_tokens
                        logger.warning("Ford LLM 422 — reducing max_tokens to %d", use_max_tokens)
                        continue

                    response.raise_for_status()
                    data = response.json()

                    text = self._extract_text(data)
                    return {
                        "provider": "ford_llm",
                        "model": model,
                        "text": text,
                        "usage": self._extract_usage(data),
                        "data": data,
                    }
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                logger.warning(
                    "Ford LLM [%s] attempt %d/%d failed (HTTP %d): %s",
                    model, attempt, self.max_retries, status, exc.response.text[:300],
                )
                if status in (504, 502, 503, 429):
                    await asyncio.sleep(min(2 ** attempt, 10))
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning("Ford LLM [%s] attempt %d/%d failed: %s", model, attempt, self.max_retries, exc)
                await asyncio.sleep(min(2 ** attempt, 10))

        raise last_exc or ValueError(f"Ford LLM [{model}]: all retry attempts exhausted")

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

        # Check cache
        cache_key = build_llm_cache_key("ford-llm", {"prompt": prompt, "system": system_prompt, "model": model or self.model})
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
            logger.error("FordLLMService.generate error: %s", e)
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

        logger.warning("Ford LLM response contained no extractable text. Keys: %s", list(data.keys()))
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
