"""
Groq LLM Token Manager (replaces Ford LLM Token Manager)
Groq uses simple API key auth — no OAuth needed.
This manager provides a compatible interface for the rest of the codebase
by reading the API key from the GROQ_API_KEY / FORD_LLM_API_KEY env vars.
"""
import os
import time
import logging

logger = logging.getLogger(__name__)


class FordLLMTokenManager:
    """
    Simplified token manager for Groq API (replaces Ford OAuth token manager).
    
    Groq uses static API keys — no OAuth token refresh needed.
    This class provides a compatible interface for code that previously
    depended on the Ford LLM OAuth token manager.
    
    Usage:
        manager = FordLLMTokenManager()
        token = manager.get_token()           # returns the Groq API key
    """

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", os.getenv("FORD_LLM_API_KEY", "")).strip()
        if not self.api_key:
            logger.warning(
                "GROQ_API_KEY not set. Groq LLM API calls will fail. "
                "Set GROQ_API_KEY in .env to enable Groq LLM."
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def ensure_fresh_token(self) -> str:
        return self.api_key

    def force_refresh(self) -> str:
        return self.api_key

    def get_token(self) -> str:
        return self.api_key

    def _propagate_token(self, token: str):
        os.environ["FORD_LLM_API_KEY"] = token
        try:
            from services.ford_llm_service import ford_llm_service
            ford_llm_service.api_key = token
        except Exception:
            pass
        try:
            from services.ai_service_huggingface import huggingface_ai_service
            huggingface_ai_service.ford_llm_api_key = token
            huggingface_ai_service.available = True
        except Exception:
            pass
        try:
            from services.llm_test_pipeline import llm_test_pipeline
            llm_test_pipeline.ford_llm_api_key = token
        except Exception:
            pass

    def fetch_token(self) -> str:
        return self.api_key

    def start_auto_refresh(self, interval_seconds: int = 3000):
        pass

    def stop_auto_refresh(self):
        pass


# ── Module-level singleton ──
ford_token_manager = FordLLMTokenManager()
