"""Validation for the Selenium END-TO-END (E2E) journey tuning.

The user asked to "use E2E testing" for functional tests. Instead of a set of
isolated "open one page" checks, the pipeline now also produces a single
end-to-end journey that walks EVERY UI page in sequence (one continuous video +
a screenshot of every page in the Allure report).

This smoketest verifies, WITHOUT running Maven/Chrome, that:

  1. ``_build_selenium_e2e_journey`` chains all UI routes into ONE Selenium test
     (type=="e2e"), navigating to each page in order, and prepends a login flow
     when one is supplied. It returns None when there are too few pages.

  2. When that journey dict is handed to the deterministic ``_render_selenium``
     renderer, it produces a SINGLE @Test method that navigates to every page and
     calls attachPageScreenshot after each navigation — i.e. one E2E test whose
     Allure output is a per-page screenshot trail plus a single journey video.
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_module():
    spec = importlib.util.spec_from_file_location("ftp_isolated_e2e", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_isolated_e2e", mod)
    spec.loader.exec_module(mod)
    return mod


UI_ROUTES = [
    {"route": "/", "source_file": "index.html", "page_type": "html"},
    {"route": "/report", "source_file": "report.vm", "page_type": "html"},
    {"route": "/support", "source_file": "support.vm", "page_type": "html"},
    {"route": "/amrList", "source_file": "amrList.vm", "page_type": "html"},
    {"route": "/api/data", "source_file": "DataServlet.java"},  # API — must be excluded
]

# page_data is keyed by SOURCE FILE (not route) — exactly how the pipeline stores it.
PAGE_DATA = {
    "index.html": {"title": "MAPS Home", "headings": ["Welcome"]},
    "report.vm": {
        "title": "Report",
        "forms": [{
            "id": "reportForm",
            "fields": [
                {"name": "reportName", "type": "text"},
                {"name": "startDate", "type": "text"},
            ],
            "buttons": ["Generate"],
        }],
    },
    "support.vm": {
        "title": "Support",
        "has_tables": True,
        "table_headers": ["Ticket", "Status"],
    },
    "amrList.vm": {"title": "AMR List", "headings": ["Active AMRs"]},
}

LOGIN_ACTIONS = [
    {"type": "navigate", "url": "/login"},
    {"type": "fill", "locator": "[name=username]", "value": "admin"},
    {"type": "fill", "locator": "[name=password]", "value": "TestPassword123!"},
    {"type": "click", "locator": "button[type=submit]"},
]


def check(cond: bool, ok_msg: str, fail_msg: str, failures: list) -> None:
    if cond:
        print(f"  PASS: {ok_msg}")
    else:
        print(f"  FAIL: {fail_msg}")
        failures.append(fail_msg)


def main() -> int:
    mod = _load_pipeline_module()

    cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_build_selenium_e2e_journey"):
            cls = obj
            break
    if cls is None:
        print("FAIL: could not find class with _build_selenium_e2e_journey")
        return 1
    print(f"Using pipeline class: {cls.__name__}\n")

    inst = cls.__new__(cls)  # bypass __init__
    failures: list = []

    # ---- 1. journey builder --------------------------------------------------
    print("[1] _build_selenium_e2e_journey(ui_routes, page_data, login_actions):")
    journey = inst._build_selenium_e2e_journey(UI_ROUTES, PAGE_DATA, LOGIN_ACTIONS)
    check(journey is not None, "produced a journey", "journey was None", failures)
    if journey:
        check(journey.get("type") == "e2e" and journey.get("tool") == "SELENIUM",
              "journey is a single SELENIUM e2e test",
              f"unexpected type/tool: {journey.get('type')}/{journey.get('tool')}", failures)
        nav_urls = [a["url"] for a in journey["actions"] if a.get("type") == "navigate"]
        # login nav + 4 UI pages (the /api/data route must be excluded)
        check(nav_urls[:1] == ["/login"],
              "journey starts with the login flow",
              f"journey did not start with login: {nav_urls[:1]}", failures)
        page_navs = [u for u in nav_urls if u != "/login"]
        check(page_navs == ["/", "/report", "/support", "/amrList"],
              f"visits every UI page in order ({page_navs})",
              f"unexpected page order/coverage: {page_navs}", failures)
        check("/api/data" not in nav_urls,
              "excludes API routes from the journey",
              "API route leaked into the E2E journey", failures)

        # ---- per-page FUNCTION checks (the whole point of the request) --------
        acts = journey["actions"]
        # report.vm form must be filled + submitted inside the journey
        fills = [a for a in acts if a.get("type") == "fill"]
        filled_names = " ".join(a.get("locator", "") for a in fills)
        check("reportName" in filled_names and "startDate" in filled_names,
              "fills the real form fields on /report (reportName, startDate)",
              f"journey did not fill /report form fields: {filled_names}", failures)
        # a title assertion from real page data must appear
        title_asserts = [a for a in acts if a.get("type") == "assert_title"]
        check(any(a.get("title") == "Report" for a in title_asserts),
              "asserts the real page title on /report",
              "journey did not assert the /report page title", failures)
        # support.vm table must be verified
        table_asserts = [a for a in acts
                         if a.get("type") == "assert_visible" and a.get("locator") == "table"]
        check(len(table_asserts) >= 1,
              "verifies the data table on /support",
              "journey did not verify the /support table", failures)
        header_texts = [a.get("text") for a in acts if a.get("type") == "assert_visible"]
        check("Ticket" in header_texts and "Status" in header_texts,
              "checks the real table headers on /support (Ticket, Status)",
              f"journey missing /support table headers: {header_texts}", failures)
        # every page must guard against a server error
        err_guards = [a for a in acts
                      if a.get("type") == "assert_not_visible"
                      and "500" in str(a.get("text", ""))]
        check(len(err_guards) >= 4,
              f"guards every page against server errors ({len(err_guards)} checks)",
              f"too few error guards: {len(err_guards)}", failures)

    # too few pages -> no journey
    none_journey = inst._build_selenium_e2e_journey([{"route": "/only"}], {}, None)
    check(none_journey is None,
          "returns None when there are fewer than two pages",
          "should not build a journey for a single page", failures)

    # ---- 2. journey renders as ONE multi-page Selenium test ------------------
    print("\n[2] _render_selenium([journey], base_url):")
    java = inst._render_selenium([journey], "http://localhost:8080")
    test_count = len(re.findall(r"@Test", java))
    check(test_count == 1,
          f"renders as a single @Test method (E2E journey) [{test_count}]",
          f"expected 1 @Test, got {test_count}", failures)
    check("@Video" in java,
          "journey test is recorded (@Video)", "journey missing @Video", failures)
    shot_calls = java.count("attachPageScreenshot(driver,")
    check(shot_calls >= 4,
          f"captures a screenshot for every page in the journey ({shot_calls} calls)",
          f"too few per-page screenshots: {shot_calls}", failures)
    for url in ("/", "/report", "/support", "/amrList"):
        check(f'driver.get(baseUrl + "{url}")' in java,
              f"journey navigates to {url}",
              f"journey missing navigation to {url}", failures)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — functional tests now include a Selenium E2E journey across all pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
