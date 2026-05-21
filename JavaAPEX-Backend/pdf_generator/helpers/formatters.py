from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlparse


def format_timestamp(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return "N/A"
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return text


def get_repository_name(repo_url: Optional[str]) -> str:
    if not repo_url:
        return "Repository"
    if repo_url.startswith("local://"):
        normalized = repo_url.replace("local://", "").rstrip("/\\")
        return normalized.split("/")[-1].split("\\")[-1] or "Local Project"
    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if not path:
        return repo_url
    return path.split("/")[-1].replace(".git", "") or repo_url


def compact_path(path: Optional[str], max_length: int = 58) -> str:
    if not path:
        return "N/A"
    if len(path) <= max_length:
        return path
    return "..." + path[-(max_length - 3):]


def normalize_severity(severity: Optional[str]) -> str:
    return (severity or "INFO").strip().upper() or "INFO"


def severity_bucket(severity: Optional[str]) -> str:
    normalized = normalize_severity(severity)
    if normalized in {"BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"}:
        return normalized
    if normalized == "LOW":
        return "MINOR"
    if normalized == "MEDIUM":
        return "MAJOR"
    if normalized == "HIGH":
        return "CRITICAL"
    return "INFO"

