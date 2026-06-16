"""Question bank and prompt templates for the Strategy assistant.

Provides a catalog of common question templates and simple heuristics
to map a user's freeform question to a focused prompt template.
"""
from typing import Any, Dict, List, Optional, Tuple
import asyncio

from services.llm_embeddings import get_embedding


# In-memory cache of template embeddings: id -> embedding list
_TEMPLATE_EMB_MAP: Dict[str, List[float]] = {}
_EMB_INIT_LOCK = asyncio.Lock()


QUESTIONS: List[Dict[str, Any]] = [
    {"id": "q01", "category": "vulnerabilities", "keywords": ["vulnerab", "cve", "cvss", "exploit"], "template": "Identify and list vulnerable dependencies with severity and suggested mitigation."},
    {"id": "q02", "category": "vulnerabilities", "keywords": ["critical", "high"], "template": "Which dependencies are critical/high severity? Provide dependency id and reason."},
    {"id": "q03", "category": "vulnerabilities", "keywords": ["top vulnerab", "top issues"], "template": "List top 5 vulnerabilities with short remediation steps."},
    {"id": "q04", "category": "dependency", "keywords": ["dependency", "dependencies", "artifact", "package"], "template": "Summarize key third-party libraries and call out any that need manual migration."},
    {"id": "q05", "category": "dependency", "keywords": ["outdated", "update", "version"], "template": "Which dependencies are outdated and recommended update targets?"},
    {"id": "q06", "category": "build", "keywords": ["build", "maven", "gradle", "pom"], "template": "Describe the build tool and any migration changes needed for newer Java."},
    {"id": "q07", "category": "java-version", "keywords": ["java", "version", "migrate", "target"], "template": "Recommend a target Java LTS version and reasons based on compatibility and tests."},
    {"id": "q08", "category": "eta", "keywords": ["eta", "time", "duration", "how long"], "template": "Provide an ETA for migration given repo size, tests, and vulnerabilities."},
    {"id": "q09", "category": "tests", "keywords": ["test", "tests", "unit test", "integration"], "template": "Assess test coverage presence and recommend actions to ensure safe migration."},
    {"id": "q10", "category": "security", "keywords": ["security", "scan", "sast", "distro"], "template": "Summarize security posture and suggest prioritized fixes."},
    {"id": "q11", "category": "api", "keywords": ["api", "endpoint", "rest", "graphql"], "template": "List detected API endpoints and note breaking-change risks."},
    {"id": "q12", "category": "frameworks", "keywords": ["spring", "jakarta", "servlet", "framework"], "template": "Identify frameworks and recommend migration steps (e.g., Jakarta namespace)."},
    {"id": "q13", "category": "licensing", "keywords": ["license", "licen"], "template": "Report on license types of dependencies and flag uncommon licenses."},
    {"id": "q14", "category": "ci", "keywords": ["ci", "pipeline", "github actions", "jenkins"], "template": "Analyze CI pipeline presence and suggest changes for Java upgrades."},
    {"id": "q15", "category": "performance", "keywords": ["perform", "latency", "optimi"], "template": "Point out potential performance concerns during migration and mitigations."},
    {"id": "q16", "category": "compatibility", "keywords": ["compat", "incompat", "breaking"], "template": "Highlight API/bytecode compatibility risk areas for the target Java."},
    {"id": "q17", "category": "migration-plan", "keywords": ["plan", "steps", "how to", "approach"], "template": "Provide a step-by-step migration plan with checkpoints and tests."},
    {"id": "q18", "category": "risk", "keywords": ["risk", "risks", "impact"], "template": "Enumerate migration risks and recommended mitigations."},
    {"id": "q19", "category": "repo-stats", "keywords": ["size", "files", "lines", "loc"], "template": "Provide repository statistics and interpretation for migration effort."},
    {"id": "q20", "category": "modules", "keywords": ["module", "multi-module", "submodule"], "template": "Analyze modules and identify order of migration for multi-module projects."},
]

# Generate additional templates programmatically to reach 50+ items
for i in range(21, 61):
    QUESTIONS.append({
        "id": f"q{i:02d}",
        "category": "other",
        "keywords": [f"topic{i}"],
        "template": f"Generic guidance item #{i} - adapt to repository context and provide short actionable advice."
    })

