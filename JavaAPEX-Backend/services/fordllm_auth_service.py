"""
Compatibility auth service for legacy FordLLM integrations.
Now uses standard OpenAI-compatible API keys/providers.
"""
import os
import logging
import threading
from typing import Optional
from dotenv import load_dotenv

load_dotenv(encoding="utf-8")
logger = logging.getLogger(__name__)


class FordLLMAuthService:
    """Backward-compatible singleton that returns an API key token.

    Priority:
    1) LLM_API_KEY
    2) OPENAI_API_KEY
    3) FORDLLM_CLIENT_SECRET (legacy fallback)
    """

    _instance: Optional["FordLLMAuthService"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "FordLLMAuthService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        self.client_id = os.getenv("LLM_CLIENT_ID", os.getenv("FORDLLM_CLIENT_ID", ""))
        self.client_secret = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("FORDLLM_CLIENT_SECRET", "")

        if not self.client_secret:
            logger.warning("No LLM API key configured (set LLM_API_KEY or OPENAI_API_KEY).")

    @property
    def token(self) -> str:
        token = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("FORDLLM_CLIENT_SECRET", "")
        if not token:
            raise RuntimeError("No API key found. Set LLM_API_KEY or OPENAI_API_KEY.")
        return token

    def refresh_token(self) -> str:
        """No-op refresh for static API keys."""
        return self.token


fordllm_auth = FordLLMAuthService()
