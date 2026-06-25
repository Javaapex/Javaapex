"""Validate the mock static server now renders meaningful UI for the real
PinnacleTools webapp: the stub index gets a styled panel, and status.jsp's
<%= new java.util.Date() %> is rendered instead of shown raw.
"""
import asyncio
import importlib.util
import sys
import types
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "services" / "functional_test_pipeline.py"

sys.path.insert(0, str(ROOT))
_stub = types.ModuleType("services")
_stub.__path__ = [str(ROOT / "services")]
sys.modules["services"] = _stub

spec = importlib.util.spec_from_file_location("ftp_jsp", str(MOD))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Svc = mod.FunctionalTestPipelineService
svc = Svc.__new__(Svc)

WEBAPP_ROOT = Path(
    r"C:\Users\KARUNAC4\Downloads\16170-pinnacle-middleware-master"
    r"\16170-pinnacle-middleware-master\PinnacleToolsWAR\src\main\webapp"
)


def get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode("utf-8", errors="replace")


async def amain() -> int:
    # _start_static_file_server searches for src/main/webapp under the given root.
    project_root = WEBAPP_ROOT.parents[2]  # …/PinnacleToolsWAR
    profile = {"runtime": {"baseUrl": "http://localhost:8080"}}
    res = await svc._start_static_file_server(project_root, profile)
    if not res.get("started"):
        print("[jsp] FAIL — server did not start:", res.get("message"))
        return 1
    base = res["baseUrl"]
    httpd = res.get("_httpd")
    print(f"[jsp] server on {base} serving {res.get('serving_dir')}")

    try:
        index_html = get(base + "/")
        status_html = get(base + "/status.jsp")
    finally:
        if httpd:
            httpd.shutdown()

    print("\n[jsp] ── index.html (stub) ───────────────")
    has_panel = "data-javaapex-panel" in index_html
    has_links = "Available pages" in index_html
    keeps_real = "First Page" in index_html
    print("  styled panel injected :", has_panel)
    print("  lists available pages :", has_links)
    print("  keeps real content    :", keeps_real)
    print("  snippet:", svc._visible_text(index_html)[:160])

    print("\n[jsp] ── status.jsp (rendered) ───────────")
    title_ok = "CSM Test Page" in status_html
    no_raw_jsp = "<%" not in status_html and "%>" not in status_html
    # The <%= new java.util.Date() %> should have become a date-like string.
    import re
    has_date = bool(re.search(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", status_html)) or "Current time is" in status_html
    print("  has <title> content   :", title_ok)
    print("  no raw <% %> tags     :", no_raw_jsp)
    print("  date expr rendered    :", has_date)
    print("  visible:", svc._visible_text(status_html)[:160])

    ok = has_panel and has_links and title_ok and no_raw_jsp
    print("\n[jsp]", "PASS — pages render meaningful UI" if ok else "FAIL — rendering incomplete")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
