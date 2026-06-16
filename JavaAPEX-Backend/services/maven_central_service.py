"""Maven Central-backed dependency upgrade guidance."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, Optional

import httpx

from utils.config import (
    MAVEN_CENTRAL_ALLOW_PRERELEASES,
    MAVEN_CENTRAL_ENABLED,
    MAVEN_CENTRAL_MAX_ROWS,
    MAVEN_CENTRAL_SEARCH_URL,
    MAVEN_CENTRAL_TIMEOUT_SEC,
)

logger = logging.getLogger(__name__)


class MavenCentralService:
    MANUAL_COORDINATE_UPGRADES: Dict[str, tuple[str, str]] = {
        "javax.servlet:javax.servlet-api": (
            "jakarta.servlet:jakarta.servlet-api:6.0.0",
            "needs_manual_review",
        ),
        "javax.servlet:jstl": (
            "jakarta.servlet.jsp.jstl:jakarta.servlet.jsp.jstl-api:3.0.1",
            "needs_manual_review",
        ),
        "javax.persistence:javax.persistence-api": (
            "jakarta.persistence:jakarta.persistence-api:3.1.0",
            "needs_manual_review",
        ),
    }

    STATIC_FALLBACK_UPGRADES: Dict[str, tuple[str, str]] = {
        "org.springframework.boot:spring-boot-starter": ("3.2.0", "upgraded"),
        "org.springframework:spring-core": ("6.1.0", "upgraded"),
        "junit:junit": ("4.13.2", "upgraded"),
        "org.junit.jupiter:junit-jupiter": ("5.10.0", "upgraded"),
        "log4j:log4j": ("org.apache.logging.log4j:log4j-core:2.22.0", "upgraded"),
        "commons-lang:commons-lang": ("org.apache.commons:commons-lang3:3.14.0", "upgraded"),
    }

    PRE_RELEASE_PATTERN = re.compile(
        r"(?:^|[.\-_])(alpha|beta|milestone|m\d+|rc\d*|cr\d*|preview|ea|snapshot)(?:$|[.\-_])",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self.enabled = MAVEN_CENTRAL_ENABLED
        self.search_url = MAVEN_CENTRAL_SEARCH_URL
        self.timeout_sec = MAVEN_CENTRAL_TIMEOUT_SEC
        self.max_rows = MAVEN_CENTRAL_MAX_ROWS
        self.allow_prereleases = MAVEN_CENTRAL_ALLOW_PRERELEASES
        self._latest_version_cache: Dict[str, Optional[str]] = {}
        self._cache_lock = threading.Lock()

    def get_upgrade_guidance(self, group_id: str, artifact_id: str, current_version: str) -> Dict[str, Optional[str]]:
        key = self._coordinate_key(group_id, artifact_id)

        manual_upgrade = self.MANUAL_COORDINATE_UPGRADES.get(key)
        if manual_upgrade:
            return {
                "new_version": manual_upgrade[0],
                "status": manual_upgrade[1],
                "source": "manual_migration_rule",
            }

        latest_version = self.lookup_latest_version_sync(group_id, artifact_id)
        if latest_version and self.should_upgrade_version(current_version, latest_version):
            return {
                "new_version": latest_version,
                "status": "upgraded",
                "source": "maven_central",
            }

        fallback_upgrade = self.STATIC_FALLBACK_UPGRADES.get(key)
        if fallback_upgrade:
            fallback_version, fallback_status = fallback_upgrade
            if fallback_status != "upgraded" or self.should_upgrade_version(current_version, fallback_version):
                return {
                    "new_version": fallback_version,
                    "status": fallback_status,
                    "source": "static_fallback",
                }

        return {"new_version": None, "status": "compatible", "source": None}

    def lookup_latest_version_sync(self, group_id: str, artifact_id: str) -> Optional[str]:
        if not self.enabled:
            return None

        coordinate_key = self._coordinate_key(group_id, artifact_id)
        if not coordinate_key:
            return None

        with self._cache_lock:
            if coordinate_key in self._latest_version_cache:
                return self._latest_version_cache[coordinate_key]

        latest_version = self._fetch_latest_version_sync(group_id.strip(), artifact_id.strip())

        with self._cache_lock:
            self._latest_version_cache[coordinate_key] = latest_version

        return latest_version

    def should_upgrade_version(self, current_version: str, candidate_version: str) -> bool:
        normalized_current = (current_version or "").strip()
        normalized_candidate = (candidate_version or "").strip()
        if not normalized_candidate:
            return False
        if normalized_current == normalized_candidate:
            return False
        if self._is_placeholder_version(normalized_current):
            return True

        current_parts = self._parse_version_parts(normalized_current)
        candidate_parts = self._parse_version_parts(normalized_candidate)
        if current_parts and candidate_parts:
            return candidate_parts > current_parts

        return normalized_current.lower() != normalized_candidate.lower()

    def _fetch_latest_version_sync(self, group_id: str, artifact_id: str) -> Optional[str]:
        try:
            with httpx.Client(timeout=self.timeout_sec, follow_redirects=True) as client:
                quick_response = client.get(
                    self.search_url,
                    params={
                        "q": f"g:{group_id} AND a:{artifact_id}",
                        "rows": 1,
                        "wt": "json",
                    },
                )
                quick_response.raise_for_status()
                quick_docs = quick_response.json().get("response", {}).get("docs", [])

                quick_candidate = self._extract_latest_version_from_docs(quick_docs)
                if quick_candidate and (self.allow_prereleases or not self._is_prerelease_version(quick_candidate)):
                    return quick_candidate

                gav_response = client.get(
                    self.search_url,
                    params={
                        "q": f"g:{group_id} AND a:{artifact_id}",
                        "core": "gav",
                        "rows": self.max_rows,
                        "wt": "json",
                    },
                )
                gav_response.raise_for_status()
                gav_docs = gav_response.json().get("response", {}).get("docs", [])
                return self._select_best_version_from_gav(gav_docs)
        except httpx.HTTPError as exc:
            logger.debug(
                "Maven Central lookup failed group_id=%s artifact_id=%s error=%s",
                group_id,
                artifact_id,
                exc,
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.debug(
                "Unexpected Maven Central lookup failure group_id=%s artifact_id=%s error=%s",
                group_id,
                artifact_id,
                exc,
            )
            return None

    def _extract_latest_version_from_docs(self, docs: list[Dict[str, Any]]) -> Optional[str]:
        for doc in docs:
            latest_version = (doc.get("latestVersion") or doc.get("v") or "").strip()
            if latest_version:
                return latest_version
        return None

    def _select_best_version_from_gav(self, docs: list[Dict[str, Any]]) -> Optional[str]:
        fallback_candidate: Optional[str] = None
        for doc in docs:
            version = (doc.get("v") or doc.get("latestVersion") or "").strip()
            if not version:
                continue
            if fallback_candidate is None:
                fallback_candidate = version
            if self.allow_prereleases or not self._is_prerelease_version(version):
                return version
        return fallback_candidate

    def _coordinate_key(self, group_id: str, artifact_id: str) -> str:
        normalized_group = (group_id or "").strip().lower()
        normalized_artifact = (artifact_id or "").strip().lower()
        if not normalized_group or not normalized_artifact:
            return ""
        return f"{normalized_group}:{normalized_artifact}"

    def _is_placeholder_version(self, version: str) -> bool:
        normalized = (version or "").strip().lower()
        if not normalized:
            return True
        return normalized in {"inherited", "unspecified", "unknown"} or normalized.startswith("${")

    def _is_prerelease_version(self, version: str) -> bool:
        normalized = (version or "").strip()
        return bool(normalized and self.PRE_RELEASE_PATTERN.search(normalized))

    def _parse_version_parts(self, version: str) -> Optional[tuple[int, ...]]:
        normalized = (version or "").strip()
        if not normalized or self._is_placeholder_version(normalized):
            return None

        numeric_parts = re.findall(r"\d+", normalized)
        if not numeric_parts:
            return None

        return tuple(int(part) for part in numeric_parts[:4])


maven_central_service = MavenCentralService()
