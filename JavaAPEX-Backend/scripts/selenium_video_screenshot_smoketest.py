"""Validation for the Selenium-only video + per-page screenshot tuning.

The user asked to tune the LLM pipeline so this repo produces **Selenium only**
with an **Allure report that contains a screenshot of every page and a video**.

This smoketest verifies, WITHOUT running Maven/Chrome, that:

  1. ``_render_selenium_pom`` now declares the automation-remarks video-recorder
     dependencies, keeps the run going on failures (testFailureIgnore), disables
     AWT headless so the screen recorder can capture the browser, and configures
     the recorder to save a video for EVERY test.

  2. ``_render_selenium`` (the deterministic fallback renderer) emits a class that
     is wired for video (@ExtendWith(RecorderExtension.class) + @Video), takes a
     screenshot of every page (attachPageScreenshot after each navigation) and
     defaults Chrome to a VISIBLE window (SELENIUM_HEADLESS toggle) so the video
     shows the browser.

  3. ``_ensure_selenium_video_features`` upgrades *LLM-generated* code that omitted
     the video/screenshot wiring — adding imports, the class extension, @Video on
     every @Test, per-page screenshot calls after driver.get(...) and the helper
     methods — and is idempotent.
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
PIPELINE = BACKEND / "services" / "functional_test_pipeline.py"


def _load_pipeline_module():
    """Load functional_test_pipeline without triggering services/__init__."""
    spec = importlib.util.spec_from_file_location("ftp_isolated_sel_video", str(PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ftp_isolated_sel_video", mod)
    spec.loader.exec_module(mod)
    return mod


# An LLM-style class that FORGOT the video + screenshot wiring entirely.
LLM_WITHOUT_VIDEO = (
    "import org.junit.jupiter.api.Test;\n"
    "import org.openqa.selenium.WebDriver;\n"
    "import org.openqa.selenium.chrome.ChromeDriver;\n"
    "import org.openqa.selenium.chrome.ChromeOptions;\n"
    "import static org.junit.jupiter.api.Assertions.*;\n\n"
    "class GeneratedSeleniumFunctionalTest {\n"
    "    @Test\n"
    "    void loadsReportPage() throws Exception {\n"
    "        ChromeOptions options = new ChromeOptions();\n"
    "        options.addArguments(\"--headless=new\");\n"
    "        WebDriver driver = new ChromeDriver(options);\n"
    "        try {\n"
    "            driver.get(\"http://localhost:8080/report\");\n"
    "            assertNotNull(driver.getTitle());\n"
    "        } finally {\n"
    "            driver.quit();\n"
    "        }\n"
    "    }\n\n"
    "    @Test\n"
    "    void loadsSupportPage() throws Exception {\n"
    "        WebDriver driver = new ChromeDriver(new ChromeOptions());\n"
    "        try {\n"
    "            driver.get(\"http://localhost:8080/support\");\n"
    "            assertTrue(driver.getPageSource().length() > 0);\n"
    "        } finally {\n"
    "            driver.quit();\n"
    "        }\n"
    "    }\n"
    "}\n"
)


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
        if isinstance(obj, type) and hasattr(obj, "_render_selenium_pom"):
            cls = obj
            break
    if cls is None:
        print("FAIL: could not find class with _render_selenium_pom")
        return 1
    print(f"Using pipeline class: {cls.__name__}\n")

    inst = cls.__new__(cls)  # bypass __init__ (avoids heavy deps)
    failures: list = []

    # ---- 1. pom.xml ----------------------------------------------------------
    print("[1] _render_selenium_pom():")
    pom = inst._render_selenium_pom()
    check("video-recorder-junit5" in pom,
          "declares video-recorder-junit5", "pom missing video-recorder-junit5", failures)
    check("video-recorder-allure" in pom,
          "declares video-recorder-allure (attaches video to Allure)",
          "pom missing video-recorder-allure", failures)
    check("<testFailureIgnore>true</testFailureIgnore>" in pom,
          "testFailureIgnore=true so every page is reported",
          "pom missing testFailureIgnore", failures)
    check("java.awt.headless=false" in pom,
          "AWT non-headless so the recorder can capture the browser",
          "pom missing java.awt.headless=false argLine", failures)
    check("<video.save.mode>ALL</video.save.mode>" in pom,
          "records/saves a video for EVERY test (save.mode ALL)",
          "pom missing video.save.mode ALL", failures)
    check("<video.enabled>true</video.enabled>" in pom,
          "video recording enabled", "pom missing video.enabled", failures)
    check("allure-junit5" in pom and "allure-maven" in pom,
          "Allure report plugins present", "pom missing Allure plugins", failures)

    # ---- 2. deterministic fallback renderer ----------------------------------
    print("\n[2] _render_selenium(tests, base_url) fallback:")
    tests = [
        {"name": "Report page", "route": "/report", "page_type": "html",
         "actions": [{"type": "navigate", "url": "/report"}]},
        {"name": "Support page", "route": "/support", "page_type": "html"},  # no actions -> fallback nav
    ]
    java = inst._render_selenium(tests, "http://localhost:8080")
    check("@ExtendWith(RecorderExtension.class)" in java,
          "class wired with RecorderExtension (video)",
          "fallback missing @ExtendWith(RecorderExtension.class)", failures)
    video_count = len(re.findall(r"@Video", java))
    test_count = len(re.findall(r"@Test", java))
    check(video_count == test_count and test_count >= 2,
          f"@Video on every @Test ({video_count}/{test_count})",
          f"@Video/@Test mismatch ({video_count}/{test_count})", failures)
    check("import com.automation.remarks.junit5.RecorderExtension;" in java
          and "import com.automation.remarks.video.annotations.Video;" in java,
          "video-recorder imports present", "fallback missing video-recorder imports", failures)
    check("void attachPageScreenshot(" in java,
          "attachPageScreenshot helper defined", "fallback missing attachPageScreenshot helper", failures)
    check(java.count("attachPageScreenshot(driver,") >= 2,
          f"per-page screenshot after each navigation ({java.count('attachPageScreenshot(driver,')} calls)",
          "fallback missing per-page attachPageScreenshot calls", failures)
    check('System.getenv().getOrDefault("SELENIUM_HEADLESS"' in java,
          "Chrome visible by default (SELENIUM_HEADLESS toggle) so video shows the browser",
          "fallback missing SELENIUM_HEADLESS toggle", failures)

    # ---- 3. LLM safety-net ---------------------------------------------------
    print("\n[3] _ensure_selenium_video_features(llm_code):")
    upgraded = inst._ensure_selenium_video_features(LLM_WITHOUT_VIDEO)
    check("@ExtendWith(RecorderExtension.class)" in upgraded,
          "adds class-level RecorderExtension",
          "did not add @ExtendWith(RecorderExtension.class)", failures)
    up_video = len(re.findall(r"@Video", upgraded))
    up_test = len(re.findall(r"@Test", upgraded))
    check(up_video == up_test and up_test == 2,
          f"adds @Video to every @Test ({up_video}/{up_test})",
          f"@Video/@Test mismatch after upgrade ({up_video}/{up_test})", failures)
    check("import com.automation.remarks.video.annotations.Video;" in upgraded
          and "import com.automation.remarks.junit5.RecorderExtension;" in upgraded,
          "injects the missing video imports", "missing video imports after upgrade", failures)
    check(upgraded.count("attachPageScreenshot(driver,") >= 2,
          f"injects a per-page screenshot after each driver.get(...) ({upgraded.count('attachPageScreenshot(driver,')} calls)",
          "did not inject attachPageScreenshot calls", failures)
    check("void attachPageScreenshot(" in upgraded,
          "defines the attachPageScreenshot helper it now references",
          "did not define attachPageScreenshot helper", failures)

    # idempotency: running again must not add duplicates.
    twice = inst._ensure_selenium_video_features(upgraded)
    check(twice.count("@ExtendWith(RecorderExtension.class)") == 1
          and len(re.findall(r"@Video", twice)) == up_video
          and twice.count("attachPageScreenshot(driver,") == upgraded.count("attachPageScreenshot(driver,"),
          "idempotent (no duplicate wiring on a second pass)",
          "NOT idempotent — duplicated video/screenshot wiring", failures)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — Selenium generates video + per-page screenshots for the Allure report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
