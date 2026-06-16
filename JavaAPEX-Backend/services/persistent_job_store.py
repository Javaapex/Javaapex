from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

try:
    import redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - optional dependency
    redis = None

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)

T = TypeVar("T")
ItemT = TypeVar("ItemT")


class PersistentJobStore(MutableMapping[str, T], Generic[T]):
    def __init__(
        self,
        serializer: Callable[[T], Dict],
        deserializer: Callable[[Dict], T],
        redis_url: Optional[str] = None,
        namespace: str = "migration",
        ttl_for_value: Optional[Callable[[T], Optional[int]]] = None,
        cache_in_memory_when_redis: bool = True,
        max_cached_items: int = 256,
    ) -> None:
        self._serializer = serializer
        self._deserializer = deserializer
        self._namespace = namespace
        self._cache: OrderedDict[str, T] = OrderedDict()
        self._cache_expiry: Dict[str, float] = {}
        self._redis_url = (redis_url or os.environ.get("REDIS_URL") or "").strip()
        self._ttl_for_value = ttl_for_value
        self._cache_in_memory_when_redis = cache_in_memory_when_redis
        self._max_cached_items = max(1, int(max_cached_items or 1))
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

    def _should_cache_in_memory(self) -> bool:
        return not self._redis_enabled or self._client is None or self._cache_in_memory_when_redis

    def _cache_value(self, job_id: str, value: T, ttl_seconds: Optional[int] = None) -> None:
        if not self._should_cache_in_memory():
            self._evict_cache_entry(job_id)
            return
        self._cache.pop(job_id, None)
        self._cache[job_id] = value
        self._cache.move_to_end(job_id)
        if ttl_seconds and ttl_seconds > 0:
            self._cache_expiry[job_id] = time.time() + ttl_seconds
        else:
            self._cache_expiry.pop(job_id, None)
        while len(self._cache) > self._max_cached_items:
            oldest_job_id, _ = self._cache.popitem(last=False)
            self._cache_expiry.pop(oldest_job_id, None)

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
        if not self._redis_enabled or self._client is None:
            if job_id in self._cache:
                return self._cache[job_id]
            return None
        try:
            payload = self._client.get(self._job_key(job_id))
        except RedisError as exc:
            logger.warning("Failed to load migration job %s from Redis: %s", job_id, exc)
            return self._cache.get(job_id)
        if not payload:
            self._evict_cache_entry(job_id)
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
            return self._cache.get(job_id)

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
        if not self._redis_enabled or self._client is None:
            for key in list(self._cache.keys()):
                yield key
            return
        seen = set()
        try:
            for key in self._client.smembers(self._index_key()):
                if not self._client.exists(self._job_key(key)):
                    self._client.srem(self._index_key(), key)
                    self._evict_cache_entry(key)
                    continue
                seen.add(key)
                yield key
        except RedisError as exc:
            logger.warning("Failed to iterate migration jobs from Redis: %s", exc)
            for key in list(self._cache.keys()):
                yield key
            return
        for key in list(self._cache.keys()):
            if key not in seen:
                yield key

    def __len__(self) -> int:
        return len(list(iter(self)))

    def __contains__(self, job_id: object) -> bool:
        if not isinstance(job_id, str):
            return False
        self._prune_expired_cache_entries()
        if not self._redis_enabled or self._client is None:
            return job_id in self._cache
        try:
            exists = bool(self._client.exists(self._job_key(job_id)))
            if not exists:
                self._evict_cache_entry(job_id)
            return exists
        except RedisError as exc:
            logger.warning("Failed to check migration job %s in Redis: %s", job_id, exc)
            return job_id in self._cache

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


