"""Logging helpers for safe, consistent backend observability."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
import logging
import os
import re

DEFAULT_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] "
    "[trace=%(trace_id)s req=%(request_id)s job=%(job_id)s worker=%(worker_id)s] "
    "%(name)s: %(message)s"
)
DEFAULT_LOG_DATEFMT = "%H:%M:%S"

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_job_id_var: ContextVar[str] = ContextVar("job_id", default="-")
_worker_id_var: ContextVar[str] = ContextVar("worker_id", default="-")

_SENSITIVE_ENV_MARKERS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "KEY",
    "AUTH",
    "COOKIE",
    "SESSION",
)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _request_id_var.get() or "-"
        job_id = _job_id_var.get() or "-"
        worker_id = _worker_id_var.get() or "-"

        record.request_id = request_id
        record.job_id = job_id
        record.worker_id = worker_id
        record.trace_id = job_id if job_id != "-" else request_id
        return True


_context_filter = RequestContextFilter()


def _configure_handler(handler: logging.Handler) -> None:
    handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATEFMT))
    if not any(isinstance(existing_filter, RequestContextFilter) for existing_filter in handler.filters):
        handler.addFilter(_context_filter)


def configure_logging() -> None:
    """Configure root logging once, using env-driven log level."""
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format=DEFAULT_LOG_FORMAT,
            datefmt=DEFAULT_LOG_DATEFMT,
        )
    else:
        root_logger.setLevel(level)

    for handler in root_logger.handlers:
        _configure_handler(handler)


def set_request_id(request_id: str) -> Token[str]:
    return _request_id_var.set((request_id or "").strip() or "-")


def set_job_id(job_id: str) -> Token[str]:
    return _job_id_var.set((job_id or "").strip() or "-")


def set_worker_id(worker_id: str) -> Token[str]:
    return _worker_id_var.set((worker_id or "").strip() or "-")


def reset_request_id(token: Token[str]) -> None:
    _request_id_var.reset(token)


def reset_job_id(token: Token[str]) -> None:
    _job_id_var.reset(token)


def reset_worker_id(token: Token[str]) -> None:
    _worker_id_var.reset(token)


def get_request_id() -> str:
    return _request_id_var.get()


def get_job_id() -> str:
    return _job_id_var.get()


def get_worker_id() -> str:
    return _worker_id_var.get()


@contextmanager
def logging_context(
    *,
    request_id: str | None = None,
    job_id: str | None = None,
    worker_id: str | None = None,
):
    tokens: list[tuple[str, Token[str]]] = []
    try:
        if request_id is not None:
            tokens.append(("request_id", set_request_id(request_id)))
        if job_id is not None:
            tokens.append(("job_id", set_job_id(job_id)))
        if worker_id is not None:
            tokens.append(("worker_id", set_worker_id(worker_id)))
        yield
    finally:
        for key, token in reversed(tokens):
            if key == "request_id":
                reset_request_id(token)
            elif key == "job_id":
                reset_job_id(token)
            else:
                reset_worker_id(token)


def redact_token(value: str, *, prefix_chars: int = 4, suffix_chars: int = 2) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= prefix_chars + suffix_chars:
        return "[REDACTED]"
    return f"{raw[:prefix_chars]}...[REDACTED]...{raw[-suffix_chars:]}"


def redact_url_credentials(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    return re.sub(r"://[^/@\s]+@", "://[REDACTED]@", raw)


def redact_env_value(name: str, value: str) -> str:
    env_name = (name or "").strip().upper()
    if any(marker in env_name for marker in _SENSITIVE_ENV_MARKERS):
        return "[REDACTED]"
    if env_name.endswith("_OPTS"):
        return "[REDACTED]"
    return str(value)
