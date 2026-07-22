"""Validation for the CONTENT-AWARE Selenium relaxation.

The user reported that generated Selenium suites "only check the launch page" —
every test collapsed into an identical reachability check (navigate + screenshot
+ "page was served") with no real, per-page UI assertions or actions.

Root cause: when the real Java app cannot be built/started, the pipeline serves
the project's REAL pages through an in-process mock server, but the old
relaxation (``_make_selenium_lenient``) discarded every page-specific assertion.

Fix: because the mock server is LIVE at relaxation time and serves the REAL page
content, ``_relax_selenium_for_mock`` now first tries ``_make_selenium_content_aware``,
which PROBES each page and asserts what is actually rendered — the real
``<title>``, a visible heading, page content, navigation links, and a genuine
form fill + submit — so every page is truly exercised while still passing.

This smoketest verifies, WITHOUT Maven/Chrome, that:

  1. Against a tiny live server (distinct titled pages, one with a real form),
     ``_relax_selenium_for_mock`` rewrites the class in CONTENT-AWARE mode.
  2. The generated Java asserts the REAL title of each page (assertEquals),
     asserts a real visible heading, verifies navigation links, and performs a
     real form fill (sendKeys) + submit (click) with per-page screenshots.
  3. The E2E journey method still visits every page in order.
  4. The class is structurally sound (balanced braces/parens, @Video per @Test,
     required imports present, no leftover template placeholders).
  5. When NOTHING is served (dead server), it falls back to reachability-only.
"""
import importlib.util
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_module():
    spec = importlib.util.spec_from_file_location("ftp_isolated_content_aware", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_isolated_content_aware", mod)
    spec.loader.exec_module(mod)
    return mod


# ── The pages our fake mock server serves (mirrors a legacy JSP/HTML webapp) ──
PAGES = {
    "/index.html": (
        "<!DOCTYPE html><html><head><title>MAPS ~ Launch Page</title></head>"
        "<body><h1>Launch Page</h1><p>Welcome to MAPS.</p>"
        "<a href='/help.html'>Help</a> <a href='/emptyPage.html'>Form</a> "
        "<a href='/guides/iconsGuide.html'>Icons</a></body></html>"
    ),
    "/help.html": (
        "<!DOCTYPE html><html><head><title>MAPS Help Links</title></head>"
        "<body><h2>Help Links</h2><a href='/index.html'>Home</a> "
        "<a href='/guides/iconsGuide.html'>Icons Guide</a></body></html>"
    ),
    "/guides/iconsGuide.html": (
        "<!DOCTYPE html><html><head><title>Icons Guide</title></head>"
        "<body><h1>Icons Guide</h1><p>Size classes are documented here.</p>"
        "<a href='/index.html'>Home</a></body></html>"
    ),
    "/emptyPage.html": (
        "<!DOCTYPE html><html><head><title>MAPS ~ Empty Page</title></head>"
        "<body><h1>Empty Page</h1>"
        "<form action='/MAPS' method='post'>"
        "<input type='text' name='userIdCd' />"
        "<input type='text' name='requestId' />"
        "<input type='submit' value='Submit' />"
        "</form></body></html>"
    ),
}


def _synth(path: str) -> str:
    name = (path.strip("/").split("/")[-1] or "Home").replace("-", " ").replace("_", " ").title()
    return (
        f"<!DOCTYPE html><html><head><title>{name}</title></head>"
        f"<body><h1>{name}</h1><div id='content' data-mock='true'>OK</div>"
        "<a href='/index.html'>Home</a></body></html>"
    )


def _make_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a, **k):
            return

        def _send(self, html: str, status: int = 200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            clean = self.path.split("?")[0]
            if clean in ("", "/"):
                self._send(PAGES["/index.html"])
            elif clean in PAGES:
                self._send(PAGES[clean])
            else:
                self._send(_synth(clean))  # dynamic servlet route → synthesized page

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    self.rfile.read(length)
            except Exception:
                pass
            self._send(_synth(self.path.split("?")[0]))

        do_HEAD = do_GET

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True, name="content-aware-mock").start()
    return httpd, f"http://127.0.0.1:{port}"


