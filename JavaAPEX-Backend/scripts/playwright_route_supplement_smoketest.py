"""End-to-end validation for the Playwright route-supplement fix.

Simulates the real failure: the LLM emits a spec covering only ``/index.html``
(2 tests) while the plan has 5 routes. Confirms that
``_supplement_missing_playwright_routes`` adds the 4 missing routes so all 5
planned test cases end up in the executable spec, and that the merged spec is
syntactically valid TypeScript.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_module():
    """Load functional_test_pipeline without triggering services/__init__."""
    spec = importlib.util.spec_from_file_location(
        "ftp_isolated", str(PIPELINE)
    )
    mod = importlib.util.module_from_spec(spec)
    # Make 'services' resolvable as a namespace so intra-package refs work.
    sys.modules.setdefault("ftp_isolated", mod)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = _load_pipeline_module()

    # Find the pipeline class that owns the supplement helper.
    cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(
            obj, "_supplement_missing_playwright_routes"
        ):
            cls = obj
            break
    if cls is None:
        print("FAIL: could not find class with _supplement_missing_playwright_routes")
        return 1
    print(f"Using pipeline class: {cls.__name__}")

    # Instance without running __init__ (avoids heavy deps).
    inst = cls.__new__(cls)

    base_url = "http://localhost:8080"

    # The LLM-generated spec only covered /index.html (the real under-generation).
    pw_code = (
        "import { test, expect } from '@playwright/test';\n\n"
        "const baseUrl = process.env.BASE_URL || 'http://localhost:8080';\n\n"
        "test('GET /index.html renders', async ({ page }) => {\n"
        "  const res = await page.goto(`${baseUrl}/index.html`);\n"
        "  expect(res && res.status()).toBeLessThan(500);\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n\n"
        "test('index has content', async ({ page }) => {\n"
        "  await page.goto(`${baseUrl}/index.html`);\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    # The plan has 5 routes (mirrors the real functional-test-plan.json).
    pw_tests = [
        {"name": "Load index", "route": "/index.html", "method": "GET", "route_type": "static"},
        {"name": "Load status page", "route": "/status.jsp", "method": "GET", "route_type": "jsp"},
        {"name": "CIRequest view", "route": "/CIRequest", "method": "GET", "route_type": "servlet"},
        {"name": "CIRequest submit", "route": "/CIRequest", "method": "POST", "route_type": "servlet"},
        {"name": "Health check", "route": "/health", "method": "GET", "route_type": "servlet"},
    ]

    merged = inst._supplement_missing_playwright_routes(pw_code, pw_tests, base_url)

    # Count executable tests.
    test_count = len(re.findall(r"\btest\s*\(", merged))
    print(f"\nExecutable test() blocks after supplement: {test_count}")

    # Verify every planned route+method is represented.
    expected = [
        ("GET", "/index.html"),
        ("GET", "/status.jsp"),
        ("GET", "/CIRequest"),
        ("POST", "/CIRequest"),
        ("GET", "/health"),
    ]
    missing = []
    for method, route in expected:
        if route not in merged:
            missing.append((method, route))
    if missing:
        print(f"FAIL: routes missing from merged spec: {missing}")
        print("---- merged ----")
        print(merged)
        return 1
    print("All 5 planned routes present in merged spec: PASS")

    # POST must use page.request.post (executable), not just a comment.
    if "request.post" not in merged.replace(" ", ""):
        # tolerate .request.post( spacing
        if not re.search(r"request\s*\.\s*post\s*\(", merged):
            print("FAIL: POST /CIRequest is not an executable request.post call")
            print(merged)
            return 1
    print("POST /CIRequest rendered as executable request: PASS")

    # Idempotency: running again must not add duplicates.
    merged2 = inst._supplement_missing_playwright_routes(merged, pw_tests, base_url)
    test_count2 = len(re.findall(r"\btest\s*\(", merged2))
    if test_count2 != test_count:
        print(f"FAIL: not idempotent ({test_count} -> {test_count2})")
        return 1
    print(f"Idempotent re-run keeps {test_count2} tests: PASS")

    # esbuild syntax validation (frontend has esbuild available).
    frontend = BACKEND.parent / "JavaAPEX-Frontend"
    with tempfile.TemporaryDirectory() as td:
        spec_file = Path(td) / "functional.spec.ts"
        spec_file.write_text(merged, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["npx", "esbuild", str(spec_file), "--loader:.ts=ts", "--bundle=false"],
                cwd=str(frontend),
                capture_output=True,
                text=True,
                shell=True,
                timeout=120,
            )
            if proc.returncode != 0:
                print("FAIL: esbuild rejected the merged spec")
                print(proc.stderr[:2000])
                return 1
            print("esbuild validated merged spec: PASS")
        except FileNotFoundError:
            print("WARN: esbuild not available; skipped TS validation")

    print("\n================ MERGED SPEC ================")
    print(merged)
    print("============================================")
    print("\nALL CHECKS PASSED: all 5 planned routes now execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
