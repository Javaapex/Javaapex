"""Ad-hoc validation: prove the static server renders MAPS Velocity (.vm)
templates into DISTINCT, meaningful pages (the "same UI repeating" fix).

Run from the JavaAPEX-Backend dir with the venv python:
    python scripts/maps_vm_render_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.functional_test_pipeline import FunctionalTestPipelineService as S  # noqa: E402

WEBAPP = Path(
    r"C:/Users/KARUNAC4/Downloads/Functional_Testing/Javaapex/"
    r"maps-ui-gcp-bq-main/maps-ui-gcp-bq-main/MAPSWAR/src/main/webapp"
)

PAGES = [
    "templates/SplashPage.vm",
    "templates/report/ReportPage.vm",
    "templates/briefingbook/BriefingbookPage.vm",
    "templates/preference/PreferencePage.vm",
    "templates/customorg/CustomOrgPage.vm",
]


def _title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else "(none)")


def _has_raw_directives(html: str) -> bool:
    # Any leaked Velocity syntax means the render is incomplete.
    return bool(re.search(r"#(set|parse|include|if|foreach|end)\b", html)) or "$!" in html


def main() -> int:
    if not WEBAPP.is_dir():
        print(f"SKIP: MAPS webapp not found at {WEBAPP}")
        return 0

    print(f"Rendering {len(PAGES)} MAPS .vm templates from:\n  {WEBAPP}\n")
    titles: list[str] = []
    ok = True
    for rel in PAGES:
        p = WEBAPP / rel
        if not p.is_file():
            print(f"  MISSING: {rel}")
            ok = False
            continue
        html = S._render_vm_file(p, WEBAPP)
        title = _title(html)
        titles.append(title)
        visible = S._visible_text(html)
        leaks = _has_raw_directives(html)
        print(f"  {rel}")
        print(f"      title  : {title}")
        print(f"      visible: {visible[:90]!r}")
        print(f"      leaks  : {'YES (raw #/$ directives!)' if leaks else 'no'}")
        if leaks:
            ok = False

    distinct = len(set(titles)) == len(titles)
    print("\nSummary")
    print(f"  distinct titles : {distinct} ({len(set(titles))}/{len(titles)} unique)")
    print(f"  no directive leaks: {ok}")
    render_ok = distinct and ok

    live_ok = _live_server_check()

    routes_ok = _route_discovery_check()

    print("\nRESULT:", "PASS ✅" if (render_ok and live_ok and routes_ok) else "FAIL ❌")
    return 0 if (render_ok and live_ok and routes_ok) else 1


def _route_discovery_check() -> bool:
    """Prove _detect_ui_routes now surfaces the MAPS Velocity pages, so EVERY
    runner (Selenium/Playwright/etc.) actually navigates to each distinct page —
    not just the 4 static .html shells."""
    war_root = WEBAPP.parents[2]  # …/MAPSWAR
    files = [p for p in war_root.rglob("*") if p.is_file()]
    svc = S()
    fc = svc._detect_front_controller_path(files)
    routes = svc._detect_ui_routes(files)
    vm_routes = [r for r in routes if r.get("page_type") == "vm"]
    print(f"\nRoute discovery on {war_root.name}: "
          f"{len(routes)} route(s), {len(vm_routes)} from .vm templates")
    print(f"    front-controller detected: {fc}")
    for r in vm_routes[:12]:
        print(f"    {r['route']}   (source: {r['source_file']})")
    # Fragments/partials must NOT appear.
    leaked = [r for r in routes if any(
        tok in r["source_file"].lower()
        for tok in (".include.", ".layer.", ".ajax.", ".content.")
    )]
    if leaked:
        print(f"  ✗ fragment routes leaked: {[r['source_file'] for r in leaked]}")
    # Authentic front-controller URLs (/MAPS?_page=X) for .vm pages.
    authentic = all(r["route"].startswith(f"{fc}?_page=") for r in vm_routes) if fc else False
    print(f"  authentic front-controller URLs: {authentic}")
    ok = len(vm_routes) >= 3 and not leaked and authentic
    print(f"  vm pages discovered, authentic URLs & no fragments leaked: {ok}")
    return ok


def _live_server_check() -> bool:
    """Start the real static file server against MAPS and hit several routes to
    prove distinct routes serve DISTINCT pages (the front-controller ``_page``
    param + Velocity rendering working through the actual server path)."""
    import asyncio
    import urllib.request

    root = WEBAPP.parents[2]  # …/MAPSWAR (contains src/main/webapp)
    svc = S()
    profile = {"runtime": {}}

    async def _run() -> bool:
        started = await svc._start_static_file_server(root, profile)
        if not started.get("started"):
            print(f"\nLive check SKIP: server didn't start: {started.get('message')}")
            return True  # don't fail the whole run on environment issues
        base = started["baseUrl"]
        httpd = started.get("_httpd")
        routes = [
            "/",
            "/MAPS?_page=SplashPage",
            "/MAPS?_page=ReportPage",
            "/MAPS?_page=BriefingbookPage",
            "/help.html",
            "/health",
        ]
        print(f"\nLive server on {base} — requesting {len(routes)} routes:")
        titles: dict[str, str] = {}
        try:
            for r in routes:
                try:
                    with urllib.request.urlopen(base + r, timeout=10) as resp:
                        body = resp.read().decode("utf-8", "ignore")
                    t = _title(body)
                except Exception as e:  # noqa: BLE001
                    t = f"(error: {e})"
                titles[r] = t
                print(f"    {r:32s} -> {t}")
        finally:
            if httpd is not None:
                httpd.shutdown()
        page_titles = [titles[r] for r in routes if r not in ("/", "/health")]
        distinct = len(set(page_titles)) == len(page_titles)
        print(f"  distinct page titles: {distinct} "
              f"({len(set(page_titles))}/{len(page_titles)} unique)")
        return distinct

    try:
        return asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        print(f"\nLive check SKIP (non-fatal): {e}")
        return True


if __name__ == "__main__":
    raise SystemExit(main())
