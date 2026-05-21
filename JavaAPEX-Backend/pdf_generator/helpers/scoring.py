from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List

from .formatters import severity_bucket


def _get_details(report: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = report.get(key) or []
    return [item for item in value if isinstance(item, dict)]


def severity_distribution(report: Dict[str, Any]) -> Dict[str, int]:
    counts = Counter({"BLOCKER": 0, "CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "INFO": 0})
    detail_keys = ("bug_details", "vulnerability_details", "code_smell_details")
    for key in detail_keys:
        for item in _get_details(report, key):
            counts[severity_bucket(item.get("severity"))] += 1
    for hotspot in _get_details(report, "security_hotspot_details"):
        probability = str(hotspot.get("vulnerability_probability") or "").upper()
        mapped = "MINOR" if probability == "LOW" else "MAJOR" if probability == "MEDIUM" else "CRITICAL"
        counts[mapped] += 1
    return dict(counts)


def issue_category_distribution(job: Any) -> Dict[str, int]:
    return {
        "Vulnerabilities": int(getattr(job, "sonar_vulnerabilities", 0) or 0),
        "Code Smells": int(getattr(job, "sonar_code_smells", 0) or 0),
        "Bugs": int(getattr(job, "sonar_bugs", 0) or 0),
        "Security Hotspots": int(getattr(job, "sonar_security_hotspots", 0) or 0),
    }


def remediation_effort_hours(report: Dict[str, Any]) -> Dict[str, float]:
    buckets = {
        "Vulnerabilities": _get_details(report, "vulnerability_details"),
        "Code Cleanup": _get_details(report, "code_smell_details"),
        "Bugs": _get_details(report, "bug_details"),
        "Security Review": _get_details(report, "security_hotspot_details"),
    }
    summary: Dict[str, float] = {}
    for label, items in buckets.items():
        total_minutes = 0
        for item in items:
            effort = str(item.get("effort") or item.get("debt") or "").strip().lower()
            if effort.endswith("min"):
                total_minutes += float(effort.replace("min", "").strip() or 0)
            elif effort.endswith("h"):
                total_minutes += float(effort.replace("h", "").strip() or 0) * 60
        summary[label] = round(total_minutes / 60, 1)
    return summary


def risk_posture(job: Any, report: Dict[str, Any]) -> str:
    distribution = severity_distribution(report)
    vulnerabilities = int(getattr(job, "sonar_vulnerabilities", 0) or 0)
    hotspots = int(getattr(job, "sonar_security_hotspots", 0) or 0)
    if distribution.get("BLOCKER", 0) > 0 or vulnerabilities >= 3:
        return "Critical"
    if distribution.get("CRITICAL", 0) > 0 or vulnerabilities > 0 or hotspots > 0:
        return "High"
    if int(getattr(job, "sonar_code_smells", 0) or 0) > 25 or int(getattr(job, "sonar_bugs", 0) or 0) > 0:
        return "Moderate"
    return "Low"


def scorecard(job: Any, report: Dict[str, Any]) -> Dict[str, int]:
    distribution = severity_distribution(report)
    vulnerabilities = int(getattr(job, "sonar_vulnerabilities", 0) or 0)
    hotspots = int(getattr(job, "sonar_security_hotspots", 0) or 0)
    smells = int(getattr(job, "sonar_code_smells", 0) or 0)
    bugs = int(getattr(job, "sonar_bugs", 0) or 0)
    coverage = float(getattr(job, "sonar_coverage", 0.0) or 0.0)

    security = max(10, 100 - vulnerabilities * 18 - hotspots * 10 - distribution.get("BLOCKER", 0) * 10 - distribution.get("CRITICAL", 0) * 4)
    maintainability = max(15, 100 - smells - distribution.get("CRITICAL", 0) * 3 - distribution.get("BLOCKER", 0) * 5)
    testability = max(5, min(100, int(round(coverage))))
    cloud_readiness = max(20, min(100, int(round((security * 0.4) + (maintainability * 0.35) + (testability * 0.25)))))
    java_upgrade = max(20, min(100, int(round((maintainability * 0.45) + (security * 0.35) + ((100 - bugs * 8) * 0.20)))))
    modernization = int(round((security + maintainability + testability + cloud_readiness + java_upgrade) / 5))
    health = int(round((security * 0.35) + (maintainability * 0.25) + (testability * 0.15) + (cloud_readiness * 0.1) + (java_upgrade * 0.15)))

    return {
        "security": max(0, min(100, int(security))),
        "maintainability": max(0, min(100, int(maintainability))),
        "testability": max(0, min(100, int(testability))),
        "cloud_readiness": max(0, min(100, int(cloud_readiness))),
        "java_upgrade_compatibility": max(0, min(100, int(java_upgrade))),
        "modernization_readiness": max(0, min(100, int(modernization))),
        "project_health": max(0, min(100, int(health))),
    }


def build_ai_recommendations(job: Any, report: Dict[str, Any]) -> List[Dict[str, str]]:
    recommendations: List[Dict[str, str]] = []
    rules = Counter()
    findings: List[Dict[str, Any]] = []
    for key in ("vulnerability_details", "code_smell_details", "bug_details", "security_hotspot_details"):
        findings.extend(_get_details(report, key))
    for item in findings:
        if item.get("rule"):
            rules[str(item["rule"])] += 1

    if int(getattr(job, "sonar_vulnerabilities", 0) or 0) > 0:
        recommendations.append({
            "priority": "Immediate",
            "title": "Eliminate exposed secrets and unsafe parsers",
            "detail": "Replace hardcoded credentials with environment variables or vault-backed configuration and lock down XML parser external entity handling.",
        })
    if rules.get("java:S3776", 0) > 0 or rules.get("java:S6541", 0) > 0:
        recommendations.append({
            "priority": "High",
            "title": "Reduce brain methods and cognitive complexity",
            "detail": "Split oversized methods into smaller orchestration and helper methods to improve Java upgrade safety and unit-testability.",
        })
    if rules.get("java:S106", 0) > 0:
        recommendations.append({
            "priority": "High",
            "title": "Replace console logging with structured logging",
            "detail": "Use SLF4J-backed structured logging instead of System.out so operational observability remains production-ready.",
        })
    if float(getattr(job, "sonar_coverage", 0.0) or 0.0) < 50:
        recommendations.append({
            "priority": "High",
            "title": "Improve automated test coverage",
            "detail": "Add focused unit and integration tests for high-complexity services before making broader modernization changes.",
        })
    if int(getattr(job, "sonar_code_smells", 0) or 0) > 25:
        recommendations.append({
            "priority": "Medium",
            "title": "Plan a maintainability cleanup sprint",
            "detail": "Address duplicated literals, empty catch blocks, and utility-class design issues to reduce long-term modernization drag.",
        })

    if not recommendations:
        recommendations.append({
            "priority": "Medium",
            "title": "Maintain continuous code quality governance",
            "detail": "Keep Sonar scanning in CI/CD and review new findings per pull request to preserve the current healthy posture.",
        })

    return recommendations[:5]


def top_findings_by_severity(report: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    severity_rank = {"BLOCKER": 5, "CRITICAL": 4, "MAJOR": 3, "MINOR": 2, "INFO": 1}
    findings: List[Dict[str, Any]] = []
    for key, label in (
        ("vulnerability_details", "Vulnerability"),
        ("code_smell_details", "Code Smell"),
        ("bug_details", "Bug"),
    ):
        for item in _get_details(report, key):
            enriched = dict(item)
            enriched["_category"] = label
            findings.append(enriched)
    findings.sort(key=lambda item: (severity_rank.get(severity_bucket(item.get("severity")), 0), str(item.get("effort") or "")), reverse=True)
    return findings[:limit]


def rule_frequency(findings: Iterable[Dict[str, Any]], limit: int = 6) -> List[tuple[str, int]]:
    counter = Counter()
    for item in findings:
        rule = str(item.get("rule") or "").strip()
        if rule:
            counter[rule] += 1
    return counter.most_common(limit)

