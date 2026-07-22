"""Smoketest for the offline Python Selenium runner.

This exercises :meth:`FunctionalTestPipelineService._run_selenium_python` — the
dependency-light execution path that drives a REAL Microsoft Edge browser
straight from Python (no Maven / Docker / JDK required) so a locked-down
corporate Windows machine still produces per-page screenshots, an offline
journey video and a viewable HTML report instead of dropping to source-only
"internal validation".

What it does
------------
1. Serves a tiny static site (an index page + a MAPS-style form page) on a free
   local port using Python's ``http.server`` — ZERO compilation, always works.
2. Builds a small SELENIUM functional test plan (navigate / fill / click /
   assert) exactly like the pipeline generates from source analysis.
3. Runs the Python Selenium runner against the served site.
4. Verifies the artefacts the UI depends on were produced:
      • .functional_tests/selenium/target/screenshots/*.png   (real frames)
      • .functional_tests/selenium/reports/index.html          (HTML report)
      • .functional_tests/selenium/reports/journey-video.html  (offline video)

Run it (from JavaAPEX-Backend):
    python scripts/selenium_python_runner_smoketest.py

Notes
-----
• Needs the ``selenium`` pip package + Microsoft Edge. The runner will try to
  ``pip install selenium`` itself (through the corporate proxy) if it is missing.
• Set ``SELENIUM_HEADLESS=true`` to run without a visible window (still captures
  screenshots + the journey video). On a desktop, headed (the default) records
  the most faithful journey.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import socket
import sys
import tempfile
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _load_service():
    """Import the pipeline service, tolerating environments where the
    ``services`` package ``__init__`` pulls heavy optional deps (e.g. PyGithub)."""
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from services.functional_test_pipeline import functional_test_pipeline  # type: ignore
        return functional_test_pipeline
    except Exception:
        spec = importlib.util.spec_from_file_location(
            "ftp_standalone", str(BACKEND_ROOT / "services" / "functional_test_pipeline.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.functional_test_pipeline


INDEX_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>MAPS - Launch Page</title></head>
<body>
  <h1>MAPS Launch Page</h1>
  <p>Welcome to the Materials Analysis Planning System.</p>
  <a href="/emptypage.html">Empty Page</a>
  <a href="/help.html">Help</a>
  <a href="/iconsguide.html">Icons Guide</a>
  <!-- about.html is linked but NOT in the test plan — the site crawl must find it -->
  <a href="/about.html">About</a>
</body></html>
"""

ABOUT_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>MAPS - About</title></head>
<body><h1>About MAPS</h1><p>UNIQUE_ABOUT_MARKER — discovered only by crawling.</p></body></html>
"""

EMPTY_PAGE_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>MAPS - Empty Page</title></head>
<body>
  <h1>Empty Page</h1>
  <form id="mapsForm" method="post" action="/emptypage.html">
    <input type="text" name="page" placeholder="Page" />
    <input type="text" name="action" placeholder="Action" />
    <input type="text" name="verticalScroll" placeholder="Vertical Scroll" />
    <button type="submit">Submit</button>
  </form>
</body></html>
"""

HELP_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>MAPS Help Links</title></head>
<body><h1>MAPS Help Links</h1><ul><li>Getting Started</li><li>FAQ</li></ul></body></html>
"""


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(webroot: Path, port: int) -> HTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(webroot))
    httpd = HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _build_plan() -> dict:
    empty_actions = [
        {"type": "navigate", "url": "/emptypage.html"},
        {"type": "assert_title", "title": "MAPS - Empty Page"},
        {"type": "fill", "locator": "[name=page]", "value": "Home"},
        {"type": "fill", "locator": "[name=action]", "value": "view"},
        {"type": "fill", "locator": "[name=verticalScroll]", "value": "0"},
        {"type": "click", "locator": 'button:has-text("Submit"), input[type=submit], button'},
        {"type": "assert_not_visible", "text": "500"},
        {"type": "assert_not_visible", "text": "Exception"},
    ]
    return {
        "tests": [
            {
                "name": "Fill and submit /emptypage.html form and verify response",
                "tool": "SELENIUM", "type": "legacy-ui", "route": "/emptypage.html",
                "actions": empty_actions,
            },
            {
                "name": "Verify /help.html renders with title MAPS Help Links",
                "tool": "SELENIUM", "type": "legacy-ui", "route": "/help.html",
                "actions": [
                    {"type": "navigate", "url": "/help.html"},
                    {"type": "assert_visible", "text": "MAPS Help Links"},
                ],
            },
            {
                "name": "E2E user journey across pages",
                "tool": "SELENIUM", "type": "legacy-ui", "route": "/",
                "actions": [
                    {"type": "navigate", "url": "/index.html"},
                    {"type": "navigate", "url": "/emptypage.html"},
                    {"type": "navigate", "url": "/help.html"},
                ],
            },
        ]
    }


def main() -> int:
    svc = _load_service()

    webroot = Path(tempfile.mkdtemp(prefix="maps-webroot-"))
    (webroot / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (webroot / "emptypage.html").write_text(EMPTY_PAGE_HTML, encoding="utf-8")
    (webroot / "help.html").write_text(HELP_HTML, encoding="utf-8")
    (webroot / "about.html").write_text(ABOUT_HTML, encoding="utf-8")

    port = _free_port()
    httpd = _serve(webroot, port)
    base_url = f"http://127.0.0.1:{port}"
    print(f"[smoketest] serving {webroot} at {base_url}")

    work = Path(tempfile.mkdtemp(prefix="selepy-run-"))
    test_dir = work / ".functional_tests" / "selenium"
    test_dir.mkdir(parents=True, exist_ok=True)
    profile = {"runtime": {"baseUrl": base_url}, "recommendedFunctionalTools": ["SELENIUM"]}
    plan = _build_plan()

    try:
        runner = asyncio.run(svc._run_selenium_python(test_dir, profile, plan))
    finally:
        httpd.shutdown()

    print("\n[smoketest] runner result:")
    for k in ("tool", "status", "executed", "tests_run", "tests_passed",
              "tests_failed", "browser", "screenshots_captured",
              "report_available", "report_tool", "video_available", "video_tool"):
        print(f"  {k:22}: {runner.get(k)}")
    print("  output:", runner.get("output") or runner.get("message"))

    shots = sorted((test_dir / "target" / "screenshots").glob("*.png"))
    report = test_dir / "reports" / "index.html"
    journey = test_dir / "reports" / "journey-video.html"
    print("\n[smoketest] artefacts:")
    print(f"  screenshots : {len(shots)}")
    print(f"  report      : {report.exists()}  ({report})")
    print(f"  journey     : {journey.exists()}  ({journey})")

    # The site crawl must have discovered /about.html (linked from index but NOT
    # in the test plan) and tested it as its own page.
    details = runner.get("details") or []
    crawled_about = any("about" in str(d.get("route", "")).lower() for d in details)
    print(f"  crawl found /about.html (unplanned): {crawled_about}")

    if runner.get("status") == "skipped":
        print(
            "\n[smoketest] SKIPPED — selenium/Edge unavailable in this environment. "
            "Install the 'selenium' package (through your proxy) and ensure Microsoft "
            "Edge is present, then re-run to capture real screenshots + video."
        )
        return 2

    ok = (
        int(runner.get("tests_run", 0) or 0) > 0
        and len(shots) > 0
        and report.exists()
        and crawled_about
    )
    print("\n[smoketest]", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
