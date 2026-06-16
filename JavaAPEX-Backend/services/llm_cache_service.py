from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

try:
    import redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - optional dependency
    redis = None

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)

_LLM_CACHE_TTL_SECONDS = max(60, int(os.getenv("LLM_CACHE_TTL_SECONDS", "86400")))
_LLM_CACHE_MAX_ENTRIES = max(32, int(os.getenv("LLM_CACHE_MAX_ENTRIES", "1024")))
_LLM_CACHE_BACKEND = (os.getenv("LLM_CACHE_BACKEND", "local") or "local").strip().lower()
_LLM_CACHE_REDIS_URL = (
    os.getenv("LLM_CACHE_REDIS_URL")
    or os.getenv("REDIS_URL")
    or os.getenv("CELERY_BROKER_URL")
    or os.getenv("CELERY_RESULT_BACKEND")
    or ""
).strip()
_LLM_CACHE_REDIS_PREFIX = (os.getenv("LLM_CACHE_REDIS_PREFIX") or "llm-cache").strip() or "llm-cache"

_LLM_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
_LLM_CACHE_LOCK = threading.RLock()
_LLM_CACHE_REDIS_CLIENT = None
_LLM_CACHE_REDIS_INITIALIZED = False
_LLM_CACHE_REDIS_ENABLED = False
_LLM_CACHE_STATS = {
    "hits": 0,
    "misses": 0,
    "writes": 0,
    "redis_hits": 0,
    "redis_misses": 0,
    "redis_writes": 0,
    "redis_errors": 0,
    "local_hits": 0,
    "local_misses": 0,
    "local_writes": 0,
}


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(raw) for key, raw in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize(item) for item in value]
    if isinstance(value, set):
        return sorted(
            (_canonicalize(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_llm_cache_key(namespace: str, payload: Any) -> str:
    normalized_payload = _canonicalize(payload)
    serialized = json.dumps(normalized_payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    normalized_namespace = (namespace or "llm").strip().lower().replace(" ", "-")
    return f"{normalized_namespace}:{digest}"


def _redis_cache_key(cache_key: str) -> str:
    return f"{_LLM_CACHE_REDIS_PREFIX}:{cache_key}"


def _ensure_redis_client():
    global _LLM_CACHE_REDIS_CLIENT, _LLM_CACHE_REDIS_INITIALIZED, _LLM_CACHE_REDIS_ENABLED

    if _LLM_CACHE_BACKEND != "redis":
        return None

    with _LLM_CACHE_LOCK:
        if _LLM_CACHE_REDIS_INITIALIZED:
            return _LLM_CACHE_REDIS_CLIENT if _LLM_CACHE_REDIS_ENABLED else None

        _LLM_CACHE_REDIS_INITIALIZED = True
        if redis is None:
            logger.warning(
                "LLM_CACHE_BACKEND=redis but the redis dependency is not installed; using local cache instead."
            )
            return None

        if not _LLM_CACHE_REDIS_URL:
            logger.warning(
                "LLM_CACHE_BACKEND=redis but no Redis URL is configured; using local cache instead."
            )
            return None

        try:
            client = redis.Redis.from_url(
                _LLM_CACHE_REDIS_URL,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            client.ping()
            _LLM_CACHE_REDIS_CLIENT = client
            _LLM_CACHE_REDIS_ENABLED = True
            logger.info(
                "LLM cache using Redis backend with prefix '%s'",
                _LLM_CACHE_REDIS_PREFIX,
            )
        except Exception as exc:
            _LLM_CACHE_REDIS_CLIENT = None
            _LLM_CACHE_REDIS_ENABLED = False
            logger.warning("LLM cache Redis backend unavailable; using local cache instead: %s", exc)

    return _LLM_CACHE_REDIS_CLIENT if _LLM_CACHE_REDIS_ENABLED else None


def _prune_local_cache_locked() -> None:
    now = time.time()
    expired_keys = [key for key, (timestamp, _) in list(_LLM_CACHE.items()) if now - timestamp >= _LLM_CACHE_TTL_SECONDS]
    for key in expired_keys:
        _LLM_CACHE.pop(key, None)

    overflow = len(_LLM_CACHE) - _LLM_CACHE_MAX_ENTRIES
    if overflow > 0:
        oldest_keys = list(_LLM_CACHE.keys())[:overflow]
        for key in oldest_keys:
            _LLM_CACHE.pop(key, None)


def _encode_value(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _decode_value(payload: str) -> Any:
    return json.loads(payload)


def get_cached_llm_response(cache_key: str) -> Optional[Any]:
    redis_client = _ensure_redis_client()
    if redis_client is not None:
        try:
            payload = redis_client.get(_redis_cache_key(cache_key))
            if payload is None:
                with _LLM_CACHE_LOCK:
                    _LLM_CACHE_STATS["misses"] += 1
                    _LLM_CACHE_STATS["redis_misses"] += 1
                return None
            with _LLM_CACHE_LOCK:
                _LLM_CACHE_STATS["hits"] += 1
                _LLM_CACHE_STATS["redis_hits"] += 1
            return _decode_value(payload)
        except RedisError as exc:
            with _LLM_CACHE_LOCK:
                _LLM_CACHE_STATS["redis_errors"] += 1
            logger.warning("LLM cache Redis read failed for %s; falling back to local cache: %s", cache_key, exc)
        except Exception as exc:
            with _LLM_CACHE_LOCK:
                _LLM_CACHE_STATS["redis_errors"] += 1
            logger.warning("LLM cache Redis read failed for %s; falling back to local cache: %s", cache_key, exc)

    with _LLM_CACHE_LOCK:
        _prune_local_cache_locked()
        entry = _LLM_CACHE.get(cache_key)
        if not entry:
            _LLM_CACHE_STATS["misses"] += 1
            _LLM_CACHE_STATS["local_misses"] += 1
            return None

        timestamp, value = entry
        if time.time() - timestamp >= _LLM_CACHE_TTL_SECONDS:
            _LLM_CACHE.pop(cache_key, None)
            _LLM_CACHE_STATS["misses"] += 1
            _LLM_CACHE_STATS["local_misses"] += 1
            return None

        _LLM_CACHE.move_to_end(cache_key)
        _LLM_CACHE_STATS["hits"] += 1
        _LLM_CACHE_STATS["local_hits"] += 1
        return value


def set_cached_llm_response(cache_key: str, value: Any) -> None:
    redis_client = _ensure_redis_client()
    if redis_client is not None:
        try:
            redis_client.set(_redis_cache_key(cache_key), _encode_value(value), ex=_LLM_CACHE_TTL_SECONDS)
            with _LLM_CACHE_LOCK:
                _LLM_CACHE_STATS["writes"] += 1
                _LLM_CACHE_STATS["redis_writes"] += 1
            return
        except RedisError as exc:
            with _LLM_CACHE_LOCK:
                _LLM_CACHE_STATS["redis_errors"] += 1
            logger.warning("LLM cache Redis write failed for %s; falling back to local cache: %s", cache_key, exc)
        except Exception as exc:
            with _LLM_CACHE_LOCK:
                _LLM_CACHE_STATS["redis_errors"] += 1
            logger.warning("LLM cache Redis write failed for %s; falling back to local cache: %s", cache_key, exc)

    with _LLM_CACHE_LOCK:
        _LLM_CACHE[cache_key] = (time.time(), value)
        _LLM_CACHE.move_to_end(cache_key)
        _prune_local_cache_locked()
        _LLM_CACHE_STATS["writes"] += 1
        _LLM_CACHE_STATS["local_writes"] += 1


def get_llm_cache_stats() -> dict[str, Any]:
    with _LLM_CACHE_LOCK:
        _prune_local_cache_locked()
        return {
            "backend": _LLM_CACHE_BACKEND,
            "redis_enabled": _LLM_CACHE_REDIS_ENABLED,
            "ttl_seconds": _LLM_CACHE_TTL_SECONDS,
            "max_entries": _LLM_CACHE_MAX_ENTRIES,
            "current_entries": len(_LLM_CACHE),
            **_LLM_CACHE_STATS,
        }
