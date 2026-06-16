"""Shared configuration helpers and environment-backed defaults."""

from __future__ import annotations

import os
import tempfile
from typing import List

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CORS_ALLOWED_ORIGINS = [
    "https://java-apex-accelerator.onrender.com",
    "https://java-apex-backend.onrender.com",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "https://javaapex-frontend-r4sl.onrender.com",
]


def get_default_work_dir() -> str:
    configured = (os.environ.get("WORK_DIR") or "").strip()
    if configured:
        return configured

    if os.name == "nt":
        system_drive = (os.environ.get("SystemDrive") or "C:").rstrip("\\/")
        return os.path.join(f"{system_drive}\\", "migrations")

    return os.path.join(tempfile.gettempdir(), "migrations")


def normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/")


def parse_origin_list(value: str) -> List[str]:
    seen = set()
    origins: List[str] = []
    for raw_origin in value.split(","):
        origin = normalize_origin(raw_origin)
        if not origin or origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return origins


def get_cors_allowed_origins() -> List[str]:
    seen = set()
    merged_origins: List[str] = []

    def add_origin(origin: str) -> None:
        normalized = normalize_origin(origin)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        merged_origins.append(normalized)

    configured = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    for origin in parse_origin_list(configured):
        add_origin(origin)

    frontend_origin = normalize_origin(os.environ.get("FRONTEND_ORIGIN", ""))
    if frontend_origin:
        add_origin(frontend_origin)

    for origin in DEFAULT_CORS_ALLOWED_ORIGINS:
        add_origin(origin)

    return merged_origins


