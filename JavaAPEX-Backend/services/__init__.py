"""
Services package for Java Migration Backend.

Submodules are imported lazily (PEP 562) so lightweight, dependency-free
services -- most notably :mod:`services.functional_test_pipeline`, which only
uses the Python standard library -- can be imported and exercised even when the
heavier optional dependencies (PyGithub, gitpython, ...) are not installed.

``from services import GitHubService`` continues to work unchanged whenever the
underlying dependency is available; the import simply happens on first access
instead of at package-import time.
"""

from importlib import import_module
from typing import Any

# Public attribute name -> (submodule, symbol) it is exported from.
_LAZY_EXPORTS = {
    "GitHubService": (".github_service", "GitHubService"),
    "GitHubCloneAnalysisService": (".github_clone_analysis_service", "GitHubCloneAnalysisService"),
    "MigrationService": (".migration_service", "MigrationService"),
    "EmailService": (".email_service", "EmailService"),
    "SonarQubeService": (".sonarqube_service", "SonarQubeService"),
    "run_jacoco_coverage_pipeline": (".jacoco_coverage_service", "run_jacoco_coverage_pipeline"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve exported services on first access (PEP 562 lazy import)."""
    try:
        module_name, symbol = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = import_module(module_name, __name__)
    value = getattr(module, symbol)
    globals()[name] = value  # cache so subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
