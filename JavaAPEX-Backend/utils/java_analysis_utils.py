from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Sequence, Set


JAVA_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
JAVA_COMMENT_LINE_RE = re.compile(r"//.*")
PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", re.MULTILINE)
ANNOTATION_RE = re.compile(r"@\s*(?:[\w.]+\.)?([A-Za-z_]\w*)")
CLASS_RE = re.compile(
    r"(?P<annotations>(?:@\s*[\w.]+(?:\s*\([^)]*\))?\s*)*)"
    r"(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed)\s+)*"
    r"(?P<kind>class|interface|record)\s+(?P<name>[A-Za-z_]\w*)",
    re.MULTILINE,
)

GENERIC_NAMESPACE_TOKENS = {
    "com", "org", "net", "io", "dev", "edu", "gov", "co", "app",
}
STRUCTURAL_PACKAGE_TOKENS = {
    "api", "app", "application", "apps", "backend", "client", "clients",
    "common", "commons", "config", "configuration", "controller", "controllers",
    "core", "dao", "data", "domain", "dto", "entity", "entities", "impl",
    "infrastructure", "integration", "model", "models", "persistence", "repository",
    "repositories", "rest", "server", "service", "services", "shared", "starter",
    "tool", "tools", "transport", "util", "utils", "web",
}


def strip_java_comments(content: str) -> str:
    without_blocks = JAVA_COMMENT_BLOCK_RE.sub("", content)
    return JAVA_COMMENT_LINE_RE.sub("", without_blocks)


def parse_package(content: str) -> str:
    match = PACKAGE_RE.search(content)
    return match.group(1).strip() if match else ""


def parse_imports(content: str) -> List[str]:
    return [match.group(1).strip() for match in IMPORT_RE.finditer(content)]


def parse_class_names_and_annotations(content: str) -> List[dict]:
    class_profiles: List[dict] = []
    for match in CLASS_RE.finditer(content):
        annotation_block = match.group("annotations") or ""
        annotations: Set[str] = {annotation.group(1) for annotation in ANNOTATION_RE.finditer(annotation_block)}
        class_profiles.append({
            "name": match.group("name"),
            "kind": match.group("kind"),
            "annotations": annotations,
        })
    return class_profiles


def common_package_prefix(packages: Sequence[str]) -> List[str]:
    token_lists = [pkg.split(".") for pkg in packages if pkg]
    if not token_lists:
        return []
    prefix = token_lists[0][:]
    for tokens in token_lists[1:]:
        limit = min(len(prefix), len(tokens))
        index = 0
        while index < limit and prefix[index] == tokens[index]:
            index += 1
        prefix = prefix[:index]
        if not prefix:
            break
    return prefix if len(prefix) >= 2 else []


def infer_module_from_package(package_name: str, base_prefix: Sequence[str]) -> str:
    if not package_name:
        return "root"
    tokens = package_name.split(".")
    normalized_base = list(base_prefix or [])

    if normalized_base and tokens[:len(normalized_base)] == normalized_base:
        candidate_tokens = tokens[len(normalized_base):]
    else:
        index = 0
        if tokens and tokens[0] in GENERIC_NAMESPACE_TOKENS:
            index += 1
        if len(tokens) - index >= 2 and tokens[index] not in STRUCTURAL_PACKAGE_TOKENS:
            index += 1
        candidate_tokens = tokens[index:]

    for token in candidate_tokens:
        normalized = sanitize_module_name(token)
        if not normalized or normalized == "root":
            continue
        if normalized in GENERIC_NAMESPACE_TOKENS:
            continue
        if normalized in STRUCTURAL_PACKAGE_TOKENS and len(candidate_tokens) > 1:
            continue
        return normalized

    for token in reversed(candidate_tokens or tokens):
        normalized = sanitize_module_name(token)
        if normalized and normalized != "root":
            return normalized
    return "root"


def infer_module_from_path(file_path: str | Path) -> str:
    normalized = str(file_path).replace("\\", "/").lower()
    for marker in ("/java/", "/kotlin/"):
        if marker in normalized:
            remainder = normalized.split(marker, 1)[1]
            tokens = [token for token in remainder.split("/") if token]
            if tokens:
                return sanitize_module_name(tokens[0])
    stem = Path(file_path).stem if not isinstance(file_path, Path) else file_path.stem
    return sanitize_module_name(stem or "root")


def sanitize_module_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "root"


def titleize_module_name(value: str) -> str:
    words = [part for part in re.split(r"[-_.\s]+", value or "") if part]
    return " ".join(word.capitalize() for word in words) or "Core"


def top_n_items(values: Iterable[str], limit: int = 5) -> List[str]:
    seen = set()
    items: List[str] = []
    for value in values:
        normalized = (value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
        if len(items) >= limit:
            break
    return items
