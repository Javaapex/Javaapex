"""Regression test for the "SELENIUM PASSED (0/11 passed)" status bug.

Because the Selenium pom sets <testFailureIgnore>true</testFailureIgnore> (so one
failing page never aborts the whole run), Maven exits 0 even when every test
ERRORS — e.g. all 11 tests hit net::ERR_CONNECTION_REFUSED because the app was
unreachable. The old code derived the runner status purely from the exit code, so
an all-errored run was mislabeled "passed" with 0/11 passing.

This verifies ``_enhance_selenium_result`` now:
  * reads the authoritative surefire TEST-*.xml for exact counts, and
  * derives status from the COUNTS (fail when any test failed/errored, or when 0
    tests ran) — never from Maven's (testFailureIgnore-masked) exit code.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load():
    spec = importlib.util.spec_from_file_location("ftp_isolated_sel_status", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_isolated_sel_status", mod)
    spec.loader.exec_module(mod)
    return mod


def _surefire_xml(tests: int, failures: int, errors: int, skipped: int = 0) -> str:
    cases = []
    remaining_err = errors
    remaining_fail = failures
    for i in range(tests):
        if remaining_err > 0:
            cases.append(
                f'  <testcase name="t{i}" classname="GeneratedSeleniumFunctionalTest" time="1.0">'
                f'<error message="unknown error: net::ERR_CONNECTION_REFUSED">stack</error></testcase>'
            )
            remaining_err -= 1
        elif remaining_fail > 0:
            cases.append(
                f'  <testcase name="t{i}" classname="GeneratedSeleniumFunctionalTest" time="1.0">'
                f'<failure message="assertion">stack</failure></testcase>'
            )
            remaining_fail -= 1
        else:
            cases.append(
                f'  <testcase name="t{i}" classname="GeneratedSeleniumFunctionalTest" time="1.0"/>'
            )
    body = "\n".join(cases)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="GeneratedSeleniumFunctionalTest" tests="{tests}" '
        f'failures="{failures}" errors="{errors}" skipped="{skipped}" time="10.0">\n'
        f'{body}\n</testsuite>\n'
    )


def check(cond, ok, bad, failures):
    print(f"  {'PASS' if cond else 'FAIL'}: {ok if cond else bad}")
    if not cond:
        failures.append(bad)


def _make_runner(cls, xml_content, exit_code, output):
    inst = cls.__new__(cls)
    test_dir = Path(tempfile.mkdtemp()) / "selenium"
    sd = test_dir / "target" / "surefire-reports"
    sd.mkdir(parents=True, exist_ok=True)
    if xml_content is not None:
        (sd / "TEST-GeneratedSeleniumFunctionalTest.xml").write_text(xml_content, encoding="utf-8")
    # Simulate _runner_from_command: status derived from exit_code (0 -> passed).
    runner = {
        "tool": "SELENIUM", "executed": True,
        "status": "passed" if exit_code == 0 else "failed",
        "exit_code": exit_code, "output": output,
    }
    inst._enhance_selenium_result(runner, test_dir)
    return runner


def main() -> int:
    mod = _load()
    cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_enhance_selenium_result"):
            cls = obj
            break
    if cls is None:
        print("FAIL: class not found")
        return 1
    print(f"Using pipeline class: {cls.__name__}\n")
    failures = []

    # 1) The reported bug: 11 tests, all ERROR, Maven exit 0 (testFailureIgnore).
    print("[1] 11 errors, Maven exit 0 (testFailureIgnore) — the reported bug:")
    r = _make_runner(cls, _surefire_xml(11, 0, 11), exit_code=0,
                     output="Tests run: 11, Failures: 0, Errors: 11 - in GeneratedSeleniumFunctionalTest\nBUILD SUCCESS")
    check(r.get("tests_run") == 11, "tests_run=11", f"tests_run={r.get('tests_run')}", failures)
    check(r.get("tests_passed") == 0, "tests_passed=0", f"tests_passed={r.get('tests_passed')}", failures)
    check(r.get("tests_failed") == 11, "tests_failed=11", f"tests_failed={r.get('tests_failed')}", failures)
    check(r.get("status") == "failed",
          "status=failed (NOT the misleading 'passed')",
          f"status={r.get('status')} — regression!", failures)

    # 2) All green run stays passed.
    print("\n[2] 11 tests, all pass, exit 0:")
    r = _make_runner(cls, _surefire_xml(11, 0, 0), exit_code=0,
                     output="Tests run: 11, Failures: 0, Errors: 0\nBUILD SUCCESS")
    check(r.get("tests_passed") == 11 and r.get("status") == "passed",
          "status=passed with 11/11", f"status={r.get('status')} passed={r.get('tests_passed')}", failures)

    # 3) Mixed: 8 pass, 3 fail -> failed.
    print("\n[3] 11 tests, 3 failed, exit 0 (testFailureIgnore):")
    r = _make_runner(cls, _surefire_xml(11, 3, 0), exit_code=0,
                     output="Tests run: 11, Failures: 3, Errors: 0")
    check(r.get("tests_failed") == 3 and r.get("status") == "failed",
          "status=failed with 8/11 passing", f"status={r.get('status')} failed={r.get('tests_failed')}", failures)

    # 4) Build/compile failure: no XML, non-zero exit, 0 tests -> failed.
    print("\n[4] compile failure, no surefire XML, exit 1:")
    r = _make_runner(cls, None, exit_code=1, output="COMPILATION ERROR : cannot find symbol")
    check(r.get("status") == "failed",
          "status=failed when 0 tests ran and build failed",
          f"status={r.get('status')}", failures)

    # 5) No XML but stdout summary present (fallback path) with errors, exit 0.
    print("\n[5] no XML, stdout summary shows errors, exit 0:")
    r = _make_runner(cls, None, exit_code=0,
                     output="Tests run: 5, Failures: 0, Errors: 5 - in GeneratedSeleniumFunctionalTest")
    check(r.get("tests_run") == 5 and r.get("tests_failed") == 5 and r.get("status") == "failed",
          "stdout fallback → failed 0/5", f"status={r.get('status')} run={r.get('tests_run')} failed={r.get('tests_failed')}", failures)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — Selenium status now reflects real pass/fail, not the testFailureIgnore exit code")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