# The lenient-style class we start from (what the user is unhappy with).
INPUT_JAVA = '''\
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.openqa.selenium.OutputType;
import org.openqa.selenium.TakesScreenshot;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.chrome.ChromeDriver;
import org.openqa.selenium.chrome.ChromeOptions;
import org.openqa.selenium.remote.RemoteWebDriver;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import io.qameta.allure.Allure;
import io.qameta.allure.Description;
import io.qameta.allure.Severity;
import io.qameta.allure.SeverityLevel;

import com.automation.remarks.junit5.RecorderExtension;
import com.automation.remarks.video.annotations.Video;

@ExtendWith(RecorderExtension.class)
class GeneratedSeleniumFunctionalTest {
    private static final String BASE_URL = System.getenv().getOrDefault("BASE_URL", "http://localhost:8080");

    private WebDriver createDriver() throws Exception {
        ChromeOptions options = new ChromeOptions();
        return new ChromeDriver(options);
    }

    static void captureScreenshot(WebDriver driver) {}
    static void attachPageScreenshot(WebDriver driver, String name) {}

    @Description("Verify the MAPS Launch Page renders")
    @Severity(SeverityLevel.CRITICAL)
    @Video
    @Test
    void testLaunchPageRendering() throws Exception {
        WebDriver driver = createDriver();
        try {
            driver.get(BASE_URL + "/index.html");
            attachPageScreenshot(driver, "Page: /index.html");
            assertNotNull(driver.getPageSource());
        } finally {
            driver.quit();
        }
    }

    @Description("Verify the MAPS Help Links page renders")
    @Severity(SeverityLevel.NORMAL)
    @Video
    @Test
    void testHelpLinksPageRendering() throws Exception {
        WebDriver driver = createDriver();
        try {
            driver.get(BASE_URL + "/help.html");
            attachPageScreenshot(driver, "Page: /help.html");
            assertNotNull(driver.getPageSource());
        } finally {
            driver.quit();
        }
    }

    @Description("Verify emptyPage.html form")
    @Severity(SeverityLevel.NORMAL)
    @Video
    @Test
    void testEmptyPageFormPresence() throws Exception {
        WebDriver driver = createDriver();
        try {
            driver.get(BASE_URL + "/emptyPage.html");
            attachPageScreenshot(driver, "Page: /emptyPage.html");
            assertNotNull(driver.getPageSource());
        } finally {
            driver.quit();
        }
    }

    @Description("E2E journey across all pages")
    @Severity(SeverityLevel.CRITICAL)
    @Video
    @Test
    void testEndToEndNavigationJourney() throws Exception {
        WebDriver driver = createDriver();
        try {
            driver.get(BASE_URL + "/index.html");
            attachPageScreenshot(driver, "Page: /index.html");
            driver.get(BASE_URL + "/help.html");
            attachPageScreenshot(driver, "Page: /help.html");
            driver.get(BASE_URL + "/guides/iconsGuide.html");
            attachPageScreenshot(driver, "Page: /guides/iconsGuide.html");
            driver.get(BASE_URL + "/emptyPage.html");
            attachPageScreenshot(driver, "Page: /emptyPage.html");
        } finally {
            driver.quit();
        }
    }

    @Description("Verify servlet /health response")
    @Severity(SeverityLevel.NORMAL)
    @Video
    @Test
    void testHealthServletResponse() throws Exception {
        WebDriver driver = createDriver();
        try {
            driver.get(BASE_URL + "/health");
            attachPageScreenshot(driver, "Page: /health");
            assertNotNull(driver.getPageSource());
        } finally {
            driver.quit();
        }
    }
}
'''


def check(cond: bool, ok_msg: str, fail_msg: str, failures: list) -> None:
    if cond:
        print(f"  PASS: {ok_msg}")
    else:
        print(f"  FAIL: {fail_msg}")
        failures.append(fail_msg)