class PersistentListStore(Generic[ItemT]):
    def __init__(
        self,
        serializer: Callable[[ItemT], Any],
        deserializer: Callable[[Any], ItemT],
        redis_url: Optional[str] = None,
        namespace: str = "migration_list",
        cache_in_memory_when_redis: bool = True,
        max_cached_items: int = 128,
    ) -> None:
        self._serializer = serializer
        self._deserializer = deserializer
        self._namespace = namespace
        self._cache: OrderedDict[str, List[ItemT]] = OrderedDict()
        self._cache_expiry: Dict[str, float] = {}
        self._redis_url = (redis_url or os.environ.get("REDIS_URL") or "").strip()
        self._cache_in_memory_when_redis = cache_in_memory_when_redis
        self._max_cached_items = max(1, int(max_cached_items or 1))
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
                logger.info("PersistentListStore connected to Redis namespace '%s'", self._namespace)
            except Exception as exc:
                self._client = None
                logger.warning("PersistentListStore falling back to in-memory mode: %s", exc)
        elif self._redis_url and redis is None:
            logger.warning("REDIS_URL is set but redis dependency is not installed; using in-memory list store")

    def _list_key(self, key: str) -> str:
        return f"{self._namespace}:list:{key}"

    def _cache_is_expired(self, key: str) -> bool:
        expires_at = self._cache_expiry.get(key)
        return expires_at is not None and expires_at <= time.time()

    def _should_cache_in_memory(self) -> bool:
        return not self._redis_enabled or self._client is None or self._cache_in_memory_when_redis

    def _cache_value(self, key: str, values: List[ItemT], ttl_seconds: Optional[int] = None) -> None:
        if not self._should_cache_in_memory():
            self._evict_cache_entry(key)
            return
        self._cache.pop(key, None)
        self._cache[key] = list(values)
        self._cache.move_to_end(key)
        if ttl_seconds and ttl_seconds > 0:
            self._cache_expiry[key] = time.time() + ttl_seconds
        else:
            self._cache_expiry.pop(key, None)
        while len(self._cache) > self._max_cached_items:
            oldest_key, _ = self._cache.popitem(last=False)
            self._cache_expiry.pop(oldest_key, None)

    def _evict_cache_entry(self, key: str) -> None:
        self._cache.pop(key, None)
        self._cache_expiry.pop(key, None)

    def _prune_expired_cache_entries(self) -> None:
        expired_keys = [key for key in list(self._cache.keys()) if self._cache_is_expired(key)]
        for key in expired_keys:
            self._evict_cache_entry(key)

    def get_list(self, key: str) -> List[ItemT]:
        self._prune_expired_cache_entries()
        if not self._redis_enabled or self._client is None:
            return list(self._cache.get(key, []))

        try:
            payload = self._client.lrange(self._list_key(key), 0, -1)
        except RedisError as exc:
            logger.warning("Failed to load list %s from Redis: %s", key, exc)
            return list(self._cache.get(key, []))

        if not payload:
            self._evict_cache_entry(key)
            return []

        try:
            values = [self._deserializer(json.loads(item)) for item in payload]
        except Exception as exc:
            logger.warning("Failed to deserialize list %s from Redis: %s", key, exc)
            return list(self._cache.get(key, []))

        ttl_seconds = None
        try:
            ttl_probe = self._client.ttl(self._list_key(key))
            if isinstance(ttl_probe, int) and ttl_probe > 0:
                ttl_seconds = ttl_probe
        except RedisError:
            ttl_seconds = None
        self._cache_value(key, values, ttl_seconds)
        return list(values)

    def set_list(self, key: str, values: List[ItemT], ttl_seconds: Optional[int] = None) -> int:
        serialized_values = [json.dumps(self._serializer(value)) for value in values]
        self._cache_value(key, list(values), ttl_seconds)

        if self._redis_enabled and self._client is not None:
            try:
                pipeline = self._client.pipeline()
                pipeline.delete(self._list_key(key))
                if serialized_values:
                    pipeline.rpush(self._list_key(key), *serialized_values)
                if ttl_seconds and ttl_seconds > 0:
                    pipeline.expire(self._list_key(key), ttl_seconds)
                pipeline.execute()
            except RedisError as exc:
                logger.warning("Failed to persist list %s to Redis: %s", key, exc)

        return len(values)

    def append(self, key: str, value: ItemT, ttl_seconds: Optional[int] = None) -> int:
        self._prune_expired_cache_entries()
        cached_values: Optional[List[ItemT]] = None
        if self._should_cache_in_memory():
            cached_values = list(self._cache.get(key, []))
            cached_values.append(value)
            self._cache_value(key, cached_values, ttl_seconds)

        if not self._redis_enabled or self._client is None:
            return len(cached_values or [])

        try:
            new_length = self._client.rpush(self._list_key(key), json.dumps(self._serializer(value)))
            if ttl_seconds and ttl_seconds > 0:
                self._client.expire(self._list_key(key), ttl_seconds)
            return int(new_length)
        except RedisError as exc:
            logger.warning("Failed to append to list %s in Redis: %s", key, exc)
            if cached_values is not None:
                return len(cached_values)
            fallback_values = list(self._cache.get(key, []))
            fallback_values.append(value)
            self._cache_value(key, fallback_values, ttl_seconds)
            return len(fallback_values)

    def delete(self, key: str) -> None:
        self._evict_cache_entry(key)
        if not self._redis_enabled or self._client is None:
            return
        try:
            self._client.delete(self._list_key(key))
        except RedisError as exc:
            logger.warning("Failed to delete list %s from Redis: %s", key, exc)

    def expire(self, key: str, ttl_seconds: Optional[int]) -> None:
        if ttl_seconds and ttl_seconds > 0:
            if key in self._cache_expiry:
                self._cache_expiry[key] = time.time() + ttl_seconds
        else:
            self._cache_expiry.pop(key, None)

        if not self._redis_enabled or self._client is None:
            return

        try:
            if ttl_seconds and ttl_seconds > 0:
                self._client.expire(self._list_key(key), ttl_seconds)
            else:
                self._client.persist(self._list_key(key))
        except RedisError as exc:
            logger.warning("Failed to update TTL for list %s: %s", key, exc)

    def capabilities(self) -> Dict[str, object]:
        return {
            "backend": "redis" if self._redis_enabled else "memory",
            "persistence_enabled": self._redis_enabled,
            "redis_configured": bool(self._redis_url),
            "redis_dependency_available": redis is not None,
            "namespace": self._namespace,
            "cached_lists": len(self._cache),
        }
