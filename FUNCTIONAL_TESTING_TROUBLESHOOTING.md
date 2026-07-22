# Functional Testing – Why It Fails, What It Needs, and What Has Been Done

**Component:** `JavaAPEX-Backend/services/functional_test_pipeline.py`
**Audience:** Developers / reviewers running the JavaAPEX migration + functional-test pipeline
**Last updated:** 13 July 2026

---

## 1. What the Functional Testing feature is supposed to do

The `FunctionalTestPipelineService` runs **after** a Java project is migrated. In one pass it:

1. **Profiles** the generated project (detects if it is a REST API, a JSP/Servlet web app, or a JavaScript SPA).
2. **Builds a functional test plan** (a structured list of scenarios per page/endpoint).
3. **Generates tool-specific test scripts**:
   - `REST_ASSURED` / `MOCK_MVC` → Java + Maven (`mvn test`)
   - `SELENIUM` → real browser UI tests
   - `PLAYWRIGHT` → JavaScript SPA UI tests (real browser + video/screenshots)
   - `SCHEMATHESIS` → API contract tests
4. **Tries to build and start the real application**, then **executes** the tests against it and collects reports, screenshots and videos.

> Key design principle (from the module docstring): *"Execution is intentionally best-effort so the migration pipeline can surface functional-testing readiness without making Docker/Podman mandatory for every user."*
> **That single sentence is the root cause of most "it didn't work" confusion:** when a required runtime is missing, the pipeline does **not** crash — it *silently degrades* to a lighter mode and reports `skipped` or `internal_validation`.

---

## 2. Why functional testing "does not work" — the real reasons

There is rarely a single bug. In almost every case the pipeline falls into one of the degraded paths below because a **prerequisite is missing** in the environment.

### 2.1 No container runtime (Docker / Podman)
- The browser-based runners (`PLAYWRIGHT`, `SELENIUM` grid, `SCHEMATHESIS`) and the Tomcat app-server are launched as **`docker run …`** commands.
- The code checks: `shutil.which("docker") or shutil.which("podman")`.
- **If neither is on `PATH`:**
  - Selenium escalation to a real browser (`auto → external`) is **cancelled** and it stays in static "internal validation" — so **no video, no screenshots** are ever produced. This is the exact symptom users report most often.
  - Playwright/Schemathesis container commands cannot run.

### 2.2 No JDK / Maven (for the real app + REST_ASSURED / MOCK_MVC)
- The app is started with `mvn … jetty:run` (or a Tomcat container) and REST/MockMvc tests run through **`mvn test`**.
- `mvn test` **downloads** RestAssured, JUnit, Hamcrest, etc. from Maven Central.
- **On a locked-down / offline network the download fails → the whole build fails → 0 tests pass**, even though the tests themselves are valid.
- Without a JDK the app never starts, so browser tests hit `ERR_CONNECTION_REFUSED`.

### 2.3 No Selenium / Playwright runtime installed
- Selenium needs either the Python `selenium` package importable **or** a container runtime.
- Playwright needs Node/npm + browser binaries (or the `mcr.microsoft.com/playwright` image).
- On locked-down Windows machines **Chrome is frequently absent** (the code deliberately prefers Edge for this reason), and browser-driver downloads are blocked.

### 2.4 The migrated code does not compile
- Migration frequently leaves **compile errors** in the generated project.
- The pipeline mitigates this by rebuilding the WAR from the **original** source (either via `original_source_path` or a `git clone --local` recovery of the pre-conversion commit).
- **If the original source is unavailable** (path was a URL like `https://…`/`git@…`, or the project is not a git repo), the real app cannot be built and everything falls back to source-level validation.

### 2.5 The LLM provider is offline / template-mode
- Plan enhancement and code generation call an LLM (`ford_llm` by default).
- If the provider is offline/template, the log shows `skipping LLM … (deterministic plan/templates used)`. Tests are still generated, but they are the deterministic templates rather than richer LLM-authored scenarios.

### 2.6 The app type "needs manual review"
- For unrecognised project shapes the pipeline returns status **`skipped`** with:
  *"Functional test execution skipped because the application type needs manual review."*

### 2.7 Result looks like "0 tests / skipped" or "internal_validation"
This is **not a crash** — it is the fallback path. It means one or more of 2.1–2.6 was true and the pipeline validated the generated cases against the **project source** (routes/endpoints/pages exist, status < 500) instead of driving a live browser.

---

## 3. What you need for functional testing to *fully* work