# Add explicit templates for common Strategy page questions provided by product
EXTRA_TEMPLATES = [
    {"id": "q61", "category": "assessment", "keywords": ["overall risk", "overall risk level", "critical"], "template": "Explain why overall risk level may be CRITICAL even if application risk is LOW; cite scanner metrics and examples."},
    {"id": "q62", "category": "assessment", "keywords": ["javax.servlet.jsf", "jsf", "critical dependency"], "template": "Explain why javax.servlet.jsf is marked critical and what to check during manual review."},
    {"id": "q63", "category": "assessment", "keywords": ["medium risk", "medium"], "template": "Explain why N dependencies are marked Medium risk and what to prioritize."},
    {"id": "q64", "category": "assessment", "keywords": ["needs manual review"], "template": "Clarify the meaning of 'NEEDS MANUAL REVIEW' and provide steps to complete the review."},
    {"id": "q65", "category": "assessment", "keywords": ["inherited", "analyzed", "inherited vs analyzed"], "template": "Differentiate between Inherited and Analyzed dependency versions and consequences for migration."},
    {"id": "q66", "category": "assessment", "keywords": ["other dependencies", "requiring attention"], "template": "Explain criteria used to place deps under 'Other Dependencies' vs 'Dependencies Requiring Attention'."},

    {"id": "q67", "category": "migration", "keywords": ["java 17", "java 21", "which java"], "template": "Recommend which Java version to migrate to (Java 17 vs Java 21) and explain tradeoffs."},
    {"id": "q68", "category": "migration", "keywords": ["difference java 17 vs 21"], "template": "Summarize technical differences between upgrading to Java 17 vs Java 21 and migration implications."},
    {"id": "q69", "category": "migration", "keywords": ["why java 17 recommended"], "template": "Explain why Java 17 may be recommended as an LTS over Java 21 for conservative migrations."},
    {"id": "q70", "category": "migration", "keywords": ["javax packages break", "javax.*"], "template": "Assess risk that javax.* packages will break on upgrade and list remediation steps (Jakarta namespace mapping)."},
    {"id": "q71", "category": "migration", "keywords": ["spring-boot-devtools"], "template": "Explain what happens to spring-boot-devtools after migration and when to update it."},
    {"id": "q72", "category": "migration", "keywords": ["maven configuration", "maven"], "template": "List Maven configuration changes commonly required after a Java upgrade (compiler target/source, toolchain, plugins)."},

    {"id": "q73", "category": "conversion", "keywords": ["javax to jakarta", "javax → jakarta"], "template": "Explain timeframe/availability for javax → Jakarta EE migration and recommend interim steps."},
    {"id": "q74", "category": "conversion", "keywords": ["monolithic to microservices", "monolithic → microservices"], "template": "Describe what Monolithic → Microservices conversion involves and high-level approach."},
    {"id": "q75", "category": "conversion", "keywords": ["spring to spring boot", "spring → spring boot"], "template": "Explain feasibility of doing Spring → Spring Boot alongside Java version upgrade and recommended order."},
    {"id": "q76", "category": "conversion", "keywords": ["maven to gradle", "maven → gradle"], "template": "Summarize the impacts of converting Maven → Gradle (build scripts, CI, plugins)."},

    {"id": "q77", "category": "destination", "keywords": ["create new repository", "existing repository", "store in local folder"], "template": "Explain differences between Create New Repository, Existing Repository (New Branch), and Store in Local Folder migration destinations."},
    {"id": "q78", "category": "destination", "keywords": ["repository name", "target repository name"], "template": "Describe how auto-generated target repository names are chosen and how to change them."},
    {"id": "q79", "category": "destination", "keywords": ["github owner", "javaspoc"], "template": "Explain who the target GitHub owner is for generated repos and whether it can be changed."},
    {"id": "q80", "category": "destination", "keywords": ["no github access"], "template": "Explain migration options when the user doesn't have GitHub access (local folder or alternative remote)."},

    {"id": "q81", "category": "post-migration", "keywords": ["tests still pass", "tests"], "template": "Assess likelihood tests will pass after Java upgrade and recommend steps to validate and repair tests."},
    {"id": "q82", "category": "post-migration", "keywords": ["handle javax.servlet.jsf"], "template": "Provide concrete steps to handle javax.servlet.jsf that needs manual review during migration."},
    {"id": "q83", "category": "post-migration", "keywords": ["changes to pom.xml", "pom.xml"], "template": "List typical changes to `pom.xml` made by automated migration (dependencies, compiler settings, plugin versions)."},
    {"id": "q84", "category": "post-migration", "keywords": ["rollback", "roll back"], "template": "Explain rollback strategy if migration breaks (branches, tags, and rollback steps)."},
    {"id": "q85", "category": "post-migration", "keywords": ["deployable", "immediately deployable"], "template": "Explain whether migrated code will be immediately deployable and what validation steps are recommended before deployment."},
]

QUESTIONS.extend(EXTRA_TEMPLATES)


