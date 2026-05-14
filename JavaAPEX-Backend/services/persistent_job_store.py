from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator, MutableMapping
from typing import Callable, Dict, Generic, List, Optional, TypeVar

try:
    import redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - optional dependency
    redis = None

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)

T = TypeVar("T")


class PersistentJobStore(MutableMapping[str, T], Generic[T]):
    def __init__(
        self,
        serializer: Callable[[T], Dict],
        deserializer: Callable[[Dict], T],
        redis_url: Optional[str] = None,
        namespace: str = "migration",
        ttl_for_value: Optional[Callable[[T], Optional[int]]] = None,
    ) -> None:
        self._serializer = serializer
        self._deserializer = deserializer
        self._namespace = namespace
        self._cache: Dict[str, T] = {}
        self._cache_expiry: Dict[str, float] = {}
        self._redis_url = (redis_url or os.environ.get("REDIS_URL") or "").strip()
        self._ttl_for_value = ttl_for_value
        self._client = None
        self._redis_enabled = False

        if self._redis_url and redis is not None:
            try:
                self._client = redis.Redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                )
                self._client.ping()
                self._redis_enabled = True
                logger.info("PersistentJobStore connected to Redis namespace '%s'", self._namespace)
            except Exception as exc:
                self._client = None
                logger.warning("PersistentJobStore falling back to in-memory mode: %s", exc)
        elif self._redis_url and redis is None:
            logger.warning("REDIS_URL is set but redis dependency is not installed; using in-memory job store")

    def _job_key(self, job_id: str) -> str:
        return f"{self._namespace}:job:{job_id}"

    def _index_key(self) -> str:
        return f"{self._namespace}:jobs"

    def _cache_is_expired(self, job_id: str) -> bool:
        expires_at = self._cache_expiry.get(job_id)
        return expires_at is not None and expires_at <= time.time()

    def _cache_value(self, job_id: str, value: T, ttl_seconds: Optional[int] = None) -> None:
        self._cache[job_id] = value
        if ttl_seconds and ttl_seconds > 0:
            self._cache_expiry[job_id] = time.time() + ttl_seconds
        else:
            self._cache_expiry.pop(job_id, None)

    def _evict_cache_entry(self, job_id: str) -> None:
        self._cache.pop(job_id, None)
        self._cache_expiry.pop(job_id, None)

    def _prune_expired_cache_entries(self) -> None:
        expired_job_ids = [job_id for job_id in list(self._cache.keys()) if self._cache_is_expired(job_id)]
        for job_id in expired_job_ids:
            self._evict_cache_entry(job_id)

    def _persist(self, job_id: str, value: T) -> None:
        if not self._redis_enabled or self._client is None:
            return
        payload = json.dumps(self._serializer(value))
        ttl_seconds = self._ttl_for_value(value) if self._ttl_for_value else None
        try:
            if ttl_seconds and ttl_seconds > 0:
                self._client.set(self._job_key(job_id), payload, ex=ttl_seconds)
            else:
                self._client.set(self._job_key(job_id), payload)
            self._client.sadd(self._index_key(), job_id)
        except RedisError as exc:
            logger.warning("Failed to persist migration job %s to Redis: %s", job_id, exc)

    def save(self, job_id: str, value: T) -> None:
        ttl_seconds = self._ttl_for_value(value) if self._ttl_for_value else None
        self._cache_value(job_id, value, ttl_seconds)
        self._persist(job_id, value)

    def _load(self, job_id: str) -> Optional[T]:
        self._prune_expired_cache_entries()
        if job_id in self._cache:
            return self._cache[job_id]
        if not self._redis_enabled or self._client is None:
            return None
        try:
            payload = self._client.get(self._job_key(job_id))
        except RedisError as exc:
            logger.warning("Failed to load migration job %s from Redis: %s", job_id, exc)
            return None
        if not payload:
            return None
        try:
            parsed = json.loads(payload)
            value = self._deserializer(parsed)
            ttl_seconds = None
            try:
                ttl_probe = self._client.ttl(self._job_key(job_id))
                if isinstance(ttl_probe, int) and ttl_probe > 0:
                    ttl_seconds = ttl_probe
            except RedisError:
                ttl_seconds = None
            self._cache_value(job_id, value, ttl_seconds)
            return value
        except Exception as exc:
            logger.warning("Failed to deserialize migration job %s from Redis: %s", job_id, exc)
            return None

    def __getitem__(self, job_id: str) -> T:
        value = self._load(job_id)
        if value is None:
            raise KeyError(job_id)
        return value

    def __setitem__(self, job_id: str, value: T) -> None:
        self.save(job_id, value)

    def __delitem__(self, job_id: str) -> None:
        self._evict_cache_entry(job_id)
        if not self._redis_enabled or self._client is None:
            return
        try:
            self._client.delete(self._job_key(job_id))
            self._client.srem(self._index_key(), job_id)
        except RedisError as exc:
            logger.warning("Failed to delete migration job %s from Redis: %s", job_id, exc)

    def __iter__(self) -> Iterator[str]:
        self._prune_expired_cache_entries()
        seen = set(self._cache.keys())
        for key in list(self._cache.keys()):
            yield key
        if not self._redis_enabled or self._client is None:
            return
        try:
            for key in self._client.smembers(self._index_key()):
                if not self._client.exists(self._job_key(key)):
                    self._client.srem(self._index_key(), key)
                    continue
                if key not in seen:
                    yield key
        except RedisError as exc:
            logger.warning("Failed to iterate migration jobs from Redis: %s", exc)

    def __len__(self) -> int:
        return len(list(iter(self)))

    def __contains__(self, job_id: object) -> bool:
        if not isinstance(job_id, str):
            return False
        self._prune_expired_cache_entries()
        if job_id in self._cache:
            return True
        if not self._redis_enabled or self._client is None:
            return False
        try:
            return bool(self._client.exists(self._job_key(job_id)))
        except RedisError as exc:
            logger.warning("Failed to check migration job %s in Redis: %s", job_id, exc)
            return False

    def values(self) -> List[T]:  # type: ignore[override]
        values: List[T] = []
        for job_id in list(iter(self)):
            try:
                values.append(self[job_id])
            except KeyError:
                continue
        return values

    @property
    def persistence_enabled(self) -> bool:
        return self._redis_enabled

    def capabilities(self) -> Dict[str, object]:
        return {
            "backend": "redis" if self._redis_enabled else "memory",
            "persistence_enabled": self._redis_enabled,
            "redis_configured": bool(self._redis_url),
            "redis_dependency_available": redis is not None,
            "namespace": self._namespace,
            "cached_jobs": len(self._cache),
        }
