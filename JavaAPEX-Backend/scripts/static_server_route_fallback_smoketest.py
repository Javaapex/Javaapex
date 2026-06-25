"""Integration smoketest for the static-file-server route fallback fix.

Reproduces the PinnacleTools failure: a legacy JSP/servlet webapp whose
``index.html`` only says "First Page…". An unbacked servlet route like
``/health`` was SPA-falling-back to that index (so ``toContainText('OK')``
failed). After the fix, server-rendered apps serve the route-aware synth page
(which carries a <title> and a visible "OK") for unbacked routes, while real
files (index.html, *.jsp) are still served verbatim.

Starts the REAL ``_start_static_file_server`` and asserts over HTTP.
"""
import asyncio
import importlib.util
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_module():
    # Stub the eager 'services' package import chain so we can load just this module.
    spec = importlib.util.spec_from_file_location("ftp_static_iso", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_static_iso", mod)
    spec.loader.exec_module(mod)
    return mod


def _find_pipeline_class(mod):
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_start_static_file_server"):
            return obj
    raise RuntimeError("pipeline class not found")


def _make_pinnacle_webapp(base: Path) -> Path:
    """Create a minimal legacy JSP/servlet webapp like PinnacleTools."""
    webapp = base / "PinnacleToolsWAR" / "src" / "main" / "webapp"
    webapp.mkdir(parents=True, exist_ok=True)
    (webapp / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>Insert title here</title></head>"
        "<body>First Page............................</body></html>",
        encoding="utf-8",
    )
    (webapp / "status.jsp").write_text(
        "<%@ page language='java' %><html><head><title>CSM Test Page</title></head>"
        "<body><h1>Status</h1><p>Dynamic content here</p></body></html>",
        encoding="utf-8",
    )
    (webapp / "WEB-INF").mkdir(exist_ok=True)
    (webapp / "WEB-INF" / "web.xml").write_text(
        "<web-app><servlet><servlet-name>ci</servlet-name>"
        "<servlet-class>DefaultServletLoader</servlet-class></servlet>"
        "<servlet-mapping><servlet-name>ci</servlet-name>"
        "<url-pattern>/CIRequest</url-pattern></servlet-mapping></web-app>",
        encoding="utf-8",
    )
    return base / "PinnacleToolsWAR"


def _get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


async def _run() -> int:
    mod = _load_pipeline_module()
    cls = _find_pipeline_class(mod)
    inst = cls.__new__(cls)
    # Minimal attrs the method/handler touch.
    inst.find_available_port = cls.find_available_port.__get__(inst, cls)

    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = _make_pinnacle_webapp(Path(td))
        profile = {"runtime": {"baseUrl": "http://localhost:0", "allocatedPort": 0}}
        result = await inst._start_static_file_server(root, profile)
        if not result.get("started"):
            print(f"FAIL: server did not start: {result.get('message')}")
            return 1
        base_url = result["baseUrl"]
        print(f"Server up: {base_url} (type={result.get('server_type')})")

        # 1) /health (unbacked servlet route) → synth page containing "OK".
        status, body = _get(f"{base_url}/health")
        cond = status == 200 and "OK" in body
        ok = ok and cond
        print(f"[{'PASS' if cond else 'FAIL'}] GET /health → {status}, contains 'OK': {'OK' in body}")
        if not cond:
            print("  body:", body[:400])

        # 2) /CIRequest (unbacked servlet route) → synth, status 200, has a title.
        status, body = _get(f"{base_url}/CIRequest")
        cond = status == 200 and "<title>" in body.lower()
        ok = ok and cond
        print(f"[{'PASS' if cond else 'FAIL'}] GET /CIRequest → {status}, has <title>: {'<title>' in body.lower()}")

        # 3) /index.html (real file) → served verbatim, keeps its real title + content.
        status, body = _get(f"{base_url}/index.html")
        cond = status == 200 and "Insert title here" in body and "First Page" in body
        ok = ok and cond
        print(f"[{'PASS' if cond else 'FAIL'}] GET /index.html → real title+content: {cond}")

        # 4) /status.jsp (real JSP) → rendered, keeps its real title.
        status, body = _get(f"{base_url}/status.jsp")
        cond = status == 200 and "CSM Test Page" in body
        ok = ok and cond
        print(f"[{'PASS' if cond else 'FAIL'}] GET /status.jsp → real title 'CSM Test Page': {cond}")

        # Shut the server down.
        httpd = result.get("_httpd")
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass

    print("\n" + ("ALL CHECKS PASSED — /health now returns OK" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
