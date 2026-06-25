"""Integration proof: call the REAL pipeline method `_run_playwright` and assert
it produces a native Playwright HTML report + per-test .webm videos on this host.

Unlike the smoke test (which drives npx directly), this exercises the exact
production code path: `_get_npm_proxy_env`, `_find_edge_path`, `_run_command`
(with the Python-3.14 Windows sync fallback) and the Edge `msedge` channel.
"""
import asyncio
import importlib.util
import socket
import sys
import tempfile
import threading
import types
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "services" / "functional_test_pipeline.py"

# Make `from services.java_test_runner import ...` (used inside _run_playwright)
# resolve to the real submodule WITHOUT executing services/__init__.py, which
# imports PyGithub (absent in this env). A stub package with __path__ set lets
# Python find submodules on disk while skipping the package __init__.
sys.path.insert(0, str(ROOT))
_services_stub = types.ModuleType("services")
_services_stub.__path__ = [str(ROOT / "services")]
sys.modules["services"] = _services_stub

spec = importlib.util.spec_from_file_location("ftp_integ", str(MOD))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Svc = mod.FunctionalTestPipelineService
svc = Svc.__new__(Svc)
# Minimal attributes _run_playwright relies on.
svc.runner_timeout_sec = 180


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def amain() -> int:
    work = Path(tempfile.mkdtemp(prefix="pw_integ_"))
    web = work / "web"
    web.mkdir()
    (web / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Integration Page</title></head>"
        "<body><h1>Hello Integration</h1></body></html>",
        encoding="utf-8",
    )

    # The playwright test dir, written exactly like the pipeline does.
    pw_dir = work / "playwright"
    pw_dir.mkdir()
    (pw_dir / "package.json").write_text(svc._render_playwright_package(), encoding="utf-8")
    (pw_dir / "playwright.config.ts").write_text(svc._render_playwright_config(), encoding="utf-8")
    (pw_dir / "functional.spec.ts").write_text(
        "import { test, expect } from '@playwright/test';\n\n"
        "test('integration home title', async ({ page }) => {\n"
        "  await page.goto('/index.html');\n"
        "  await expect(page).toHaveTitle(/Integration Page/);\n"
        "  await expect(page.locator('h1')).toBeVisible();\n"
        "});\n",
        encoding="utf-8",
    )

    port = free_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(web))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}"
    print(f"[integ] static server on {base_url}")
    print(f"[integ] edge = {svc._find_edge_path()}")
    print(f"[integ] proxy = {svc._resolve_npm_proxy()}")

    profile = {"runtime": {"baseUrl": base_url}}

    print("[integ] calling REAL svc._run_playwright(...) — this may take a minute …")
    runner = await svc._run_playwright(pw_dir, profile)

    print("\n[integ] runner result keys:", sorted(runner.keys()))
    print("  status        :", runner.get("status"))
    print("  exit_code     :", runner.get("exit_code"))
    print("  tests_run     :", runner.get("tests_run"))
    print("  tests_passed  :", runner.get("tests_passed"))
    print("  tests_failed  :", runner.get("tests_failed"))
    print("  report_avail  :", runner.get("report_available"))
    print("  report_tool   :", runner.get("report_tool"))
    print("  allure_avail  :", runner.get("allure_report_available"))
    print("  allure_tool   :", runner.get("allure_report_tool"))
    tail = (runner.get("output_tail") or "")[-600:]
    if tail:
        print("  output_tail   :", tail)

    report = pw_dir / "playwright-report" / "index.html"
    allure_report = pw_dir / "allure-report" / "index.html"
    videos = list(pw_dir.rglob("*.webm"))
    print("\n[integ] ── RESULTS ─────────────────────────")
    print("  report index.html exists:", report.exists())
    print("  allure index.html exists:", allure_report.exists())
    print("  .webm videos found      :", len(videos))
    for v in videos[:5]:
        print("     -", v.name, f"({v.stat().st_size} bytes) in {v.parent}")

    httpd.shutdown()

    ok = (
        bool(runner.get("report_available"))
        and runner.get("report_tool") == "playwright"
        and report.exists()
        and len(videos) >= 1
    )
    allure_ok = bool(runner.get("allure_report_available")) and allure_report.exists()
    print("\n[integ]", "PASS — production _run_playwright produced real video + report"
          if ok else "FAIL — real video/report not produced by _run_playwright")
    print("[integ]", "PASS — Allure report generated" if allure_ok else "WARN — Allure report NOT generated (check allure-commandline install)")
    print(f"[integ] artifacts in: {pw_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(amain()))
