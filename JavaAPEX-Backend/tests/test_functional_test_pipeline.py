import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

# Keep the pipeline deterministic and OFFLINE for unit tests:
#  * SELENIUM_ONLY=false  → honour the per-application tool recommendation
#    (REST_ASSURED / MOCK_MVC / PLAYWRIGHT / SELENIUM) instead of forcing one tool.
#  * SELENIUM_EXTERNAL=false → never escalate to a real browser/app launch, so
#    tests don't block on app startup or attempt a network driver download.
os.environ.setdefault("FUNCTIONAL_TEST_SELENIUM_ONLY", "false")
os.environ.setdefault("FUNCTIONAL_TEST_SELENIUM_EXTERNAL", "false")

from services.functional_test_pipeline import FunctionalTestPipelineService


class FunctionalTestPipelineServiceTest(unittest.TestCase):
    def test_detects_spring_rest_api_and_generates_restassured_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").write_text("<project>spring-boot-starter-web</project>", encoding="utf-8")
            src = root / "src" / "main" / "java" / "demo"
            src.mkdir(parents=True)
            (src / "CustomerController.java").write_text(
                '@RestController @RequestMapping("/api") class CustomerController {'
                ' @GetMapping("/customers") String list(){ return "ok"; }'
                "}",
                encoding="utf-8",
            )

            service = FunctionalTestPipelineService()
            result = asyncio.run(service.run_pipeline(str(root), job_id="unit"))

            self.assertEqual(result["application_type"], "SPRING_BOOT_REST_API")
            self.assertIn("REST_ASSURED", result["recommended_tools"])
            # One real endpoint (/api/customers) plus the auto-added Spring Boot
            # actuator health check → at least one test, and both paths covered.
            self.assertGreaterEqual(result["total_tests"], 1)
            self.assertTrue(any(path.endswith("GeneratedRestAssuredFunctionalTest.java") for path in result["generated_files"]))
            self.assertTrue((root / ".functional_tests" / "application-profile.json").exists())
            self.assertTrue((root / ".functional_tests" / "functional-test-plan.json").exists())

            plan = json.loads((root / ".functional_tests" / "functional-test-plan.json").read_text(encoding="utf-8"))
            # The deterministic planner runs offline; the LLM step only upgrades the
            # label to "deterministic_profile_plus_llm" when a provider is reachable.
            self.assertTrue(str(plan["planning"]["mode"]).startswith("deterministic"))
            paths = {test.get("path") for test in plan["tests"] if test.get("tool") == "REST_ASSURED"}
            self.assertIn("/api/customers", paths)
            self.assertIn("/actuator/health", paths)

    def test_detects_spring_mvc_and_copies_mockmvc_test_into_app_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").write_text("<project>spring-boot-starter-web</project>", encoding="utf-8")
            src = root / "src" / "main" / "java" / "demo"
            src.mkdir(parents=True)
            (src / "DemoApplication.java").write_text(
                "package demo;\n@SpringBootApplication class DemoApplication {}",
                encoding="utf-8",
            )
            (src / "HomeController.java").write_text(
                "package demo;\n@Controller class HomeController { @GetMapping(\"/\") String home(){ return \"home\"; } }",
                encoding="utf-8",
            )

            service = FunctionalTestPipelineService()
            result = asyncio.run(service.run_pipeline(str(root), job_id="unit-mvc"))

            self.assertEqual(result["application_type"], "SPRING_BOOT_MVC")
            self.assertIn("MOCK_MVC", result["recommended_tools"])
            project_test = root / "src" / "test" / "java" / "demo" / "GeneratedMockMvcFunctionalTest.java"
            self.assertTrue(project_test.exists())
            self.assertIn("package demo;", project_test.read_text(encoding="utf-8"))

    def test_detects_react_ui_and_prepares_playwright_container_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"dependencies":{"react":"latest"}}', encoding="utf-8")
            pages = root / "src" / "pages"
            pages.mkdir(parents=True)
            (pages / "Customers.tsx").write_text("export default function Customers(){ return <div/> }", encoding="utf-8")

            service = FunctionalTestPipelineService()
            result = asyncio.run(service.run_pipeline(str(root), job_id="unit-ui"))

            self.assertEqual(result["application_type"], "REACT_UI")
            self.assertIn("PLAYWRIGHT", result["recommended_tools"])
            self.assertTrue(result["container_required"])
            self.assertTrue(any(path.endswith("functional.spec.ts") for path in result["generated_files"]))

    def test_detects_legacy_enterprise_app_and_generates_selenium_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web_inf = root / "src" / "main" / "webapp" / "WEB-INF"
            web_inf.mkdir(parents=True)
            (web_inf / "web.xml").write_text("<web-app></web-app>", encoding="utf-8")
            (root / "src" / "main" / "webapp" / "index.jsp").write_text("<html><body>Home</body></html>", encoding="utf-8")

            service = FunctionalTestPipelineService()
            result = asyncio.run(service.run_pipeline(str(root), job_id="unit-legacy"))

            self.assertEqual(result["application_type"], "LEGACY_ENTERPRISE_APPLICATION")
            self.assertIn("SELENIUM", result["recommended_tools"])
            self.assertTrue(any(path.endswith("GeneratedSeleniumFunctionalTest.java") for path in result["generated_files"]))
            self.assertTrue(any(path.endswith("pom.xml") and "selenium" in path.lower() for path in result["generated_files"]))