def _parse_int_env(name: str, default: int) -> int:
    raw_value = (os.environ.get(name) or "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = (os.environ.get(name) or "").strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


def _parse_float_env(name: str, default: float) -> float:
    raw_value = (os.environ.get(name) or "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _parse_csv_env(name: str, default: List[str]) -> List[str]:
    raw_value = (os.environ.get(name) or "").strip()
    if not raw_value:
        return default.copy()
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _normalize_openai_model_name(value: str, default: str) -> str:
    raw_value = (value or "").strip() or default
    normalized_key = raw_value.strip().lower().replace(" ", "")
    aliases = {
        "gpt4o": "gpt-4o",
        "gpt-4o": "gpt-4o",
        "gpt4.1": "gpt-4.1",
        "gpt-4.1": "gpt-4.1",
    }
    return aliases.get(normalized_key, raw_value)


CORS_ALLOWED_ORIGINS = get_cors_allowed_origins()
DEFAULT_GITHUB_TOKEN = (os.environ.get("GITHUB_TOKEN") or "").strip()
STATIC_DIR = (os.environ.get("STATIC_DIR") or "/app/static").strip() or "/app/static"
INDEX_FILE = os.path.join(STATIC_DIR, "index.html")
DEFAULT_WORK_DIR = get_default_work_dir()
WORKSPACE_ARTIFACT_ROOT = (
    (os.environ.get("WORKSPACE_ARTIFACT_ROOT") or os.path.join(DEFAULT_WORK_DIR, "workspace_artifacts")).strip()
    or os.path.join(DEFAULT_WORK_DIR, "workspace_artifacts")
)
WORKSPACE_RESTORE_ROOT = (
    (os.environ.get("WORKSPACE_RESTORE_ROOT") or os.path.join(DEFAULT_WORK_DIR, "workspace_restores")).strip()
    or os.path.join(DEFAULT_WORK_DIR, "workspace_restores")
)
DEFAULT_JMETER_BASE_URL = (os.environ.get("JMETER_BASE_URL") or "http://localhost:8080").strip()
APP_HOST = (os.environ.get("HOST") or "0.0.0.0").strip() or "0.0.0.0"
APP_PORT = _parse_int_env("PORT", 8000)
# ============================================
# FORD LLM CONFIGURATION (Primary LLM Provider)
# ============================================
FORD_LLM_ENABLED = _parse_bool_env("FORD_LLM_ENABLED", True)
FORD_LLM_API_ENDPOINT = (os.environ.get("FORD_LLM_API_ENDPOINT") or "https://api.pivpn.core.ford.com/fordllmapi/api/v1/chat/completions").strip()
FORD_LLM_BASE_URL = (os.environ.get("FORD_LLM_BASE_URL") or "https://api.pivpn.core.ford.com/fordllmapi/api/v1").strip().rstrip("/")
FORD_LLM_API_KEY = (os.environ.get("FORD_LLM_API_KEY") or "").strip()
FORD_LLM_AUTH_TYPE = (os.environ.get("FORD_LLM_AUTH_TYPE") or "bearer").strip().lower()
FORD_LLM_MODEL = (os.environ.get("FORD_LLM_MODEL") or "gemini-2.5-flash").strip()
FORD_LLM_EXTRA_MODELS = _parse_csv_env("FORD_LLM_EXTRA_MODELS", ["gemini-2.5-flash", "gemini-2.5-pro"])
FORD_LLM_FALLBACK_MODELS = _parse_csv_env("FORD_LLM_FALLBACK_MODELS", ["gpt-5-mini-2025-08-07", "gemini-2.5-flash"])
FORD_LLM_TIMEOUT = max(5, _parse_int_env("FORD_LLM_TIMEOUT", 180))
FORD_LLM_MAX_RETRIES = max(0, _parse_int_env("FORD_LLM_MAX_RETRIES", 5))
FORD_LLM_TEMPERATURE = _parse_float_env("FORD_LLM_TEMPERATURE", 0.1)
FORD_LLM_MAX_TOKENS = max(1, _parse_int_env("FORD_LLM_MAX_TOKENS", 4096))
FORD_LLM_PROXY_URL = (os.environ.get("FORD_LLM_PROXY_URL") or "http://internet.ford.com:83").strip()
FORD_LLM_VERIFY_SSL = _parse_bool_env("FORD_LLM_VERIFY_SSL", True)
FORD_LLM_OAUTH_TOKEN_URL = (os.environ.get("FORD_LLM_OAUTH_TOKEN_URL") or "").strip()
FORD_LLM_OAUTH_CLIENT_ID = (os.environ.get("FORD_LLM_OAUTH_CLIENT_ID") or os.environ.get("FORDLLM_CLIENT_ID") or "").strip()
FORD_LLM_OAUTH_CLIENT_SECRET = (os.environ.get("FORD_LLM_OAUTH_CLIENT_SECRET") or os.environ.get("FORDLLM_CLIENT_SECRET") or "").strip()
FORD_LLM_OAUTH_SCOPE = (os.environ.get("FORD_LLM_OAUTH_SCOPE") or "").strip()

OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")
OPENAI_TEST_MODEL = (os.environ.get("OPENAI_TEST_MODEL") or "gpt-4.1").strip()
OPENAI_TEST_TEMPERATURE = _parse_float_env("OPENAI_TEST_TEMPERATURE", 0.2)
OPENAI_TEST_MAX_OUTPUT_TOKENS = max(1, _parse_int_env("OPENAI_TEST_MAX_OUTPUT_TOKENS", 1500))
OPENAI_TEST_TIMEOUT_SEC = max(5, _parse_int_env("OPENAI_TEST_TIMEOUT_SEC", 60))
CHATGPT_API_KEY = (os.environ.get("CHATGPT_API_KEY") or OPENAI_API_KEY).strip()
CHATGPT_BASE_URL = (os.environ.get("CHATGPT_BASE_URL") or OPENAI_BASE_URL).strip().rstrip("/")
CHATGPT_MODEL = _normalize_openai_model_name(
    os.environ.get("CHATGPT_MODEL") or OPENAI_TEST_MODEL,
    "gpt-4o",
)
ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
ANTHROPIC_BASE_URL = (os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com/v1").strip().rstrip("/")
ANTHROPIC_TEST_MODEL = (os.environ.get("ANTHROPIC_TEST_MODEL") or "claude-3-7-sonnet-latest").strip()
ANTHROPIC_API_VERSION = (os.environ.get("ANTHROPIC_API_VERSION") or "2023-06-01").strip()
ANTHROPIC_TEST_TEMPERATURE = _parse_float_env("ANTHROPIC_TEST_TEMPERATURE", 0.2)
ANTHROPIC_TEST_MAX_TOKENS = max(1, _parse_int_env("ANTHROPIC_TEST_MAX_TOKENS", 1500))
ANTHROPIC_TEST_TIMEOUT_SEC = max(5, _parse_int_env("ANTHROPIC_TEST_TIMEOUT_SEC", 60))
CLAUDE_MODEL = (
    (os.environ.get("CLAUDE_MODEL") or os.environ.get("ANTHROPIC_MODEL") or ANTHROPIC_TEST_MODEL).strip()
    or ANTHROPIC_TEST_MODEL
)
DEESEEK_API_KEY = (os.environ.get("DEESEEK_API_KEY") or "").strip()
DEEPSEEK_BASE_URL = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.ai/v1").strip().rstrip("/")
DEEPSEEK_TEST_MODEL = (os.environ.get("DEEPSEEK_TEST_MODEL") or "deeplens-alpha").strip()
DEEPSEEK_TEST_TEMPERATURE = _parse_float_env("DEEPSEEK_TEST_TEMPERATURE", 0.15)
DEEPSEEK_TEST_MAX_TOKENS = max(1, _parse_int_env("DEEPSEEK_TEST_MAX_TOKENS", 1200))
DEEPSEEK_TEST_TIMEOUT_SEC = max(5, _parse_int_env("DEEPSEEK_TEST_TIMEOUT_SEC", 60))
GROQ_API_KEY = (os.environ.get("GROQ_API_KEY") or "").strip()
GROQ_API_KEYS = _parse_csv_env("GROQ_API_KEYS", [GROQ_API_KEY] if GROQ_API_KEY else [])
GROQ_BASE_URL = (os.environ.get("GROQ_BASE_URL") or "https://api.groq.com/openai/v1").strip().rstrip("/")
GROQ_TEST_MODEL = (os.environ.get("GROQ_TEST_MODEL") or "llama-3.3-70b-versatile").strip()
GROQ_TEST_MODELS = _parse_csv_env(
    "GROQ_TEST_MODELS",
    ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"],
)
GROQ_TEST_TEMPERATURE = _parse_float_env("GROQ_TEST_TEMPERATURE", 0.2)
GROQ_TEST_TOP_P = _parse_float_env("GROQ_TEST_TOP_P", 0.9)
GROQ_TEST_MAX_TOKENS = max(1, _parse_int_env("GROQ_TEST_MAX_TOKENS", 1500))
GROQ_TEST_TIMEOUT_SEC = max(5, _parse_int_env("GROQ_TEST_TIMEOUT_SEC", 90))
HUGGINGFACE_API_KEY = (os.environ.get("HUGGINGFACE_API_KEY") or "").strip()
HUGGINGFACE_ROUTER_BASE_URL = (os.environ.get("HUGGINGFACE_ROUTER_BASE_URL") or "https://router.huggingface.co").strip().rstrip("/")
HUGGINGFACE_CHAT_COMPLETIONS_URL = (
    os.environ.get("HUGGINGFACE_CHAT_COMPLETIONS_URL")
    or f"{HUGGINGFACE_ROUTER_BASE_URL}/v1/chat/completions"
).strip()
HUGGINGFACE_INFERENCE_BASE_URL = (
    os.environ.get("HUGGINGFACE_INFERENCE_BASE_URL")
    or f"{HUGGINGFACE_ROUTER_BASE_URL}/hf-inference/models"
).strip().rstrip("/")
HUGGINGFACE_TEST_MODEL = (os.environ.get("HUGGINGFACE_TEST_MODEL") or "mistralai/Mistral-7B-Instruct-v0.3").strip()
HUGGINGFACE_TEST_MODELS = _parse_csv_env(
    "HUGGINGFACE_TEST_MODELS",
    [
        "mistralai/Mistral-7B-Instruct-v0.3",
        "HuggingFaceH4/zephyr-7b-beta",
        "google/flan-t5-xxl",
    ],
)
HUGGINGFACE_PRIORITY_TEST_MODELS = _parse_csv_env(
    "HUGGINGFACE_PRIORITY_TEST_MODELS",
    ["Qwen/Qwen2.5-Coder-32B-Instruct"],
)
HUGGINGFACE_TEST_TEMPERATURE = _parse_float_env("HUGGINGFACE_TEST_TEMPERATURE", 0.2)
HUGGINGFACE_TEST_TOP_P = _parse_float_env("HUGGINGFACE_TEST_TOP_P", 0.9)
HUGGINGFACE_TEST_MAX_TOKENS = max(1, _parse_int_env("HUGGINGFACE_TEST_MAX_TOKENS", 1500))
HUGGINGFACE_TEST_MAX_NEW_TOKENS = max(1, _parse_int_env("HUGGINGFACE_TEST_MAX_NEW_TOKENS", 1500))
HUGGINGFACE_TEST_TIMEOUT_SEC = max(5, _parse_int_env("HUGGINGFACE_TEST_TIMEOUT_SEC", 90))
HF_TOKEN = (os.environ.get("HF_TOKEN") or "").strip()
HF_MODEL = (os.environ.get("HF_MODEL") or "openai/gpt-oss-120b:fastest").strip()
HF_RECOMMENDATION_ENDPOINT = (
    os.environ.get("HF_RECOMMENDATION_ENDPOINT")
    or HUGGINGFACE_CHAT_COMPLETIONS_URL
).strip()
MICROSERVICE_ELIGIBILITY_MODEL = (
    os.environ.get("MICROSERVICE_ELIGIBILITY_MODEL")
    or "openai/gpt-oss-120b:fastest"
).strip()
MICROSERVICE_ELIGIBILITY_LLM_URL = (
    os.environ.get("MICROSERVICE_ELIGIBILITY_LLM_URL")
    or HUGGINGFACE_CHAT_COMPLETIONS_URL
).strip()
BUILD_CONVERSION_LLM_MODEL = (
    os.environ.get("BUILD_CONVERSION_LLM_MODEL")
    or "Qwen/Qwen2.5-Coder-32B-Instruct"
).strip()
BUILD_CONVERSION_LLM_URL = (
    os.environ.get("BUILD_CONVERSION_LLM_URL")
    or HUGGINGFACE_CHAT_COMPLETIONS_URL
).strip()
HF_CODE_ANALYSIS_MODEL = (os.environ.get("HF_CODE_ANALYSIS_MODEL") or "bigcode/starcoder2-15b-instruct").strip()
HF_BUSINESS_LOGIC_MODEL = (os.environ.get("HF_BUSINESS_LOGIC_MODEL") or "microsoft/DialoGPT-large").strip()
HF_CODE_QUALITY_MODEL = (os.environ.get("HF_CODE_QUALITY_MODEL") or "microsoft/codebert-base").strip()
HF_GENERAL_MODEL = (os.environ.get("HF_GENERAL_MODEL") or "mistralai/Mistral-7B-Instruct-v0.2").strip()
HF_CHECK_MODELS = _parse_bool_env("HF_CHECK_MODELS", False)
OLLAMA_URL = (os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434").strip().rstrip("/")
OLLAMA_MODEL = (os.environ.get("OLLAMA_MODEL") or "deepseek-coder:6.7b-instruct").strip()
OLLAMA_TEST_TEMPERATURE = _parse_float_env("OLLAMA_TEST_TEMPERATURE", 0.2)
OLLAMA_TEST_TIMEOUT_SEC = max(5, _parse_int_env("OLLAMA_TEST_TIMEOUT_SEC", 120))
JAVA_TEST_TIMEOUT_SEC = max(30, _parse_int_env("JAVA_TEST_TIMEOUT_SEC", 300))
DEFAULT_LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "ford_llm").strip().lower() or "ford_llm"
LLM_TEST_GENERATE_ADDITIONAL_WHEN_EXISTING = _parse_bool_env(
    "LLM_TEST_GENERATE_ADDITIONAL_WHEN_EXISTING", False
)
LLM_TEST_MIN_EXISTING_TEST_CASES_FOR_GENERATION = max(
    0,
    _parse_int_env("LLM_TEST_MIN_EXISTING_TEST_CASES_FOR_GENERATION", 3),
)
LLM_TEST_MAX_ITERS = max(0, _parse_int_env("LLM_TEST_MAX_ITERS", 2))
LLM_TEST_MAX_NEW_TESTS_PER_ITER = max(1, _parse_int_env("LLM_TEST_MAX_NEW_TESTS_PER_ITER", 4))
LLM_TEST_MAX_CLASSES = max(1, _parse_int_env("LLM_TEST_MAX_CLASSES", 15))
LLM_TEST_TARGET_LINE_COVERAGE = min(
    1.0,
    max(0.0, _parse_float_env("LLM_TEST_TARGET_LINE_COVERAGE", 0.80)),
)
LLM_TEST_TARGET_BRANCH_COVERAGE = min(
    1.0,
    max(0.0, _parse_float_env("LLM_TEST_TARGET_BRANCH_COVERAGE", 0.60)),
)
MICROSERVICE_ELIGIBILITY_MAX_FILE_INSPECTIONS = max(
    24, _parse_int_env("MICROSERVICE_ELIGIBILITY_MAX_FILE_INSPECTIONS", 160)
)
LLM_TEST_DEFAULT_JAVA_VERSION = (os.environ.get("LLM_TEST_DEFAULT_JAVA_VERSION") or "17").strip()
LLM_TEST_SPRING_BOOT_PARENT_VERSION = (
    os.environ.get("LLM_TEST_SPRING_BOOT_PARENT_VERSION") or "3.2.5"
).strip()
LLM_TEST_JUNIT4_VERSION = (os.environ.get("LLM_TEST_JUNIT4_VERSION") or "4.13.2").strip()
LLM_TEST_JUNIT5_VERSION = (os.environ.get("LLM_TEST_JUNIT5_VERSION") or "5.10.2").strip()
LLM_TEST_MOCKITO_JUNIT_JUPITER_VERSION = (
    os.environ.get("LLM_TEST_MOCKITO_JUNIT_JUPITER_VERSION") or "5.11.0"
).strip()
LLM_TEST_SUREFIRE_PLUGIN_VERSION = (
    os.environ.get("LLM_TEST_SUREFIRE_PLUGIN_VERSION") or "3.2.5"
).strip()
LLM_TEST_JACOCO_PLUGIN_VERSION = (
    os.environ.get("LLM_TEST_JACOCO_PLUGIN_VERSION") or "0.8.12"
).strip()
FOSSA_API_BASE_URL = (
    os.environ.get("FOSSA_API_BASE_URL") or "https://app.fossa.com"
).strip().rstrip("/")
MAVEN_CENTRAL_ENABLED = _parse_bool_env("MAVEN_CENTRAL_ENABLED", True)
MAVEN_CENTRAL_SEARCH_URL = (
    os.environ.get("MAVEN_CENTRAL_SEARCH_URL") or "https://search.maven.org/solrsearch/select"
).strip()
MAVEN_CENTRAL_TIMEOUT_SEC = max(1, _parse_int_env("MAVEN_CENTRAL_TIMEOUT_SEC", 4))
MAVEN_CENTRAL_MAX_ROWS = max(1, _parse_int_env("MAVEN_CENTRAL_MAX_ROWS", 20))
MAVEN_CENTRAL_ALLOW_PRERELEASES = _parse_bool_env("MAVEN_CENTRAL_ALLOW_PRERELEASES", False)
REDIS_URL = (os.environ.get("REDIS_URL") or "").strip()
CELERY_BROKER_URL = (os.environ.get("CELERY_BROKER_URL") or REDIS_URL).strip()
CELERY_RESULT_BACKEND = (os.environ.get("CELERY_RESULT_BACKEND") or CELERY_BROKER_URL).strip()
CELERY_TASK_QUEUE_CORE = (
    (os.environ.get("CELERY_TASK_QUEUE_CORE") or os.environ.get("CELERY_TASK_QUEUE") or "migration-core").strip()
    or "migration-core"
)
CELERY_TASK_QUEUE_TESTS = (
    (os.environ.get("CELERY_TASK_QUEUE_TESTS") or "migration-tests").strip()
    or "migration-tests"
)
CELERY_TASK_QUEUE_SCANS = (
    (os.environ.get("CELERY_TASK_QUEUE_SCANS") or "migration-scans").strip()
    or "migration-scans"
)
CELERY_TASK_QUEUE = CELERY_TASK_QUEUE_CORE
MIGRATION_MAX_CONCURRENT_JOBS = max(1, _parse_int_env("MIGRATION_MAX_CONCURRENT_JOBS", 1))
WORKER_HEARTBEAT_INTERVAL_SEC = max(1, _parse_int_env("WORKER_HEARTBEAT_INTERVAL_SEC", 15))
JOB_STALE_TIMEOUT_SEC = max(WORKER_HEARTBEAT_INTERVAL_SEC, _parse_int_env("JOB_STALE_TIMEOUT_SEC", 90))
CELERY_TASK_SOFT_TIME_LIMIT_SEC = max(60, _parse_int_env("CELERY_TASK_SOFT_TIME_LIMIT_SEC", 2 * 60 * 60))
CELERY_TASK_TIME_LIMIT_SEC = max(
    CELERY_TASK_SOFT_TIME_LIMIT_SEC,
    _parse_int_env("CELERY_TASK_TIME_LIMIT_SEC", CELERY_TASK_SOFT_TIME_LIMIT_SEC + (5 * 60)),
)
ALLOW_IN_PROCESS_JOB_FALLBACK = _parse_bool_env("ALLOW_IN_PROCESS_JOB_FALLBACK", True)
FORCE_IN_PROCESS_MIGRATION = _parse_bool_env("FORCE_IN_PROCESS_MIGRATION", False)

# Qdrant vector store configuration (optional)
QDRANT_URL = (os.environ.get("QDRANT_URL") or "http://127.0.0.1:6333").strip().rstrip("/")
QDRANT_API_KEY = (os.environ.get("QDRANT_API_KEY") or "").strip()
QDRANT_COLLECTION_PREFIX = (os.environ.get("QDRANT_COLLECTION_PREFIX") or "javaapex").strip()


# ---------------------------------------------------------------------------
# httpx proxy compatibility helper
# ---------------------------------------------------------------------------
# httpx < 0.28 uses ``proxies=`` (dict), httpx >= 0.28 uses ``proxy=`` (str).
# This helper returns the right kwargs dict so callers can just unpack it:
#   ``httpx.AsyncClient(**httpx_proxy_kwargs(url), ...)``
def httpx_proxy_kwargs(proxy_url: str | None = None) -> dict:
    """Return httpx-version-safe proxy keyword arguments."""
    if not proxy_url:
        return {}
    try:
        import httpx as _hx
        _ver = tuple(int(p) for p in _hx.__version__.split(".")[:2])
    except Exception:
        _ver = (0, 25)
    if _ver >= (0, 28):
        return {"proxy": proxy_url}
    return {"proxies": {"http://": proxy_url, "https://": proxy_url}}
