from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Dict, List, Any

import httpx

from utils.config import (
    FORD_LLM_API_KEY,
    FORD_LLM_BASE_URL,
    FORD_LLM_ENABLED,
    FORD_LLM_OAUTH_CLIENT_ID,
    FORD_LLM_OAUTH_CLIENT_SECRET,
    FORD_LLM_OAUTH_SCOPE,
    FORD_LLM_OAUTH_TOKEN_URL,
    FORD_LLM_PROXY_URL,
    FORD_LLM_VERIFY_SSL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    httpx_proxy_kwargs as _proxy_kw,
)

logger = logging.getLogger(__name__)

# In-memory embedding cache to avoid repeated provider calls during runtime.
# Keyed by the input text. For long-running processes consider persistent cache.
_EMB_CACHE: Dict[str, List[float]] = {}

# Track in-flight embedding requests to deduplicate concurrent requests for same text.
_IN_FLIGHT: Dict[str, asyncio.Future] = {}

# Limit concurrent embedding requests to external providers to avoid bursts.
_EMBEDDING_CONCURRENCY = 4
_EMB_SEMAPHORE = asyncio.Semaphore(_EMBEDDING_CONCURRENCY)

# Cache a discovered Groq embedding model name to avoid repeated /models calls
_GROQ_EMBEDDING_MODEL: str | None = None

# ── Ford LLM OAuth token cache for embeddings ──
import time as _time
_FORD_EMB_OAUTH_TOKEN: str | None = None
_FORD_EMB_OAUTH_EXPIRY: float = 0.0


async def _get_ford_embedding_token() -> str:
    """Return a valid Ford LLM bearer token for embeddings.

    Uses OAuth2 client-credentials when the env vars are present (the token
    auto-refreshes ~60 s before expiry).  Falls back to the static
    FORD_LLM_API_KEY otherwise.
    """
    global _FORD_EMB_OAUTH_TOKEN, _FORD_EMB_OAUTH_EXPIRY
    has_oauth = bool(FORD_LLM_OAUTH_TOKEN_URL and FORD_LLM_OAUTH_CLIENT_ID and FORD_LLM_OAUTH_CLIENT_SECRET)
    if has_oauth:
        now = _time.time()
        if _FORD_EMB_OAUTH_TOKEN and now < _FORD_EMB_OAUTH_EXPIRY - 60:
            return _FORD_EMB_OAUTH_TOKEN
        data = {
            "grant_type": "client_credentials",
            "client_id": FORD_LLM_OAUTH_CLIENT_ID,
            "client_secret": FORD_LLM_OAUTH_CLIENT_SECRET,
            "scope": FORD_LLM_OAUTH_SCOPE,
        }
        proxy = FORD_LLM_PROXY_URL or None
        async with httpx.AsyncClient(timeout=30.0, **_proxy_kw(proxy), verify=FORD_LLM_VERIFY_SSL) as client:
            resp = await client.post(FORD_LLM_OAUTH_TOKEN_URL, data=data)
            resp.raise_for_status()
            token_data = resp.json()
        _FORD_EMB_OAUTH_TOKEN = token_data["access_token"]
        _FORD_EMB_OAUTH_EXPIRY = _time.time() + token_data.get("expires_in", 3600)
        logger.info("Ford LLM embedding OAuth2 token refreshed (expires_in=%s)", token_data.get("expires_in"))
        return _FORD_EMB_OAUTH_TOKEN
    if not FORD_LLM_API_KEY:
        raise ValueError("Ford LLM API key not configured for embeddings")
    return FORD_LLM_API_KEY


