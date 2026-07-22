"""Smoketest for static-server route → real-page resolution.

Reproduces and guards the "all pages look the same / repeated" bug: a legacy
Front-Controller webapp (single servlet handling many URLs) used to make every
route without an exact backing file fall through to ONE identical synthesized
mock page, so every captured screenshot looked the same.

:meth:`FunctionalTestPipelineService._start_static_file_server` now fuzzy-resolves
those routes to the CORRECT distinct real page via:
  • front-controller query params  (``/MAPS?page=help.html``)
  • path tails                     (``/MAPS/help.html``)
  • extension-less stems           (``/help``, ``/emptypage``)
  • case-insensitive filenames     (``/iconsguide.html`` → ``iconsGuide.html``)

Run it (from JavaAPEX-Backend):
    python scripts/static_server_route_resolution_smoketest.py

Exit code 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _load_service():
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


PAGES = {
    "index.html": "<html><head><title>MAPS - Launch Page</title></head><body><h1>Launch Page</h1><p>UNIQUE_LAUNCH_MARKER</p></body></html>",
    "emptyPage.html": "<html><head><title>MAPS - Empty Page</title></head><body><h1>Empty Page</h1><form><input name='page'><button>Submit</button></form><p>UNIQUE_EMPTY_MARKER</p></body></html>",
    "help.html": "<html><head><title>MAPS Help Links</title></head><body><h1>Help Links</h1><p>UNIQUE_HELP_MARKER</p></body></html>",
    "iconsGuide.html": "<html><head><title>MAPS Icons Guide</title></head><body><h1>Icons Guide</h1><p>UNIQUE_ICONS_MARKER</p></body></html>",
}


def main() -> int:
    svc = _load_service()

    root = Path(tempfile.mkdtemp(prefix="maps-app-"))
    webapp = root / "src" / "main" / "webapp"
    webapp.mkdir(parents=True)
    for name, html in PAGES.items():
        (webapp / name).write_text(html, encoding="utf-8")

    profile = {"runtime": {"baseUrl": "http://localhost:0", "allocatedPort": 0}}
    res = asyncio.run(svc._start_static_file_server(root, profile))
    if not res.get("started"):
        print("[smoketest] FAIL — static server did not start:", res.get("message"))
        return 1
    base = res.get("baseUrl")
    httpd = res.get("_httpd")

    def get(path: str) -> str:
        try:
            with urllib.request.urlopen(base + path, timeout=5) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            return f"ERR {exc}"

    checks = [
        ("/help.html", "UNIQUE_HELP_MARKER"),                 # exact
        ("/help", "UNIQUE_HELP_MARKER"),                      # extension-less stem
        ("/iconsguide.html", "UNIQUE_ICONS_MARKER"),          # case-insensitive
        ("/MAPS/help.html", "UNIQUE_HELP_MARKER"),            # front-controller path tail
        ("/MAPS?page=iconsGuide.html", "UNIQUE_ICONS_MARKER"),# front-controller query param
        ("/emptypage", "UNIQUE_EMPTY_MARKER"),                # lowercase stem
        ("/", "UNIQUE_LAUNCH_MARKER"),                        # index
    ]

    print("[smoketest] route resolution:")
    all_ok = True
    bodies = {}
    for path, marker in checks:
        body = get(path)
        bodies[path] = body
        ok = marker in body
        all_ok = all_ok and ok
        print(f"  {path:32} -> {'OK' if ok else 'FAIL'}  (expected {marker})")

    mock = get("/MAPS")
    mock_ok = "Mock response for route" in mock
    print(f"  {'/MAPS':32} -> {'SYNTH MOCK' if mock_ok else 'other'}  (no page file; mock expected)")

    distinct = {bodies["/help.html"], bodies["/iconsguide.html"], bodies["/emptypage"], bodies["/"]}
    not_repeated = len(distinct) == 4
    print(f"\n[smoketest] distinct bodies among 4 page routes: {len(distinct)} (want 4)")

    try:
        httpd.shutdown()
    except Exception:  # noqa: BLE001
        pass

    passed = all_ok and mock_ok and not_repeated
    print("\n[smoketest]", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
