from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from utils.config import QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION_PREFIX

logger = logging.getLogger(__name__)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
except Exception:  # pragma: no cover - optional dependency
    QdrantClient = None
    rest = None


def _collection_name(repo_snapshot_id: str) -> str:
    return f"{QDRANT_COLLECTION_PREFIX}_{repo_snapshot_id}"[:63]


def _ensure_client() -> Optional[QdrantClient]:
    if QdrantClient is None:
        logger.warning("qdrant-client not installed; Qdrant integration disabled")
        return None
    kwargs = {"url": QDRANT_URL}
    if QDRANT_API_KEY:
        kwargs["api_key"] = QDRANT_API_KEY
    return QdrantClient(**kwargs)


def ensure_collection(repo_snapshot_id: str, vector_size: int = 1536) -> bool:
    client = _ensure_client()
    if client is None:
        return False
    name = _collection_name(repo_snapshot_id)
    try:
        if not client.has_collection(name):
            client.recreate_collection(
                collection_name=name,
                vectors_config=rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
            )
        return True
    except Exception as exc:
        logger.warning("Failed to ensure Qdrant collection %s: %s", name, exc)
        return False


def upsert_embeddings(repo_snapshot_id: str, items: List[Dict[str, Any]], vector_size: int = 1536) -> int:
    """Upsert embeddings into Qdrant collection.

    items: list of {id: str|int, vector: List[float], payload: dict}
    Returns number of upserted points.
    """
    client = _ensure_client()
    if client is None:
        raise RuntimeError("Qdrant client not available")
    name = _collection_name(repo_snapshot_id)
    ensure_collection(repo_snapshot_id, vector_size=vector_size)
    points = []
    for it in items:
        pid = it.get("id")
        vec = it.get("vector")
        payload = it.get("payload") or {}
        if pid is None or vec is None:
            continue
        points.append(rest.PointsList(points=[rest.PointStruct(id=str(pid), vector=vec, payload=payload)]))
    # qdrant-client supports upsert with client.upsert but our wrapper uses batches
    count = 0
    for p in points:
        try:
            client.upsert(collection_name=name, points=p.points)
            count += len(p.points)
        except Exception as exc:
            logger.warning("Failed to upsert points to Qdrant: %s", exc)
    return count


def query_vector(repo_snapshot_id: str, vector: List[float], top_k: int = 10, filter: Optional[dict] = None) -> List[Dict[str, Any]]:
    client = _ensure_client()
    if client is None:
        raise RuntimeError("Qdrant client not available")
    name = _collection_name(repo_snapshot_id)
    try:
        res = client.search(collection_name=name, query_vector=vector, limit=top_k, query_filter=filter)
        results = []
        for hit in res:
            results.append({"id": hit.id, "score": float(hit.score or 0.0), "payload": hit.payload})
        return results
    except Exception as exc:
        logger.warning("Qdrant query failed: %s", exc)
        return []
