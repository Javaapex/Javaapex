# RAG-based Strategy Prompting — Plan & Prompt Guide

This document describes a practical, phased plan to implement Retrieval-Augmented Generation (RAG) for the Strategy assistant used on the Strategy page. It includes implementation phases, timelines, concrete prompt templates, expected LLM response schema, retrieval guidance, caching and fingerprinting, UI notes, and rollout checklist.

---

## Goals
- Deliver high-quality, grounded answers about vulnerabilities, Java version recommendations, migration ETA, remediation steps, and repository-specific findings.
- Minimize hallucinations by feeding the LLM a curated context pack (RAG).
- Control cost and latency using caching, fingerprinting, and selective retrieval.
- Provide provenance/evidence to increase user trust.

---

## High-level architecture
- Context Pack Builder — server: `services/llm_context_service.build_repository_context_pack(...)`
- Retriever — server: select top-K facts from the context pack relevant to the question (vulns, deps, sample files)
- Prompt Templates & Few-shot examples — server: structured system/user/instruction roles
- Provider wrapper — server: `preferred_llm_service` or existing provider adapters
- Cache & Fingerprint — cache responses keyed by `(context_fingerprint, question_hash)`
- Frontend — streaming UI (SSE) and conversation history; evidence viewer

---

## Phase 1 — Proof of concept (1–2 days)
Purpose: validate the RAG flow with a single LLM call, minimal infra, and caching.

Tasks:
- Build context pack: call `build_repository_context_pack` passing repo analysis returned by the existing analyzers.
- Compute fingerprint: use `context_pack_fingerprint(context)`.
- Create prompt templates (system + instruction + user question) that request a structured JSON response (see schema below).
- Implement a provider adapter that calls `preferred_llm_service` or `openai_recommendation_service` with the prompt (single-turn, no streaming).
- Add a simple in-memory or file-based cache keyed by `(fingerprint, sha256(question))` with short TTL (e.g., 24 hours).
- Wire backend router `strategy_prompt_router` to call the new RAG handler, falling back to the current heuristic function on errors.
- Frontend: reuse existing chat widget to send question and display the structured answer. Show a small provenance panel listing which context items were referenced.

Acceptance criteria:
- Strategy page questions return grounded, well-structured answers in JSON.
- Responses include `answer`, `rationale[]`, and `evidence[]` (ids referencing context pack).

Estimated effort: 8–16 hours.

---

## Phase 2 — Robust RAG + Provenance + Streaming (3–5 days)
Purpose: improve relevance by retrieving top-K facts, add provenance and streaming UX.

Tasks:
- Implement Retriever:
  - Index the context pack into a simple vector store (optional for POC) or implement a lightweight relevance scorer by keyword overlap and metadata.
  - For each question, compute relevance and pick top-K facts (e.g., top 5 vulnerabilities, top 5 dependency signatures, 2–3 file snippets).
- Prompt engineering:
  - Insert selected top-K facts into prompt under a labeled `CONTEXT` block.
  - Use few-shot examples for common question types (vuln, java-version, ETA, remediation) — see templates below.
- Provenance:
  - Instruct the LLM to return `evidence[]` containing references like `dependency:log4j:2.14.1` or `file:/src/main/java/com/example/Foo.java:lines 10-20`.
  - Display evidence in the UI with snippets and links to repository files.
- Streaming:
  - Add SSE (Server-Sent Events) or provider streaming to stream partial assistant outputs to the frontend chat widget.
  - On the backend, stream tokens or partial JSON fragments if supported by the provider; otherwise emulate streaming by progressively revealing the final response.
- Caching & TTL:
  - Use Redis (recommended) or file/DB cache keyed by `(fingerprint, question_hash)`.
  - Add cache invalidation strategy: invalidate when repo analysis fingerprint changes (new commit or reanalysis).

Acceptance criteria:
- UI shows streaming assistant replies.
- Users can expand evidence items and see the supporting facts used.
- Retries/fallbacks in provider errors return graceful heuristic outputs.

Estimated effort: 24–40 hours.

---

## Phase 3 — Production hardening (2–4 weeks)
Purpose: make system secure, robust, cost-controlled, and observable.

Tasks:
- Rate limiting: implement per-user and global rate limits for LLM calls.
- Token accounting & billing: log token usage per request and expose dashboard/alerts for budgets.
- Provider A/B & failover: implement configurable provider priority and automatic failover.
- Audit logging: store question, fingerprint, provider response, latency, and user feedback for QA.
- Monitoring & alerting: latency, error rate, cost anomalies.
- Unit/integration tests: prompt templates, retriever logic, caching behavior.
- Security review: ensure context packs don't include secrets or tokens; redact sensitive values.
- Deployment: CI, secrets management (vault), scaling (Redis, worker pool), and backup.

