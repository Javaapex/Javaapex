"""Simple strategy prompt endpoint for the Strategy page.

This router provides a lightweight handler that accepts a freeform question
and a small repository analysis/context payload and returns a heuristic
answer. It's intentionally simple so the frontend can be wired quickly;
LLM integration can be added later by calling the existing LLM services.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.llm_context_service import (
    build_repository_context_pack,
    context_pack_fingerprint,
)
from services.preferred_llm_service import preferred_llm_service
from services.llm_retriever import warmup_embeddings_and_persist
from services.strategy_question_bank import match_question, match_top_n_semantic


router = APIRouter(tags=["strategy"])

logger = logging.getLogger(__name__)


class StrategyQuery(BaseModel):
    repo_url: Optional[str]
    question: str
    # analysis may be a dict for a single repo or a list of analysis dicts for multiple repos
    analysis: Optional[Any] = None
    strategy_context: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None
    persist_embeddings: Optional[bool] = False
    include_evidence: Optional[bool] = False


class StrategyAnswer(BaseModel):
    answer: str
    rationale: Optional[List[str]] = []
    details: Optional[Dict[str, Any]] = {}


STRATEGY_CONTEXT_MAX_DEPTH = 3
STRATEGY_CONTEXT_MAX_KEYS = 12
STRATEGY_CONTEXT_MAX_LIST = 6
STRATEGY_CONTEXT_MAX_STRING = 220
STRATEGY_CONTEXT_MAX_ANSWER = 900
STRATEGY_LLM_MAX_TOKENS = 2048


def _truncate_text(value: Any, limit: int = STRATEGY_CONTEXT_MAX_STRING) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _strategy_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dependency_label(dependency: Dict[str, Any]) -> str:
    return (
        dependency.get("display_name")
        or dependency.get("displayName")
        or dependency.get("name")
        or dependency.get("artifact_id")
        or dependency.get("artifactId")
        or dependency.get("group_id")
        or dependency.get("groupId")
        or "unknown dependency"
    )


def _dependency_risk_level(value: Any) -> str:
    return str(value or "").strip().lower()


def _dependency_matches(question_lower: str, dependency: Dict[str, Any]) -> bool:
    label = _dependency_label(dependency).lower()
    current_version = str(dependency.get("current_version") or "").lower()
    status = _dependency_risk_level(dependency.get("status"))
    category = str(dependency.get("category") or "").lower()
    return any(
        token and token in question_lower
        for token in (label, current_version, status, category)
    )


def _format_dependency_entry(dependency: Dict[str, Any]) -> str:
    name = _dependency_label(dependency)
    version = dependency.get("current_version")
    risk = str(dependency.get("risk") or "medium").upper()
    reason = dependency.get("reason") or "needs review"
    status = dependency.get("status")
    parts = [name]
    if version:
        parts.append(f"version {version}")
    parts.append(f"{risk} risk")
    if status:
        parts.append(f"status {status}")
    if reason:
        parts.append(str(reason))
    return " — ".join(parts[:4])


def _build_dependency_highlights(
    attention_dependencies: List[Dict[str, Any]],
    *,
    limit: int = 5,
    risk_filter: Optional[str] = None,
) -> List[str]:
    highlights: List[str] = []
    for dependency in attention_dependencies:
        if not isinstance(dependency, dict):
            continue
        risk = _dependency_risk_level(dependency.get("risk")) or "medium"
        if risk_filter and risk != risk_filter:
            continue
        highlights.append(_format_dependency_entry(dependency))
        if len(highlights) >= limit:
            break
    return highlights


def _find_dependency_by_question(question_lower: str, dependencies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for dependency in dependencies:
        if isinstance(dependency, dict) and _dependency_matches(question_lower, dependency):
            return dependency
    return None


def _count_risk_level(dependency_risk_summary: Dict[str, Any], level: str) -> int:
    try:
        return int(dependency_risk_summary.get(level, 0) or 0)
    except Exception:
        return 0


def _strategy_recommendation_answer(recommendation: Dict[str, Any]) -> str:
    recommended = recommendation.get("recommended_target_version")
    confidence = recommendation.get("confidence")
    rationale = recommendation.get("rationale") if isinstance(recommendation.get("rationale"), list) else []
    answer = (
        f"Recommended target Java version: Java {recommended}."
        if recommended
        else "The strategy page does not show a target Java recommendation."
    )
    if confidence:
        answer += f" Confidence: {confidence}."
    if rationale:
        answer += f" {rationale[0]}"
    return answer


def _strategy_destination_context(strategy_context: Dict[str, Any]) -> Dict[str, Any]:
    destination = strategy_context.get("migration_destination")
    return destination if isinstance(destination, dict) else {}


def _strategy_version_tradeoff_context(question_lower: str) -> bool:
    return any(
        token in question_lower
        for token in (
            "java 21",
            "what if",
            "pros and cons",
            "benefits",
            "drawbacks",
            "downside",
            "compare",
            "should i choose",
        )
    )


def _build_strategy_comparison_table(
    strategy_context: Dict[str, Any],
    question_lower: str,
) -> Optional[Dict[str, Any]]:
    if not any(token in question_lower for token in ("pros and cons", "pros", "cons", "difference", "different between", "compare")):
        return None

    if "java" not in question_lower and "version" not in question_lower and "upgrade" not in question_lower:
        return None

    assessment = strategy_context.get("assessment") if isinstance(strategy_context.get("assessment"), dict) else {}
    strategy = strategy_context.get("strategy") if isinstance(strategy_context.get("strategy"), dict) else {}
    recommendation = strategy_context.get("recommendation") if isinstance(strategy_context.get("recommendation"), dict) else {}

    source_version = str(strategy.get("source_java_version") or assessment.get("java_version") or "17")
    target_version = str(strategy.get("target_java_version") or recommendation.get("recommended_target_version") or "21")

    version_matches = re.findall(r"java\s*(\d{2})", question_lower)
    if len(version_matches) >= 2:
        left_version, right_version = version_matches[0], version_matches[1]
    else:
        left_version, right_version = source_version, target_version

    if left_version == right_version:
        left_version, right_version = "17", "21"

    recommended_version = str(recommendation.get("recommended_target_version") or right_version)
    if recommended_version not in {left_version, right_version}:
        recommended_version = right_version

    def _is_recommended(version: str) -> bool:
        return str(version) == recommended_version

    better_choice = f"Java {recommended_version}"
    table = {
        "caption": f"Java {left_version} vs Java {right_version}",
        "headers": ["Aspect", f"Java {left_version}", f"Java {right_version}"],
        "rows": [
            [
                "LTS fit",
                "Stable, conservative choice" if left_version == "17" else "Newer LTS with a longer runway",
                "Stable, newer LTS with more future-proofing" if right_version == "21" else "Stable, conservative choice",
            ],
            [
                "Compatibility risk",
                "Lower migration risk" if left_version == "17" else "Usually lower than newer LTS targets",
                "Higher compatibility checks" if right_version == "21" else "Usually lower than newer LTS targets",
            ],
            [
                "Pros",
                "Easier to adopt, smaller migration step, fewer dependency surprises" if not _is_recommended(left_version) else "Aligned with the page recommendation and safer for incremental migration",
                "More modern language/runtime features and longer runway" if not _is_recommended(right_version) else "Aligned with the page recommendation and better future-proofing",
            ],
            [
                "Cons",
                "Less runway than the newer LTS line" if left_version == "17" else "More testing and compatibility effort",
                "May need more dependency and framework validation" if right_version == "21" else "Less runway than the newer LTS line",
            ],
            [
                "Best fit for this repo",
                better_choice if _is_recommended(left_version) else "Good if you want the safer incremental path",
                better_choice if _is_recommended(right_version) else "Good if your dependencies are already ready",
            ],
        ],
    }
    return table


def _answer_strategy_dependency_question(
    strategy_context: Dict[str, Any],
    question_lower: str,
    attention_dependencies: List[Dict[str, Any]],
    dependency_risk_summary: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    summary_total = sum(_count_risk_level(dependency_risk_summary, level) for level in ("critical", "high", "medium", "low"))
    critical_count = _count_risk_level(dependency_risk_summary, "critical")
    high_count = _count_risk_level(dependency_risk_summary, "high")
    medium_count = _count_risk_level(dependency_risk_summary, "medium")
    low_count = _count_risk_level(dependency_risk_summary, "low")
    remediation_requested = any(
        token in question_lower
        for token in ("how to fix", "fix", "resolve", "remediat", "mitigat", "patch", "upgrade", "update")
    )

    specific_dependency = _find_dependency_by_question(question_lower, attention_dependencies)
    if specific_dependency:
        label = _dependency_label(specific_dependency)
        risk = str(specific_dependency.get("risk") or "medium").upper()
        reason = specific_dependency.get("reason") or "needs review"
        status = str(specific_dependency.get("status") or "").strip()
        status_text = status.replace("_", " ") if status else ""
        current_version = specific_dependency.get("current_version")

        if remediation_requested:
            answer = (
                f"To fix {label}, start with the safest compatible upgrade or replacement path shown by the page. "
                "Update the dependency version in the build file, rerun tests, and verify that the app still builds cleanly."
            )
            if current_version:
                answer += f" Current version: {current_version}."
            if status:
                answer += f" Status: {status_text or status}."
            if "manual review" in question_lower or "needs manual review" in question_lower or status_text == "needs manual review":
                answer += " Because this item needs manual review, confirm compatibility or replacement before applying the change."
            if risk in {"CRITICAL", "HIGH"}:
                answer += " This should be prioritized before medium-risk items."
            return {
                "answer": answer,
                "rationale": [
                    "Fixing a migration-sensitive dependency usually means upgrading, replacing, or explicitly validating it before the Java change.",
                    "The strategy page marks this item because it needs review before you can treat it as safe.",
                ],
                "cited_fields": ["attention_dependencies", "dependency_risk_summary", "dependency_overview"],
                "confidence": 0.95,
                "follow_up_suggestions": [
                    "Ask whether a newer compatible version exists.",
                    "Ask whether this dependency should be replaced instead of upgraded.",
                ],
            }

        if "manual review" in question_lower or "needs manual review" in question_lower or "review" in question_lower:
            answer = f"{label} needs manual review because the analyzer cannot fully prove it is safe to migrate automatically."
            if reason:
                answer += f" {reason}"
            if current_version:
                answer += f" Current version: {current_version}."
            return {
                "answer": answer,
                "rationale": [
                    "The page marks this dependency as requiring human validation before migration.",
                    "Manual review usually means version mapping, API compatibility, or replacement needs to be checked by a person.",
                ],
                "cited_fields": ["attention_dependencies", "dependency_risk_summary"],
                "confidence": 0.96,
                "follow_up_suggestions": [
                    "Ask what replacement or upgrade path to use.",
                    "Ask whether this dependency blocks the target Java version.",
                ],
            }

    if remediation_requested:
        highlights = _build_dependency_highlights(attention_dependencies, limit=5)
        answer = (
            "To fix the vulnerabilities shown on the strategy page, work from highest risk to lowest: critical first, then high, then medium. "
            "For each dependency, check whether a compatible upgrade exists, replace it if the library is obsolete, update the build file, and rerun tests."
        )
        if highlights:
            answer += " The page currently highlights: " + "; ".join(highlights) + "."
        return {
            "answer": answer,
            "rationale": [
                "The strategy page already ranks the dependencies by migration risk, so the safest fix order follows that ranking.",
                "A dependency is usually fixed by upgrading, replacing, or validating it before the target Java migration.",
            ],
            "cited_fields": ["attention_dependencies", "dependency_risk_summary", "dependency_overview"],
            "confidence": 0.94,
            "follow_up_suggestions": [
                "Ask which highlighted dependency is the first one to fix.",
                "Ask what the safest upgrade path is for a specific dependency.",
            ],
        }

    if "inherited" in question_lower or "analyzed" in question_lower:
        answer = (
            f"{label} shows current version {current_version or 'unknown'} and is treated as {risk.lower()} risk on the strategy page."
        )
        answer += " Inherited versions come from a parent POM, BOM, or transitive declaration; analyzed versions are detected directly from the repository files."
        if status:
            answer += f" Status: {status}."
        return {
            "answer": answer,
            "rationale": [
                "Inherited means the version is not pinned directly in this module.",
                "Analyzed means the repository scan detected the dependency version from source or build metadata.",
            ],
            "cited_fields": ["attention_dependencies", "dependency_overview"],
            "confidence": 0.93,
            "follow_up_suggestions": [
                "Ask which inherited versions should be pinned first.",
                "Ask which analyzed dependencies are safest to keep as-is.",
            ],
        }

    answer = f"{label} is marked {risk} because {reason}."
    if current_version:
        answer += f" Current version: {current_version}."
    if status:
        answer += f" Status: {status_text or status}."
    return {
        "answer": answer,
        "rationale": [
            "The strategy page highlights this dependency because it needs migration attention.",
        ],
        "cited_fields": ["attention_dependencies"],
        "confidence": 0.95,
        "follow_up_suggestions": [
            "Ask what this dependency changes in the migration.",
            "Ask whether there is a safer replacement or upgrade path.",
        ],
    }

    if "overall risk" in question_lower or ("application risk" in question_lower and "critical" in question_lower):
        answer = f"Overall strategy risk is {str(strategy_context.get('assessment', {}).get('risk_level') or 'unknown').upper()}."
        if critical_count or high_count or medium_count:
            answer += (
                f" That is driven by {critical_count} critical, {high_count} high, and {medium_count} medium dependencies on the page,"
                " even if the application-level code changes look comparatively small."
            )
        return {
            "answer": answer,
            "rationale": [
                "The assessment section and dependency scan can point to different risk layers.",
                "Overall migration risk includes dependency compatibility, not just application code size.",
            ],
            "cited_fields": ["assessment", "dependency_risk_summary", "attention_dependencies"],
            "confidence": 0.95,
            "follow_up_suggestions": [
                "Ask which dependency is causing the biggest risk jump.",
                "Ask how to reduce the overall risk level.",
            ],
        }

    if "manual review" in question_lower or "needs manual review" in question_lower:
        return {
            "answer": "NEEDS MANUAL REVIEW means the analyzer could not safely make an automatic migration decision, so a human needs to confirm the compatibility or replacement path before migration continues.",
            "rationale": [
                "This label is used when the dependency is migration-sensitive or the scan does not have enough certainty.",
                "It usually applies to legacy APIs, namespace changes, or version gaps that need a person to verify.",
            ],
            "cited_fields": ["attention_dependencies", "dependency_risk_summary"],
            "confidence": 0.94,
            "follow_up_suggestions": [
                "Ask which exact dependency is marked manual review.",
                "Ask what checks are needed before proceeding.",
            ],
        }

    if "other dependencies" in question_lower or "requiring attention" in question_lower:
        attention_count = critical_count + high_count + medium_count
        answer = (
            f"Dependencies Requiring Attention are the {attention_count} non-low-risk dependencies on the page "
            f"({critical_count} critical, {high_count} high, {medium_count} medium). "
            f"Other Dependencies are the {low_count} low-risk ones that do not currently show strong migration-risk signals."
        )
        return {
            "answer": answer,
            "rationale": [
                "The strategy page separates higher-risk items from low-risk items so you can focus review time where it matters most.",
            ],
            "cited_fields": ["dependency_risk_summary"],
            "confidence": 0.96,
            "follow_up_suggestions": [
                "Ask for the full list of attention dependencies.",
                "Ask which low-risk dependencies should still be spot-checked.",
            ],
        }

    if "medium" in question_lower:
        medium_dependencies = _build_dependency_highlights(attention_dependencies, limit=5, risk_filter="medium")
        answer = f"{medium_count} dependency(s) are marked Medium risk."
        if medium_dependencies:
            answer += " The page highlights: " + "; ".join(medium_dependencies)
        return {
            "answer": answer,
            "rationale": [
                "Medium risk usually means compatibility is plausible but should be validated during migration.",
            ],
            "cited_fields": ["attention_dependencies", "dependency_risk_summary"],
            "confidence": 0.94,
            "follow_up_suggestions": [
                "Ask why a specific dependency is medium risk.",
                "Ask which medium-risk items should be fixed first.",
            ],
        }

    if any(token in question_lower for token in ("dependency", "dependencies", "vulnerab", "attention", "risk")):
        highlights = _build_dependency_highlights(attention_dependencies, limit=5)
        if highlights:
            answer = "Dependencies needing migration attention: " + "; ".join(highlights)
            remaining = max(0, len(attention_dependencies) - len(highlights))
            if remaining > 0:
                answer += f". {remaining} more dependency(s) also need review."
        else:
            answer = "The current strategy page does not show any dependencies requiring attention."
        return {
            "answer": answer,
            "rationale": [
                f"The strategy page marks {summary_total - low_count} dependencies above low risk.",
                "The list is derived from the page's own dependency risk summary.",
            ],
            "cited_fields": ["attention_dependencies", "dependency_risk_summary", "dependency_overview"],
            "confidence": 0.93,
            "follow_up_suggestions": [
                "Ask which dependency is highest risk.",
                "Ask for the critical, high, and medium split.",
            ],
        }

    return None


def _answer_strategy_version_question(
    strategy_context: Dict[str, Any],
    question_lower: str,
    recommendation: Dict[str, Any],
    assessment: Dict[str, Any],
    strategy: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not any(token in question_lower for token in ("java", "version", "migrate", "upgrade", "lts")):
        return None

    requested_version_match = re.search(r"java\s*(\d{2})", question_lower)
    requested_version = requested_version_match.group(1) if requested_version_match else None
    recommended = recommendation.get("recommended_target_version")
    recommended_versions = recommendation.get("recommended_versions") if isinstance(recommendation.get("recommended_versions"), list) else []
    alternative_options = recommendation.get("alternative_options") if isinstance(recommendation.get("alternative_options"), list) else []

    if requested_version == "21" or _strategy_version_tradeoff_context(question_lower):
        if recommended and str(recommended) == "21":
            answer = (
                "Java 21 is the page's recommended target. Pros: newer language and runtime features, a longer LTS runway, and better future-proofing. "
                "Cons: you still need to validate framework and dependency compatibility, plus run a full regression test cycle before committing to it."
            )
            return {
                "answer": answer,
                "rationale": [
                    "Java 21 is the modern LTS line, so it can be a strong long-term target.",
                    "The main work is usually compatibility and test validation, not just changing the version number.",
                ],
                "cited_fields": ["recommendation", "strategy", "assessment"],
                "confidence": 0.92,
                "follow_up_suggestions": [
                    "Ask which dependencies should be checked first.",
                    "Ask what testing changes are needed before moving to Java 21.",
                ],
            }

        answer = (
            "Java 21 can be a good long-term target, but compared with Java 17 it usually carries more migration risk. "
            "Pros: newer language and runtime features, a longer support runway, and stronger future-proofing. "
            "Cons: more chance of framework or library compatibility issues, more testing effort, and a slightly bigger migration step. "
        )
        if recommended:
            answer += f"Based on the current strategy page, Java {recommended} is still the safer recommendation for this repo right now."
        else:
            answer += "The current strategy page does not show a target recommendation, so the safest choice depends on your dependency and framework compatibility."
        return {
            "answer": answer,
            "rationale": [
                "Java 21 is a newer LTS target, but newer targets usually increase compatibility validation work.",
                "The current strategy page recommends the lower-risk option for this repository.",
            ],
            "cited_fields": ["recommendation", "strategy", "assessment"],
            "confidence": 0.94,
            "follow_up_suggestions": [
                "Ask what changes are needed if you still want Java 21.",
                "Ask which dependencies are the biggest blockers for Java 21.",
            ],
        }

    if requested_version and recommended and requested_version != str(recommended):
        if requested_version not in {str(item) for item in recommended_versions}:
            answer = (
                f"Java {requested_version} is not shown in the current strategy page context. "
                f"The page recommends Java {recommended} instead."
            )
            if alternative_options:
                alt_lines = []
                for option in alternative_options[:2]:
                    if not isinstance(option, dict):
                        continue
                    version = option.get("version")
                    reason = option.get("reason")
                    risk = option.get("risk")
                    line = f"Java {version}"
                    if risk:
                        line += f" ({risk})"
                    if reason:
                        line += f": {reason}"
                    alt_lines.append(line)
                if alt_lines:
                    answer += " Alternatives on the page: " + "; ".join(alt_lines) + "."
            return {
                "answer": answer,
                "rationale": recommendation.get("rationale")[:3] if isinstance(recommendation.get("rationale"), list) else ["Based on the current strategy page recommendation."],
                "cited_fields": ["recommendation", "strategy"],
                "confidence": 0.89,
                "follow_up_suggestions": [
                    "Ask why this target version was recommended.",
                    "Ask what library updates are needed for the selected target.",
                ],
            }

    if recommended:
        answer = _strategy_recommendation_answer(recommendation)
        if requested_version and requested_version != str(recommended):
            answer += f" The page does not currently recommend Java {requested_version}."
        if alternative_options:
            alt_lines = []
            for option in alternative_options[:2]:
                if not isinstance(option, dict):
                    continue
                version = option.get("version")
                reason = option.get("reason")
                risk = option.get("risk")
                line = f"Java {version}"
                if risk:
                    line += f" ({risk})"
                if reason:
                    line += f": {reason}"
                alt_lines.append(line)
            if alt_lines:
                answer += " Other page alternatives: " + "; ".join(alt_lines) + "."
        return {
            "answer": answer,
            "rationale": recommendation.get("rationale")[:3] if isinstance(recommendation.get("rationale"), list) else ["Based on the current strategy page recommendation."],
            "cited_fields": ["recommendation", "strategy", "assessment"],
            "confidence": 0.96,
            "follow_up_suggestions": [
                "Ask why the page prefers this Java version.",
                "Ask what changes are needed before migrating.",
            ],
        }

    source_version = strategy.get("source_java_version") or assessment.get("java_version")
    target_version = strategy.get("target_java_version")
    if source_version or target_version:
        answer = f"The strategy page currently shows Java {source_version or 'unknown'} as the source"
        if target_version:
            answer += f" and Java {target_version} as the target."
        else:
            answer += "."
        return {
            "answer": answer,
            "rationale": ["The page shows the current migration version fields but no computed recommendation."],
            "cited_fields": ["strategy", "assessment"],
            "confidence": 0.8,
            "follow_up_suggestions": [
                "Ask for the recommended target version.",
                "Ask whether the current source version is already the latest supported.",
            ],
        }

    return {
        "answer": "The strategy page does not currently show enough Java version detail to compare targets.",
        "rationale": ["No Java version recommendation or source/target pair was present in the current context."],
        "cited_fields": ["strategy", "recommendation"],
        "confidence": 0.72,
        "follow_up_suggestions": [
            "Ask for the currently recommended target version.",
        ],
    }


def _answer_strategy_conversion_question(
    strategy_context: Dict[str, Any],
    question_lower: str,
    strategy: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not any(token in question_lower for token in ("conversion", "javax", "jakarta", "spring boot", "spring-boot", "maven", "gradle", "monolithic", "microservices")):
        return None

    conversion_options = _strategy_list_of_dicts(strategy_context.get("conversion_options"))
    selected_conversions = strategy.get("selected_conversions") or []

    if "javax" in question_lower and "jakarta" in question_lower:
        available = [option for option in conversion_options if "jakarta" in str(option.get("key") or "").lower() or "jakarta" in str(option.get("title") or "").lower()]
        if available:
            return {
                "answer": "The strategy page shows the Jakarta-related path as not yet available or still coming soon in the visible conversion options. There is no specific launch date shown in the current page context.",
                "rationale": [
                    "The page only exposes the conversion options currently wired into the strategy screen.",
                ],
                "cited_fields": ["conversion_options"],
                "confidence": 0.88,
                "follow_up_suggestions": [
                    "Ask which visible conversion options are active now.",
                ],
            }
        return {
            "answer": "The current strategy page does not list a javax-to-Jakarta conversion path as available yet.",
            "rationale": ["That option is not shown in the visible conversion choices."],
            "cited_fields": ["conversion_options"],
            "confidence": 0.9,
            "follow_up_suggestions": [
                "Ask which conversion options are currently available.",
            ],
        }

    if "maven" in question_lower and "gradle" in question_lower:
        option = next((item for item in conversion_options if "build" in str(item.get("key") or "").lower() or "maven" in str(item.get("title") or "").lower()), None)
        answer = "The Maven -> Gradle path affects build scripts, plugin configuration, dependency declarations, and CI/build tooling."
        if option and str(option.get("status") or "").lower() == "coming_soon":
            answer += " On the current strategy page, this conversion option is marked coming soon."
        return {
            "answer": answer,
            "rationale": [
                "Build-system conversions usually require changes beyond dependencies, including plugins and pipeline config.",
            ],
            "cited_fields": ["conversion_options", "strategy"],
            "confidence": 0.9,
            "follow_up_suggestions": [
                "Ask what files will likely change in pom.xml or build.gradle.",
            ],
        }

    if "spring" in question_lower and "boot" in question_lower:
        return {
            "answer": "The current strategy page does not show a Spring -> Spring Boot conversion path as an active option. If you want that conversion, it would need to be added as a dedicated strategy step.",
            "rationale": ["That conversion is not present in the visible conversion options."],
            "cited_fields": ["conversion_options"],
            "confidence": 0.89,
            "follow_up_suggestions": [
                "Ask which conversion options are active right now.",
            ],
        }

    if "microservices" in question_lower or "monolithic" in question_lower:
        return {
            "answer": "The current strategy page does not expose a Monolithic -> Microservices conversion path in the visible options.",
            "rationale": ["That migration style is not part of the current strategy-page choices."],
            "cited_fields": ["conversion_options"],
            "confidence": 0.9,
            "follow_up_suggestions": [
                "Ask which conversion paths are visible on the page now.",
            ],
        }

    if "conversion" in question_lower:
        active = ", ".join(str(item) for item in selected_conversions[:5]) if selected_conversions else "none"
        return {
            "answer": f"Selected conversion choices on the strategy page: {active}.",
            "rationale": ["This comes from the strategy selection area on the page."],
            "cited_fields": ["strategy", "conversion_options"],
            "confidence": 0.84,
            "follow_up_suggestions": [
                "Ask which conversion option is currently active.",
            ],
        }

    return None


def _answer_strategy_destination_question(strategy_context: Dict[str, Any], question_lower: str) -> Optional[Dict[str, Any]]:
    if not any(token in question_lower for token in ("repository", "branch", "folder", "github", "owner", "destination", "target repo", "target repository", "local folder", "access")):
        return None

    destination = _strategy_destination_context(strategy_context)
    options = _strategy_list_of_dicts(strategy_context.get("migration_approach_options"))
    if not destination:
        return {
            "answer": "The strategy page does not currently expose a migration destination summary in the context I received.",
            "rationale": ["No destination fields were present in the current strategy context."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.72,
            "follow_up_suggestions": [
                "Ask which destination options are available on the page.",
            ],
        }

    approach = str(destination.get("approach") or "").lower()
    label = destination.get("label") or destination.get("approach") or "the selected destination"
    description = destination.get("description")
    target_repo_name = destination.get("target_repo_name")
    target_repo_owner = destination.get("target_repo_owner")
    target_repo_host = destination.get("target_repo_host")
    editable = bool(destination.get("target_repo_name_editable"))

    if "difference" in question_lower and all(
        token in question_lower
        for token in ("create new repository", "existing repository", "local folder")
    ):
        comparison_lines = []
        for option in options[:3]:
            option_label = option.get("label") or option.get("value") or "Destination option"
            option_desc = option.get("desc") or option.get("tooltip") or "No description shown."
            comparison_lines.append(f"{option_label}: {option_desc}")
        return {
            "answer": "Here’s the difference shown on the strategy page: " + " ".join(comparison_lines),
            "rationale": ["The page presents each destination option with a short workflow description."],
            "cited_fields": ["migration_approach_options", "migration_destination"],
            "confidence": 0.96,
            "follow_up_suggestions": [
                "Ask which option is safest if you do not want to touch GitHub.",
                "Ask which option keeps the source repository unchanged.",
            ],
        }

    if "create new repository" in question_lower or "existing repository" in question_lower or "local folder" in question_lower:
        answer = f"{label}: {description or 'This is the selected migration destination.'}"
        return {
            "answer": answer,
            "rationale": ["The page labels each destination with a short description so you can choose the publishing target."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.95,
            "follow_up_suggestions": [
                "Ask whether the target name is editable.",
                "Ask what happens if you choose the local folder option.",
            ],
        }

    if "owner" in question_lower or "javaspoc" in question_lower or "javaapex" in question_lower:
        answer = f"The current target GitHub owner shown in the strategy context is {target_repo_owner or 'not shown'}."
        if approach == "fork":
            answer += " For Create New Repository, that owner is typically fixed by the app's default publishing target."
        else:
            answer += " For branch or local workflows, the owner is derived from the source repository context or the signed-in user."
        return {
            "answer": answer,
            "rationale": ["The destination context includes the owner the app will use for publishing migrated code."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.91,
            "follow_up_suggestions": [
                "Ask whether the owner can be changed in the current workflow.",
            ],
        }

    if "name" in question_lower or "rename" in question_lower:
        answer = f"Auto-generated target name: {target_repo_name or 'not shown'}."
        if editable:
            answer += " It is editable in the current workflow."
        else:
            answer += " In the current workflow it appears read-only."
        return {
            "answer": answer,
            "rationale": ["The destination summary captures whether the target name is auto-generated or manually editable."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.94,
            "follow_up_suggestions": [
                "Ask what name will be used by default if you leave it unchanged.",
            ],
        }

    if "github" in question_lower and "access" in question_lower:
        return {
            "answer": "If you do not have GitHub access, the Store in Local Folder option is the safest path because it keeps the migrated output on this machine instead of pushing to a remote repository.",
            "rationale": ["The local-folder workflow avoids remote publishing requirements."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.95,
            "follow_up_suggestions": [
                "Ask whether the branch workflow requires write access.",
            ],
        }

    if "fork" in question_lower or "branch" in question_lower or "local" in question_lower:
        return {
            "answer": f"{label}: {description or 'This is the currently selected destination.'}",
            "rationale": ["The strategy page lists the destination choice along with a short explanation."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.92,
            "follow_up_suggestions": [
                "Ask how the target name is generated for this destination.",
            ],
        }

    return None


def _answer_strategy_post_migration_question(
    strategy_context: Dict[str, Any],
    question_lower: str,
    assessment: Dict[str, Any],
    strategy: Dict[str, Any],
    recommendation: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not any(token in question_lower for token in ("after migration", "post-migration", "deploy", "rollback", "pom.xml", "tests still pass", "deployable", "roll back", "rollback", "devtools", "javax.servlet.jsf")):
        return None

    has_tests = assessment.get("has_tests")
    risk_level = str(assessment.get("risk_level") or "unknown").upper()
    selected_conversions = strategy.get("selected_conversions") or []
    target_version = strategy.get("target_java_version") or recommendation.get("recommended_target_version")

    if "tests" in question_lower:
        if has_tests is True:
            return {
                "answer": "The strategy page detects tests, which is a good sign, but migration success is still not guaranteed. You should run the test suite after the Java upgrade and fix any failures before deploying.",
                "rationale": ["Detected tests reduce risk, but they do not eliminate compatibility issues."],
                "cited_fields": ["assessment"],
                "confidence": 0.91,
                "follow_up_suggestions": [
                    "Ask which test types were detected.",
                    "Ask what to do if tests fail after migration.",
                ],
            }
        if has_tests is False:
            return {
                "answer": "The strategy page does not detect tests, so you should assume the migrated code is not immediately safe to deploy until you add validation coverage.",
                "rationale": ["Missing tests increases migration and deployment risk."],
                "cited_fields": ["assessment"],
                "confidence": 0.92,
                "follow_up_suggestions": [
                    "Ask for a minimal smoke-test plan.",
                ],
            }

    if "pom.xml" in question_lower:
        if "maven" in str(assessment.get("build_tool") or "").lower() or "maven" in question_lower:
            return {
                "answer": "The Maven path usually changes pom.xml compiler settings, plugin versions, dependency coordinates, and sometimes dependency scopes or namespace mappings.",
                "rationale": ["Build-tool upgrades often require updates to compiler and plugin configuration."],
                "cited_fields": ["assessment", "strategy", "conversion_options"],
                "confidence": 0.9,
                "follow_up_suggestions": [
                    "Ask which specific pom.xml sections are most likely to change.",
                ],
            }

    if "rollback" in question_lower or "roll back" in question_lower:
        return {
            "answer": "Rollback is safest when the migration output is isolated: use a new branch or local folder so you can revert without touching the source repository. If the page is using a forked/new repository flow, the original source stays intact as the fallback.",
            "rationale": ["Isolated destinations make rollback much simpler."],
            "cited_fields": ["migration_destination"],
            "confidence": 0.93,
            "follow_up_suggestions": [
                "Ask how rollback differs for branch versus local folder workflows.",
            ],
        }

    if "deploy" in question_lower or "deployable" in question_lower:
        answer = f"No, migrated code should not be treated as immediately deployable just because a target version is selected. The page shows risk level {risk_level} and target Java {target_version or 'unknown'}, so validation and test runs are still required."
        return {
            "answer": answer,
            "rationale": [
                "A successful migration still needs build and test verification.",
            ],
            "cited_fields": ["assessment", "strategy", "recommendation"],
            "confidence": 0.9,
            "follow_up_suggestions": [
                "Ask what validation steps to run before deployment.",
            ],
        }

    if "devtools" in question_lower:
        return {
            "answer": "spring-boot-devtools is usually a development-time helper, so after migration it should be checked for compatibility and typically kept out of production packaging.",
            "rationale": ["Devtools is often safe to keep for local development but should be reviewed during runtime upgrades."],
            "cited_fields": ["attention_dependencies", "dependency_overview"],
            "confidence": 0.84,
            "follow_up_suggestions": [
                "Ask whether devtools appears in the page's dependency attention list.",
            ],
        }

    if "javax.servlet.jsf" in question_lower:
        return {
            "answer": "For javax.servlet.jsf, the safest path is to confirm whether the dependency is still needed, then check its Jakarta-compatible replacement or a framework-level migration path before changing the Java target.",
            "rationale": [
                "Legacy javax namespace dependencies are usually migration-sensitive.",
            ],
            "cited_fields": ["attention_dependencies", "dependency_risk_summary"],
            "confidence": 0.92,
            "follow_up_suggestions": [
                "Ask which replacement package should be used.",
            ],
        }

    return None


def _prune_prompt_value(value: Any, *, depth: int = 0) -> Any:
    if value is None:
        return None
    if depth >= STRATEGY_CONTEXT_MAX_DEPTH:
        return _truncate_text(value)
    if isinstance(value, dict):
        pruned: Dict[str, Any] = {}
        for key, item in list(value.items())[:STRATEGY_CONTEXT_MAX_KEYS]:
            if item is None or item == "" or item == [] or item == {}:
                continue
            pruned[str(key)] = _prune_prompt_value(item, depth=depth + 1)
        return pruned
    if isinstance(value, list):
        return [_prune_prompt_value(item, depth=depth + 1) for item in value[:STRATEGY_CONTEXT_MAX_LIST]]
    if isinstance(value, (bool, int, float)):
        return value
    return _truncate_text(value)


def _select_analysis_payload(analysis: Any, repo_url: Optional[str]) -> Dict[str, Any]:
    if isinstance(analysis, list):
        for item in analysis:
            if isinstance(item, dict) and repo_url and (item.get("repo_url") == repo_url or item.get("url") == repo_url):
                return item
        for item in analysis:
            if isinstance(item, dict):
                return item
        return {}
    if isinstance(analysis, dict):
        return analysis
    return {}


def _build_strategy_context(payload: StrategyQuery) -> Tuple[Dict[str, Any], str]:
    if isinstance(payload.strategy_context, dict) and payload.strategy_context:
        return _prune_prompt_value(payload.strategy_context), "strategy_page"

    selected_analysis = _select_analysis_payload(payload.analysis or {}, payload.repo_url)
    if selected_analysis:
        try:
            context = build_repository_context_pack(
                repo_name=(selected_analysis.get("name") or ""),
                repo_url=(payload.repo_url or ""),
                analysis_data=selected_analysis,
                base_document=None,
            )
            return _prune_prompt_value(context), "analysis_fallback"
        except Exception:
            return _prune_prompt_value(selected_analysis), "analysis_fallback"

    return {"page": "Assessment & Migration Strategy"}, "empty"


def _infer_strategy_intent(question: str, template_item: Optional[Dict[str, Any]] = None) -> str:
    question_lower = (question or "").lower()
    template_id = str(template_item.get("id") or "").lower() if isinstance(template_item, dict) else ""
    template_category = str(template_item.get("category") or "").lower() if isinstance(template_item, dict) else ""

    intent_by_template = {
        "assessment": "assessment",
        "vulnerabilities": "dependency",
        "dependency": "dependency",
        "java-version": "version",
        "migration-plan": "version",
        "conversion": "conversion",
        "migration": "conversion",
        "destination": "destination",
        "post-migration": "post_migration",
        "tests": "post_migration",
        "risk": "assessment",
    }

    if template_category in intent_by_template:
        return intent_by_template[template_category]
    if template_id in {f"q{value}" for value in range(61, 67)}:
        return "dependency"
    if template_id in {f"q{value}" for value in range(67, 73)}:
        return "version"
    if template_id in {f"q{value}" for value in range(73, 77)}:
        return "conversion"
    if template_id in {f"q{value}" for value in range(77, 81)}:
        return "destination"
    if template_id in {f"q{value}" for value in range(81, 86)}:
        return "post_migration"

    if any(token in question_lower for token in ("dependency", "dependencies", "vulnerab", "manual review", "inherited", "analyzed")):
        return "dependency"
    if any(token in question_lower for token in ("java 17", "java 21", "java version", "lts", "upgrade java", "which java", "maven configuration", "spring-boot-devtools")):
        return "version"
    if any(token in question_lower for token in ("create new repository", "existing repository", "store in local folder", "github owner", "target repo", "repository name", "github access")):
        return "destination"
    if any(token in question_lower for token in ("javax to jakarta", "monolithic", "microservices", "spring to spring boot", "maven to gradle", "conversion")):
        return "conversion"
    if any(token in question_lower for token in ("rollback", "deploy", "deployable", "pom.xml", "tests still pass", "manual review")):
        return "post_migration"
    if any(token in question_lower for token in ("overall risk", "critical", "medium risk", "assessment", "why is my overall risk", "risk level")):
        return "assessment"
    return "general"


def _build_strategy_focus_context(
    strategy_context: Dict[str, Any],
    intent: str,
    question: str,
    template_item: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    focus: Dict[str, Any] = {}
    repository = strategy_context.get("repository")
    assessment = strategy_context.get("assessment")
    strategy = strategy_context.get("strategy")
    recommendation = strategy_context.get("recommendation")
    destination = strategy_context.get("migration_destination")
    approach_options = strategy_context.get("migration_approach_options")
    dependency_risk_summary = strategy_context.get("dependency_risk_summary")
    attention_dependencies = _strategy_list_of_dicts(strategy_context.get("attention_dependencies"))
    dependency_overview = _strategy_list_of_dicts(strategy_context.get("dependency_overview"))

    if repository:
        focus["repository"] = repository

    specific_dependency = _find_dependency_by_question(question.lower(), attention_dependencies)

    if intent == "dependency":
        if assessment:
            focus["assessment"] = {
                key: assessment.get(key)
                for key in ("risk_level", "risk_reason", "build_tool", "java_version", "has_tests", "dependency_count")
                if assessment.get(key) is not None
            }
        if dependency_risk_summary:
            focus["dependency_risk_summary"] = dependency_risk_summary
        if specific_dependency:
            focus["attention_dependencies"] = [specific_dependency]
        elif attention_dependencies:
            focus["attention_dependencies"] = attention_dependencies[:5]
        if dependency_overview:
            focus["dependency_overview"] = dependency_overview[:5]

    elif intent == "version":
        if assessment:
            focus["assessment"] = {
                key: assessment.get(key)
                for key in ("risk_level", "risk_reason", "build_tool", "java_version", "has_tests", "dependency_count")
                if assessment.get(key) is not None
            }
        if strategy:
            focus["strategy"] = {
                key: strategy.get(key)
                for key in ("source_java_version", "target_java_version", "selected_conversions", "source_already_at_latest_supported_version")
                if strategy.get(key) is not None
            }
        if recommendation:
            focus["recommendation"] = recommendation

    elif intent == "destination":
        if strategy:
            focus["strategy"] = {
                key: strategy.get(key)
                for key in ("source_java_version", "target_java_version", "selected_conversions")
                if strategy.get(key) is not None
            }
        if destination:
            focus["migration_destination"] = destination
        if approach_options:
            focus["migration_approach_options"] = approach_options

    elif intent == "conversion":
        if strategy:
            focus["strategy"] = {
                key: strategy.get(key)
                for key in ("source_java_version", "target_java_version", "selected_conversions")
                if strategy.get(key) is not None
            }
        if strategy_context.get("conversion_options"):
            focus["conversion_options"] = strategy_context.get("conversion_options")
        if recommendation:
            focus["recommendation"] = recommendation

    elif intent == "assessment":
        if assessment:
            focus["assessment"] = {
                key: assessment.get(key)
                for key in ("risk_level", "risk_reason", "build_tool", "java_version", "has_tests", "dependency_count")
                if assessment.get(key) is not None
            }
        if dependency_risk_summary:
            focus["dependency_risk_summary"] = dependency_risk_summary
        if specific_dependency:
            focus["attention_dependencies"] = [specific_dependency]
        elif attention_dependencies:
            focus["attention_dependencies"] = attention_dependencies[:5]
        if recommendation:
            focus["recommendation"] = recommendation

    elif intent == "post_migration":
        if assessment:
            focus["assessment"] = {
                key: assessment.get(key)
                for key in ("risk_level", "risk_reason", "build_tool", "java_version", "has_tests")
                if assessment.get(key) is not None
            }
        if strategy:
            focus["strategy"] = {
                key: strategy.get(key)
                for key in ("source_java_version", "target_java_version", "selected_conversions")
                if strategy.get(key) is not None
            }
        if recommendation:
            focus["recommendation"] = recommendation
        if destination:
            focus["migration_destination"] = destination
        if attention_dependencies:
            focus["attention_dependencies"] = attention_dependencies[:5]
        if dependency_risk_summary:
            focus["dependency_risk_summary"] = dependency_risk_summary

    else:
        if assessment:
            focus["assessment"] = assessment
        if strategy:
            focus["strategy"] = strategy
        if recommendation:
            focus["recommendation"] = recommendation
        if destination:
            focus["migration_destination"] = destination
        if approach_options:
            focus["migration_approach_options"] = approach_options
        if dependency_risk_summary:
            focus["dependency_risk_summary"] = dependency_risk_summary
        if attention_dependencies:
            focus["attention_dependencies"] = attention_dependencies[:5]
        if dependency_overview:
            focus["dependency_overview"] = dependency_overview[:5]
        if strategy_context.get("conversion_options"):
            focus["conversion_options"] = strategy_context.get("conversion_options")

    focus["page"] = strategy_context.get("page") or "Assessment & Migration Strategy"
    focus["question_intent"] = intent
    if template_item:
        focus["matched_template"] = {
            "id": template_item.get("id"),
            "category": template_item.get("category"),
            "template": template_item.get("template"),
        }
    return _prune_prompt_value(focus)


def _build_strategy_prompts(
    strategy_context: Dict[str, Any],
    question: str,
    intent: str,
    template_item: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    template_focus = ""
    if template_item and template_item.get("template"):
        template_focus = f" Focus on: {template_item.get('template')}."
    question_lower = (question or "").lower()
    version_tradeoff_focus = ""
    if intent == "version" and _strategy_version_tradeoff_context(question_lower):
        version_tradeoff_focus = (
            " If the question mentions Java 21, explicitly compare its pros and cons with the current recommendation. "
            "Mention future-proofing, compatibility risk, and testing effort in plain language."
        )
    system_prompt = (
        "You are a strategy-page assistant for a Java migration wizard. "
        "Answer only from the provided strategy page context. "
        "Be warm, direct, and specific, like a helpful teammate. "
        "Keep answers concise but not robotic. "
        "If the answer is not shown, explain what the page does show, then ask one focused follow-up question. "
        f"Primary intent: {intent}.{template_focus}{version_tradeoff_focus} "
        "Do not invent information or use outside knowledge."
    )

    schema_req = (
        "\n\nReturn JSON only with this schema:\n"
        "{\n"
        '  "answer": string,\n'
        '  "rationale": [string],\n'
        '  "cited_fields": [string],\n'
        '  "confidence": number|null,\n'
        '  "follow_up_suggestions": [string]\n'
        "}\n"
        "Keep the answer short and grounded in the provided context."
    )

    user_prompt = (
        "STRATEGY_PAGE_CONTEXT:\n"
        + json.dumps(strategy_context, separators=(",", ":"), ensure_ascii=False)
        + "\n\nQUESTION: "
        + question
        + "\n\nReturn JSON only."
    )

    return system_prompt + schema_req, user_prompt


def _build_strategy_stream_prompts(
    strategy_context: Dict[str, Any],
    question: str,
    intent: str,
    template_item: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    template_focus = ""
    if template_item and template_item.get("template"):
        template_focus = f" Focus on: {template_item.get('template')}."
    question_lower = (question or "").lower()
    version_tradeoff_focus = ""
    if intent == "version" and _strategy_version_tradeoff_context(question_lower):
        version_tradeoff_focus = (
            " If the question mentions Java 21, compare its pros and cons against the current recommendation. "
            "Keep the explanation practical and grounded in compatibility and testing effort."
        )

    system_prompt = (
        "You are a helpful strategy-page assistant for a Java migration wizard. "
        "Answer naturally, clearly, and concisely, like a ChatGPT-style chat assistant. "
        "Use only the provided strategy page context. "
        "If the page does not show enough detail, say what it does show and ask one focused follow-up question. "
        f"Primary intent: {intent}.{template_focus}{version_tradeoff_focus} "
        "Do not output JSON in the streamed answer."
    )

    user_prompt = (
        "STRATEGY_PAGE_CONTEXT:\n"
        + json.dumps(strategy_context, separators=(",", ":"), ensure_ascii=False)
        + "\n\nQUESTION: "
        + question
        + "\n\nAnswer in plain text only."
    )
    return system_prompt, user_prompt


def _normalize_strategy_parsed(parsed: Any, raw_text: str) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    try:
        if not isinstance(parsed, dict):
            return (
                {
                    "answer": _truncate_text(raw_text, STRATEGY_CONTEXT_MAX_ANSWER),
                    "rationale": [],
                    "cited_fields": [],
                    "confidence": None,
                    "follow_up_suggestions": [],
                },
                False,
                "parsed_not_object",
            )

        answer = parsed.get("answer")
        normalized_answer = answer if isinstance(answer, str) and answer.strip() else _truncate_text(raw_text, STRATEGY_CONTEXT_MAX_ANSWER)

        rationale_source = parsed.get("rationale") if isinstance(parsed.get("rationale"), list) else []
        rationale = [_truncate_text(item, 180) for item in rationale_source if item is not None][:4]

        cited_source = parsed.get("cited_fields")
        if not isinstance(cited_source, list):
            cited_source = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
        cited_fields = [_truncate_text(item, 120) for item in cited_source if item is not None][:6]

        follow_up_source = parsed.get("follow_up_suggestions") if isinstance(parsed.get("follow_up_suggestions"), list) else []
        follow_up = [_truncate_text(item, 180) for item in follow_up_source if item is not None][:4]

        confidence = parsed.get("confidence")
        if isinstance(confidence, (int, float)):
            normalized_confidence: Optional[float | str] = float(confidence)
        elif isinstance(confidence, str):
            try:
                normalized_confidence = float(confidence)
            except Exception:
                normalized_confidence = _truncate_text(confidence, 32)
        else:
            normalized_confidence = None

        normalized = {
            "answer": normalized_answer,
            "rationale": rationale,
            "cited_fields": cited_fields,
            "confidence": normalized_confidence,
            "follow_up_suggestions": follow_up,
        }

        if not normalized["answer"]:
            return (normalized, False, "empty_answer")

        return (normalized, True, None)
    except Exception as exc:
        logger.exception("Strategy JSON validation failed")
        return (
            {
                "answer": _truncate_text(raw_text, STRATEGY_CONTEXT_MAX_ANSWER),
                "rationale": [],
                "cited_fields": [],
                "confidence": None,
                "follow_up_suggestions": [],
            },
            False,
            str(exc),
        )


def _build_strategy_rule_based_answer_v2(strategy_context: Dict[str, Any], question: str) -> Optional[Dict[str, Any]]:
    question_lower = question.lower()
    matched_template, match_score = match_question(question)
    matched_id = matched_template.get("id") if isinstance(matched_template, dict) and match_score >= 0.2 else None
    assessment = strategy_context.get("assessment") if isinstance(strategy_context.get("assessment"), dict) else {}
    strategy = strategy_context.get("strategy") if isinstance(strategy_context.get("strategy"), dict) else {}
    recommendation = strategy_context.get("recommendation") if isinstance(strategy_context.get("recommendation"), dict) else {}
    attention_dependencies = _strategy_list_of_dicts(strategy_context.get("attention_dependencies"))
    dependency_risk_summary = strategy_context.get("dependency_risk_summary") if isinstance(strategy_context.get("dependency_risk_summary"), dict) else {}

    if matched_id in {"q61", "q62", "q63", "q64", "q65", "q66"}:
        dependency_answer = _answer_strategy_dependency_question(
            strategy_context,
            question_lower,
            attention_dependencies,
            dependency_risk_summary,
        )
        if dependency_answer is not None:
            return dependency_answer

    version_answer = _answer_strategy_version_question(
        strategy_context,
        question_lower,
        recommendation,
        assessment,
        strategy,
    )
    if version_answer is not None:
        return version_answer

    if matched_id in {"q73", "q74", "q75", "q76"}:
        conversion_answer = _answer_strategy_conversion_question(strategy_context, question_lower, strategy)
        if conversion_answer is not None:
            return conversion_answer

    destination_answer = _answer_strategy_destination_question(strategy_context, question_lower)
    if destination_answer is not None:
        return destination_answer

    post_answer = _answer_strategy_post_migration_question(
        strategy_context,
        question_lower,
        assessment,
        strategy,
        recommendation,
    )
    if post_answer is not None:
        return post_answer

    if any(keyword in question_lower for keyword in ("test", "tests", "coverage", "unit", "integration")):
        has_tests = assessment.get("has_tests")
        if has_tests is True:
            return {
                "answer": "The strategy page indicates tests are present, which is a positive sign for migration safety. Even so, you should rerun them after the Java upgrade.",
                "rationale": ["The page includes a detected test signal in the assessment section."],
                "cited_fields": ["assessment"],
                "confidence": 0.9,
                "follow_up_suggestions": [
                    "Ask which test types were detected.",
                    "Ask whether any additional tests should be added.",
                ],
            }
        if has_tests is False:
            return {
                "answer": "The strategy page indicates tests are not detected, so migration risk is higher and additional validation is recommended.",
                "rationale": ["The assessment section shows test coverage is missing or unavailable."],
                "cited_fields": ["assessment"],
                "confidence": 0.9,
                "follow_up_suggestions": [
                    "Ask for a safe test strategy before migration.",
                    "Ask what test coverage should be added first.",
                ],
            }

    if any(keyword in question_lower for keyword in ("roadmap", "plan", "step", "approach")):
        selected_conversions = strategy.get("selected_conversions") or []
        if selected_conversions:
            answer = "Current strategy selections: " + ", ".join(str(item) for item in selected_conversions[:5]) + "."
        else:
            answer = "The strategy page currently shows the migration path options, but no conversion choice is selected yet."
        return {
            "answer": answer,
            "rationale": ["This is derived from the strategy selection area on the page."],
            "cited_fields": ["strategy", "conversion_options"],
            "confidence": 0.8,
            "follow_up_suggestions": [
                "Ask which conversion option is currently active.",
                "Ask what the next migration step should be.",
            ],
        }

    if any(keyword in question_lower for keyword in ("risk", "overall", "assessment")):
        risk_level = assessment.get("risk_level") or "unknown"
        risk_reason = assessment.get("risk_reason")
        answer = f"The strategy page risk level is {str(risk_level).upper()}."
        if risk_reason:
            answer += f" {risk_reason}"
        return {
            "answer": answer,
            "rationale": ["This comes from the assessment summary shown on the strategy page."],
            "cited_fields": ["assessment"],
            "confidence": 0.88,
            "follow_up_suggestions": [
                "Ask why the risk level is set this way.",
                "Ask what would reduce the risk level.",
            ],
        }

    return None


def _build_strategy_fallback_v2(strategy_context: Dict[str, Any], question: str) -> Dict[str, Any]:
    assessment = strategy_context.get("assessment") if isinstance(strategy_context.get("assessment"), dict) else {}
    strategy = strategy_context.get("strategy") if isinstance(strategy_context.get("strategy"), dict) else {}
    recommendation = strategy_context.get("recommendation") if isinstance(strategy_context.get("recommendation"), dict) else {}
    destination = _strategy_destination_context(strategy_context)
    attention_dependencies = _strategy_list_of_dicts(strategy_context.get("attention_dependencies"))

    visible_fields: List[str] = []
    if assessment:
        visible_fields.append("risk level, build tool, Java version, tests, and dependency count")
    if strategy:
        visible_fields.append("selected source and target Java versions plus conversion choices")
    if recommendation:
        visible_fields.append("the current Java version recommendation")
    if destination:
        visible_fields.append("the migration destination")
    if attention_dependencies:
        visible_fields.append("dependencies that need attention")

    if not visible_fields:
        visible_fields.append("the current strategy page context")

    return {
        "answer": (
            "Here’s what the strategy page shows: "
            + "; ".join(visible_fields)
            + ". If your question asks for something not shown here, I can only answer from the current page context."
        ),
        "rationale": ["Fallback used because the LLM response was unavailable or invalid."],
        "cited_fields": list(strategy_context.keys())[:6] if isinstance(strategy_context, dict) else [],
        "confidence": None,
        "follow_up_suggestions": [
            "Ask about the risk summary, Java recommendation, or destination options.",
        ],
    }


def _build_strategy_stream_metadata(
    strategy_context: Dict[str, Any],
    intent: str,
    question: str,
) -> Dict[str, Any]:
    fallback = _build_strategy_fallback_v2(strategy_context, question)
    fallback["confidence"] = fallback.get("confidence")
    fallback["cited_fields"] = fallback.get("cited_fields") or []
    fallback["follow_up_suggestions"] = fallback.get("follow_up_suggestions") or []
    return fallback


async def _generate_strategy_answer(payload: StrategyQuery) -> Tuple[StrategyAnswer, Dict[str, Any], Dict[str, Any]]:
    question = (payload.question or "").strip()
    question_lower = question.lower()
    matched_template, match_score = match_question(question)
    intent = _infer_strategy_intent(question, matched_template)
    strategy_context_raw, context_source = _build_strategy_context(payload)
    strategy_context = _build_strategy_focus_context(strategy_context_raw, intent, question, matched_template)
    fingerprint = context_pack_fingerprint(strategy_context)
    comparison_table = _build_strategy_comparison_table(strategy_context_raw, question_lower)
    system_prompt, user_prompt = _build_strategy_prompts(strategy_context, question, intent, matched_template)
    cache_key = f"{intent}:{fingerprint}:{hashlib.sha256(question.encode('utf-8')).hexdigest()}"

    try:
        llm_result = await preferred_llm_service.request_json_groq(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=STRATEGY_LLM_MAX_TOKENS,
            temperature=0.05,
            cache_key=cache_key,
        )

        parsed_raw = llm_result.get("parsed") or {}
        parsed_norm, parsed_valid, parse_err = _normalize_strategy_parsed(parsed_raw, llm_result.get("text") or "")
        if not parsed_valid:
            logger.warning(
                "Strategy parsed JSON invalid for question '%s' provider=%s model=%s err=%s raw=%s",
                question,
                llm_result.get("provider"),
                llm_result.get("model"),
                parse_err,
                llm_result.get("text"),
            )

        details: Dict[str, Any] = {
            "provider": llm_result.get("provider"),
            "model": llm_result.get("model"),
            "usage": llm_result.get("usage"),
            "fingerprint": fingerprint,
            "context_source": context_source,
            "question_intent": intent,
            "matched_template_id": matched_template.get("id") if isinstance(matched_template, dict) else None,
            "matched_template_score": match_score,
            "parsed_valid": bool(parsed_valid),
            "parse_error": parse_err,
            "cited_fields": parsed_norm.get("cited_fields") or [],
            "follow_up_suggestions": parsed_norm.get("follow_up_suggestions") or [],
            "comparison_table": comparison_table,
        }

        return StrategyAnswer(
            answer=parsed_norm.get("answer") or "",
            rationale=parsed_norm.get("rationale") or [],
            details=details,
        ), parsed_norm, details
    except Exception as exc:
        logger.warning("Strategy Groq request failed, falling back to context summary: %s", exc)
        fallback_parsed = _build_strategy_fallback_v2(strategy_context_raw, question)
        details = {
            "fallback": True,
            "error": str(exc),
            "fingerprint": fingerprint,
            "context_source": context_source,
            "question_intent": intent,
            "matched_template_id": matched_template.get("id") if isinstance(matched_template, dict) else None,
            "matched_template_score": match_score,
            "cited_fields": fallback_parsed.get("cited_fields") or [],
            "follow_up_suggestions": fallback_parsed.get("follow_up_suggestions") or [],
            "comparison_table": comparison_table,
        }
        return StrategyAnswer(
            answer=fallback_parsed.get("answer") or "",
            rationale=fallback_parsed.get("rationale") or [],
            details=details,
        ), fallback_parsed, details


@router.post("/strategy/query", response_model=StrategyAnswer)
async def handle_strategy_query(payload: StrategyQuery):
    return (await _generate_strategy_answer(payload))[0]


def _sse_event(data: Dict[str, Any], event: Optional[str] = None) -> str:
    payload = json.dumps(data, default=str)
    if event:
        return f"event: {event}\n" + f"data: {payload}\n\n"
    return f"data: {payload}\n\n"


def _chunk_text(text: str, size: int = 28) -> List[str]:
    words = (text or "").split()
    if not words:
        return []
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and current_len + extra > size:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += extra
    if current:
        chunks.append(" ".join(current))
    return chunks


@router.post("/strategy/query/stream")
async def handle_strategy_query_stream(payload: StrategyQuery):
    async def stream_generator():
        question = (payload.question or "").strip()
        question_lower = question.lower()
        matched_template, match_score = match_question(question)
        intent = _infer_strategy_intent(question, matched_template)
        strategy_context_raw, context_source = _build_strategy_context(payload)
        strategy_context = _build_strategy_focus_context(strategy_context_raw, intent, question, matched_template)
        fingerprint = context_pack_fingerprint(strategy_context)
        comparison_table = _build_strategy_comparison_table(strategy_context_raw, question_lower)
        metadata = _build_strategy_stream_metadata(strategy_context_raw, intent, question)

        for message in ("Reading strategy page", "Using page context", "Preparing answer"):
            yield _sse_event({"phase": "phase", "message": message}, event="phase")
            await asyncio.sleep(0.06)

        provider = "groq"
        model = ""
        usage: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        collected_text = ""

        try:
            stream_system_prompt, stream_user_prompt = _build_strategy_stream_prompts(
                strategy_context,
                question,
                intent,
                matched_template,
            )
            cache_key = f"stream:{intent}:{fingerprint}:{hashlib.sha256(question.encode('utf-8')).hexdigest()}"
            async for event in preferred_llm_service.request_text_stream_groq(
                system_prompt=stream_system_prompt,
                user_prompt=stream_user_prompt,
                max_tokens=STRATEGY_LLM_MAX_TOKENS,
                temperature=0.1,
                cache_key=cache_key,
            ):
                event_type = event.get("type")
                if event_type == "provider":
                    provider = str(event.get("provider") or provider)
                    model = str(event.get("model") or model)
                elif event_type == "delta":
                    delta_text = event.get("text")
                    if isinstance(delta_text, str) and delta_text:
                        collected_text += delta_text
                        yield _sse_event({"chunk": delta_text}, event="chunk")
                elif event_type == "final":
                    provider = str(event.get("provider") or provider)
                    model = str(event.get("model") or model)
                    if isinstance(event.get("usage"), dict):
                        usage = event.get("usage")
                    # Prefer the complete text from the final event over partial collected_text
                    event_text = event.get("text")
                    if isinstance(event_text, str) and event_text.strip():
                        if len(event_text.strip()) >= len(collected_text.strip()):
                            collected_text = event_text

            final_answer = collected_text.strip() or metadata.get("answer") or ""
            parsed_payload = {
                "answer": final_answer,
                "rationale": metadata.get("rationale") or [],
                "confidence": metadata.get("confidence"),
                "cited_fields": metadata.get("cited_fields") or [],
                "follow_up_suggestions": metadata.get("follow_up_suggestions") or [],
            }
            details = {
                "provider": provider,
                "model": model,
                "usage": usage,
                "fingerprint": fingerprint,
                "context_source": context_source,
                "question_intent": intent,
                "matched_template_id": matched_template.get("id") if isinstance(matched_template, dict) else None,
                "matched_template_score": match_score,
                "cited_fields": parsed_payload.get("cited_fields") or [],
                "follow_up_suggestions": parsed_payload.get("follow_up_suggestions") or [],
                "comparison_table": comparison_table,
                "streaming": True,
            }
            yield _sse_event({"phase": "final", "parsed": parsed_payload, "details": details}, event="final")
        except Exception as exc:
            logger.warning("Strategy streaming request failed: %s — trying non-streaming LLM call", exc)
            # Try a non-streaming LLM call before resorting to heuristic fallback
            non_stream_answer = ""
            try:
                llm_result = await preferred_llm_service.request_text(
                    system_prompt=stream_system_prompt,
                    user_prompt=stream_user_prompt,
                    max_tokens=STRATEGY_LLM_MAX_TOKENS,
                    temperature=0.1,
                    cache_key=f"nonstream:{cache_key}",
                )
                non_stream_answer = (llm_result.get("text") or "").strip()
                provider = str(llm_result.get("provider") or provider)
                model = str(llm_result.get("model") or model)
                if isinstance(llm_result.get("usage"), dict):
                    usage = llm_result.get("usage")
                if non_stream_answer:
                    yield _sse_event({"chunk": non_stream_answer}, event="chunk")
            except Exception as llm_exc:
                logger.warning("Non-streaming LLM also failed: %s — using heuristic fallback", llm_exc)

            if non_stream_answer:
                final_answer = non_stream_answer
            elif collected_text.strip():
                final_answer = collected_text.strip()
            else:
                fallback = _build_strategy_fallback_v2(strategy_context_raw, question)
                final_answer = fallback.get("answer") or ""

            parsed_payload = {
                "answer": final_answer,
                "rationale": metadata.get("rationale") or [],
                "confidence": metadata.get("confidence"),
                "cited_fields": metadata.get("cited_fields") or [],
                "follow_up_suggestions": metadata.get("follow_up_suggestions") or [],
            }
            details = {
                "fallback": not bool(non_stream_answer),
                "error": str(exc),
                "fingerprint": fingerprint,
                "context_source": context_source,
                "question_intent": intent,
                "matched_template_id": matched_template.get("id") if isinstance(matched_template, dict) else None,
                "matched_template_score": match_score,
                "cited_fields": parsed_payload.get("cited_fields") or [],
                "follow_up_suggestions": parsed_payload.get("follow_up_suggestions") or [],
                "comparison_table": comparison_table,
                "streaming": True,
            }
            yield _sse_event({"phase": "final", "parsed": parsed_payload, "details": details}, event="final")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@router.post("/strategy/warmup")
async def handle_strategy_warmup(payload: StrategyQuery):
    """Trigger embeddings warmup for the provided analysis/context payload."""
    analysis = payload.analysis or {}
    try:
        context = build_repository_context_pack(
            repo_name=(analysis.get("name") or ""),
            repo_url=(payload.repo_url or ""),
            analysis_data=analysis,
            base_document=None,
        )
    except Exception:
        context = analysis or {}

    try:
        stats = await warmup_embeddings_and_persist(context, concurrency=6, persist=bool(payload.persist_embeddings))
        return {"status": "ok", "stats": stats}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/strategy/related")
async def handle_strategy_related(payload: Dict[str, Any]):
    """Return top related question templates for a given question text."""
    question = (payload.get("question") or "").strip()
    top_n = int(payload.get("top_n") or 5)
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    try:
        items = await match_top_n_semantic(question, n=top_n)
        return {"status": "ok", "related": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
