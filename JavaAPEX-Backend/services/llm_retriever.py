from __future__ import annotations

import asyncio
import math
import re
import hashlib
from typing import Any, Dict, List, Tuple

from services.llm_embeddings import get_embedding
from services.llm_context_service import context_pack_fingerprint


_EMBED_CACHE: Dict[str, List[float]] = {}


def _tokens(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"\W+", text.lower())
    return [p for p in parts if p]


def _score_snippet(question_tokens: List[str], snippet: str) -> float:
    toks = _tokens(snippet)
    if not toks or not question_tokens:
        return 0.0
    overlap = len(set(toks) & set(question_tokens))
    return overlap / max(1, len(toks))


def _gather_candidates(context_pack: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    candidates: List[Tuple[str, Dict[str, Any]]] = []

    # dependencies
    for d in context_pack.get("dependencies", []) or []:
        if isinstance(d, dict):
            gid = d.get("group_id") or ""
            aid = d.get("artifact_id") or ""
            ver = d.get("version") or ""
            snippet = f"dependency {gid}:{aid} version {ver}".strip()
            candidates.append((snippet, {"type": "dependency", "id": f"{gid}:{aid}", "source": d}))

    # vulnerable dependencies
    for v in context_pack.get("vulnerable_dependencies", []) or []:
        if isinstance(v, dict):
            name = v.get("dependency") or v.get("artifact_id") or v.get("package") or ""
            sev = v.get("severity") or v.get("score") or ""
            snippet = f"vulnerable {name} severity {sev}".strip()
            candidates.append((snippet, {"type": "vulnerability", "id": name, "source": v}))

    # API endpoints
    for e in context_pack.get("api_endpoints", []) or []:
        if isinstance(e, dict):
            endpoint = e.get("endpoint") or e.get("path") or ""
            desc = e.get("description") or ""
            snippet = f"endpoint {endpoint} {desc}".strip()
            candidates.append((snippet, {"type": "api", "id": endpoint, "source": e}))

    # file samples
    for f in context_pack.get("file_samples", []) or []:
        snippet = f"file {f}"
        candidates.append((snippet, {"type": "file", "id": f, "source": f}))

    # module hints
    for m in context_pack.get("module_hints", []) or []:
        name = m.get("name") or ""
        desc = m.get("description") or ""
        snippet = f"module {name} {desc}".strip()
        candidates.append((snippet, {"type": "module", "id": name, "source": m}))

    # top-level facts
    java_ver = context_pack.get("java_version")
    if java_ver:
        candidates.append((f"java_version {java_ver}", {"type": "fact", "id": "java_version", "source": java_ver}))

    build_tool = context_pack.get("build_tool")
    if build_tool:
        candidates.append((f"build_tool {build_tool}", {"type": "fact", "id": "build_tool", "source": build_tool}))

    return candidates


def _norm(vec: List[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


async def retrieve_top_k(context_pack: Dict[str, Any], question: str, k: int = 12, use_embeddings: bool = False) -> List[Dict[str, Any]]:
    """Return top-k context snippets. If `use_embeddings` is True and embeddings provider
    is available, use vector scoring (cosine). Falls back to token overlap scoring.
    """
    candidates = _gather_candidates(context_pack)

    # If embeddings requested, attempt to compute embeddings for question and candidates
    if use_embeddings:
        try:
            q_emb = await get_embedding(question)
            q_norm = _norm(q_emb) or 1.0
            scored: List[Tuple[float, str, Dict[str, Any]]] = []
            # fingerprint the context pack to cache candidate embeddings
            fingerprint = context_pack_fingerprint(context_pack)

            for snippet, meta in candidates:
                key = hashlib.sha256(f"{fingerprint}:{snippet}".encode("utf-8")).hexdigest()
                emb = _EMBED_CACHE.get(key)
                if emb is None:
                    try:
                        emb = await get_embedding(snippet)
                        _EMBED_CACHE[key] = emb
                    except Exception:
                        emb = None
                if emb:
                    score = _dot(q_emb, emb) / (q_norm * (_norm(emb) or 1.0))
                else:
                    # fallback to token overlap if embedding unavailable for this snippet
                    score = _score_snippet(_tokens(question), snippet)
                scored.append((float(score), snippet, meta))

            scored.sort(key=lambda t: t[0], reverse=True)
            results: List[Dict[str, Any]] = []
            for score, snippet, meta in scored[:k]:
                results.append({"snippet": snippet, "score": float(round(score, 6)), "provenance": meta})
            return results
        except Exception:
            # embedder failed; fall through to token overlap
            await asyncio.sleep(0)

    # Fallback: token overlap scoring
    q_tokens = _tokens(question)
    scored: List[Tuple[float, str, Dict[str, Any]]] = []
    for snippet, meta in candidates:
        score = _score_snippet(q_tokens, snippet)
        scored.append((score, snippet, meta))

    scored.sort(key=lambda t: t[0], reverse=True)
    results: List[Dict[str, Any]] = []
    for score, snippet, meta in scored[:k]:
        results.append({"snippet": snippet, "score": float(round(score, 3)), "provenance": meta})
    return results


async def warmup_embeddings(context_pack: Dict[str, Any], concurrency: int = 6) -> Dict[str, int]:
    """Precompute and cache embeddings for all candidate snippets in the context pack.

    Returns a small stats dict: requested, cached_new, cached_total
    """
    candidates = _gather_candidates(context_pack)
    fingerprint = context_pack_fingerprint(context_pack)
    tasks = []
    for snippet, _meta in candidates:
        key = hashlib.sha256(f"{fingerprint}:{snippet}".encode("utf-8")).hexdigest()
        if key in _EMBED_CACHE:
            continue
        tasks.append((key, snippet))

    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _do(key: str, snippet: str) -> bool:
        async with sem:
            try:
                emb = await get_embedding(snippet)
                _EMBED_CACHE[key] = emb
                return True
            except Exception:
                return False

    results = await asyncio.gather(*[_do(k, s) for k, s in tasks], return_exceptions=False)
    added = sum(1 for r in results if r)
    return {"requested": len(tasks), "cached_new": int(added), "cached_total": len(_EMBED_CACHE)}


async def warmup_embeddings_and_persist(context_pack: Dict[str, Any], concurrency: int = 6, persist: bool = False) -> Dict[str, Any]:
    stats = await warmup_embeddings(context_pack, concurrency=concurrency)
    persisted = 0
    repo_snapshot = context_pack.get("repo_snapshot_id") or "default"
    if persist:
        try:
            from services import vector_store_qdrant as qstore

            # Build items from candidates
            candidates = _gather_candidates(context_pack)
            items = []
            for i, (snippet, meta) in enumerate(candidates):
                key = hashlib.sha256(f"{repo_snapshot}:{snippet}".encode("utf-8")).hexdigest()
                emb = _EMBED_CACHE.get(key)
                if not emb:
                    continue
                items.append({"id": key, "vector": emb, "payload": {"snippet": snippet, "provenance": meta}})

            if items:
                persisted = qstore.upsert_embeddings(repo_snapshot, items, vector_size=len(items[0]["vector"]))
        except Exception:
            persisted = 0

    return {**stats, "persisted": int(persisted)}