Acceptance criteria:
- Production-grade reliability, controlled cost, and observability.

Estimated effort: 2–4 weeks (80–160 hours) depending on scope.

---

## Prompt templates and examples

Design considerations:
- Keep `CONTEXT` short and label each piece with an `id` used in `evidence[]`.
- Ask for structured output (JSON) with explicit fields and short textual `answer` plus `rationale[]` and `evidence[]`.
- Provide a maximum tokens budget and instruct the model to be concise.

System prompt (base):
```
You are a developer assistant specialized in Java migration analysis. Use the supplied CONTEXT to answer repository-specific questions. Always provide a concise answer and a structured JSON object with these keys: answer (short), rationale (array of short bullet points), evidence (array of context ids and short notes). If you cannot find evidence in CONTEXT, say so and give a conservative fallback recommendation.
Be concise and avoid hallucination. Prefer to say "I don't know" rather than invent facts.
``` 

User prompt (example injection):
```
CONTEXT:
1) dependency:org.apache.logging.log4j:log4j:2.14.1 (vulnerable CVE-xxxx-xxxx) - reason: remote code execution; suggested fix: upgrade to 2.17.1
2) dependency:javax.servlet:javax.servlet-api:3.1.0 - reason: uses javax.servlet API (Jakarta rename needed for Java 17+ in some frameworks)
3) file:/src/main/java/com/example/Service.java (lines 12-48) - uses HttpServlet and javax.servlet imports

QUESTION: Why is Java 17 recommended for this project? Please explain concisely and list key facts from CONTEXT that support this recommendation.
```

Expected structured response (JSON):
```
{
  "answer": "Recommend upgrading to Java 17 due to platform LTS and compatibility with modern libraries.",
  "rationale": ["Detected project currently uses Java 11","Dependency set is small and many dependencies are compatible with Java 17","Fewer breaking API changes between 11 and 17"],
  "evidence": [
    {"id":"dependency:org.apache.logging.log4j:log4j:2.14.1","note":"vulnerable dependency to be upgraded"},
    {"id":"file:/src/main/java/com/example/Service.java","note":"uses javax.servlet - needs Jakarta consideration"}
  ]
}
```

Few-shot examples (vulnerabilities): include 2–3 miniature examples in the prompt showing how to summarize vulnerability counts, severity, and top-3 remediations.

---

## Response JSON schema (recommended)
- `answer`: string — short human-readable summary (≤ 200 chars)
- `rationale`: string[] — 2–6 short bullets explaining reasoning
- `evidence`: array of { id: string, note?: string, score?: number }
- optional: `estimated_hours`: number — when question asks ETA
- optional: `confidence`: "low" | "medium" | "high"

---

## Retriever & evidence selection guidance
- Prioritize: vulnerable_dependencies (severity desc), dependency signatures, build files (pom/gradle), detected frameworks, sample code snippets that reference problematic APIs, sonar hotspots.
- Evidence items should carry `id` strings and short `summary` used for provenance in the UI.
- For large code snippets, include only small excerpts (≤ 200 tokens) and a link/path to full file in the repo viewer.

---

## Caching and fingerprinting
- Compute `context_fingerprint = context_pack_fingerprint(context)`.
- Cache keyed by `sha256(question) + ':' + context_fingerprint`.
- Short TTL for interactive answers (24h) and invalidation on new analysis fingerprint.

---

## Frontend UX recommendations
- Stream responses progressively (SSE) if available.
- Show `answer` immediately, and allow expanding `rationale` and `evidence`.
- Provide a provenance panel showing which `evidence` items were used and links to files/CVEs.
- Allow user feedback (thumbs up/down) to collect corrections for prompt tuning.

---

## Testing & tuning
- Create a set of 20 representative questions and expected outputs for each repo type (Spring, Jakarta, plain Servlets, Gradle, Maven).
- Measure: factual accuracy (provenance matches context), response time, token usage.
- Iterate on few-shot examples and retrieval heuristics based on failure cases.

---

## Rollout checklist
- Phase 1 validated in staging with internal users.
- Observe token usage and tune context packing to fit budget.
- Enable caching and monitor cache hit rate.
- Add telemetry for errors and low-confidence answers.

---

If you'd like, I can implement Phase 1 now (create server handler that builds context pack, calls `preferred_llm_service`, caches results, and returns structured JSON). Tell me which LLM provider you prefer to prioritize (OpenAI, Anthropic/Claude, Hugging Face / Groq, or Ollama/local), and I will begin implementing.