async def _call_openai_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    if not OPENAI_API_KEY:
        raise ValueError("OpenAI API key not configured")
    url = f"{OPENAI_BASE_URL}/embeddings"
    payload = {"model": model, "input": text}
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    # response structure: { data: [ { embedding: [...] } ] }
    if not data or not isinstance(data, dict):
        raise ValueError("Invalid embedding response from OpenAI")
    arr = data.get("data") or []
    if not arr or not isinstance(arr, list):
        raise ValueError("OpenAI embedding response missing data")
    emb = arr[0].get("embedding")
    if not isinstance(emb, list):
        raise ValueError("OpenAI embedding payload invalid")
    return [float(x) for x in emb]


class ModelNotFoundError(RuntimeError):
    pass


async def _get_groq_models() -> List[str]:
    """Return a list of model ids available on the Groq account (best-effort).

    This calls the Groq `/models` endpoint and extracts model ids. On error
    it returns an empty list.
    """
    if not GROQ_API_KEY:
        return []
    url = f"{GROQ_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers)
            # don't raise here; parse body for helpful info
            if r.status_code != 200:
                logger.info("Groq /models returned %s", r.status_code)
                return []
            data = r.json()
    except Exception as exc:
        logger.warning("Failed to list Groq models: %s", exc)
        return []

    models = []
    if isinstance(data, dict):
        # expected: { "data": [ {"id": "..."}, ... ] } or { "models": [...] }
        for key in ("data", "models", "items"):
            arr = data.get(key)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict):
                        mid = it.get("id") or it.get("model") or it.get("name")
                        if isinstance(mid, str):
                            models.append(mid)
                if models:
                    break
    return models


async def _call_groq_embedding(text: str, model: str | None = None) -> List[float]:
    # Groq embeddings endpoint may vary; attempt a generic embeddings route
    global _GROQ_EMBEDDING_MODEL
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY not configured")

    # if no model provided, try cached or discover
    if model is None:
        if _GROQ_EMBEDDING_MODEL:
            model = _GROQ_EMBEDDING_MODEL
        else:
            models = await _get_groq_models()
            # prefer models with 'embed' in the name, fallback to any model containing 'embed' or 'embedding'
            chosen = None
            for m in models:
                if "embed" in m.lower() or "embedding" in m.lower():
                    chosen = m
                    break
            # If none matched, try known vendor model name as last resort
            model = chosen or "embed-3-small"

    url = f"{GROQ_BASE_URL}/embeddings"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "input": text}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as http_exc:
            resp = http_exc.response
            try:
                body = resp.json()
            except Exception:
                body = {}
            # Groq/OpenAI-style error payloads may include code 'model_not_found'
            err_code = None
            if isinstance(body, dict) and body.get("error"):
                err_code = body.get("error", {}).get("code")
            if err_code == "model_not_found" or resp.status_code == 404:
                # signal to caller that the model is not available
                raise ModelNotFoundError(f"Groq model not found: {model}") from http_exc
            raise

    arr = data.get("data") or []
    if not arr or not isinstance(arr, list):
        raise ValueError("Groq embedding response missing data")
    emb = arr[0].get("embedding")
    if not isinstance(emb, list):
        raise ValueError("Groq embedding payload invalid")

    # cache the discovered working model for future calls
    try:
        _GROQ_EMBEDDING_MODEL = model
    except Exception:
        pass

    return [float(x) for x in emb]


