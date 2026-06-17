import json
import logging
import re
import time
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from services.llm_cache_service import build_llm_cache_key, get_cached_llm_response, set_cached_llm_response
from utils.config import (
    FORD_LLM_API_ENDPOINT,
    FORD_LLM_API_KEY,
    FORD_LLM_BASE_URL,
    FORD_LLM_ENABLED,
    FORD_LLM_EXTRA_MODELS,
    FORD_LLM_MAX_RETRIES,
    FORD_LLM_MAX_TOKENS,
    FORD_LLM_MODEL,
    FORD_LLM_PROXY_URL,
    FORD_LLM_TEMPERATURE,
    FORD_LLM_TIMEOUT,
    FORD_LLM_VERIFY_SSL,
    FORD_LLM_AUTH_TYPE,
    ANTHROPIC_API_KEY,
    ANTHROPIC_API_VERSION,
    ANTHROPIC_BASE_URL,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_TEST_MODEL,
    CHATGPT_API_KEY,
    CHATGPT_BASE_URL,
    CHATGPT_MODEL,
    CLAUDE_MODEL,
    httpx_proxy_kwargs as _proxy_kw,
)


logger = logging.getLogger(__name__)


class PreferredLLMService:
    def __init__(self) -> None:
        # Ford LLM (primary)
        self.ford_llm_enabled = FORD_LLM_ENABLED
        self.ford_llm_api_endpoint = FORD_LLM_API_ENDPOINT
        self.ford_llm_base_url = FORD_LLM_BASE_URL
        self.ford_llm_api_key = FORD_LLM_API_KEY
        self.ford_llm_auth_type = FORD_LLM_AUTH_TYPE
        self.ford_llm_model = FORD_LLM_MODEL
        self.ford_llm_extra_models = FORD_LLM_EXTRA_MODELS
        self.ford_llm_timeout = FORD_LLM_TIMEOUT
        self.ford_llm_max_retries = FORD_LLM_MAX_RETRIES
        self.ford_llm_temperature = FORD_LLM_TEMPERATURE
        self.ford_llm_max_tokens = FORD_LLM_MAX_TOKENS
        self.ford_llm_proxy_url = FORD_LLM_PROXY_URL
        self.ford_llm_verify_ssl = FORD_LLM_VERIFY_SSL
        # OAuth fields removed — Groq uses simple API key auth
        # Legacy fallbacks
        self.groq_api_key = GROQ_API_KEY
        self.groq_base_url = GROQ_BASE_URL.rstrip("/")
        self.groq_model = GROQ_TEST_MODEL
        self.claude_api_key = ANTHROPIC_API_KEY
        self.claude_base_url = ANTHROPIC_BASE_URL.rstrip("/")
        self.claude_api_version = ANTHROPIC_API_VERSION
        self.claude_model = CLAUDE_MODEL
        self.openai_api_key = CHATGPT_API_KEY
        self.openai_base_url = CHATGPT_BASE_URL.rstrip("/")
        self.openai_model = CHATGPT_MODEL
        self.chatgpt_api_key = self.openai_api_key
        self.chatgpt_base_url = self.openai_base_url
        self.chatgpt_model = self.openai_model

    # ── Strategy-router LLM methods (Ford LLM primary → Groq fallback) ──

    async def request_text_groq(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        json_mode: bool = False,
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        cache_token = None
        if cache_key:
            cache_token = build_llm_cache_key(
                "groq-llm",
                {
                    "cache_key": cache_key,
                    "system_prompt": system_prompt or "",
                    "user_prompt": user_prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "json_mode": json_mode,
                },
            )
            cached = get_cached_llm_response(cache_token)
            if cached is not None:
                return {**cached, "cached": True}

        failures = []

        # Try Ford LLM first when enabled
        if self.ford_llm_enabled and self.ford_llm_api_key:
            try:
                result = await self._call_ford_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=json_mode,
                )
                if cache_token:
                    set_cached_llm_response(cache_token, result)
                return result
            except Exception as exc:
                failures.append(f"Ford LLM failed: {exc}")
                logger.warning("Ford LLM strategy request failed, trying Groq: %s", exc)

        # Groq fallback
        try:
            result = await self._call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            if cache_token:
                set_cached_llm_response(cache_token, result)
            return result
        except Exception as exc:
            failures.append(f"Groq failed: {exc}")

        raise ValueError("; ".join(failures) or "No strategy LLM provider available.")

    async def request_json_groq(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = await self.request_text_groq(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
            cache_key=cache_key,
        )
        return {
            **result,
            "parsed": self._parse_json_payload(result["text"]),
        }

    async def request_text_stream_groq(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        cache_key: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        cache_token = None
        if cache_key:
            cache_token = build_llm_cache_key(
                "groq-llm-stream",
                {
                    "cache_key": cache_key,
                    "system_prompt": system_prompt or "",
                    "user_prompt": user_prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            cached = get_cached_llm_response(cache_token)
            if cached is not None:
                text = cached.get("text") or ""
                yield {
                    "type": "provider",
                    "provider": cached.get("provider"),
                    "model": cached.get("model"),
                    "cached": True,
                }
                if text:
                    yield {"type": "delta", "text": text}
                yield {"type": "final", **cached, "cached": True}
                return

        # Build provider list: Ford LLM first (if enabled), then Groq
        providers = []
        if self.ford_llm_enabled and self.ford_llm_api_key:
            providers.append(("ford_llm", self._stream_ford_llm))
        if self.groq_api_key:
            providers.append(("groq", self._stream_groq))

        if not providers:
            raise ValueError("No LLM streaming provider is configured (Ford LLM disabled and GROQ_API_KEY not set).")

        failures = []
        for provider_name, stream_fn in providers:
            started_at = time.perf_counter()
            full_text = ""
            usage: Dict[str, Any] = {}
            provider_out = provider_name
            model_out = ""
            try:
                async for event in stream_fn(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    event_type = event.get("type")
                    if event_type == "provider":
                        provider_out = str(event.get("provider") or provider_out)
                        model_out = str(event.get("model") or model_out)
                        yield event
                    elif event_type == "delta":
                        text = event.get("text")
                        if isinstance(text, str) and text:
                            full_text += text
                            yield {"type": "delta", "text": text}
                    elif event_type == "usage":
                        event_usage = event.get("usage")
                        if isinstance(event_usage, dict):
                            usage = event_usage
                    elif event_type == "final":
                        if isinstance(event.get("usage"), dict):
                            usage = event.get("usage")
                        model_out = str(event.get("model") or model_out)

                result = {
                    "provider": provider_out,
                    "model": model_out,
                    "text": full_text,
                    "usage": usage,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                }
                if cache_token:
                    set_cached_llm_response(cache_token, result)
                yield {"type": "final", **result}
                return  # success — stop trying other providers
            except Exception as exc:
                failures.append(f"{provider_name} stream failed: {exc}")
                logger.warning("%s streaming failed, trying next: %s", provider_name, exc)
                if full_text:
                    yield {
                        "type": "final",
                        "provider": provider_out,
                        "model": model_out or provider_out,
                        "text": full_text,
                        "usage": usage,
                        "latency_ms": int((time.perf_counter() - started_at) * 1000),
                        "partial": True,
                    }
                    return

        # ── Last resort: non-streaming Ford LLM call, emitted as chunks ──
        if self.ford_llm_enabled and self.ford_llm_api_key:
            try:
                logger.info("All streaming providers failed; falling back to non-streaming Ford LLM call")
                result = await self._call_ford_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=False,
                )
                full_text = result.get("text") or ""
                yield {"type": "provider", "provider": result.get("provider", "ford_llm"), "model": result.get("model", self.ford_llm_model)}
                # Emit in small chunks to simulate streaming
                chunk_size = 80
                for i in range(0, len(full_text), chunk_size):
                    yield {"type": "delta", "text": full_text[i : i + chunk_size]}
                if cache_token:
                    set_cached_llm_response(cache_token, result)
                yield {"type": "final", **result}
                return
            except Exception as exc:
                failures.append(f"Ford LLM non-stream fallback failed: {exc}")
                logger.warning("Ford LLM non-streaming fallback also failed: %s", exc)

        raise ValueError("; ".join(failures) or "All streaming providers failed.")

    # ── Multi-provider methods (Ford LLM primary) ──

    async def request_text(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        json_mode: bool = False,
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        cache_token = None
        if cache_key:
            cache_token = build_llm_cache_key(
                "preferred-llm",
                {
                    "cache_key": cache_key,
                    "system_prompt": system_prompt or "",
                    "user_prompt": user_prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "json_mode": json_mode,
                },
            )
            cached = get_cached_llm_response(cache_token)
            if cached is not None:
                return {**cached, "cached": True}

        failures = []

        # ── Primary: Ford LLM ──
        if self.ford_llm_enabled and self.ford_llm_api_key:
            try:
                result = await self._call_ford_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=json_mode,
                )
                if cache_token:
                    set_cached_llm_response(cache_token, result)
                return result
            except Exception as exc:
                failures.append(f"Ford LLM failed: {exc}")
                logger.warning("Ford LLM primary request failed, trying Groq fallback: %s", exc)

        # ── Fallback 1: Groq ──
        try:
            result = await self._call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            if cache_token:
                set_cached_llm_response(cache_token, result)
            return result
        except Exception as exc:
            failures.append(f"Groq failed: {exc}")
            logger.warning("Groq primary request failed, trying Claude secondary: %s", exc)

        try:
            result = await self._call_claude(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            if cache_token:
                set_cached_llm_response(cache_token, result)
            return result
        except Exception as exc:
            failures.append(f"Claude failed: {exc}")
            logger.warning("Claude secondary request failed, trying OpenAI fallback: %s", exc)

        try:
            result = await self._call_openai(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            if cache_token:
                set_cached_llm_response(cache_token, result)
            return result
        except Exception as exc:
            failures.append(f"OpenAI failed: {exc}")
            logger.warning("OpenAI fallback request failed: %s", exc)

        raise ValueError("; ".join(failures) or "No configured LLM provider is available.")

    async def request_json(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = await self.request_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
            cache_key=cache_key,
        )
        return {
            **result,
            "parsed": self._parse_json_payload(result["text"]),
        }

    async def request_text_stream(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.2,
        cache_key: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        cache_token = None
        if cache_key:
            cache_token = build_llm_cache_key(
                "preferred-llm-stream",
                {
                    "cache_key": cache_key,
                    "system_prompt": system_prompt or "",
                    "user_prompt": user_prompt,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            cached = get_cached_llm_response(cache_token)
            if cached is not None:
                text = cached.get("text") or ""
                yield {
                    "type": "provider",
                    "provider": cached.get("provider"),
                    "model": cached.get("model"),
                    "cached": True,
                }
                if text:
                    yield {"type": "delta", "text": text}
                yield {"type": "final", **cached, "cached": True}
                return

        failures: list[str] = []
        provider_streams = []
        if self.ford_llm_enabled and self.ford_llm_api_key:
            provider_streams.append(("ford_llm", self._stream_ford_llm))
        provider_streams.extend([
            ("groq", self._stream_groq),
            ("claude", self._stream_claude),
            ("openai", self._stream_openai),
        ])

        for provider_name, stream_callable in provider_streams:
            started_at = time.perf_counter()
            full_text = ""
            usage: Dict[str, Any] = {}
            model_name = ""
            try:
                async for event in stream_callable(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    event_type = event.get("type")
                    if event_type == "provider":
                        provider_name = str(event.get("provider") or provider_name)
                        model_name = str(event.get("model") or model_name)
                        yield event
                    elif event_type == "delta":
                        text = event.get("text")
                        if isinstance(text, str) and text:
                            full_text += text
                            yield {"type": "delta", "text": text}
                    elif event_type == "usage":
                        event_usage = event.get("usage")
                        if isinstance(event_usage, dict):
                            usage = event_usage
                    elif event_type == "final":
                        model_name = str(event.get("model") or model_name)
                        event_usage = event.get("usage")
                        if isinstance(event_usage, dict):
                            usage = event_usage
                        if not model_name:
                            model_name = str(event.get("model") or "")

                result = {
                    "provider": provider_name,
                    "model": model_name,
                    "text": full_text,
                    "usage": usage,
                    "latency_ms": int((time.perf_counter() - started_at) * 1000),
                }
                if cache_token:
                    set_cached_llm_response(cache_token, result)
                yield {"type": "final", **result}
                return
            except Exception as exc:
                failures.append(f"{provider_name} failed: {exc}")
                logger.warning("%s streaming request failed, trying next provider: %s", provider_name, exc)
                if full_text:
                    yield {
                        "type": "final",
                        "provider": provider_name,
                        "model": model_name or provider_name,
                        "text": full_text,
                        "usage": usage,
                        "latency_ms": int((time.perf_counter() - started_at) * 1000),
                        "partial": True,
                    }
                    return

        # ── Last resort: non-streaming Ford LLM call ──
        if self.ford_llm_enabled and self.ford_llm_api_key:
            try:
                logger.info("All streaming providers failed; falling back to non-streaming Ford LLM")
                result = await self._call_ford_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=False,
                )
                full_text = result.get("text") or ""
                yield {"type": "provider", "provider": result.get("provider", "ford_llm"), "model": result.get("model", self.ford_llm_model)}
                chunk_size = 80
                for i in range(0, len(full_text), chunk_size):
                    yield {"type": "delta", "text": full_text[i : i + chunk_size]}
                if cache_token:
                    set_cached_llm_response(cache_token, result)
                yield {"type": "final", **result}
                return
            except Exception as exc:
                failures.append(f"Ford LLM non-stream fallback failed: {exc}")
                logger.warning("Ford LLM non-streaming fallback also failed: %s", exc)

        raise ValueError("; ".join(failures) or "No configured LLM provider is available.")

    async def _get_ford_auth_token(self) -> str:
        """Return the Groq API key (replaces Ford OAuth token flow)."""
        return self.ford_llm_api_key

    async def _call_ford_llm(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> Dict[str, str]:
        """Call Groq API via OpenAI-compatible chat/completions (replaces Ford LLM)."""
        token = await self._get_ford_auth_token()
        if not token:
            raise ValueError("Groq API key is not available. Set GROQ_API_KEY in .env.")

        url = self.ford_llm_api_endpoint
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.ford_llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        proxy = self.ford_llm_proxy_url or None
        started_at = time.perf_counter()
        async with httpx.AsyncClient(
            timeout=float(self.ford_llm_timeout),
            **_proxy_kw(proxy),
            verify=self.ford_llm_verify_ssl,
        ) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 400 and "temperature" in (response.text or "").lower():
                payload.pop("temperature", None)
                logger.info("Model %s does not support custom temperature; retrying without it", self.ford_llm_model)
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return {
            "provider": "groq",
            "model": self.ford_llm_model,
            "text": self._extract_openai_text(data),
            "usage": self._extract_usage(data),
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _call_groq(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> Dict[str, str]:
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        url = f"{self.groq_base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.groq_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return {
            "provider": "groq",
            "model": self.groq_model,
            "text": self._extract_openai_text(data),
            "usage": self._extract_usage(data),
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _call_claude(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> Dict[str, str]:
        if not self.claude_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured.")

        url = self.claude_base_url
        if not url.endswith("/messages"):
            url = f"{url}/messages"

        headers = {
            "x-api-key": self.claude_api_key,
            "anthropic-version": self.claude_api_version,
            "content-type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.claude_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["messages"][0]["content"] = f"{user_prompt}\n\nReturn valid JSON only."

        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return {
            "provider": "claude",
            "model": self.claude_model,
            "text": self._extract_claude_text(data),
            "usage": self._extract_usage(data),
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _call_openai(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> Dict[str, str]:
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is not configured.")

        url = f"{self.openai_base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.openai_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return {
            "provider": "openai",
            "model": self.openai_model,
            "text": self._extract_openai_text(data),
            "usage": self._extract_usage(data),
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _call_chatgpt(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> Dict[str, str]:
        return await self._call_openai(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
        )

    # ── Streaming internal methods ──

    async def _stream_ford_llm(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream from Groq API via OpenAI-compatible SSE (replaces Ford LLM)."""
        token = await self._get_ford_auth_token()
        if not token:
            raise ValueError("Groq API key is not available. Set GROQ_API_KEY in .env.")

        url = self.ford_llm_api_endpoint
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload: Dict[str, Any] = {
            "model": self.ford_llm_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        yield {"type": "provider", "provider": "groq", "model": self.ford_llm_model}
        usage: Dict[str, Any] = {}
        proxy = self.ford_llm_proxy_url or None
        started_at = time.perf_counter()
        async with httpx.AsyncClient(
            timeout=float(self.ford_llm_timeout),
            **_proxy_kw(proxy),
            verify=self.ford_llm_verify_ssl,
        ) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_text = line.replace("data:", "", 1).strip()
                    if data_text == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                        usage = self._extract_usage(chunk)
                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    if isinstance(choices, list) and choices:
                        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                        text = delta.get("content") if isinstance(delta, dict) else None
                        if isinstance(text, str) and text:
                            yield {"type": "delta", "text": text}

        yield {
            "type": "final",
            "provider": "groq",
            "model": self.ford_llm_model,
            "usage": usage,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _stream_groq(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        url = f"{self.groq_base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.groq_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        yield {"type": "provider", "provider": "groq", "model": self.groq_model}
        usage: Dict[str, Any] = {}
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_text = line.replace("data:", "", 1).strip()
                    if data_text == "[DONE]":
                        break
                    chunk = json.loads(data_text)
                    if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                        usage = self._extract_usage(chunk)
                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    if isinstance(choices, list) and choices:
                        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                        text = delta.get("content") if isinstance(delta, dict) else None
                        if isinstance(text, str) and text:
                            yield {"type": "delta", "text": text}

        yield {
            "type": "final",
            "provider": "groq",
            "model": self.groq_model,
            "usage": usage,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _stream_openai(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is not configured.")

        url = f"{self.openai_base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.openai_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        yield {"type": "provider", "provider": "openai", "model": self.openai_model}
        usage: Dict[str, Any] = {}
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_text = line.replace("data:", "", 1).strip()
                    if data_text == "[DONE]":
                        break
                    chunk = json.loads(data_text)
                    if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                        usage = self._extract_usage(chunk)
                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    if isinstance(choices, list) and choices:
                        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                        text = delta.get("content") if isinstance(delta, dict) else None
                        if isinstance(text, str) and text:
                            yield {"type": "delta", "text": text}

        yield {
            "type": "final",
            "provider": "openai",
            "model": self.openai_model,
            "usage": usage,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    async def _stream_claude(
        self,
        *,
        system_prompt: Optional[str],
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        if not self.claude_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured.")

        url = self.claude_base_url
        if not url.endswith("/messages"):
            url = f"{url}/messages"

        headers = {
            "x-api-key": self.claude_api_key,
            "anthropic-version": self.claude_api_version,
            "content-type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.claude_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        }
        if system_prompt:
            payload["system"] = system_prompt

        yield {"type": "provider", "provider": "claude", "model": self.claude_model}
        usage: Dict[str, Any] = {}
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                current_event: Optional[str] = None
                data_lines: list[str] = []

                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.replace("event:", "", 1).strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.replace("data:", "", 1).strip())
                        continue
                    if line.strip():
                        continue

                    if not current_event or not data_lines:
                        current_event = None
                        data_lines = []
                        continue

                    payload_text = "\n".join(data_lines)
                    try:
                        chunk = json.loads(payload_text)
                    except Exception:
                        chunk = {}

                    if current_event == "content_block_delta":
                        delta = chunk.get("delta") if isinstance(chunk, dict) else None
                        text = delta.get("text") if isinstance(delta, dict) else None
                        if isinstance(text, str) and text:
                            yield {"type": "delta", "text": text}
                    elif current_event == "message_delta":
                        if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                            usage = chunk.get("usage") or usage
                    elif current_event == "message_stop":
                        if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                            usage = chunk.get("usage") or usage

                    current_event = None
                    data_lines = []

                if current_event and data_lines:
                    payload_text = "\n".join(data_lines)
                    try:
                        chunk = json.loads(payload_text)
                    except Exception:
                        chunk = {}
                    if current_event == "content_block_delta":
                        delta = chunk.get("delta") if isinstance(chunk, dict) else None
                        text = delta.get("text") if isinstance(delta, dict) else None
                        if isinstance(text, str) and text:
                            yield {"type": "delta", "text": text}
                    elif current_event == "message_delta":
                        if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                            usage = chunk.get("usage") or usage

        yield {
            "type": "final",
            "provider": "claude",
            "model": self.claude_model,
            "usage": usage,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    def _extract_claude_text(self, data: Dict[str, Any]) -> str:
        content = data.get("content") or []
        if isinstance(content, list):
            parts = [
                chunk.get("text", "")
                for chunk in content
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str)
            ]
            text = "".join(parts).strip()
            if text:
                return text
        raise ValueError("Claude returned an empty response.")

    def _extract_openai_text(self, data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
        raise ValueError("ChatGPT returned an empty response.")

    def _extract_usage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        usage = data.get("usage")
        if isinstance(usage, dict):
            return {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        return {}

    def _parse_json_payload(self, text: str) -> Dict[str, Any]:
        stripped = (text or "").strip()
        if not stripped:
            raise ValueError("LLM returned an empty JSON payload.")

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, re.DOTALL)
            if not match:
                raise ValueError("LLM response did not contain valid JSON.") from None
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON payload must be an object.")
        return parsed


preferred_llm_service = PreferredLLMService()
