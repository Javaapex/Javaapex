"""
Ford LLM Token Manager
Automatically fetches and refreshes the Ford LLM API bearer token
using OAuth2 client_credentials flow (same as fordllm-sdk TokenFetcher).

Token is cached for ~55 minutes (3300s) and auto-refreshed before expiry.
Proactive refresh: ensure_fresh_token() pre-fetches if < 10 min remain.
No external SDK dependency — uses only `requests` and `threading`.
"""
import os
import time
import logging
import threading
import requests

logger = logging.getLogger(__name__)

# Token endpoint and scope — loaded from .env (no hardcoded defaults)
_TOKEN_ENDPOINT = os.getenv("FORD_LLM_OAUTH_TOKEN_URL", "").strip()
_DEFAULT_SCOPE = os.getenv("FORD_LLM_OAUTH_SCOPE", "").strip()

# Refresh token 5 minutes before expiry (tokens last ~1 hour = 3600s)
_TOKEN_TTL_SECONDS = 3300  # 55 minutes

# Proactive refresh threshold — fetch new token if < this many seconds remain
_PROACTIVE_REFRESH_SECONDS = 600  # 10 minutes


class FordLLMTokenManager:
    """
    Manages automatic fetching and refreshing of Ford LLM bearer tokens.

    Usage:
        manager = FordLLMTokenManager()       # reads from .env
        token = manager.get_token()           # always returns a valid token
        manager.start_auto_refresh()          # background thread refreshes every 50 min
        manager.stop_auto_refresh()           # stop background thread
    """

    def __init__(
        self,
        client_id: str = None,
        client_secret: str = None,
        scope: str = None,
    ):
        self.client_id = client_id or os.getenv("FORDLLM_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("FORDLLM_CLIENT_SECRET", "")
        self.scope = scope or _DEFAULT_SCOPE

        # Proxy settings (loaded from .env — no hardcoded defaults)
        _proxy = os.getenv("FORD_LLM_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", "")))
        self.proxies = {
            "http": os.getenv("HTTP_PROXY", _proxy),
            "https": os.getenv("HTTPS_PROXY", _proxy),
        } if _proxy else None

        # Token cache
        self._token: str = ""
        self._token_fetched_at: float = 0.0
        self._token_expires_in: int = 3600  # last reported expires_in from server
        self._lock = threading.Lock()

        # Refresh tracking — how many times token was refreshed since startup
        self._refresh_count: int = 0
        self._last_refresh_at: float = 0.0

        # Background refresh thread
        self._refresh_thread: threading.Thread = None
        self._stop_event = threading.Event()

        if not self.client_id or not self.client_secret:
            logger.warning(
                "FORDLLM_CLIENT_ID or FORDLLM_CLIENT_SECRET not set. "
                "Auto token refresh will not work. "
                "Set them in .env to enable automatic token management."
            )

    @property
    def is_configured(self) -> bool:
        """Check if client credentials are configured"""
        return bool(self.client_id and self.client_secret)

    def _is_token_valid(self) -> bool:
        """Check if cached token is still valid (within TTL)"""
        if not self._token:
            return False
        return (time.time() - self._token_fetched_at) < _TOKEN_TTL_SECONDS

    @property
    def remaining_seconds(self) -> float:
        """How many seconds until the current token expires (estimated)."""
        if not self._token or self._token_fetched_at == 0:
            return 0.0
        elapsed = time.time() - self._token_fetched_at
        remaining = self._token_expires_in - elapsed
        return max(remaining, 0.0)

    @property
    def refresh_count(self) -> int:
        """How many times the token has been refreshed since startup."""
        return self._refresh_count

    @property
    def refresh_stats(self) -> dict:
        """Return current token health stats."""
        return {
            "refresh_count": self._refresh_count,
            "remaining_seconds": round(self.remaining_seconds),
            "token_valid": self._is_token_valid(),
            "last_refresh_at": self._last_refresh_at,
        }

    def needs_proactive_refresh(self) -> bool:
        """Check if token should be proactively refreshed (< 10 min remaining)."""
        return self.remaining_seconds < _PROACTIVE_REFRESH_SECONDS

    def ensure_fresh_token(self) -> str:
        """
        Ensure we have a token with at least 10 minutes of life remaining.
        If the current token has < 10 min left, fetch a new one proactively.
        This should be called BEFORE each LLM API call.

        Returns:
            str: A valid token with sufficient remaining lifetime.
        """
        if self._is_token_valid() and not self.needs_proactive_refresh():
            return self._token

        # Token expired or close to expiring — fetch new one
        remaining = round(self.remaining_seconds)
        if self._token:
            logger.info("Proactive token refresh — only %ds remaining (threshold: %ds)", remaining, _PROACTIVE_REFRESH_SECONDS)
        else:
            logger.info("No token available — fetching initial token")

        new_token = self.fetch_token()
        self._propagate_token(new_token)
        return new_token

    def force_refresh(self) -> str:
        """
        Force an immediate token refresh regardless of remaining time.
        Used after receiving a 401 error from the LLM API.

        Returns:
            str: A freshly fetched token.
        """
        logger.warning("Force token refresh triggered (likely 401 error)")
        with self._lock:
            self._token = ""
            self._token_fetched_at = 0.0
        new_token = self.fetch_token()
        self._propagate_token(new_token)
        return new_token

    def _propagate_token(self, token: str):
        """Push the new token into env var and all live service instances."""
        os.environ["FORD_LLM_API_KEY"] = token

        # Update ford_llm_service singleton
        try:
            from services.ford_llm_service import ford_llm_service
            ford_llm_service.api_key = token
            ford_llm_service._oauth_token = token
            ford_llm_service._oauth_token_expiry = time.time() + self._token_expires_in
        except Exception:
            pass

        # Update ai_service_huggingface singleton
        try:
            from services.ai_service_huggingface import huggingface_ai_service
            huggingface_ai_service.ford_llm_api_key = token
            huggingface_ai_service.available = True
        except Exception:
            pass

        # Update llm_test_pipeline singleton
        try:
            from services.llm_test_pipeline import llm_test_pipeline
            llm_test_pipeline.ford_llm_api_key = token
            llm_test_pipeline._ford_oauth_token = token
            llm_test_pipeline._ford_oauth_token_expiry = time.time() + self._token_expires_in
        except Exception:
            pass

    def fetch_token(self) -> str:
        """
        Fetch a new bearer token from Microsoft OAuth2 endpoint.
        This is the same flow as fordllm-sdk's TokenFetcher.

        Returns:
            str: The access token (JWT)

        Raises:
            RuntimeError: If token fetch fails
        """
        if not self.is_configured:
            raise RuntimeError(
                "Cannot fetch Ford LLM token: FORDLLM_CLIENT_ID and FORDLLM_CLIENT_SECRET "
                "must be set in .env file."
            )

        if not _TOKEN_ENDPOINT:
            raise RuntimeError(
                "Cannot fetch Ford LLM token: FORD_LLM_OAUTH_TOKEN_URL must be set in .env file."
            )

        if not self.scope:
            raise RuntimeError(
                "Cannot fetch Ford LLM token: FORD_LLM_OAUTH_SCOPE must be set in .env file."
            )

        logger.info("Fetching new Ford LLM access token...")

        try:
            response = requests.post(
                _TOKEN_ENDPOINT,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": self.scope,
                    "grant_type": "client_credentials",
                },
                proxies=self.proxies,
                timeout=30,
            )

            if not response.ok:
                raise RuntimeError(
                    f"Token fetch failed (HTTP {response.status_code}): {response.text[:500]}"
                )

            token_data = response.json()
            token = token_data.get("access_token", "")

            if not token:
                raise RuntimeError("Token response did not contain access_token")

            with self._lock:
                self._token = token
                self._token_fetched_at = time.time()
                self._token_expires_in = token_data.get("expires_in", 3600)
                self._refresh_count += 1
                self._last_refresh_at = time.time()

            logger.info(
                "Ford LLM access token fetched (refresh #%d, expires_in=%ds)",
                self._refresh_count, self._token_expires_in,
            )
            return token

        except requests.RequestException as e:
            raise RuntimeError(f"Network error fetching Ford LLM token: {e}")

    def get_token(self) -> str:
        """
        Get a valid token. Returns cached token if still valid,
        otherwise fetches a new one.

        Returns:
            str: A valid access token
        """
        with self._lock:
            if self._is_token_valid():
                return self._token

        # Token expired or not yet fetched — get a new one
        return self.fetch_token()

    def start_auto_refresh(self, interval_seconds: int = 3000):
        """
        Start a background thread that refreshes the token every `interval_seconds`.
        Default: 3000 seconds (50 minutes) — well before the 1-hour expiry.
        """
        if not self.is_configured:
            logger.warning("Cannot start auto-refresh: client credentials not configured")
            return

        if self._refresh_thread and self._refresh_thread.is_alive():
            logger.info("Auto-refresh thread already running")
            return

        self._stop_event.clear()

        def _refresh_loop():
            while not self._stop_event.is_set():
                # Wait for the interval (or until stop is signaled)
                self._stop_event.wait(timeout=interval_seconds)
                if self._stop_event.is_set():
                    break
                try:
                    logger.info(
                        "Auto-refreshing Ford LLM token (remaining: %ds)...",
                        round(self.remaining_seconds),
                    )
                    new_token = self.fetch_token()
                    self._propagate_token(new_token)
                    logger.info(
                        "Auto-refresh complete — token #%d active, ~%ds remaining",
                        self._refresh_count, round(self.remaining_seconds),
                    )
                except Exception as e:
                    logger.error("Auto-refresh failed: %s — will retry at next interval", e)

        self._refresh_thread = threading.Thread(
            target=_refresh_loop,
            daemon=True,
            name="ford-llm-token-refresh"
        )
        self._refresh_thread.start()
        logger.info(
            "Token auto-refresh started (every %d minutes)",
            interval_seconds // 60,
        )

    def stop_auto_refresh(self):
        """Stop the background refresh thread"""
        self._stop_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
            logger.info("Token auto-refresh stopped")


# ── Module-level singleton ──
ford_token_manager = FordLLMTokenManager()
