from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from models.microservice_readiness import ServiceCandidate

PACKAGE_DECLARATION_RE = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;", re.MULTILINE)
DEFAULT_OUTPUT_DIR = "microservices-output"
DEFAULT_COMMON_DIR = "common"


def _extract_package_name(java_file: Path) -> Optional[str]:
    try:
        content = java_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    match = PACKAGE_DECLARATION_RE.search(content)
    return match.group(1) if match else None


def _normalize_package_prefix(package: str) -> str:
    return package.strip().rstrip(".*")


def _sanitize_service_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()
    return sanitized or "service"


def _match_candidate(package_name: str, candidates: List[ServiceCandidate]) -> Optional[ServiceCandidate]:
    if not package_name:
        return None

    best_candidate: Optional[ServiceCandidate] = None
    best_length = -1

    for candidate in candidates:
        for package_prefix in candidate.packages:
            normalized = _normalize_package_prefix(package_prefix)
            if normalized and (package_name == normalized or package_name.startswith(normalized + ".")):
                if len(normalized) > best_length:
                    best_candidate = candidate
                    best_length = len(normalized)

    return best_candidate


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_build_files(source_root: Path, destination_root: Path) -> None:
    for build_file in ["pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"]:
        src = source_root / build_file
        if src.exists():
            shutil.copy2(src, destination_root / src.name)


def _create_service_readme(service_dir: Path, candidate: ServiceCandidate) -> None:
    lines = [
        f"# {candidate.name}",
        "",
        "This service was generated as part of a microservices extraction output.",
        "",
    ]
    if candidate.packages:
        lines.append("## Package roots")
        lines.extend([f"- `{package}`" for package in candidate.packages])
        lines.append("")
    if candidate.evidence:
        lines.append("## Evidence")
        lines.extend([f"- {item}" for item in candidate.evidence])
        lines.append("")
    if candidate.scaling_signals:
        lines.append("## Scaling signals")
        lines.extend([f"- {signal}" for signal in candidate.scaling_signals])
        lines.append("")
    if candidate.external_integrations:
        lines.append("## External integrations")
        lines.extend([f"- {integration}" for integration in candidate.external_integrations])
        lines.append("")
    lines.append("## Notes")
    lines.append("This folder contains a package-scoped extraction of Java sources related to the identified service candidate.")
    service_dir.joinpath("README.md").write_text("\n".join(lines), encoding="utf-8")


def split_project_into_microservices(
    source_root: str,
    service_candidates: List[ServiceCandidate],
    output_root: Optional[str] = None,
) -> str:
    source_path = Path(source_root).resolve()
    output_path = Path(output_root).resolve() if output_root else source_path / DEFAULT_OUTPUT_DIR

    print(f"DEBUG: Splitting project from {source_path} to {output_path}")
    print(f"DEBUG: Service candidates: {[c.name for c in service_candidates]}")

    if output_path.exists():
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    candidates = [candidate for candidate in service_candidates if candidate.name]
    if not candidates:
        print("DEBUG: No valid candidates found, creating fallback")
        candidates = [ServiceCandidate(name="service", packages=[], evidence=[], scaling_signals=[], external_integrations=[])]

    candidate_dirs: dict[str, Path] = {}
    for candidate in candidates:
        dest = output_path / _sanitize_service_name(candidate.name)
        dest.mkdir(parents=True, exist_ok=True)
        candidate_dirs[candidate.name] = dest
        print(f"DEBUG: Created directory for candidate {candidate.name}: {dest}")

    common_dir = output_path / DEFAULT_COMMON_DIR
    common_dir.mkdir(parents=True, exist_ok=True)

    candidate_dirs: dict[str, Path] = {}
    for candidate in candidates:
        dest = output_path / _sanitize_service_name(candidate.name)
        dest.mkdir(parents=True, exist_ok=True)
        candidate_dirs[candidate.name] = dest

    common_dir = output_path / DEFAULT_COMMON_DIR
    common_dir.mkdir(parents=True, exist_ok=True)

    java_roots = [
        source_path / "src" / "main" / "java",
        source_path / "src" / "test" / "java",
    ]
    processed_files = 0
    for root in java_roots:
        if not root.exists():
            print(f"DEBUG: Java root {root} does not exist")
            continue
        print(f"DEBUG: Processing Java root {root}")
        for java_file in root.rglob("*.java"):
            package_name = _extract_package_name(java_file) or ""
            candidate = _match_candidate(package_name, candidates)
            destination_base = candidate_dirs[candidate.name] if candidate else common_dir
            
            relative_path = java_file.relative_to(source_path)
            destination_file = destination_base / relative_path
            _copy_file(java_file, destination_file)
            processed_files += 1
            
            if processed_files <= 10:  # Log first 10 files
                print(f"DEBUG: {java_file} -> {destination_file} (package: {package_name}, candidate: {candidate.name if candidate else 'common'})")

    print(f"DEBUG: Processed {processed_files} Java files")

    # Ensure build files are included for each generated service and the common folder.
    for service_dir in list(candidate_dirs.values()) + [common_dir]:
        _copy_build_files(source_path, service_dir)

    # Add README files for each service and for the common folder.
    for candidate in candidates:
        _create_service_readme(candidate_dirs[candidate.name], candidate)

    common_readme = [
        "# Shared / Common Project Artifacts",
        "",
        "This directory contains sources that were not confidently assigned to a specific microservice candidate.",
        "",
        "Use these files as shared library or utility components during further extraction work.",
    ]
    common_dir.joinpath("README.md").write_text("\n".join(common_readme), encoding="utf-8")

    service_summary = [
        "# Microservice Extraction Output",
        "",
        "This folder contains generated microservice candidate project folders.",
        "",
        "## Services",
    ]
    for candidate in candidates:
        service_summary.append(f"- {candidate.name}: packages={', '.join(candidate.packages) if candidate.packages else 'unknown'}")
    service_summary.append(f"- Shared/common folder: {DEFAULT_COMMON_DIR}")
    output_path.joinpath("README.md").write_text("\n".join(service_summary), encoding="utf-8")

    return str(output_path)