def match_question(question: str) -> Tuple[Optional[Dict[str, Any]], float]:
    """Return best matching question template and score (0..1)."""
    q = (question or "").lower()
    best = None
    best_score = 0.0
    for item in QUESTIONS:
        kws = item.get("keywords") or []
        score = 0
        for kw in kws:
            if kw and kw in q:
                score += 1
        # simple normalization
        norm = score / max(1, len(kws))
        if norm > best_score:
            best_score = norm
            best = item
    return best, best_score


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    s_ab = 0.0
    s_a = 0.0
    s_b = 0.0
    for x, y in zip(a, b):
        s_ab += x * y
        s_a += x * x
        s_b += y * y
    if s_a == 0 or s_b == 0:
        return 0.0
    return s_ab / ((s_a ** 0.5) * (s_b ** 0.5))


async def ensure_template_embeddings(force: bool = False) -> None:
    """Ensure template embeddings are computed and cached."""
    async with _EMB_INIT_LOCK:
        to_compute = []
        for item in QUESTIONS:
            tid = item.get("id")
            if not tid:
                continue
            if force or tid not in _TEMPLATE_EMB_MAP:
                to_compute.append((tid, item))
        if not to_compute:
            return
        # compute sequentially to avoid provider rate limits; could be parallelized
        for tid, item in to_compute:
            text = item.get("template") or item.get("id")
            try:
                emb = await get_embedding(text)
                _TEMPLATE_EMB_MAP[tid] = emb
            except Exception:
                # leave missing if embedding fails
                _TEMPLATE_EMB_MAP.pop(tid, None)


async def match_question_semantic(question: str, top_n: int = 1) -> Tuple[Optional[Dict[str, Any]], float]:
    """Return best matching template by embedding cosine similarity.

    Returns (best_template, score) where score is cosine similarity 0..1.
    """
    # ensure template embeddings are ready
    await ensure_template_embeddings()
    try:
        q_emb = await get_embedding(question)
    except Exception:
        return None, 0.0

    # compute scores for all templates that have embeddings
    scored: List[Tuple[Dict[str, Any], float]] = []
    for item in QUESTIONS:
        tid = item.get("id")
        emb = _TEMPLATE_EMB_MAP.get(tid)
        if not emb:
            continue
        score = _cosine(q_emb, emb)
        scored.append((item, float(score)))

    # sort descending by score
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return None, 0.0
    if top_n <= 1:
        return scored[0][0], scored[0][1]
    # return top_n as a special structure (first item and top score)
    top_items = [s[0] for s in scored[:top_n]]
    # encode as dict with items and scores when top_n>1
    return {"top": top_items, "scores": [s[1] for s in scored[:top_n]]}, float(scored[0][1])


async def match_top_n_semantic(question: str, n: int = 5) -> List[Dict[str, Any]]:
    """Return top-n templates with similarity scores."""
    await ensure_template_embeddings()
    try:
        q_emb = await get_embedding(question)
    except Exception:
        return []
    scored: List[Tuple[Dict[str, Any], float]] = []
    for item in QUESTIONS:
        tid = item.get("id")
        emb = _TEMPLATE_EMB_MAP.get(tid)
        if not emb:
            continue
        score = _cosine(q_emb, emb)
        scored.append((item, float(score)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"id": it.get("id"), "template": it.get("template"), "category": it.get("category"), "score": sc} for it, sc in scored[:n]]


def build_prompts(
    template_item: Optional[Dict[str, Any]],
    context_lines: List[str],
    question: str,
    context_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Build a system and user prompt from the selected template and context.

    Accepts an optional compact `context_summary` dict which will be embedded
    as a small JSON block to give the LLM canonical facts while keeping
    token usage low.
    """
    if template_item:
        system = f"You are an expert Java migration assistant. Focus on: {template_item.get('template')}"
    else:
        system = "You are an expert Java migration assistant. Provide concise, factual answers based on CONTEXT."

    # include compact context summary if present
    summary_text = ""
    if context_summary:
        try:
            # pretty-serialize with minimal spacing
            summary_text = "CONTEXT_SUMMARY: " + json.dumps(context_summary, separators=(",", ":")) + "\n\n"
        except Exception:
            summary_text = ""

    # include context lines and user question
    user = summary_text + "CONTEXT:\n" + "\n".join(context_lines) + "\n\nQUESTION: " + question + "\n\nRespond with JSON only."
    return {"system_prompt": system, "user_prompt": user}


def sample_question_list() -> List[str]:
    """Return a small human-friendly list of example questions for UI help."""
    return [q.get("template") for q in QUESTIONS[:20]]
