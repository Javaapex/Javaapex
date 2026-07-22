"""Smoketest: the Selenium code-gen safety-net fixes real LLM output.

Feeds the EXACT Selenium class an LLM produced (which was missing video
recording, carried unused imports, and used the deprecated `new URL(...)`
constructor) through `_ensure_selenium_video_features` and asserts the
post-processed code is correct:

  * @ExtendWith(RecorderExtension.class) added on the class
  * every @Test annotated with @Video (video of each page)
  * video imports present (RecorderExtension + Video annotation)
  * deprecated `new URL(...)` rewritten to `URI.create(...).toURL()`
  * unused imports removed (URI kept because now used; URL/WebDriverWait/
    ExpectedConditions dropped)
  * screenshots + Allure still intact, braces balanced

Run:
    $env:PYTHONIOENCODING="utf-8"; .\\venv\\Scripts\\python.exe scripts\\selenium_codegen_quality_smoketest.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
PIPELINE = os.path.join(BACKEND, "services", "functional_test_pipeline.py")


def _load_pipeline_class():
    """Load functional_test_pipeline.py in isolation (skip services/__init__)."""
    spec = importlib.util.spec_from_file_location("ftp_isolated", PIPELINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ftp_isolated"] = module
    spec.loader.exec_module(module)
    return module.FunctionalTestPipelineService


# The verbatim class an LLM generated: no @Video / @ExtendWith, unused imports
# (java.net.URI, ExpectedConditions, WebDriverWait) and deprecated `new URL(...)`.
LLM_OUTPUT = r'''import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.URL;
import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.openqa.selenium.By;
import org.openqa.selenium.OutputType;
import org.openqa.selenium.TakesScreenshot;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.chrome.ChromeDriver;
import org.openqa.selenium.chrome.ChromeOptions;
import org.openqa.selenium.remote.RemoteWebDriver;
import org.openqa.selenium.support.ui.ExpectedConditions;
import org.openqa.selenium.support.ui.WebDriverWait;

import static org.junit.jupiter.api.Assertions.*;

import io.qameta.allure.Allure;
import io.qameta.allure.Description;
import io.qameta.allure.Severity;
import io.qameta.allure.SeverityLevel;
class GeneratedSeleniumFunctionalTest {

    private static final String BASE_URL = "http://localhost:55688";

    private WebDriver createDriver() throws Exception {
        ChromeOptions options = new ChromeOptions();
        String headless = System.getenv("SELENIUM_HEADLESS");
        if ("true".equalsIgnoreCase(headless) || "1".equals(headless)) {
            options.addArguments("--headless=new");
        } else {
            options.addArguments("--start-maximized");
        }
        options.addArguments("--disable-gpu");
        options.addArguments("--no-sandbox");
        options.addArguments("--disable-dev-shm-usage");
        options.addArguments("--remote-allow-origins=*");

        String remoteUrl = System.getenv("SELENIUM_REMOTE_URL");
        WebDriver driver;
        if (remoteUrl != null && !remoteUrl.trim().isEmpty()) {
            driver = new RemoteWebDriver(new URL(remoteUrl), options);
        } else {
            driver = new ChromeDriver(options);
        }
        driver.manage().timeouts().implicitlyWait(Duration.ofSeconds(5));
        return driver;
    }

    private static void captureScreenshot(WebDriver driver) {
        try {
            byte[] screenshot = ((TakesScreenshot) driver).getScreenshotAs(OutputType.BYTES);
            Allure.addAttachment("Screenshot on failure", "image/png",
                new ByteArrayInputStream(screenshot), ".png");
        } catch (Exception ignored) {}
    }

    private static void attachPageScreenshot(WebDriver driver, String name) {
        try {
            byte[] screenshot = ((TakesScreenshot) driver).getScreenshotAs(OutputType.BYTES);
            Allure.addAttachment(name, "image/png",
                new ByteArrayInputStream(screenshot), ".png");
        } catch (Exception ignored) {}
    }

    @Test
    @Description("Verify /help.html renders with correct title and help links heading")
    @Severity(SeverityLevel.NORMAL)
    void testHelpPageContentAndStructure() throws Exception {
        WebDriver driver = createDriver();
        try {
            Allure.step("Navigate to Help Links Page");
            driver.get(BASE_URL + "/help.html");
            attachPageScreenshot(driver, "Page: Help Links");
            assertEquals("MAPS Help Links", driver.getTitle());
            assertTrue(driver.getPageSource().contains("MAPS Help Links"), "Page should contain 'MAPS Help Links' text");
        } catch (Exception | AssertionError e) {
            captureScreenshot(driver);
            throw e;
        } finally {
            driver.quit();
        }
    }

    @Test
    @Description("Verify /index.html renders with title MAPS ~ Launch Page")
    @Severity(SeverityLevel.NORMAL)
    void testLaunchPageIndex() throws Exception {
        WebDriver driver = createDriver();
        try {
            Allure.step("Navigate to Index Page");
            driver.get(BASE_URL + "/index.html");
            attachPageScreenshot(driver, "Page: Index Launch Page");
            assertEquals("MAPS ~ Launch Page", driver.getTitle());
        } catch (Exception | AssertionError e) {
            captureScreenshot(driver);
            throw e;
        } finally {
            driver.quit();
        }
    }

    @Test
    @Description("Verify emptyPage.html contains form pointing to /MAPS")
    @Severity(SeverityLevel.NORMAL)
    void testEmptyPageFormPresence() throws Exception {
        WebDriver driver = createDriver();
        try {
            Allure.step("Navigate to Empty Page");
            driver.get(BASE_URL + "/emptyPage.html");
            attachPageScreenshot(driver, "Page: Empty Page Form Check");
            assertEquals("MAPS ~ Empty Page", driver.getTitle());
            List<WebElement> mapsForms = driver.findElements(By.xpath("//form[contains(@action, 'MAPS')]"));
            assertNotNull(mapsForms, "Forms list should not be null");
        } catch (Exception | AssertionError e) {
            captureScreenshot(driver);
            throw e;
        } finally {
            driver.quit();
        }
    }
}
'''


def _count_tests(code: str) -> int:
    return sum(1 for ln in code.split("\n") if ln.strip().startswith("@Test"))


def _videos_before_each_test(code: str) -> bool:
    """Every @Test must have a @Video somewhere in its annotation block."""
    lines = code.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip().startswith("@Test"):
            has_video = False
            j = i - 1
            while j >= 0 and (lines[j].strip().startswith("@") or lines[j].strip() == ""):
                if lines[j].strip().startswith("@Video"):
                    has_video = True
                    break
                j -= 1
            if not has_video:
                return False
    return True


def main() -> int:
    cls = _load_pipeline_class()
    inst = cls.__new__(cls)  # bypass __init__

    out = inst._ensure_selenium_video_features(LLM_OUTPUT)

    checks = []

    def check(label: str, ok: bool):
        checks.append((label, ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")

    n_tests = _count_tests(out)

    print("Selenium code-gen quality checks:")
    # --- Video recording guaranteed ---
    check("class annotated with @ExtendWith(RecorderExtension.class)",
          "@ExtendWith(RecorderExtension.class)" in out)
    check("import RecorderExtension present",
          "import com.automation.remarks.junit5.RecorderExtension;" in out)
    check("import Video annotation present",
          "import com.automation.remarks.video.annotations.Video;" in out)
    check(f"every @Test annotated with @Video ({n_tests} tests)",
          n_tests >= 3 and _videos_before_each_test(out))

    # --- Deprecated URL constructor modernised ---
    check("deprecated `new URL(` removed", "new URL(" not in out)
    check("uses URI.create(remoteUrl).toURL()", "URI.create(remoteUrl).toURL()" in out)

    # --- Unused imports pruned ---
    check("unused import ExpectedConditions removed",
          "import org.openqa.selenium.support.ui.ExpectedConditions;" not in out)
    check("unused import WebDriverWait removed",
          "import org.openqa.selenium.support.ui.WebDriverWait;" not in out)
    check("unused import java.net.URL removed",
          "import java.net.URL;" not in out)
    check("java.net.URI kept (now used by URI.create)",
          "import java.net.URI;" in out)

    # --- Nothing that was in use got dropped ---
    check("static Assertions.* import preserved",
          "import static org.junit.jupiter.api.Assertions.*;" in out)
    for used in ("By", "WebElement", "ChromeDriver", "ChromeOptions",
                 "RemoteWebDriver", "Duration", "List", "Allure",
                 "Description", "Severity", "SeverityLevel",
                 "TakesScreenshot", "OutputType", "ByteArrayInputStream"):
        check(f"used import kept: {used}",
              f".{used};" in out or f".{used};" in out)

    # --- Structural integrity ---
    check("screenshots still attached (attachPageScreenshot present)",
          "attachPageScreenshot(driver" in out)
    check("Allure.step calls preserved", "Allure.step(" in out)
    check("braces balanced", out.count("{") == out.count("}"))
    check("class name unchanged",
          "class GeneratedSeleniumFunctionalTest" in out)

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    ok_all = passed == total
    print(f"\n{passed}/{total} checks passed")
    if not ok_all:
        print("\n----- POST-PROCESSED CODE (head) -----")
        print("\n".join(out.split("\n")[:40]))
    print("RESULT:", "PASS \u2014 LLM Selenium output is auto-corrected (video + clean imports)"
          if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