| # | Requirement | Needed for | How to verify |
|---|-------------|-----------|----------------|
| 1 | **Docker Desktop** or **Podman** on `PATH` | Playwright, Selenium grid, Schemathesis, Tomcat app server, real videos/screenshots | `docker --version` / `podman --version` |
| 2 | **JDK 11+** | Compiling & starting the migrated app | `java -version` |
| 3 | **Maven** on `PATH` | `mvn test` for REST_ASSURED / MOCK_MVC, `jetty:run` | `mvn -v` |
| 4 | **Network access to Maven Central** (or a local mirror) | Downloading test dependencies | `mvn dependency:resolve` succeeds |
| 5 | **Node.js + npm** and/or the Playwright container image | Playwright SPA tests | `npm -v`, `docker pull mcr.microsoft.com/playwright` |
| 6 | **A browser** (Edge preferred, Chrome optional) + drivers, OR the `selenium` Python package | Selenium UI tests | `python -c "import selenium"` |
| 7 | **Original (pre-migration) source** — via `original_source_path` **or** a committed git history | Rebuilding a clean WAR when migrated code doesn't compile | Path is a real local dir / `.git` exists |
| 8 | **A reachable LLM provider** (or accept template mode) | Richer generated scenarios | Provider health check |
| 9 | Free TCP port for the app + `4444` for Selenium grid | App startup, grid | Ports not in use / firewall allows |

### Recommended environment variables
- `FUNCTIONAL_TEST_SELENIUM_EXTERNAL=true` — force a **real browser** run (video + screenshots). Set to `false` to keep fast static validation.
- Provide `original_source_path` (a local directory, **not** an `http(s)://` / `git@` URL) so the WAR can be rebuilt cleanly.

---

## 4. What has been done so far to make it work (built-in mitigations)

The pipeline already contains several robustness features so it produces *something useful* even in constrained environments:

1. **Runtime auto-detection** – Detects `docker`/`podman`/`selenium` and only escalates to a real-browser run when a runtime actually exists, avoiding multi-minute hangs polling an app that will never start.
2. **`auto → external` Selenium escalation** – When Selenium is active **and** a runtime is available, execution mode is upgraded so a real browser runs and captures the E2E video + per-page screenshots (controlled by `FUNCTIONAL_TEST_SELENIUM_EXTERNAL`).
3. **Original-source WAR build + git recovery** – If migrated code doesn't compile, it rebuilds from `original_source_path`, or falls back to `git clone --local` to recover the pre-conversion code.
4. **Mock rescue for build-dependent tools** – When `mvn test` can't run (offline), REST_ASSURED / MOCK_MVC cases are validated against the project source so they report meaningful pass/fail instead of "0 tests".
5. **Reliability fallback to internal validation** – If the real app can't be built/started, every generated case is checked against routes/endpoints/pages (status < 500) so the user always gets a per-test pass/fail rather than a blank/skipped result.
6. **Authentic-report preservation** – If Playwright/Selenium *did* produce a real HTML report with at least one passing test (real videos/traces), that authentic report is always kept over the simulated fallback.
7. **Edge-first browser strategy** – Prefers Microsoft Edge because Chrome is often missing on locked-down Windows machines, and modernises deprecated JDK APIs in generated Selenium code.
8. **Deterministic templates when LLM is offline** – Generation continues with deterministic templates so a plan and scripts always exist.

---

## 5. How to diagnose your specific run

1. **Read the logs** – search for these markers in the backend log:
   - `no Selenium runtime is available` → install Docker/Podman or the `selenium` package (reason 2.1/2.3).
   - `Mock rescue:` / `real app unavailable` → app didn't build/start (reason 2.2/2.4).
   - `[FUNC-LLM] … skipping LLM` → LLM offline (reason 2.5).
   - `application type needs manual review` → unsupported project shape (reason 2.6).
2. **Check the result JSON** `status` / `execution_mode` field:
   - `external` = real run (best), `internal_validation` = source-level fallback, `skipped` = prerequisite missing.
3. **Confirm prerequisites** using the table in §3.
4. **Inspect** the `.functional_tests/` output directory in the project for generated scripts and any HTML report/videos.

---

## 6. Quick checklist to get a *full* (real-browser) run

- [ ] Install & start **Docker Desktop** (or Podman) — confirm `docker ps` works.
- [ ] Install **JDK 11+** and **Maven**; confirm `java -version` and `mvn -v`.
- [ ] Ensure **Maven Central** (or mirror) is reachable, or pre-populate `~/.m2`.
- [ ] For SPA tests: install **Node/npm** or pull `mcr.microsoft.com/playwright`.
- [ ] Provide a **local `original_source_path`** (not a URL) or ensure the project has git history.
- [ ] Set `FUNCTIONAL_TEST_SELENIUM_EXTERNAL=true`.
- [ ] Ensure the app port and `4444` are free and not firewalled.
- [ ] Re-run the pipeline and confirm the result `execution_mode` is `external`.

---

### Summary in one line
Functional testing "doesn't work" almost always because a **runtime prerequisite is missing** (Docker/Podman, JDK+Maven, browser/Node, network to Maven Central, or the original source). The pipeline is designed to **degrade gracefully** rather than fail — so a `skipped` / `internal_validation` result is the signal that one of the items in §3 needs to be provided.
