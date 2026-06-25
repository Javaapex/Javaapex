"""Validate Playwright test-count parsing (stdout + JUnit results.xml).

Reproduces the "EXECUTED: 1 / PASSED: 1" bug: a green Playwright run with 6
tests was falling through to the ``exit_code == 0 → return 1,1,0`` fallback in
``_parse_test_counts``. Confirms both the new stdout parser and the
authoritative ``results.xml`` parser report the correct totals.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load():
    spec = importlib.util.spec_from_file_location("ftp_counts", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_counts", mod)
    spec.loader.exec_module(mod)
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_parse_test_counts"):
            return obj
    raise RuntimeError("pipeline class not found")


PW_ALL_PASS = """
Running 6 tests using 1 worker

  ✓  1 functional.spec.ts:5:1 › GET /index.html renders (1.2s)
  ✓  2 functional.spec.ts:11:1 › index has content (0.6s)
  ✓  3 functional.spec.ts:18:1 › GET /status.jsp (0.5s)
  ✓  4 functional.spec.ts:24:1 › GET /CIRequest (0.5s)
  ✓  5 functional.spec.ts:30:1 › POST /CIRequest (0.4s)
  ✓  6 functional.spec.ts:36:1 › GET /health (0.4s)

  6 passed (5.1s)
"""

PW_WITH_FAILURE = """
Running 6 tests using 1 worker

  ✓  1 functional.spec.ts:5:1 › GET /index.html renders (1.2s)
  ✘  2 functional.spec.ts:11:1 › index has content (0.6s)

  1 failed
    functional.spec.ts:11:1 › index has content
  5 passed (5.1s)
"""

PW_DOT_REPORTER = """
......
  6 passed (4.8s)
"""

PW_WITH_SKIP = """
Running 5 tests using 1 worker

  2 skipped
  3 passed (2.1s)
"""

JUNIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites id="" name="" tests="6" failures="0" skipped="0" errors="0" time="5.1">
  <testsuite name="functional.spec.ts" timestamp="2026-06-24T08:00:00.000Z" hostname="localhost" tests="6" failures="0" skipped="0" time="5.1" errors="0">
    <testcase name="GET /index.html renders" classname="functional.spec.ts" time="1.2"/>
    <testcase name="index has content" classname="functional.spec.ts" time="0.6"/>
    <testcase name="GET /status.jsp" classname="functional.spec.ts" time="0.5"/>
    <testcase name="GET /CIRequest" classname="functional.spec.ts" time="0.5"/>
    <testcase name="POST /CIRequest" classname="functional.spec.ts" time="0.4"/>
    <testcase name="GET /health" classname="functional.spec.ts" time="0.4"/>
  </testsuite>
</testsuites>
"""

JUNIT_XML_WITH_FAIL = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="6" failures="1" skipped="1" errors="0" time="5.1">
  <testsuite name="functional.spec.ts" tests="6" failures="1" skipped="1" errors="0" time="5.1">
    <testcase name="a"/>
    <testcase name="b"><failure message="boom">boom</failure></testcase>
    <testcase name="c"><skipped/></testcase>
    <testcase name="d"/>
    <testcase name="e"/>
    <testcase name="f"/>
  </testsuite>
</testsuites>
"""


def main() -> int:
    cls = _load()
    inst = cls.__new__(cls)
    ok = True

    cases = [
        ("PW all pass (list reporter)", PW_ALL_PASS, 0, (6, 6, 0)),
        ("PW 1 fail / 5 pass", PW_WITH_FAILURE, 1, (6, 5, 1)),
        ("PW dot reporter (no header)", PW_DOT_REPORTER, 0, (6, 6, 0)),
        ("PW 2 skipped / 3 pass", PW_WITH_SKIP, 0, (5, 3, 0)),
    ]
    for label, out, ec, expected in cases:
        got = inst._parse_test_counts(out, ec)
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"[{status}] stdout {label}: got {got}, expected {expected}")

    # Regression guard: a generic non-Playwright success must still fall back to
    # the 1/1/0 behaviour (we did not break the existing contract).
    got = inst._parse_test_counts("Some build succeeded with no test summary", 0)
    status = "PASS" if got == (1, 1, 0) else "FAIL"
    if got != (1, 1, 0):
        ok = False
    print(f"[{status}] stdout generic-success fallback: got {got}, expected (1, 1, 0)")

    # ── JUnit results.xml (authoritative) ──────────────────────────────
    xml_cases = [
        ("results.xml all pass", JUNIT_XML, (6, 6, 0)),
        ("results.xml 1 fail / 1 skip", JUNIT_XML_WITH_FAIL, (6, 4, 1)),
    ]
    for label, xml, expected in xml_cases:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "results.xml"
            p.write_text(xml, encoding="utf-8")
            runner = {"tool": "PLAYWRIGHT", "executed": True, "status": "passed",
                      "tests_run": 1, "tests_passed": 1, "tests_failed": 0}
            inst._augment_runner_with_junit_xml(runner, p)
            got = (runner["tests_run"], runner["tests_passed"], runner["tests_failed"])
            status = "PASS" if got == expected else "FAIL"
            if got != expected:
                ok = False
            print(f"[{status}] {label}: got {got}, expected {expected} (status={runner['status']})")

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
