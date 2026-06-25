"""Smoketest for multi-tool functional-test selection normalization.

Verifies ``FunctionalTestPipelineService._normalize_selected_tools`` accepts a
single tool, a comma-separated string, or a list (any mix), filters to known
tools, de-dupes, preserves order, and treats ``None``/``""``/``"auto"``/unknown
as "use the auto recommendation" (empty list). This backs the Strategy page's
ability to validate with MULTIPLE recommended tools at once.
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
        ("PLAYWRIGHT", ["PLAYWRIGHT"]),
        ("playwright", ["PLAYWRIGHT"]),
        ("  playwright  ", ["PLAYWRIGHT"]),
        ("PLAYWRIGHT,REST_ASSURED", ["PLAYWRIGHT", "REST_ASSURED"]),
        ("PLAYWRIGHT, REST_ASSURED", ["PLAYWRIGHT", "REST_ASSURED"]),
        ("PLAYWRIGHT;MOCK_MVC", ["PLAYWRIGHT", "MOCK_MVC"]),
        (["PLAYWRIGHT", "REST_ASSURED"], ["PLAYWRIGHT", "REST_ASSURED"]),
        (["playwright", "auto", "BOGUS"], ["PLAYWRIGHT"]),
        (["PLAYWRIGHT,MOCK_MVC", "SELENIUM"], ["PLAYWRIGHT", "MOCK_MVC", "SELENIUM"]),
        ("PLAYWRIGHT,PLAYWRIGHT", ["PLAYWRIGHT"]),
        (["PLAYWRIGHT", "PLAYWRIGHT"], ["PLAYWRIGHT"]),
        (
            ["PLAYWRIGHT", "REST_ASSURED", "MOCK_MVC", "SELENIUM", "SCHEMATHESIS"],
            ["PLAYWRIGHT", "REST_ASSURED", "MOCK_MVC", "SELENIUM", "SCHEMATHESIS"],
        ),
        ((  # tuple input
            "REST_ASSURED", "PLAYWRIGHT"
        ), ["REST_ASSURED", "PLAYWRIGHT"]),
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
