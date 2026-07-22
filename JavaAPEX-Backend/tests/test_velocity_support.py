"""Unit tests for first-class Velocity (.vm) functional-test support.

Covers the new detection + generation logic added to the pipeline and the pure
``velocity_test_templates`` module. Runs fully OFFLINE — no network, Docker,
browser or Maven required.
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("FUNCTIONAL_TEST_SELENIUM_ONLY", "false")
os.environ.setdefault("FUNCTIONAL_TEST_SELENIUM_EXTERNAL", "false")

from services import velocity_test_templates as V
from services.functional_test_pipeline import FunctionalTestPipelineService


REPORT_VM = """#set( $_PAGE = "ReportPage")
<html><body>
  <h1>$title</h1>
  #if($show)
    <p>visible: $userName</p>
  #else
    <p>hidden</p>
  #end
  <ul>
  #foreach($row in $rows)
    <li>$row.name = $row.value</li>
  #end
  </ul>
</body></html>
"""

FRAGMENT_VM = "<div>$partialThing</div>"


class VelocityModuleTest(unittest.TestCase):
    def _make_project(self, tmp: str) -> Path:
        root = Path(tmp)
        tdir = root / "src" / "main" / "webapp" / "templates"
        tdir.mkdir(parents=True)
        (tdir / "ReportPage.vm").write_text(REPORT_VM, encoding="utf-8")
        # a fragment/partial that must be ignored
        comp = tdir / "components"
        comp.mkdir()
        (comp / "menu.vm").write_text(FRAGMENT_VM, encoding="utf-8")
        (tdir / "header.include.vm").write_text(FRAGMENT_VM, encoding="utf-8")
        # web.xml declaring a front controller
        webinf = root / "src" / "main" / "webapp" / "WEB-INF"
        webinf.mkdir(parents=True)
        (webinf / "web.xml").write_text(
            "<web-app><servlet><servlet-name>fc</servlet-name>"
            "<servlet-class>com.x.PageTableFrontController</servlet-class></servlet>"
            "<servlet-mapping><servlet-name>fc</servlet-name>"
            "<url-pattern>/MAPS</url-pattern></servlet-mapping></web-app>",
            encoding="utf-8",
        )
        return root

    def test_detect_velocity_templates_filters_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(tmp)
            files = list(root.rglob("*"))
            templates = V.detect_velocity_templates([p for p in files if p.is_file()])
            names = {t["name"] for t in templates}
            self.assertIn("ReportPage", names)
            self.assertNotIn("menu", names)        # in components/ → ignored
            self.assertNotIn("header.include", names)  # *.include.vm → ignored

    def test_page_key_from_set_directive(self):
        templates = [{
            "template": "ReportPage.vm", "name": "ReportPage",
            "page_key": V._page_key_from_text(REPORT_VM, "ReportPage"),
            "source_file": "ReportPage.vm",
        }]
        self.assertEqual(templates[0]["page_key"], "ReportPage")

    def test_map_templates_to_front_controller_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(tmp)
            files = [p for p in root.rglob("*") if p.is_file()]
            templates = V.detect_velocity_templates(files)
            routes = V.map_templates_to_routes(templates, files, "/MAPS")
            report = next(r for r in routes if r["name"] == "ReportPage")
            self.assertEqual(report["route"], "/MAPS?_page=ReportPage")

    def test_analyze_template_finds_branches_and_collections(self):
        info = V.analyze_template(REPORT_VM)
        self.assertIn("rows", info["collections"])
        self.assertTrue(info["has_if"])
        self.assertTrue(info["has_foreach"])
        self.assertIn("title", info["scalars"])

    def test_layer1_junit_generation_contains_assertions(self):
        info = V.analyze_template(REPORT_VM)
        code = V.render_layer1_junit([
            {"template": "ReportPage.vm", "name": "ReportPage", "analysis": info}
        ])
        self.assertIn("class GeneratedVelocityRenderTest", code)
        self.assertIn("Jsoup.parse", code)
        self.assertIn("XSS_PAYLOAD", code)
        self.assertIn("templatesRenderCleanly", code)
        self.assertIn("empty", code)  # #foreach empty/single/multi cases
        self.assertIn("ReportPage.vm", code)

    def test_layer1_pom_has_velocity_and_jsoup(self):
        pom = V.render_layer1_pom()
        self.assertIn("velocity-engine-core", pom)
        self.assertIn("jsoup", pom)
        self.assertIn("junit-jupiter", pom)

    def test_layer2_selenium_is_edge_first(self):
        code = V.render_layer2_selenium([{"name": "ReportPage", "route": "/MAPS?_page=ReportPage"}])
        self.assertIn("EdgeDriver", code)
        self.assertIn("/MAPS?_page=ReportPage", code)

    def test_degradation_reasons_map_covers_2_1_to_2_6(self):
        for code in ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6"]:
            rec = V.degradation_reason(code, "detail")
            self.assertEqual(rec["code"], code)
            self.assertTrue(rec["reason"])
            self.assertEqual(rec["detail"], "detail")


class PipelineVelocityIntegrationTest(unittest.TestCase):
    def test_profile_classifies_server_rendered_web_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").write_text("<project>war</project>", encoding="utf-8")
            tdir = root / "src" / "main" / "webapp" / "templates"
            tdir.mkdir(parents=True)
            (tdir / "ReportPage.vm").write_text(REPORT_VM, encoding="utf-8")
            webinf = root / "src" / "main" / "webapp" / "WEB-INF"
            webinf.mkdir(parents=True)
            (webinf / "web.xml").write_text(
                "<web-app><servlet><servlet-name>fc</servlet-name>"
                "<servlet-class>com.x.PageTableFrontController</servlet-class></servlet>"
                "<servlet-mapping><servlet-name>fc</servlet-name>"
                "<url-pattern>/MAPS</url-pattern></servlet-mapping></web-app>",
                encoding="utf-8",
            )

            svc = FunctionalTestPipelineService()
            profile = svc.build_application_profile(root)

            self.assertTrue(profile["frameworkSignals"]["velocity"])
            self.assertTrue(profile["frameworkSignals"]["hasUi"])
            self.assertNotIn("MANUAL_REVIEW", profile["recommendedFunctionalTools"])
            self.assertIn("SELENIUM", profile["recommendedFunctionalTools"])
            self.assertTrue(profile["velocityTemplates"])
            report = next(r for r in profile["velocityRoutes"] if r["name"] == "ReportPage")
            self.assertEqual(report["route"], "/MAPS?_page=ReportPage")

    def test_render_test_scripts_emits_layer1_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pom.xml").write_text("<project>war</project>", encoding="utf-8")
            tdir = root / "src" / "main" / "webapp" / "templates"
            tdir.mkdir(parents=True)
            (tdir / "ReportPage.vm").write_text(REPORT_VM, encoding="utf-8")

            svc = FunctionalTestPipelineService()
            profile = svc.build_application_profile(root)
            profile.setdefault("runtime", {})["baseUrl"] = "http://localhost:8080"
            out = root / ".functional_tests"
            generated = svc.render_test_scripts(out, profile, {"tests": []})

            self.assertTrue(any("velocity/pom.xml" in g for g in generated))
            self.assertTrue(any("GeneratedVelocityRenderTest.java" in g for g in generated))
            self.assertTrue((out / "velocity" / "pom.xml").exists())

    def test_execution_result_includes_degradation_reasons_field(self):
        svc = FunctionalTestPipelineService()
        res = svc._execution_result("passed", "ok")
        self.assertIn("degradation_reasons", res)
        self.assertEqual(res["degradation_reasons"], [])


if __name__ == "__main__":
    unittest.main()
