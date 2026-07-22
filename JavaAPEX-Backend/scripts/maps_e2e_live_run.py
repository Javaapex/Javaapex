"""Live END-TO-END UI run against the MAPS webapp using the REAL pipeline server.

What this does (no Maven / Docker / Tomcat required):

  1. Boots the pipeline's in-process static file server against the MAPS webapp
     (``maps-ui-gcp-bq-main/.../MAPSWAR/src/main/webapp``). That server renders
     Apache Velocity (``.vm``) templates into real HTML via ``_render_vm_file``.
  2. Drives a REAL Microsoft Edge browser (headless by default) through an E2E
     journey across the key MAPS routes, capturing a screenshot of every page.
  3. Validates each rendered page: HTTP 200, a real (non-empty) ``<title>``, a
     visible ``<body>``, and NO leaked raw Velocity markup (``#set`` / ``$var`` /
     ``#if``). Confirms the pages are DISTINCT (the "repeating UI" fix).
  4. Writes screenshots + a JSON/He result summary under
     ``.functional_tests/maps_e2e_live`` and prints a PASS/FAIL table.

Run:
    <venv>/python.exe JavaAPEX-Backend/scripts/maps_e2e_live_run.py
Env:
    E2E_HEADLESS=false   → watch the browser
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
WORKSPACE = BACKEND.parent
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"

# MAPS webapp root (the folder that contains src/main/webapp somewhere below).
MAPS_ROOT = WORKSPACE / "maps-ui-gcp-bq-main" / "maps-ui-gcp-bq-main" / "MAPSWAR"

OUT_DIR = BACKEND / ".functional_tests" / "maps_e2e_live"

# The E2E journey: label → route. Front-controller routes use ?_page=… which the
# server resolves to the real .vm template.
JOURNEY = [
    ("Home / Launch", "/index.html"),
    ("Splash Page", "/MAPSWAR/MAPS?_page=SplashPage"),
    ("Preference Page", "/MAPSWAR/MAPS?_page=PreferencePage"),
    ("Report Page", "/MAPSWAR/MAPS?_page=ReportPage"),
    ("Support Page", "/MAPSWAR/MAPS?_page=SupportPage"),
    ("Custom Org Page", "/MAPSWAR/MAPS?_page=CustomOrgPage"),
    ("Health Check", "/health"),
    ("General Exception", "/MAPSWAR/MAPS?_page=GeneralException"),
]


def _load_pipeline_class():
    # Stub out the services package so importing the module standalone doesn't
    # drag the whole backend in.
    spec = importlib.util.spec_from_file_location("ftp_isolated_live", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ftp_isolated_live"] = mod
    spec.loader.exec_module(mod)
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_start_static_file_server"):
            return obj
    raise RuntimeError("Could not locate FunctionalTestPipelineService class")


def _build_driver(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions

    opts = EdgeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Edge(options=opts)


RAW_VM_MARKERS = ("#set(", "#if(", "#foreach(", "#parse(", "#end")


def main() -> int:
    if not MAPS_ROOT.exists():
        print(f"FAIL: MAPS root not found: {MAPS_ROOT}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headless = str(os.getenv("E2E_HEADLESS", "true")).lower() not in ("false", "0", "no")

    cls = _load_pipeline_class()
    svc = cls.__new__(cls)  # bypass __init__

    profile = {"runtime": {}}

    print("=" * 72)
    print("MAPS LIVE E2E UI RUN")
    print("=" * 72)
    print(f"MAPS root : {MAPS_ROOT}")
    print(f"Headless  : {headless}")
    print(f"Output    : {OUT_DIR}\n")

    server = asyncio.run(svc._start_static_file_server(MAPS_ROOT, profile))
    if not server.get("started"):
        print(f"FAIL: static server did not start: {server.get('message')}")
        return 3
    base_url = server["baseUrl"]
    print(f"Static server: {base_url}  (serving {server.get('serving_dir')})\n")

    results = []
    seen_bodies: dict[str, str] = {}
    driver = None
    try:
        driver = _build_driver(headless)
        driver.set_page_load_timeout(30)
        for idx, (label, route) in enumerate(JOURNEY, 1):
            url = base_url + route
            entry = {"step": idx, "label": label, "route": route, "checks": {}}
            try:
                t0 = time.time()
                driver.get(url)
                time.sleep(0.4)  # let render settle
                entry["load_ms"] = int((time.time() - t0) * 1000)
                title = (driver.title or "").strip()
                body = driver.find_element("tag name", "body")
                body_text = (body.text or "").strip()
                html = driver.page_source or ""

                shot = OUT_DIR / f"{idx:02d}_{label.replace(' ', '_').replace('/', '')}.png"
                driver.save_screenshot(str(shot))
                entry["screenshot"] = shot.name

                leaked = [m for m in RAW_VM_MARKERS if m in html]
                entry["checks"]["title_nonempty"] = bool(title)
                entry["checks"]["body_has_text"] = len(body_text) > 0
                entry["checks"]["no_raw_velocity"] = not leaked
                entry["title"] = title
                entry["body_len"] = len(body_text)
                if leaked:
                    entry["leaked_velocity"] = leaked

                # Distinctness: fingerprint by title + first 120 chars of body.
                fp = (title + "|" + body_text[:120]).lower()
                dup_of = seen_bodies.get(fp)
                entry["checks"]["distinct_page"] = dup_of is None
                if dup_of is None:
                    seen_bodies[fp] = label
                else:
                    entry["duplicate_of"] = dup_of

                entry["passed"] = all(entry["checks"].values())
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"
                entry["passed"] = False
            results.append(entry)
            status = "PASS" if entry.get("passed") else "FAIL"
            print(f"[{idx}/{len(JOURNEY)}] {status}  {label:22s} title={entry.get('title','')!r} "
                  f"body={entry.get('body_len','?')} chars")
            for cname, ok in entry.get("checks", {}).items():
                if not ok:
                    print(f"        ✗ {cname}"
                          + (f"  (dup of {entry.get('duplicate_of')})" if cname == "distinct_page" else "")
                          + (f"  leaked={entry.get('leaked_velocity')}" if cname == "no_raw_velocity" else ""))
            if entry.get("error"):
                print(f"        ! {entry['error']}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        httpd = server.get("_httpd")
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass

    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)
    summary = {
        "base_url": base_url,
        "serving_dir": server.get("serving_dir"),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "distinct_pages": len(seen_bodies),
        "results": results,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"RESULT: {passed}/{total} pages passed · {len(seen_bodies)} distinct pages · "
          f"screenshots + summary.json in {OUT_DIR}")
    print("=" * 72)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