async def _with_retries(call_coro, *args, max_retries: int = 5, base_delay: float = 0.4, **kwargs):
    """Call `call_coro(*args, **kwargs)` with exponential backoff on transient errors (429/5xx).

    Returns the call result or raises the last exception.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return await call_coro(*args, **kwargs)
        except httpx.HTTPStatusError as http_exc:
            resp = getattr(http_exc, "response", None) or getattr(http_exc, "response", None)
            status = None
            try:
                status = int(resp.status_code) if resp is not None else None
            except Exception:
                status = None
            last_exc = http_exc
            # treat 429 and 5xx as retryable
            if status == 429 or (status and 500 <= status < 600):
                delay = base_delay * (2 ** (attempt - 1))
                jitter = random.uniform(0, delay * 0.25)
                sleep_for = delay + jitter
                logger.warning("Embedding provider returned %s; retrying in %.2fs (attempt %d/%d)", status, sleep_for, attempt, max_retries)
                await asyncio.sleep(sleep_for)
                continue
            # non-retryable HTTP error
            raise
        except Exception as exc:
            last_exc = exc
            # for connection errors, apply a short backoff
            delay = base_delay * (2 ** (attempt - 1))
            jitter = random.uniform(0, delay * 0.25)
            sleep_for = delay + jitter
            logger.warning("Embedding call failed (%s). Retrying in %.2fs (attempt %d/%d)", str(exc), sleep_for, attempt, max_retries)
            await asyncio.sleep(sleep_for)
            continue
    # exhausted
    logger.error("Embedding call failed after %d attempts: %s", max_retries, str(last_exc))
    raise last_exc


async def _call_ford_llm_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    """Call Ford LLM embeddings endpoint (OpenAI-compatible) with auto-refreshing OAuth."""
    token = await _get_ford_embedding_token()
    url = f"{FORD_LLM_BASE_URL}/embeddings"
    payload = {"model": model, "input": text}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    proxy = FORD_LLM_PROXY_URL or None
    async with httpx.AsyncClient(timeout=30.0, **_proxy_kw(proxy), verify=FORD_LLM_VERIFY_SSL) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    if not data or not isinstance(data, dict):
        raise ValueError("Invalid embedding response from Ford LLM")
    arr = data.get("data") or []
    if not arr or not isinstance(arr, list):
        raise ValueError("Ford LLM embedding response missing data")
    emb = arr[0].get("embedding")
    if not isinstance(emb, list):
        raise ValueError("Ford LLM embedding payload invalid")
    return [float(x) for x in emb]


async def get_embedding(text: str) -> List[float]:
    """Get embedding for text using available providers (Ford LLM preferred, then Groq, then OpenAI).

    This will attempt Ford LLM first, then Groq (and discover a working model via `/models`).
    If both fail, we fall back to OpenAI.
    """
    if not text:
        return []

    # quick cache hit
    cached = _EMB_CACHE.get(text)
    if cached:
        return cached

    # dedupe concurrent identical requests
    fut = _IN_FLIGHT.get(text)
    if fut:
        return await fut

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _IN_FLIGHT[text] = fut

    try:
        async with _EMB_SEMAPHORE:
            last_exc = None

            # ── Primary: Ford LLM ──
            if FORD_LLM_ENABLED and FORD_LLM_API_KEY:
                try:
                    emb = await _with_retries(_call_ford_llm_embedding, text)
                    _EMB_CACHE[text] = emb
                    fut.set_result(emb)
                    return emb
                except Exception as exc:
                    last_exc = exc
                    logger.warning("Ford LLM embedding failed, trying Groq: %s", str(exc))

            # ── Fallback 1: Groq ──
            try:
                emb = await _with_retries(_call_groq_embedding, text)
            except ModelNotFoundError as mnf:
                logger.warning("Groq model not found, falling back to OpenAI: %s", mnf)
                try:
                    emb = await _with_retries(_call_openai_embedding, text)
                except Exception as exc2:
                    last_exc = exc2
                    logger.error("All embedding providers failed: %s", str(exc2))
                    raise last_exc
            except Exception as exc:
                # other Groq errors (rate limits, etc) -> try OpenAI
                last_exc = exc
                logger.warning("Groq embedding failed, trying OpenAI: %s", str(exc))
                try:
                    emb = await _with_retries(_call_openai_embedding, text)
                except Exception as exc2:
                    last_exc = exc2
                    logger.error("All embedding providers failed: %s", str(exc2))
                    raise last_exc

        # store in cache
        _EMB_CACHE[text] = emb
        fut.set_result(emb)
        return emb
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        try:
            _IN_FLIGHT.pop(text, None)
        except Exception:
            pass
