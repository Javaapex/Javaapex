"""Smoketest for multi-tool functional-test selection normalization.

Verifies ``FunctionalTestPipelineService._normalize_selected_tools`` accepts a
single tool, a comma-separated string, or a list (any mix), filters to known
tools, de-dupes, preserves order, and treats ``None``/``""``/``"auto"``/unknown
as "use the auto recommendation" (empty list). This backs the Strategy page's
ability to validate with MULTIPLE recommended tools at once.

NOTE: ``PLAYWRIGHT`` has been RETIRED from ``KNOWN_FUNCTIONAL_TOOLS`` (the
product now uses Selenium for UI testing), so it must be filtered out exactly
like any other unknown token — several cases below pin that behaviour.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_class():
    spec = importlib.util.spec_from_file_location("ftp_tools_iso", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_tools_iso", mod)
    spec.loader.exec_module(mod)
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_normalize_selected_tools"):
            return obj
    raise RuntimeError("FunctionalTestPipelineService not found")


def main() -> int:
    cls = _load_pipeline_class()
    norm = cls._normalize_selected_tools

    cases = [
        (None, []),
        ("", []),
        ("auto", []),
        ("AUTO", []),
        ("BOGUS", []),
        # PLAYWRIGHT is retired → treated like any unknown token (filtered out).
        ("PLAYWRIGHT", []),
        ("playwright", []),
        # Single known tool, case/whitespace-insensitive.
        ("SELENIUM", ["SELENIUM"]),
        ("selenium", ["SELENIUM"]),
        ("  selenium  ", ["SELENIUM"]),
        # Comma / space / semicolon separated strings of known tools.
        ("SELENIUM,REST_ASSURED", ["SELENIUM", "REST_ASSURED"]),
        ("SELENIUM, REST_ASSURED", ["SELENIUM", "REST_ASSURED"]),
        ("SELENIUM;MOCK_MVC", ["SELENIUM", "MOCK_MVC"]),
        # List inputs, order preserved.
        (["SELENIUM", "REST_ASSURED"], ["SELENIUM", "REST_ASSURED"]),
        (["selenium", "auto", "BOGUS"], ["SELENIUM"]),
        # A list of only unknown/sentinel tokens → empty (use auto recommendation).
        (["PLAYWRIGHT", "auto", "BOGUS"], []),
        # Nested comma string inside a list element is still split.
        (["SELENIUM,MOCK_MVC", "REST_ASSURED"], ["SELENIUM", "MOCK_MVC", "REST_ASSURED"]),
        # De-duplication (string and list forms).
        ("SELENIUM,SELENIUM", ["SELENIUM"]),
        (["SELENIUM", "SELENIUM"], ["SELENIUM"]),
        # All known tools, order preserved.
        (
            ["REST_ASSURED", "MOCK_MVC", "SELENIUM", "SCHEMATHESIS"],
            ["REST_ASSURED", "MOCK_MVC", "SELENIUM", "SCHEMATHESIS"],
        ),
        # PLAYWRIGHT mixed with known tools → dropped, known ones kept in order.
        (["SELENIUM", "PLAYWRIGHT", "REST_ASSURED"], ["SELENIUM", "REST_ASSURED"]),
        ((  # tuple input
            "REST_ASSURED", "SELENIUM"
        ), ["REST_ASSURED", "SELENIUM"]),
    ]

    ok = True
    for raw, expected in cases:
        got = norm(raw)
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"[{status}] {raw!r:55} -> {got}  (expected {expected})")

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
