from __future__ import annotations

import math
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

_USAGE: Dict[str, Dict[str, Any]] = {}


def _approximate_token_count(text: str) -> int:
    if not text:
        return 0
    # rough heuristic: ~4 characters per token
    return max(1, math.ceil(len(text) / 4.0))


def _count_tokens(model: str, text: str) -> int:
    # Prefer tiktoken if available for accurate OpenAI-style counts
    try:
        import tiktoken

        model_name = (model or "").split("/")[-1]
        try:
            enc = tiktoken.encoding_for_model(model_name)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or ""))
    except Exception:
        # Fallback heuristic
        return _approximate_token_count(text or "")


class LLMTokenUsageService:
    def record_usage(
        self,
        job_id: str,
        functionality: str,
        provider: str,
        model: str,
        prompt: str,
        response: str,
    ) -> None:
        if not job_id:
            job_id = "-"  # unknown job bucket

        prompt_tokens = _count_tokens(model, prompt or "")
        response_tokens = _count_tokens(model, response or "")

        bucket = _USAGE.setdefault(job_id, {"total_prompt_tokens": 0, "total_response_tokens": 0, "functions": {}})
        func_map = bucket["functions"].setdefault(functionality or "general", {})

        func_map.setdefault("provider", provider or "")
        func_map.setdefault("model", model or "")
        func_map.setdefault("prompt_tokens", 0)
        func_map.setdefault("response_tokens", 0)
        func_map.setdefault("calls", 0)

        func_map["prompt_tokens"] += prompt_tokens
        func_map["response_tokens"] += response_tokens
        func_map["calls"] += 1

        bucket["total_prompt_tokens"] += prompt_tokens
        bucket["total_response_tokens"] += response_tokens

        logger.debug(
            "Recorded LLM token usage job=%s func=%s provider=%s model=%s prompt_tokens=%s response_tokens=%s",
            job_id,
            functionality,
            provider,
            model,
            prompt_tokens,
            response_tokens,
        )

    def get_usage(self, job_id: str) -> Dict[str, Any]:
        return _USAGE.get(job_id or "-", {})


llm_token_usage_service = LLMTokenUsageService()
