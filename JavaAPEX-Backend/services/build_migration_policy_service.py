from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BuildStackSnapshot:
    build_tool: str
    java_version: Optional[str] = None
    spring_boot_version: Optional[str] = None


class BuildMigrationPolicyService:
    _POM_PARENT_BOOT_PATTERN = re.compile(
        r"<parent>.*?<groupId>\s*org\.springframework\.boot\s*</groupId>.*?"
        r"<artifactId>\s*spring-boot-starter-parent\s*</artifactId>.*?"
        r"<version>\s*([^<\s]+)\s*</version>.*?</parent>",
        re.DOTALL | re.IGNORECASE,
    )
    _POM_BOOT_PROPERTY_PATTERN = re.compile(
        r"<spring-boot\.version>\s*([^<\s]+)\s*</spring-boot\.version>",
        re.IGNORECASE,
    )
    _GRADLE_BOOT_PLUGIN_PATTERN = re.compile(
        r"id\s+['\"]org\.springframework\.boot['\"]\s+version\s+['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )
    _GRADLE_BOOT_EXT_PATTERN = re.compile(
        r"(?:springBootVersion|spring_boot_version)\s*=?\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )

    def inspect_build_content(self, build_content: str, build_tool: str) -> BuildStackSnapshot:
        normalized_tool = (build_tool or "").strip().lower()
        if normalized_tool not in {"maven", "gradle"}:
            raise ValueError(f"Unsupported build tool for inspection: {build_tool}")

        if normalized_tool == "maven":
            return BuildStackSnapshot(
                build_tool="maven",
                java_version=self._extract_java_version_from_pom(build_content),
                spring_boot_version=self._extract_spring_boot_version_from_pom(build_content),
            )

        return BuildStackSnapshot(
            build_tool="gradle",
            java_version=self._extract_java_version_from_gradle(build_content),
            spring_boot_version=self._extract_spring_boot_version_from_gradle(build_content),
        )

    def resolve_java_target(self, source_java_version: Optional[str], minimum_target: str = "17") -> str:
        if self._is_higher_version(source_java_version, minimum_target):
            return str(source_java_version).strip()
        return minimum_target

    def resolve_spring_boot_target(self, source_boot_version: Optional[str], target_java_version: Optional[str] = None) -> str:
        # Pick a Spring Boot version compatible with the target Java version.
        # Java 25 -> needs Boot 4.0.0+ (ASM supports class v69).
        # Java 22 -> needs Boot 3.3.0+.
        # Java 17-21 -> Boot 3.2.5+ is fine.
        if target_java_version:
            try:
                ver = int(re.sub(r'[^\d].*', '', target_java_version) or '0')
                if ver >= 25:
                    minimum_target = "4.0.0"
                elif ver >= 22:
                    minimum_target = "3.3.0"
                else:
                    minimum_target = "3.2.5"
            except ValueError:
                minimum_target = "3.2.5"
        else:
            minimum_target = "3.2.5"

        if self._is_higher_version(source_boot_version, minimum_target):
            return str(source_boot_version).strip()
        return minimum_target

    def validate_no_downgrade(
        self,
        source_snapshot: BuildStackSnapshot,
        generated_snapshot: BuildStackSnapshot,
    ) -> None:
        errors: list[str] = []

        if self._is_higher_version(source_snapshot.java_version, generated_snapshot.java_version):
            errors.append(
                f"generated Java version {generated_snapshot.java_version or 'unspecified'} is lower than source Java version {source_snapshot.java_version}"
            )

        if self._is_higher_version(source_snapshot.spring_boot_version, generated_snapshot.spring_boot_version):
            errors.append(
                "generated Spring Boot version "
                f"{generated_snapshot.spring_boot_version or 'unspecified'} is lower than source Spring Boot version {source_snapshot.spring_boot_version}"
            )

        if errors:
            raise ValueError("; ".join(errors))

    def _extract_java_version_from_pom(self, pom_content: str) -> Optional[str]:
        patterns = [
            r"<java\.version>\s*(\d+(?:\.\d+)?)\s*</java\.version>",
            r"<maven\.compiler\.source>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.source>",
            r"<maven\.compiler\.target>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.target>",
            r"<maven\.compiler\.release>\s*(\d+(?:\.\d+)?)\s*</maven\.compiler\.release>",
            r"<source>\s*(\d+(?:\.\d+)?)\s*</source>",
        ]
        for pattern in patterns:
            match = re.search(pattern, pom_content, re.IGNORECASE)
            if match:
                return self._normalize_java_version(match.group(1))
        return None

    def _extract_java_version_from_gradle(self, gradle_content: str) -> Optional[str]:
        patterns = [
            r"sourceCompatibility\s*=\s*['\"]?(\d+(?:\.\d+)?)['\"]?",
            r"targetCompatibility\s*=\s*['\"]?(\d+(?:\.\d+)?)['\"]?",
            r"JavaLanguageVersion\.of\((\d+)\)",
            r"VERSION_(\d+)(?:_(\d+))?",
        ]
        for pattern in patterns:
            match = re.search(pattern, gradle_content, re.IGNORECASE)
            if match:
                if match.lastindex and match.lastindex > 1 and match.group(2):
                    return self._normalize_java_version(f"{match.group(1)}.{match.group(2)}")
                return self._normalize_java_version(match.group(1))
        return None

    def _extract_spring_boot_version_from_pom(self, pom_content: str) -> Optional[str]:
        parent_match = self._POM_PARENT_BOOT_PATTERN.search(pom_content)
        if parent_match:
            return parent_match.group(1).strip()

        property_match = self._POM_BOOT_PROPERTY_PATTERN.search(pom_content)
        if property_match:
            return property_match.group(1).strip()

        return None

    def _extract_spring_boot_version_from_gradle(self, gradle_content: str) -> Optional[str]:
        plugin_match = self._GRADLE_BOOT_PLUGIN_PATTERN.search(gradle_content)
        if plugin_match:
            return plugin_match.group(1).strip()

        ext_match = self._GRADLE_BOOT_EXT_PATTERN.search(gradle_content)
        if ext_match:
            return ext_match.group(1).strip()

        return None

    def _normalize_java_version(self, raw_version: str) -> str:
        version = (raw_version or "").strip()
        return version.replace("1.", "", 1) if version.startswith("1.") else version

    def _is_higher_version(self, current_version: Optional[str], candidate_version: Optional[str]) -> bool:
        current_parts = self._parse_version(current_version)
        candidate_parts = self._parse_version(candidate_version)
        if current_parts is None or candidate_parts is None:
            return False
        return current_parts > candidate_parts

    def _parse_version(self, version: Optional[str]) -> Optional[tuple[int, ...]]:
        normalized = str(version or "").strip()
        if not normalized:
            return None
        parts = re.findall(r"\d+", normalized)
        if not parts:
            return None
        return tuple(int(part) for part in parts[:4])


build_migration_policy_service = BuildMigrationPolicyService()
