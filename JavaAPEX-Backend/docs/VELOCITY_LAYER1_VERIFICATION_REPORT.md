# Velocity Layer 1 - Verification Report

_Environment: locked-down corporate Windows 11, PowerShell 5.1, user `KARUNAC4`._

## Toolchain versions (Step 1-3)

| Tool | Result |
|------|--------|
| JDK  | **Temurin (Eclipse Adoptium) 21.0.10+7 LTS** - already installed |
| Maven| **Apache Maven 3.9.9** (home `C:\tools\apache-maven-3.9.9`) |

Both already exceed the JDK 11+ requirement, so **install steps 2-3 were skipped**
(the fallback chain in `setup_and_verify.ps1` is present and idempotent for boxes
that lack them).

## Maven Central reachability (Step 4)

**NOT reachable.** `mvn dependency:resolve` failed with:

```
Could not transfer artifact org.apache.velocity:velocity-engine-core:pom:2.3
from/to central (https://repo.maven.apache.org/maven2): No such host is known
(repo.maven.apache.org)
```

- The local cache `%USERPROFILE%\.m2\repository` held **only** `*.pom.lastUpdated`
  failure markers for `velocity-engine-core:2.3` and `jsoup:1.17.2` - i.e. it was
  **not warmed**, so `mvn -o` (offline) also fails.
- This is degradation **reason 2.2** in spirit ("Maven Central unreachable"). Note:
  the pipeline's own code (`_run_velocity_layer1`) classifies a blocked-central +
  `go-offline` retry as **reason 2.5**, and reserves **2.2** for a *missing mvn
  executable*. Report uses the pipeline's actual codes.
- Remediation delivered: `docs/ford-nexus-settings.xml` (placeholder mirror) and
  `docs/VELOCITY_LAYER1_OFFLINE_RUNBOOK.md` (warm `~/.m2` on a connected box).

## Layer 1 `mvn test` results (Step 5)

**Could not compile/run in this environment** - dependency resolution fails before
compilation because Central is firewalled and the cache is empty. This is a genuine
environmental blocker, reported per the "stop if impossible" rule.

What *was* verified:
- The real generators (`render_layer1_junit`, `render_layer1_pom`) produce a
  well-formed Maven project + Java source (via `scripts/velocity_layer1_gen_harness.py`).
- The 11 existing Python unit tests (`tests/test_velocity_support.py`) still pass:
  `Ran 11 tests ... OK`.

## Generator finding (Step 6) - recommended fix, COMPILE-UNVERIFIED

Root-cause gap found in `services/velocity_test_templates.py` `render_layer1_junit`:
the generated `engine()` registers **no HTML escaping**, and the POM does **not**
include `velocity-tools`. Consequently, for any realistic template with scalar
variables, the two assertions are jointly **unsatisfiable**:

- Plain `$title` template -> XSS test fails (raw payload leaks into HTML).
- `$esc.html($title)` template -> `templatesRenderCleanly` fails (leftover `$esc`
  reference, since no `esc` tool is registered). `analyze_template` even mis-detects
  `esc` as a scalar.

**Recommended fix (register Velocity's `EscapeHtmlReference` on the context via an
`EventCartridge`)** - to be applied in the generator, then re-run `mvn test` on a
warmed machine:

```java
// add imports
import org.apache.velocity.app.event.EventCartridge;
import org.apache.velocity.app.event.implement.EscapeHtmlReference;

// in context(TemplateSpec ...), before `return ctx;`
EventCartridge ec = new EventCartridge();
ec.addReferenceInsertionEventHandler(new EscapeHtmlReference()); // escapes all refs
ec.attachToContext(ctx);
```

This is **not applied** in code because it cannot be compile/`mvn test`-verified in
this firewalled environment, and the task forbids claiming an unverified fix as
"green." Apply + verify on a machine with a warmed `~/.m2` (see runbook), then
re-run the 11 Python unit tests to confirm no regression.

## Full external run (Step 7)

**Not achievable here.** An `external` run with an **empty** `degradation_reasons[]`
requires Layer 1 to actually run, which requires resolvable Maven deps. While Central
is blocked and the cache is empty, Layer 1 degrades (reason 2.5), so
`degradation_reasons[]` cannot be empty. Re-attempt after warming `~/.m2`.

## Deliverables

| # | Deliverable | Location |
|---|-------------|----------|
| 1 | Idempotent PowerShell script (steps 1-5, fallback chain, `[STEP]/[OK]/[FAIL]`) | `scripts/setup_and_verify.ps1` (parses clean) |
| 2 | Generator gen harness (drives real generators to a compilable project) | `scripts/velocity_layer1_gen_harness.py` |
| 3 | Ford Nexus `settings.xml` template (placeholder mirror) | `docs/ford-nexus-settings.xml` |
| 4 | Offline `~/.m2` warming runbook | `docs/VELOCITY_LAYER1_OFFLINE_RUNBOOK.md` |
| 5 | Recommended generator diff (unverified) | this report, Step 6 |

## Self-review checklist

- [x] Step 1 toolchain detection - JDK 21 + Maven 3.9.9 found.
- [x] Step 2-3 install - correctly skipped; no-admin fallback chain implemented.
- [x] Step 4 Central reachability - measured (blocked); mirror template + runbook produced.
- [~] Step 5 `mvn test` - blocked by firewall + empty cache (reported, not faked).
- [~] Step 6 generator fix - real gap identified + concrete diff; not applied because unverifiable here.
- [~] Step 7 external run - blocked by same dependency issue; documented.
- [x] No assertions weakened; no unverified success claimed.
- [x] Existing 11 Python unit tests still green.

## Could NOT be verified in this environment

- Java compilation / `mvn test` of the generated Layer 1 project (Maven Central blocked, cache empty).
- The recommended `EscapeHtmlReference` generator fix (needs a live `mvn test`).
- Layer 2 real-browser (Edge/Selenium/Playwright) runs.
- A full `external` pipeline run with empty `degradation_reasons[]`.
