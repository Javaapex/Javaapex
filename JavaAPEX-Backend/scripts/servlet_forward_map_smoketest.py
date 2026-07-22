"""Smoketest: servlet / front-controller route -> forwarded real page.

Guards the "every servlet route shows the same generic mock" bug. Legacy
MAPS-style servlets (``/health``, ``/redirect/ReportServer``, ``/JobScheduler``,
``/CIRequest`` …) have NO backing HTML file, so served statically they used to
ALL fall through to one identical synthesized mock — making every captured
screenshot look the same.

:meth:`FunctionalTestPipelineService._build_servlet_forward_map` now scans each
servlet's Java source (and ``web.xml``) for its url-pattern(s) plus its
``RequestDispatcher.forward`` / ``sendRedirect`` / JSP target, and the static
file server renders each servlet route's ACTUAL target page instead of the mock.

Run it (from JavaAPEX-Backend):
    python scripts/servlet_forward_map_smoketest.py

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
    "index.html": "<html><head><title>MAPS - Launch Page</title></head><body><h1>Launch</h1>UNIQUE_LAUNCH</body></html>",
    "help.html": "<html><head><title>MAPS Help Links</title></head><body><h1>Help</h1>UNIQUE_HELP</body></html>",
    "iconsGuide.html": "<html><head><title>MAPS Icons Guide</title></head><body><h1>Icons</h1>UNIQUE_ICONS</body></html>",
    "emptyPage.html": "<html><head><title>MAPS - Empty Page</title></head><body><h1>Empty</h1>UNIQUE_EMPTY</body></html>",
    "reportServer.html": "<html><head><title>MAPS Report Server</title></head><body><h1>Reports</h1>UNIQUE_REPORT</body></html>",
    "jobScheduler.html": "<html><head><title>MAPS Job Scheduler</title></head><body><h1>Jobs</h1>UNIQUE_JOBS</body></html>",
}


def _write_project(root: Path) -> None:
    webapp = root / "src" / "main" / "webapp"
    webapp.mkdir(parents=True)
    srv = root / "src" / "main" / "java" / "com" / "maps"
    srv.mkdir(parents=True)
    for name, html in PAGES.items():
        (webapp / name).write_text(html, encoding="utf-8")

    # @WebServlet forward
    (srv / "ReportServerRedirectServlet.java").write_text(
        '@WebServlet("/redirect/ReportServer")\n'
        "public class ReportServerRedirectServlet extends HttpServlet {\n"
        "  protected void doGet(HttpServletRequest req, HttpServletResponse resp){\n"
        '    request.getRequestDispatcher("/reportServer.html").forward(req, resp);\n'
        "  }\n}\n",
        encoding="utf-8",
    )
    # @WebServlet sendRedirect
    (srv / "JobSchedulerServlet.java").write_text(
        '@WebServlet(urlPatterns={"/JobScheduler"})\n'
        "public class JobSchedulerServlet extends HttpServlet {\n"
        "  protected void doPost(HttpServletRequest req, HttpServletResponse resp){\n"
        '    resp.sendRedirect("jobScheduler.html");\n'
        "  }\n}\n",
        encoding="utf-8",
    )
    # web.xml-mapped servlet forward
    (webapp / "WEB-INF").mkdir()
    (webapp / "WEB-INF" / "web.xml").write_text(
        "<web-app><servlet><servlet-name>Front</servlet-name>"
        "<servlet-class>com.maps.FrontControllerServlet</servlet-class></servlet>"
        "<servlet-mapping><servlet-name>Front</servlet-name>"
        "<url-pattern>/CIRequest</url-pattern></servlet-mapping></web-app>",
        encoding="utf-8",
    )
    (srv / "FrontControllerServlet.java").write_text(
        "public class FrontControllerServlet extends HttpServlet {\n"
        "  protected void service(HttpServletRequest req, HttpServletResponse resp){\n"
        '    getServletContext().getRequestDispatcher("/help.html").forward(req, resp);\n'
        "  }\n}\n",
        encoding="utf-8",
    )


def main() -> int:
    svc = _load_service()
    root = Path(tempfile.mkdtemp(prefix="maps-servlet-"))
    _write_project(root)

    profile = {"runtime": {"baseUrl": "http://localhost:0", "allocatedPort": 0}, "endpoints": []}
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
        ("/redirect/ReportServer", "UNIQUE_REPORT"),  # annotation forward
        ("/JobScheduler", "UNIQUE_JOBS"),             # sendRedirect
        ("/CIRequest", "UNIQUE_HELP"),                # web.xml servlet forward
        ("/help", "UNIQUE_HELP"),                     # normal fuzzy still works
        ("/iconsguide.html", "UNIQUE_ICONS"),         # case-insensitive
        ("/", "UNIQUE_LAUNCH"),                        # index
    ]
    print("[smoketest] servlet route -> forwarded page:")
    all_ok = True
    bodies = {}
    for path, marker in checks:
        body = get(path)
        bodies[path] = body
        ok = marker in body
        all_ok = all_ok and ok
        print(f"  {path:26} -> {'OK' if ok else 'FAIL'}  (want {marker})")

    mock = get("/SomethingWithNoPage")
    mock_ok = "Mock response for route" in mock
    print(f"  {'/SomethingWithNoPage':26} -> {'MOCK (ok)' if mock_ok else 'other'}")

    distinct = len({
        bodies["/redirect/ReportServer"], bodies["/JobScheduler"],
        bodies["/CIRequest"], bodies["/"],
    })
    print(f"\n[smoketest] distinct bodies among 4 routes: {distinct} (want 4)")

    try:
        httpd.shutdown()
    except Exception:  # noqa: BLE001
        pass

    passed = all_ok and mock_ok and distinct == 4
    print("\n[smoketest]", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
