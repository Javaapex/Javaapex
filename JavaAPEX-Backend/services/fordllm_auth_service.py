"""
FordLLM Authentication Service
Manages token lifecycle with automatic refresh every ~55 minutes
(FordLLM tokens expire every 1 hour).
"""
import os
import json
import time
import logging
import threading
from typing import Optional
from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", ".token_cache.json")

# Token validity buffer – refresh 5 minutes before the 1-hour expiry
TOKEN_TTL_SECONDS = 3300  # 55 minutes


class FordLLMAuthService:
    """Thread-safe singleton that keeps a valid FordLLM access token."""

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

        self._token: Optional[str] = None
        self._token_timestamp: float = 0.0
        self._refresh_timer: Optional[threading.Timer] = None
        self._token_lock = threading.Lock()

        # Ford proxy – required on the corporate network
        os.environ.setdefault("HTTP_PROXY", "http://internet.ford.com:83")
        os.environ.setdefault("HTTPS_PROXY", "http://internet.ford.com:83")

        self.client_id = os.getenv("FORDLLM_CLIENT_ID", "")
        self.client_secret = os.getenv("FORDLLM_CLIENT_SECRET", "")

        if not self.client_id or not self.client_secret:
            logger.warning(
                "FORDLLM_CLIENT_ID / FORDLLM_CLIENT_SECRET not set – "
                "FordLLM integration will be unavailable."
            )

        # Try to load a cached token on startup
        self._load_cached_token()

        # Schedule the background auto-refresh loop
        self._schedule_refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def token(self) -> str:
        """Return a valid access token, fetching a new one if necessary."""
        with self._token_lock:
            if self._is_token_valid():
                return self._token  # type: ignore[return-value]

        # Token expired or missing – fetch synchronously
        return self.refresh_token()

    def refresh_token(self) -> str:
        """Force-fetch a new token from FordLLM."""
        with self._token_lock:
            return self._fetch_token()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_token_valid(self) -> bool:
        return (
            self._token is not None
            and (time.time() - self._token_timestamp) < TOKEN_TTL_SECONDS
        )

    def _fetch_token(self) -> str:
        """Use the fordllm-sdk TokenFetcher to obtain a fresh token."""
        try:
            from fordllm.utils import TokenFetcher

            logger.info("Fetching new FordLLM access token …")
            fetcher = TokenFetcher(
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            token = fetcher.token

            if not token:
                raise ValueError("TokenFetcher returned an empty token.")

            self._token = token
            self._token_timestamp = time.time()
            self._save_cached_token()

            logger.info("FordLLM access token refreshed successfully.")
            return token

        except Exception as exc:
            logger.error("Failed to fetch FordLLM token: %s", exc)
            # Clear stale cache
            self._clear_cache()
            raise RuntimeError(f"FordLLM token fetch failed: {exc}") from exc

    # ---- Cache persistence -------------------------------------------------

    def _load_cached_token(self) -> None:
        """Load token from the local JSON cache if still valid."""
        try:
            if not os.path.exists(TOKEN_CACHE_FILE):
                return
            with open(TOKEN_CACHE_FILE, "r") as fh:
                cache = json.load(fh)
            ts = cache.get("timestamp", 0)
            tok = cache.get("token", "")
            if tok and (time.time() - ts) < TOKEN_TTL_SECONDS:
                self._token = tok
                self._token_timestamp = ts
                logger.info("Loaded cached FordLLM token (age %.0fs).", time.time() - ts)
        except Exception as exc:
            logger.warning("Could not load token cache: %s", exc)

    def _save_cached_token(self) -> None:
        try:
            with open(TOKEN_CACHE_FILE, "w") as fh:
                json.dump({"token": self._token, "timestamp": self._token_timestamp}, fh)
        except Exception as exc:
            logger.warning("Could not save token cache: %s", exc)

    def _clear_cache(self) -> None:
        self._token = None
        self._token_timestamp = 0.0
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                os.remove(TOKEN_CACHE_FILE)
        except OSError:
            pass

    # ---- Background auto-refresh -------------------------------------------

    def _schedule_refresh(self) -> None:
        """Schedule the next automatic token refresh."""
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()

        self._refresh_timer = threading.Timer(TOKEN_TTL_SECONDS, self._auto_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()
        logger.debug("Next FordLLM token refresh scheduled in %d seconds.", TOKEN_TTL_SECONDS)

    def _auto_refresh(self) -> None:
        """Background callback: refresh token and reschedule."""
        try:
            self.refresh_token()
        except Exception as exc:
            logger.error("Auto-refresh failed: %s – will retry at next interval.", exc)
        finally:
            self._schedule_refresh()


# ---------------------------------------------------------------------------
# Module-level convenience singleton
# ---------------------------------------------------------------------------
fordllm_auth = FordLLMAuthService()
