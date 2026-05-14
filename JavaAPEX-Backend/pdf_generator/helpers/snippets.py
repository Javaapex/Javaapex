from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional


def resolve_clone_path(job: Any) -> Optional[str]:
    clone_path = getattr(job, "clone_path", None)
    if clone_path and os.path.isdir(clone_path):
        return clone_path
    target_repo = getattr(job, "target_repo", None)
    if target_repo and str(target_repo).startswith("local://"):
        candidate = str(target_repo).replace("local://", "")
        if os.path.isdir(candidate):
            return candidate
    return None


def load_code_snippet(job: Any, component: Optional[str], line: Optional[int], context: int = 2) -> Optional[str]:
    root = resolve_clone_path(job)
    if not root or not component:
        return None
    component_path = Path(root) / component.replace("/", os.sep)
    if not component_path.exists() or not component_path.is_file():
        return None
    try:
        lines = component_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    if not lines:
        return None
    if line and line > 0:
        start = max(0, line - context - 1)
        end = min(len(lines), line + context)
    else:
        start = 0
        end = min(len(lines), 5)
    snippet_lines = []
    for index in range(start, end):
        snippet_lines.append(f"{index + 1:>4} | {lines[index]}")
    return "\n".join(snippet_lines)


def suggest_remediation(issue: Dict[str, Any]) -> Dict[str, str]:
    rule = str(issue.get("rule") or "")
    message = str(issue.get("message") or "")

    suggestions = {
        "java:S2068": {
            "bad": 'String password = "admin123";',
            "good": 'String password = System.getenv("APP_PASSWORD");',
            "summary": "Move hardcoded credentials into environment-backed configuration or a secrets manager.",
        },
        "java:S2755": {
            "bad": 'DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();',
            "good": 'factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);',
            "summary": "Harden XML parsers by disabling unsafe external entity processing.",
        },
        "java:S106": {
            "bad": 'System.out.println("Processing request");',
            "good": 'log.info("Processing request");',
            "summary": "Replace console prints with SLF4J-based logging for structured, production-safe observability.",
        },
        "java:S3776": {
            "bad": "// large method with deeply nested branches",
            "good": "validateInput();\nprocessBusinessRules();\npersistResult();",
            "summary": "Reduce cognitive complexity by extracting orchestration logic into smaller cohesive methods.",
        },
        "java:S1192": {
            "bad": 'response.put("status", "success");\nlog.info("success");',
            "good": 'private static final String STATUS_SUCCESS = "success";',
            "summary": "Promote duplicated literals into named constants to improve maintainability and change safety.",
        },
        "java:S1118": {
            "bad": "public class UserMapper { }",
            "good": "private UserMapper() {\n    throw new UnsupportedOperationException(\"Utility class\");\n}",
            "summary": "Hide implicit public constructors for utility-only classes.",
        },
    }
    suggestion = suggestions.get(rule)
    if suggestion:
        return suggestion
    if "System.out" in message:
        return suggestions["java:S106"]
    if "cognitive complexity" in message.lower():
        return suggestions["java:S3776"]
    return {
        "bad": message or "// current implementation",
        "good": "// refactor with narrower responsibilities, safer configuration, or clearer exception handling",
        "summary": "Review the finding and implement a focused remediation aligned with the referenced Sonar rule.",
    }

