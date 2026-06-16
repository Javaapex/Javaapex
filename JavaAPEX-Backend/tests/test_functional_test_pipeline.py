import asyncio
import json
import tempfile
import unittest
from pathlib import Path

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
            self.assertEqual(result["total_tests"], 1)
            self.assertTrue(any(path.endswith("GeneratedRestAssuredFunctionalTest.java") for path in result["generated_files"]))
            self.assertTrue((root / ".functional_tests" / "application-profile.json").exists())
            self.assertTrue((root / ".functional_tests" / "functional-test-plan.json").exists())

            plan = json.loads((root / ".functional_tests" / "functional-test-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["planning"]["mode"], "deterministic_profile")
            paths = {test.get("path") for test in plan["tests"] if test.get("tool") == "REST_ASSURED"}
            self.assertIn("/api/customers", paths)

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


if __name__ == "__main__":
    unittest.main()