def _balanced(text: str, open_ch: str, close_ch: str) -> bool:
    # Ignore braces/parens inside string literals for a rough structural check.
    depth = 0
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def main() -> int:
    mod = _load_pipeline_module()

    cls = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, "_make_selenium_content_aware"):
            cls = obj
            break
    if cls is None:
        print("FAIL: could not find class with _make_selenium_content_aware")
        return 1
    print(f"Using pipeline class: {cls.__name__}\n")

    inst = cls.__new__(cls)  # bypass __init__ (avoids heavy deps)
    failures: list = []

    httpd, base_url = _make_server()
    try:
        with TemporaryDirectory() as td:
            selenium_dir = Path(td) / "selenium"
            java_path = selenium_dir / "src" / "test" / "java" / "GeneratedSeleniumFunctionalTest.java"
            java_path.parent.mkdir(parents=True, exist_ok=True)
            java_path.write_text(INPUT_JAVA, encoding="utf-8")

            relaxed = inst._relax_selenium_for_mock(selenium_dir, base_url)
            out = java_path.read_text(encoding="utf-8")

            print("[1] relaxation ran and produced content-aware output:")
            check(relaxed is True, "relaxation returned True",
                  "relaxation did not return True", failures)
            check("ACTUAL page the server serves" in out,
                  "class documents it was generated from the ACTUAL served pages",
                  "content-aware NOTE header missing (fell back to reachability?)", failures)

            print("\n[2] REAL, per-page assertions (accurate UI):")
            check('driver.getTitle().trim().equals("MAPS ~ Launch Page")' in out,
                  "asserts the REAL title of /index.html (tolerant of JS title rewrites)",
                  "missing real title assertion for /index.html", failures)
            check('driver.getTitle().trim().equals("MAPS Help Links")' in out,
                  "asserts the REAL title of /help.html (tolerant of JS title rewrites)",
                  "missing real title assertion for /help.html", failures)
            check('driver.getTitle().trim().equals("MAPS ~ Empty Page")' in out,
                  "asserts the REAL title of /emptyPage.html (tolerant of JS title rewrites)",
                  "missing real title assertion for /emptyPage.html", failures)
            check('.contains("Launch Page")' in out and '.contains("Help Links")' in out,
                  "asserts real visible headings (Launch Page, Help Links)",
                  "missing real heading assertions", failures)
            check('.contains("Icons Guide")' in out,
                  "asserts the Icons Guide heading (reached inside the E2E journey)",
                  "missing Icons Guide heading assertion", failures)
            check('By.tagName("a")' in out and "should expose navigation links" in out,
                  "verifies navigation links exist on content pages",
                  "missing navigation-link verification", failures)

            print("\n[3] REAL form interaction on the form page:")
            check('By.tagName("form")' in out and "should contain a form" in out,
                  "verifies the form exists on /emptyPage.html",
                  "missing form-presence check", failures)
            check('By.cssSelector("input, textarea")' in out and 'sendKeys("Test123")' in out,
                  "actually FILLS the form fields (sendKeys)",
                  "form fields are not filled", failures)
            check("input[type=submit]" in out and ".get(0).click()" in out,
                  "actually SUBMITS the form (click)",
                  "form is not submitted", failures)
            check('"Filled form: /emptyPage.html"' in out and '"After submit: /emptyPage.html"' in out,
                  "captures screenshots of the fill + submit steps",
                  "missing fill/submit screenshots", failures)

            print("\n[4] E2E journey still visits every page in order:")
            for url in ("/index.html", "/help.html", "/guides/iconsGuide.html", "/emptyPage.html"):
                check(f'driver.get(BASE_URL + "{url}")' in out,
                      f"journey navigates to {url}",
                      f"journey missing navigation to {url}", failures)

            print("\n[5] structure & required imports:")
            # Count annotations on real code lines only (ignore // comment lines
            # so a "@Video" mentioned in the header NOTE is not miscounted).
            code_only = "\n".join(
                ln for ln in out.splitlines() if not ln.lstrip().startswith("//")
            )
            n_tests = len(re.findall(r"@Test\b", code_only))
            n_videos = len(re.findall(r"@Video\b", code_only))
            check(n_tests == 5, f"kept all 5 @Test methods [{n_tests}]",
                  f"expected 5 @Test, got {n_tests}", failures)
            check(n_videos == n_tests, f"every @Test is recorded (@Video={n_videos})",
                  f"@Video ({n_videos}) != @Test ({n_tests})", failures)
            check(_balanced(out, "{", "}"), "braces are balanced",
                  "unbalanced braces in generated class", failures)
            check(_balanced(out, "(", ")"), "parentheses are balanced",
                  "unbalanced parentheses in generated class", failures)
            check("{v}" not in out and "{er}" not in out,
                  "no leftover template placeholders",
                  "template placeholder leaked into generated Java", failures)
            for imp in (
                "import static org.junit.jupiter.api.Assertions.assertEquals;",
                "import static org.junit.jupiter.api.Assertions.assertTrue;",
                "import org.openqa.selenium.By;",
                "import org.openqa.selenium.WebElement;",
                "import java.util.List;",
            ):
                check(imp in out, f"imports present: {imp.split('.')[-1].rstrip(';')}",
                      f"missing import: {imp}", failures)

            print("\n[6] fallback to reachability when nothing is served (dead server):")
            aware_none = inst._make_selenium_content_aware(INPUT_JAVA, "http://127.0.0.1:9")
            check(aware_none is None,
                  "content-aware returns None against an unreachable server",
                  "content-aware did not fall back on a dead server", failures)
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        return 1
    print("RESULT: PASS — Selenium relaxation now generates accurate, per-page UI tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
