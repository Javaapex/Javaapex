# Migration Note — First-Class Velocity (.vm) Support & Loud Degradation

This change adds first-class Apache Velocity (`.vm`) support and makes runtime
degradation **loud and structured** in the functional-test pipeline
(`services/functional_test_pipeline.py`). All additions are **backward
compatible** — only new fields are added to the result/profile JSON; nothing
existing was removed or renamed.

## New / changed files

| File | Purpose |
|------|---------|
| `services/velocity_test_templates.py` | Pure, dependency-free module: `.vm` detection, controller-route mapping, template analysis, Layer 1 (JUnit 5 + Velocity + Jsoup) and Layer 2 (Selenium/Playwright) generators, and the `DEGRADATION_REASONS` map (2.1–2.6). |
| `services/functional_test_pipeline.py` | Wires the above into profiling, script rendering and execution; adds `degradation_reasons`. |
| `tests/test_velocity_support.py` | Unit tests for detection + generation + integration. |

## New result-JSON fields

### Application profile (`application-profile.json`)
- `frameworkSignals.velocity` *(bool)* — true when server-rendered `.vm`
  templates were detected.
- `frameworkSignals.hasUi` — now also true when Velocity templates exist.
- `velocityTemplates` *(array)* — each item: `{template, name, page_key,
  source_file, analysis}` where `analysis` = `{scalars, collections, loop_vars,
  has_if, has_foreach}`.
- `velocityRoutes` *(array)* — each template joined to the route that renders
  it (`{... , route}`). For legacy Front-Controller apps the route is the
  authentic runtime URL, e.g. `/MAPS?_page=ReportPage`; otherwise it is derived
  from `getTemplate("*.vm")` + `@*Mapping` / servlet `<url-pattern>`, falling
  back to `/<template-name>`.
- `applicationType` may now be `SERVER_RENDERED_WEB_APP` (previously such apps
  often fell into `MANUAL_REVIEW`).

### Execution result (returned by `execute_functional_tests`)
- `degradation_reasons` *(array, always present)* — structured records naming
  exactly which prerequisite was missing:
  `{code, reason, detail?}` with `code` in **2.1–2.6**:
  - **2.1** Container runtime (Docker/Podman) missing → no WAR-in-Tomcat.
  - **2.2** JDK + Maven toolchain missing → no JVM tests.
  - **2.3** Node.js/npm missing → no Playwright E2E.
  - **2.4** No browser/webdriver → no Selenium/Playwright E2E.
  - **2.5** Maven Central / mirror blocked → offline `go-offline` fallback used.
  - **2.6** Original source (WAR build inputs) missing → real app not started.
- `execution_mode` *(string, optional)* — e.g. `external`,
  `external (gradle_test)`, `internal_validation`. Interpret as: `external*`
  = real app was built/started and real runners executed; `internal_validation`
  = source-level checks only (a degradation reason will say why).
- A new runner entry with `tool: "VELOCITY_LAYER1"` (and `layer: 1`) is appended
  to `runners[]` whenever `.vm` templates exist. Its counts are folded into the
  top-level `tests_run/passed/failed`.

## Two Velocity test layers

- **Layer 1 — dependency-free render tests** (`.functional_tests/velocity/`):
  JUnit 5 + Velocity `VelocityEngine`/`VelocityContext` + Jsoup. Asserts:
  (a) no unresolved `$refs` / leaked `#directives`, (b) HTML well-formedness via
  Jsoup, (c) HTML-escaping/XSS safety, (d) both `#if/#else` branches, (e)
  empty/single/multi `#foreach` cases. **Always runs** — needs zero
  network/Docker/browser/original-source (only a JDK+Maven toolchain + the
  Velocity/Jsoup/JUnit jars, with an offline `go-offline` fallback on a blocked
  mirror).
- **Layer 2 — E2E** (`.functional_tests/velocity/e2e/`): Edge-first Selenium
  (and a Playwright spec) hitting each rendered route. **Only executes** when a
  runtime (app server + browser) is available; otherwise it degrades with reason
  2.1/2.4/2.6.

## How to verify a full external run end-to-end

1. Ensure prerequisites: Docker/Podman OR local JDK+Maven+Tomcat, Edge/Chrome +
   webdriver, and (for the real app) `original_source_path` pointing at a **local
   directory** (http(s):// and `git@` URLs are rejected with a clear
   `[DEGRADATION 2.6]` error).
2. Set `FUNCTIONAL_TEST_SELENIUM_EXTERNAL=true` and run with
   `execution_mode="external"`.
3. Confirm in the result JSON:
   - `execution_mode` starts with `external`,
   - `degradation_reasons` is **empty**,
   - a `VELOCITY_LAYER1` runner is present with `status: "passed"`,
   - Layer 2 runners executed (Selenium/Playwright) with real screenshots.
4. If any prerequisite is missing, the run still succeeds for Layer 1 and the
   `degradation_reasons[]` names exactly what to fix (loud log line
   `[DEGRADATION <code>] …`).

## Offline unit test run

```powershell
cd JavaAPEX-Backend
python -m unittest tests.test_velocity_support -v
```