class FunctionalTestPlanDedupTest(unittest.TestCase):
    """Regression tests for the "same page repeating" fix.

    Legacy front-controller apps surface the SAME page under several route
    spellings (``/MAPS``, ``/MAPS/``, ``/MAPS?page=x``) and merging migrated +
    original source can add exact duplicates. Before the fix each variant became
    its own near-identical test (and the E2E journey walked the same page
    twice), so every captured screenshot looked the same. The plan builder must
    now collapse those to one test per DISTINCT page.
    """

    def _legacy_profile(self):
        return {
            "applicationType": "LEGACY_ENTERPRISE_APPLICATION",
            "recommendedFunctionalTools": ["SELENIUM"],
            "frameworkSignals": {"springBoot": False},
            "endpoints": [],
            "uiRoutes": [
                {"route": "/MAPS", "source_file": "MAPS.jsp"},
                {"route": "/MAPS/", "source_file": "MAPS.jsp"},
                {"route": "/MAPS?page=report", "source_file": "MAPS.jsp"},
                {"route": "/Report", "source_file": "Report.jsp"},
                "/Report/",
            ],
            "runtime": {"baseUrl": "http://localhost:8080"},
        }

    def test_front_controller_route_variants_collapse_to_distinct_pages(self):
        service = FunctionalTestPipelineService()
        plan = service.build_structured_test_plan(self._legacy_profile())

        # Five raw routes describe only two real pages.
        self.assertEqual(plan["planning"]["uiRoutesDetected"], 2)

        page_tests = [t for t in plan["tests"] if t.get("type") == "legacy-ui"]
        canonical = [service._canonical_route(t["route"]) for t in page_tests]
        # No page is exercised twice, and both real pages are covered.
        self.assertEqual(len(canonical), len(set(canonical)), f"duplicate page tests: {canonical}")
        self.assertEqual(sorted(canonical), ["/maps", "/report"])

    def test_e2e_journey_visits_each_distinct_page_once(self):
        service = FunctionalTestPipelineService()
        plan = service.build_structured_test_plan(self._legacy_profile())

        journeys = [t for t in plan["tests"] if t.get("type") == "e2e"]
        self.assertEqual(len(journeys), 1)
        navs = [a["url"] for a in journeys[0]["actions"] if a.get("type") == "navigate"]
        canonical = sorted(service._canonical_route(u) for u in navs)
        self.assertEqual(canonical, ["/maps", "/report"], f"journey repeated a page: {navs}")

    def test_canonical_route_normalizes_variants(self):
        service = FunctionalTestPipelineService()
        self.assertEqual(service._canonical_route("/MAPS/"), "/maps")
        self.assertEqual(service._canonical_route("/MAPS?page=x"), "/maps")
        self.assertEqual(service._canonical_route("/MAPS#frag"), "/maps")
        self.assertEqual(service._canonical_route("/"), "/")
        self.assertEqual(service._canonical_route(""), "/")

    def test_playwright_tool_selection_is_preserved(self):
        # Guards against dropping PLAYWRIGHT from KNOWN_FUNCTIONAL_TOOLS, which
        # would silently rewrite a valid selection to the auto recommendation.
        norm = FunctionalTestPipelineService._normalize_selected_tools
        self.assertEqual(norm("PLAYWRIGHT"), ["PLAYWRIGHT"])
        self.assertEqual(norm("playwright, rest_assured"), ["PLAYWRIGHT", "REST_ASSURED"])
        self.assertEqual(norm(["Selenium", "PLAYWRIGHT"]), ["SELENIUM", "PLAYWRIGHT"])


if __name__ == "__main__":
    unittest.main()
