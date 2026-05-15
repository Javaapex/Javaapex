"""
LLM Test Pipeline
Generates migration-aware tests using an LLM, runs them, and emits lightweight documentation.

Supported today:
- Java (Maven/Gradle): generate JUnit tests under src/test/java and run mvn/gradle test.
- Python: generate pytest module under .llm_tests and run pytest.

The pipeline also generates a manual/automation test plan markdown file under .llm_tests/.
"""
import asyncio
import difflib
import json
import logging
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

from .java_test_runner import run_java_tests


class LLMTestPipelineService:
    def __init__(self):
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.deepseek_key = os.getenv("DEESEEK_API_KEY", "").strip()
        self.groq_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_base_url = (os.getenv("GROQ_BASE_URL", "") or "https://api.groq.com/openai/v1").strip().rstrip("/")
        # Groq model config (supports chat-completions API).
        self.groq_model = (os.getenv("GROQ_TEST_MODEL", "") or "llama-3.3-70b-versatile").strip()
        self.groq_models = [
            m.strip()
            for m in (os.getenv("GROQ_TEST_MODELS", "") or "").split(",")
            if m.strip()
        ] or [
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
        ]
        self.huggingface_key = os.getenv("HUGGINGFACE_API_KEY", "").strip()
        # Single-model setting (legacy).
        self.huggingface_model = (os.getenv("HUGGINGFACE_TEST_MODEL", "") or "mistralai/Mistral-7B-Instruct-v0.3").strip()
        # Multi-model fallback list (preferred). Comma-separated.
        # Example:
        #   HUGGINGFACE_TEST_MODELS=mistralai/Mistral-7B-Instruct-v0.3,HuggingFaceH4/zephyr-7b-beta,google/flan-t5-xxl
        self.huggingface_models = [
            m.strip()
            for m in (os.getenv("HUGGINGFACE_TEST_MODELS", "") or "").split(",")
            if m.strip()
        ] or [
            "mistralai/Mistral-7B-Instruct-v0.3",
            "HuggingFaceH4/zephyr-7b-beta",
            "google/flan-t5-xxl",
        ]
        self.ollama_url = (os.getenv("OLLAMA_URL", "") or "http://127.0.0.1:11434").strip().rstrip("/")
        self.ollama_model = (os.getenv("OLLAMA_MODEL", "") or "deepseek-coder:6.7b-instruct").strip()
        self.output_dir_name = ".llm_tests"
        self._openai_disabled_reason: str = ""
        self._openai_disabled_logged: bool = False
        # Cache model support checks to reduce repeated router calls/log spam.
        self._hf_chat_not_supported: set[str] = set()
        self._hf_models_not_supported: set[str] = set()
        self._ollama_unavailable: bool = False
        self._groq_rate_limited_models: set[str] = set()
        self._groq_decommissioned_models: set[str] = set()

    async def run_pipeline(self, project_path: str, provider: str) -> Dict[str, Any]:
        provider = self._normalize_provider(provider)

        project_kind = self._detect_project_kind(project_path)
        if project_kind == "java":
            # If the project is a Gradle multi-project root, ensure we didn't corrupt the root build script
            # with test dependency/task injection (tests should live in submodules).
            try:
                self._sanitize_gradle_root(project_path)
            except Exception:
                pass
        test_plan_md = await self.generate_test_plan(project_path, provider, project_kind)
        plan_path = self._write_artifact(project_path, "manual_and_automation_test_plan.md", test_plan_md)

        generated = ""
        generated_files: List[str] = []
        migrated_test_files: List[str] = []
        tests_path = ""
        test_strategy = "generate_new_tests"
        existing_test_files: List[str] = []

        if project_kind == "java":
            existing_test_files = self._list_existing_java_test_files(project_path)
            if existing_test_files:
                test_strategy = "migrate_existing_tests_and_generate_additional"
            migrated_test_files = self._apply_existing_java_test_migrations(project_path)
            suite = await self.generate_java_test_suite(project_path, provider)
            generated = suite.get("primary_content", "")
            tests_path = suite.get("primary_path", "")
            generated_files.extend(suite.get("paths", []))

            runner_result = await self._run_java_tests(project_path)
            coverage_result = await self._run_java_coverage(project_path) if runner_result.get("exit_code") == 0 else {
                "available": False,
                "message": "Skipping coverage because tests did not pass.",
            }

            # Optional iteration to chase coverage targets (best-effort).
            coverage_targets = self._get_coverage_targets()
            max_iters = int(os.getenv("LLM_TEST_MAX_ITERS", "2") or "2")
            for i in range(max_iters):
                if not coverage_result.get("available"):
                    break
                if self._coverage_meets_targets(coverage_result, coverage_targets):
                    break
                if runner_result.get("exit_code") != 0:
                    break

                iter_suite = await self._generate_java_tests_for_coverage_gaps(
                    project_path,
                    provider,
                    coverage_result,
                    iteration=i + 1,
                )
                generated_files.extend(iter_suite.get("paths", []))

                runner_result = await self._run_java_tests(project_path)
                if runner_result.get("exit_code") != 0:
                    break
                coverage_result = await self._run_java_coverage(project_path)
        else:
            generated = await self.generate_tests(project_path, provider, project_kind)
            tests_path = self._write_tests(project_path, provider, project_kind, generated)
            runner_result = await self._run_pytest(project_path)
            coverage_result = await self._run_coverage(project_path, tests_path)

        deepeval_result = await self._run_tool(
            "deepeval",
            ["evaluate", "--input", tests_path, "--format", "json"],
            "DeepEval"
        )

        garak_result = await self._run_tool(
            "garak",
            ["assess", tests_path, "-o", "json"],
            "Garak"
        )

        patch_diff = self.generate_migration_test_patches(project_path)
        patch_path = ""
        if patch_diff.strip():
            patch_path = self._write_artifact(project_path, "migration_test_patches.diff", patch_diff)

        relative = ""
        try:
            relative = str(Path(tests_path).relative_to(Path(project_path).resolve()))
        except Exception:
            relative = os.path.basename(tests_path)

        return {
            "provider": provider,
            "project_kind": project_kind,
            "test_strategy": test_strategy,
            "existing_tests_detected": len(existing_test_files),
            "existing_test_files": existing_test_files,
            "migrated_test_files": migrated_test_files,
            "generated_tests_path": tests_path,
            "generated_tests_relative": relative,
            "generated_tests": generated,
            "generated_test_files": generated_files,
            "runner": runner_result,
            "deepeval": deepeval_result,
            "garak": garak_result,
            "coverage": coverage_result,
            "manual_test_plan_path": plan_path,
            "migration_patch_path": patch_path,
        }

    def _write_kotlin_test_file(self, module_root: str, kotlin_package: str, filename: str, content: str) -> str:
        pkg = kotlin_package or "llm"
        rel_pkg = pkg.replace(".", os.sep)
        target_dir = os.path.join(module_root, "src", "test", "kotlin", rel_pkg)
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return str(Path(path).resolve())

    def _collect_kotlin_test_targets(self, project_path: str, limit: int = 8) -> List[Dict[str, str]]:
        """
        Pick representative Kotlin classes to test from src/main/kotlin in multi-module repos.
        """
        roots: List[Path] = []
        direct = Path(project_path) / "src" / "main" / "kotlin"
        if direct.exists():
            roots.append(direct)

        for p in Path(project_path).rglob("src"):
            try:
                if p.name != "src":
                    continue
                s = str(p).lower()
                if any(x in s for x in (".git", "node_modules", "\\build", "/build", "\\target", "/target", "\\.gradle", "/.gradle")):
                    continue
                candidate = p / "main" / "kotlin"
                if candidate.exists():
                    roots.append(candidate)
            except Exception:
                continue

        seen: set[str] = set()
        src_roots: List[Path] = []
        for r in roots:
            key = str(r.resolve())
            if key in seen:
                continue
            seen.add(key)
            src_roots.append(r)

        targets: List[Dict[str, str]] = []
        for src_root in src_roots:
            for kt in sorted(src_root.rglob("*.kt")):
                if len(targets) >= limit:
                    break
                name = kt.name
                if name.endswith("Application.kt") or name.endswith("Config.kt"):
                    continue
                try:
                    text = kt.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                # Skip Compose/Android heavy files when possible.
                if "androidx.compose" in text or "setcontent" in text.lower():
                    continue

                pkg = ""
                m_pkg = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*$", text, re.MULTILINE)
                if m_pkg:
                    pkg = m_pkg.group(1).strip()

                m_cls = re.search(r"\b(class|object)\s+([A-Za-z0-9_]+)\b", text)
                if not m_cls:
                    continue
                cls = m_cls.group(2).strip()

                # Prefer files with at least one function.
                if " fun " not in f" {text} " and not re.search(r"(?m)^\s*fun\s+\w+\s*\(", text):
                    continue

                snippet = "\n".join(text.splitlines()[:220])
                try:
                    module_root = str(src_root.parents[2].resolve())  # .../src/main/kotlin -> module root
                except Exception:
                    module_root = str(Path(project_path).resolve())

                targets.append({
                    "path": str(kt),
                    "relpath": str(kt.relative_to(src_root)).replace("\\", "/"),
                    "package": pkg,
                    "class": cls,
                    "snippet": snippet,
                    "module_root": module_root,
                })

        return targets

    def _get_coverage_targets(self) -> Dict[str, float]:
        # Defaults are conservative; you can set to 1.0/1.0 to demand 100%.
        line = float(os.getenv("LLM_TEST_TARGET_LINE_COVERAGE", "0.80") or "0.80")
        branch = float(os.getenv("LLM_TEST_TARGET_BRANCH_COVERAGE", "0.60") or "0.60")
        return {"line": max(0.0, min(1.0, line)), "branch": max(0.0, min(1.0, branch))}

    def _coverage_meets_targets(self, coverage: Dict[str, Any], targets: Dict[str, float]) -> bool:
        try:
            line = float(coverage.get("line_coverage", 0.0) or 0.0)
            branch = float(coverage.get("branch_coverage", 0.0) or 0.0)
        except Exception:
            return False
        return line >= targets["line"] and branch >= targets["branch"]

    def _detect_project_kind(self, project_path: str) -> str:
        root = Path(project_path)
        if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return "java"
        return "python"

    def _detect_java_build_tool(self, project_path: str) -> str:
        root = Path(project_path)
        if (root / "pom.xml").exists():
            return "maven"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return "gradle"
        return "unknown"

    async def generate_tests(self, project_path: str, provider: str, project_kind: str) -> str:
        samples = self._collect_sample_snippets(project_path)
        prompt = self._build_prompt(samples, provider, project_kind, project_path)

        response = await self._call_llm(provider, prompt)

        return response or self._fallback_tests()

    def _is_spring_boot_project(self, project_path: str) -> bool:
        root = Path(project_path)
        for candidate in [root / "pom.xml", root / "build.gradle", root / "build.gradle.kts"]:
            if not candidate.exists():
                continue
            try:
                txt = candidate.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue
            if "spring-boot" in txt or "org.springframework.boot" in txt:
                return True
        return False

    def _ensure_jacoco(self, project_path: str) -> Dict[str, Any]:
        tool = self._detect_java_build_tool(project_path)
        if tool == "maven":
            return self._ensure_jacoco_maven(project_path)
        if tool == "gradle":
            return self._ensure_jacoco_gradle(project_path)
        return {"ok": False, "message": "No Maven/Gradle build files found for JaCoCo."}

    def _ensure_jacoco_maven(self, project_path: str) -> Dict[str, Any]:
        pom_path = Path(project_path) / "pom.xml"
        if not pom_path.exists():
            return {"ok": False, "message": "pom.xml not found"}
        try:
            pom = pom_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {"ok": False, "message": f"Failed to read pom.xml: {exc}"}

        if "jacoco-maven-plugin" in pom:
            return {"ok": True, "message": "JaCoCo already present in pom.xml"}

        plugin_block = (
            "\n            <plugin>\n"
            "                <groupId>org.jacoco</groupId>\n"
            "                <artifactId>jacoco-maven-plugin</artifactId>\n"
            "                <version>0.8.12</version>\n"
            "                <executions>\n"
            "                    <execution>\n"
            "                        <id>prepare-agent</id>\n"
            "                        <goals>\n"
            "                            <goal>prepare-agent</goal>\n"
            "                        </goals>\n"
            "                    </execution>\n"
            "                    <execution>\n"
            "                        <id>report</id>\n"
            "                        <phase>test</phase>\n"
            "                        <goals>\n"
            "                            <goal>report</goal>\n"
            "                        </goals>\n"
            "                    </execution>\n"
            "                </executions>\n"
            "            </plugin>\n"
        )

        # Insert into the first <plugins> ... </plugins> block if present.
        m_plugins = re.search(r"(<plugins>)(.*?)(</plugins>)", pom, re.DOTALL)
        if m_plugins:
            new_plugins = m_plugins.group(1) + m_plugins.group(2) + plugin_block + m_plugins.group(3)
            pom2 = pom[: m_plugins.start()] + new_plugins + pom[m_plugins.end():]
        else:
            # Create a build/plugins section before </project>.
            build_block = (
                "\n    <build>\n"
                "        <plugins>\n"
                f"{plugin_block}"
                "        </plugins>\n"
                "    </build>\n"
            )
            pom2 = re.sub(r"</project>\s*$", build_block + "\n</project>\n", pom, flags=re.DOTALL)

        try:
            pom_path.write_text(pom2, encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "message": f"Failed to write pom.xml: {exc}"}
        return {"ok": True, "message": "Injected JaCoCo into pom.xml"}

    def _ensure_jacoco_gradle(self, project_path: str) -> Dict[str, Any]:
        build_groovy = Path(project_path) / "build.gradle"
        build_kts = Path(project_path) / "build.gradle.kts"
        path = build_groovy if build_groovy.exists() else build_kts
        if not path.exists():
            return {"ok": False, "message": "build.gradle(.kts) not found"}
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return {"ok": False, "message": f"Failed to read {path.name}: {exc}"}

        if "jacoco" in txt and "jacocoTestReport" in txt:
            return {"ok": True, "message": "JaCoCo already configured in Gradle build"}

        is_kts = path.name.endswith(".kts")
        if is_kts:
            inject = (
                "\nplugins {\n"
                "    jacoco\n"
                "}\n\n"
                "tasks.test {\n"
                "    finalizedBy(tasks.jacocoTestReport)\n"
                "}\n\n"
                "tasks.jacocoTestReport {\n"
                "    dependsOn(tasks.test)\n"
                "    reports {\n"
                "        xml.required.set(true)\n"
                "        html.required.set(true)\n"
                "    }\n"
                "}\n"
            )
        else:
            inject = (
                "\nplugins {\n"
                "    id 'jacoco'\n"
                "}\n\n"
                "test {\n"
                "    finalizedBy jacocoTestReport\n"
                "}\n\n"
                "jacocoTestReport {\n"
                "    dependsOn test\n"
                "    reports {\n"
                "        xml.required = true\n"
                "        html.required = true\n"
                "    }\n"
                "}\n"
            )

        # If a plugins block exists, append jacoco there; otherwise prepend the inject block.
        if re.search(r"^\s*plugins\s*\{", txt, re.MULTILINE):
            if is_kts:
                txt2 = re.sub(r"(^\s*plugins\s*\{\s*)", r"\\1\n    jacoco\n", txt, count=1, flags=re.MULTILINE)
            else:
                txt2 = re.sub(r"(^\s*plugins\s*\{\s*)", r"\\1\n    id 'jacoco'\n", txt, count=1, flags=re.MULTILINE)
            if "jacocoTestReport" not in txt2:
                txt2 = txt2 + "\n" + inject.split("}\n\n", 1)[-1]  # append tasks/report config
        else:
            txt2 = inject + "\n" + txt

        try:
            path.write_text(txt2, encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "message": f"Failed to write {path.name}: {exc}"}
        return {"ok": True, "message": f"Injected JaCoCo into {path.name}"}

    async def _run_java_coverage(self, project_path: str) -> Dict[str, Any]:
        ensure = self._ensure_jacoco(project_path)
        if not ensure.get("ok"):
            return {"available": False, "message": ensure.get("message", "Failed to enable JaCoCo")}

        tool = self._detect_java_build_tool(project_path)
        if tool == "maven":
            pom = str((Path(project_path) / "pom.xml").resolve())
            cmd = ["mvn", "test", "jacoco:report", "-f", pom]
            report_path = Path(project_path) / "target" / "site" / "jacoco" / "jacoco.xml"
        elif tool == "gradle":
            cmd = ["gradle", "test", "jacocoTestReport"]
            report_path = Path(project_path) / "build" / "reports" / "jacoco" / "test" / "jacocoTestReport.xml"
        else:
            return {"available": False, "message": "Unknown build tool for coverage."}

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            output = (stdout.decode(errors="ignore") + stderr.decode(errors="ignore")).strip()
        except FileNotFoundError:
            return {"available": False, "message": f"{cmd[0]} binary not found"}
        except Exception as exc:
            return {"available": False, "message": f"Coverage command failed: {exc}"}

        if process.returncode != 0:
            return {"available": False, "message": "Coverage command failed", "exit_code": process.returncode, "output": output}

        parsed = self._parse_jacoco_xml(report_path)
        parsed.setdefault("output", output)
        parsed.setdefault("exit_code", process.returncode)
        parsed.setdefault("report_path", str(report_path.resolve()) if report_path.exists() else str(report_path))
        parsed.setdefault("enablement", ensure)
        return parsed

    def _parse_jacoco_xml(self, report_path: Path) -> Dict[str, Any]:
        if not report_path.exists():
            return {"available": False, "message": f"JaCoCo XML not found: {report_path}"}
        try:
            tree = ET.parse(str(report_path))
            root = tree.getroot()
        except Exception as exc:
            return {"available": False, "message": f"Failed to parse JaCoCo XML: {exc}"}

        totals = {"LINE": (0, 0), "BRANCH": (0, 0), "INSTRUCTION": (0, 0)}
        for counter in root.findall("counter"):
            ctype = counter.get("type")
            if ctype in totals:
                missed = int(counter.get("missed", "0") or "0")
                covered = int(counter.get("covered", "0") or "0")
                totals[ctype] = (missed, covered)

        def pct(missed: int, covered: int) -> float:
            denom = missed + covered
            return float(covered) / float(denom) if denom > 0 else 0.0

        line_m, line_c = totals["LINE"]
        br_m, br_c = totals["BRANCH"]
        ins_m, ins_c = totals["INSTRUCTION"]

        # Collect class-level coverage to drive iterative generation.
        classes: List[Dict[str, Any]] = []
        for pkg in root.findall("package"):
            pkg_name = pkg.get("name", "")  # e.g. com/foo
            for cls in pkg.findall("class"):
                cls_name = cls.get("name", "")  # e.g. com/foo/Bar
                counters = {c.get("type"): c for c in cls.findall("counter")}
                c_line = counters.get("LINE")
                if c_line is None:
                    continue
                m = int(c_line.get("missed", "0") or "0")
                c = int(c_line.get("covered", "0") or "0")
                cov = pct(m, c)
                classes.append({
                    "package": pkg_name.replace("/", "."),
                    "name": cls_name.replace("/", "."),
                    "line_missed": m,
                    "line_covered": c,
                    "line_coverage": cov,
                })

        classes.sort(key=lambda x: (x.get("line_coverage", 1.0), -(x.get("line_missed", 0))), reverse=False)

        return {
            "available": True,
            "line_missed": line_m,
            "line_covered": line_c,
            "line_coverage": pct(line_m, line_c),
            "branch_missed": br_m,
            "branch_covered": br_c,
            "branch_coverage": pct(br_m, br_c),
            "instruction_missed": ins_m,
            "instruction_covered": ins_c,
            "instruction_coverage": pct(ins_m, ins_c),
            "classes_low_coverage": classes[:50],
        }

    async def _generate_java_tests_for_coverage_gaps(
        self,
        project_path: str,
        provider: str,
        coverage_result: Dict[str, Any],
        iteration: int,
    ) -> Dict[str, Any]:
        max_new = int(os.getenv("LLM_TEST_MAX_NEW_TESTS_PER_ITER", "4") or "4")
        low = coverage_result.get("classes_low_coverage") or []
        if not isinstance(low, list) or not low:
            return {"paths": []}

        # Map class name to source file.
        src_root = Path(project_path) / "src" / "main" / "java"
        if not src_root.exists():
            return {"paths": []}

        picked: List[Dict[str, Any]] = []
        for entry in low:
            if len(picked) >= max_new:
                break
            cls_name = (entry.get("name") or "").strip()
            if not cls_name:
                continue
            rel = cls_name.replace(".", "/") + ".java"
            path = src_root / rel
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            pkg = ""
            m_pkg = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;\s*$", text, re.MULTILINE)
            if m_pkg:
                pkg = m_pkg.group(1).strip()
            cls = cls_name.split(".")[-1]
            picked.append({
                "package": pkg or ".".join(cls_name.split(".")[:-1]),
                "class": cls,
                "relpath": rel,
                "snippet": "\n".join(text.splitlines()[:280]),
            })

        paths: List[str] = []
        for target in picked:
            pkg = target.get("package") or "llm"
            cls = target.get("class") or "Target"
            prompt = (
                "You are improving test coverage for a migrated Java codebase.\n"
                "Generate a JUnit 5 test class that increases branch/line coverage for the target class.\n"
                "- Focus on edge cases and error handling.\n"
                "- Avoid external dependencies when possible.\n"
                f"- Use package `{pkg}` and class name `{cls}CoverageIter{iteration}Test`.\n\n"
                f"Target: {target.get('relpath')}\n\n"
                f"Source snippet:\n{target.get('snippet')}\n\n"
                "Return only the Java test source file, no explanation."
            )

            content = await self._call_llm(provider, prompt)

            if not content.strip():
                content = self._fallback_java_test(pkg, f"{cls}CoverageIter{iteration}")

            if not re.search(r"^\s*package\s+[\w.]+\s*;\s*$", content, re.MULTILINE):
                content = f"package {pkg};\n\n" + content.lstrip()

            filename = f"{cls}CoverageIter{iteration}Test.java"
            p = self._write_java_test_file(project_path, pkg, filename, content)
            paths.append(p)

        return {"paths": paths}

    def _collect_java_test_targets(self, project_path: str, limit: int = 8) -> List[Dict[str, str]]:
        """
        Pick a small set of representative Java classes to test.
        This is heuristic-based: we prioritize non-framework classes with methods.
        """
        def iter_source_roots() -> List[Path]:
            # Support mono-repos / multi-module builds by scanning for src/main/java folders.
            roots: List[Path] = []
            is_agg_root = self._is_gradle_root_aggregator(project_path, project_path)
            direct = Path(project_path) / "src" / "main" / "java"
            if direct.exists() and not is_agg_root:
                roots.append(direct)

            # Search a few levels deep, avoid .git/node_modules/build dirs.
            for p in Path(project_path).rglob("src"):
                try:
                    if p.name != "src":
                        continue
                    s = str(p).lower()
                    if any(x in s for x in (".git", "node_modules", "\\build", "/build", "\\target", "/target", "\\.gradle", "/.gradle")):
                        continue
                    candidate = p / "main" / "java"
                    if candidate.exists():
                        # Skip root-level src/main/java for Gradle aggregator roots.
                        if is_agg_root and str(candidate).lower().startswith(str(Path(project_path) / "src" / "main" / "java").lower()):
                            continue
                        roots.append(candidate)
                except Exception:
                    continue

            # De-dupe preserving order.
            seen: set[str] = set()
            uniq: List[Path] = []
            for r in roots:
                key = str(r.resolve())
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(r)
            return uniq

        src_roots = iter_source_roots()
        if not src_roots:
            return []

        targets: List[Dict[str, str]] = []
        for src_root in src_roots:
            for java_file in sorted(src_root.rglob("*.java")):
                if len(targets) >= limit:
                    break

                name = java_file.name
                # Skip obvious non-behavior files.
                if name.endswith("Application.java") or name.endswith("Config.java"):
                    continue

                try:
                    text = java_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                if "@SpringBootApplication" in text:
                    continue

                pkg = ""
                m_pkg = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;\s*$", text, re.MULTILINE)
                if m_pkg:
                    pkg = m_pkg.group(1).strip()

                m_cls = re.search(r"\bpublic\s+(?:final\s+)?class\s+([A-Za-z0-9_]+)\b", text)
                if not m_cls:
                    continue
                cls = m_cls.group(1).strip()

                # Heuristic: file should contain at least one public/protected method.
                if not re.search(r"\b(public|protected)\s+[\w<>\[\]]+\s+\w+\s*\(", text):
                    continue

                snippet = "\n".join(text.splitlines()[:220])
                try:
                    module_root = str(src_root.parents[2].resolve())  # .../src/main/java -> module root
                except Exception:
                    module_root = str(Path(project_path).resolve())

                targets.append({
                    "path": str(java_file),
                    "relpath": str(java_file.relative_to(src_root)).replace("\\", "/"),
                    "package": pkg,
                    "class": cls,
                    "snippet": snippet,
                    "module_root": module_root,
                })

        # Fallback: if strict heuristics yielded nothing, pick any class file so we still generate/apply tests.
        if not targets:
            for src_root in src_roots:
                for java_file in sorted(src_root.rglob("*.java")):
                    if len(targets) >= limit:
                        break

                    name = java_file.name
                    if name.endswith("Application.java") or name.endswith("Config.java"):
                        continue

                    try:
                        text = java_file.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue

                    pkg = ""
                    m_pkg = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;\s*$", text, re.MULTILINE)
                    if m_pkg:
                        pkg = m_pkg.group(1).strip()

                    # Accept non-public classes too.
                    m_cls = re.search(r"\bclass\s+([A-Za-z0-9_]+)\b", text)
                    if not m_cls:
                        continue
                    cls = m_cls.group(1).strip()

                    snippet = "\n".join(text.splitlines()[:220])
                    try:
                        module_root = str(src_root.parents[2].resolve())
                    except Exception:
                        module_root = str(Path(project_path).resolve())

                    targets.append({
                        "path": str(java_file),
                        "relpath": str(java_file.relative_to(src_root)).replace("\\", "/"),
                        "package": pkg,
                        "class": cls,
                        "snippet": snippet,
                        "module_root": module_root,
                    })

        return targets

    def _build_java_test_prompt(self, target: Dict[str, str], project_path: str, junit_style: str) -> str:
        pkg = target.get("package") or "llm"
        cls = target.get("class") or "Target"
        relpath = target.get("relpath") or target.get("path") or ""
        snippet = target.get("snippet") or ""
        junit_style = (junit_style or "junit5").lower()
        junit_line = "- Use JUnit 5 only.\n" if junit_style == "junit5" else "- Use JUnit 4 (org.junit.Test + Assert).\n"
        return (
            "You are generating Java unit tests for a migrated Java codebase.\n"
            "Constraints:\n"
            f"{junit_line}"
            "- Avoid extra dependencies (no Mockito unless absolutely required).\n"
            "- Tests must compile even if behavior assertions are basic.\n"
            "- Prefer deterministic tests: validation, parsing, edge cases, equals/hashCode, toString, pure functions.\n"
            f"- The test must be in package `{pkg}` and named `{cls}Test`.\n\n"
            f"Target file: {relpath}\n\n"
            f"Source snippet:\n{snippet}\n\n"
            "Return only ONE Java source file (the test class), no explanation."
        )

    def _fallback_java_test(self, package: str, class_name: str, junit_style: str = "junit5") -> str:
        pkg = package or "llm"
        cls = class_name or "Target"
        junit_style = (junit_style or "junit5").lower()
        if junit_style == "junit4":
            return (
                f"package {pkg};\n\n"
                "import org.junit.Test;\n"
                "import static org.junit.Assert.*;\n\n"
                f"public class {cls}Test {{\n"
                "    @Test\n"
                "    public void generated_smoke_test() {\n"
                "        // TODO: Replace with real assertions derived from business requirements.\n"
                "        assertTrue(true);\n"
                "    }\n"
                "}\n"
            )
        return (
            f"package {pkg};\n\n"
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.*;\n\n"
            f"class {cls}Test {{\n"
            "    @Test\n"
            "    void generated_smoke_test() {\n"
            "        // TODO: Replace with real assertions derived from business requirements.\n"
            "        assertTrue(true);\n"
            "    }\n"
            "}\n"
        )

    def _coerce_junit_style(self, content: str, junit_style: str) -> str:
        """
        Best-effort normalization so the generated test compiles under the selected JUnit style.
        This is intentionally minimal (imports + common assertion class).
        """
        junit_style = (junit_style or "junit5").lower()
        out = content or ""

        if junit_style == "junit4":
            # Jupiter -> JUnit4
            out = re.sub(r"org\.junit\.jupiter\.api\.Test", "org.junit.Test", out)
            out = re.sub(r"org\.junit\.jupiter\.api\.BeforeEach", "org.junit.Before", out)
            out = re.sub(r"org\.junit\.jupiter\.api\.AfterEach", "org.junit.After", out)
            out = re.sub(r"org\.junit\.jupiter\.api\.BeforeAll", "org.junit.BeforeClass", out)
            out = re.sub(r"org\.junit\.jupiter\.api\.AfterAll", "org.junit.AfterClass", out)
            out = re.sub(r"org\.junit\.jupiter\.api\.Disabled", "org.junit.Ignore", out)
            out = re.sub(r"org\.junit\.jupiter\.api\.Assertions", "org.junit.Assert", out)
            out = re.sub(r"import\s+static\s+org\.junit\.jupiter\.api\.Assertions\.\*\s*;",
                         "import static org.junit.Assert.*;", out)
            return out

        # For JVM modules, aggressively normalize legacy JUnit 4 test code to JUnit 5.
        return self._migrate_test_content_minimally(out)

    def _iter_java_test_roots(self, project_path: str) -> List[Path]:
        roots: List[Path] = []
        direct = Path(project_path) / "src" / "test" / "java"
        if direct.exists():
            roots.append(direct)

        for p in Path(project_path).rglob("src"):
            try:
                if p.name != "src":
                    continue
                s = str(p).lower()
                if any(x in s for x in (".git", "node_modules", "\\build", "/build", "\\target", "/target", "\\.gradle", "/.gradle")):
                    continue
                candidate = p / "test" / "java"
                if candidate.exists():
                    roots.append(candidate)
            except Exception:
                continue

        seen: set[str] = set()
        unique: List[Path] = []
        for root in roots:
            try:
                key = str(root.resolve())
            except Exception:
                key = str(root)
            if key in seen:
                continue
            seen.add(key)
            unique.append(root)
        return unique

    def _list_existing_java_test_files(self, project_path: str) -> List[str]:
        files: List[str] = []
        for root in self._iter_java_test_roots(project_path):
            for java_file in sorted(root.rglob("*.java")):
                try:
                    files.append(str(java_file.resolve()))
                except Exception:
                    files.append(str(java_file))
        return files

    def _apply_existing_java_test_migrations(self, project_path: str) -> List[str]:
        modified_files: List[str] = []
        affected_modules: Dict[str, str] = {}

        for root in self._iter_java_test_roots(project_path):
            try:
                module_root = str(root.parents[2].resolve())
            except Exception:
                module_root = str(Path(project_path).resolve())

            junit_style = "junit4" if self._is_android_gradle_module(module_root) else "junit5"
            affected_modules[module_root] = junit_style

            for java_file in sorted(root.rglob("*.java")):
                try:
                    original = java_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                updated = self._coerce_junit_style(original, junit_style)
                if updated == original:
                    continue

                try:
                    java_file.write_text(updated, encoding="utf-8")
                    modified_files.append(str(java_file.resolve()))
                except Exception:
                    continue

        for mod_root, style in affected_modules.items():
            try:
                self._ensure_junit_for_module(mod_root, style)
            except Exception:
                continue

        return modified_files

    def _write_java_test_file(self, module_root: str, java_package: str, filename: str, content: str) -> str:
        pkg = java_package or "llm"
        rel_pkg = pkg.replace(".", os.sep)
        target_dir = os.path.join(module_root, "src", "test", "java", rel_pkg)
        # Use \\?\ prefix on Windows to support paths > 260 chars
        if os.name == "nt":
            target_dir = "\\\\?\\" + os.path.abspath(target_dir) if not target_dir.startswith("\\\\?\\") else target_dir
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        # Strip \\?\ prefix for display
        resolved = str(Path(path).resolve())
        return resolved

    def _is_android_gradle_module(self, module_root: str) -> bool:
        try:
            for name in ("build.gradle", "build.gradle.kts"):
                p = Path(module_root) / name
                if not p.exists():
                    continue
                txt = p.read_text(encoding="utf-8", errors="ignore").lower()
                if "com.android.application" in txt or "com.android.library" in txt or "android {" in txt:
                    return True
        except Exception:
            return False
        return False

    def _sanitize_gradle_root(self, project_path: str) -> None:
        """
        Remove/repair any previously injected unit-test snippets from the Gradle root build script.
        This prevents root script compilation errors like "Unresolved reference testImplementation" on multi-project roots.
        """
        root = Path(project_path)
        if not ((root / "settings.gradle").exists() or (root / "settings.gradle.kts").exists()):
            return

        build_file = (root / "build.gradle.kts") if (root / "build.gradle.kts").exists() else (root / "build.gradle")
        if not build_file.exists():
            return

        txt = build_file.read_text(encoding="utf-8", errors="ignore")

        # Remove any prior marked injections (future-proof).
        txt2 = re.sub(
            r"(?s)^[ \t]*//\s*LLM_TESTS_BEGIN.*?^[ \t]*//\s*LLM_TESTS_END[ \t]*\r?\n?",
            "",
            txt,
            flags=re.MULTILINE,
        )

        # Remove common unmarked injected lines/blocks.
        patterns = [
            r'(?m)^\s*testImplementation\("org\.junit\.jupiter:junit-jupiter:[^"]+"\)\s*$',
            r'(?m)^\s*testImplementation\("junit:junit:[^"]+"\)\s*$',
            r'(?m)^\s*add\("testImplementation",\s*"org\.junit\.jupiter:junit-jupiter:[^"]+"\)\s*$',
            r'(?m)^\s*add\("testImplementation",\s*"junit:junit:[^"]+"\)\s*$',
            r'(?m)^\s*useJUnitPlatform\(\)\s*$',
            r'(?m)^\s*tasks\.test\s*\{\s*$',
            r'(?m)^\s*tasks\.withType<org\.gradle\.api\.tasks\.testing\.Test>\(\)\.configureEach\s*\{\s*$',
            r'(?m)^\s*tasks\.withType\(org\.gradle\.api\.tasks\.testing\.Test\)\.configureEach\s*\{\s*$',
        ]
        for pat in patterns:
            txt2 = re.sub(pat, "", txt2)

        if txt2 != txt:
            build_file.write_text(txt2, encoding="utf-8")

    def _is_gradle_root_aggregator(self, module_root: str, project_path: str) -> bool:
        """
        Heuristic: detect a Gradle multi-project root where plugins are declared with apply false.
        We should not write tests or inject dependencies into such a root build script.
        """
        try:
            module_root = str(Path(module_root).resolve())
            project_path = str(Path(project_path).resolve())
            if module_root != project_path:
                return False

            root = Path(project_path)
            if not ((root / "settings.gradle").exists() or (root / "settings.gradle.kts").exists()):
                return False

            build = (root / "build.gradle.kts") if (root / "build.gradle.kts").exists() else (root / "build.gradle")
            if not build.exists():
                return False

            txt = build.read_text(encoding="utf-8", errors="ignore").lower()
            # Root build scripts commonly contain "apply false" for plugins and avoid dependencies.
            if "apply false" in txt and "plugins" in txt:
                return True
        except Exception:
            return False
        return False

    def _ensure_junit_for_module(self, module_root: str, junit_style: str) -> None:
        """
        Best-effort: ensure the module build config includes the right JUnit dependency.
        For Gradle JVM + JUnit5, also enables useJUnitPlatform().
        """
        junit_style = (junit_style or "junit5").lower()

        # Never touch Gradle multi-project root aggregators.
        if self._is_gradle_root_aggregator(module_root, module_root):
            return

        gradle = None
        is_kts = False
        for name in ("build.gradle.kts", "build.gradle"):
            p = Path(module_root) / name
            if p.exists():
                gradle = p
                is_kts = name.endswith(".kts")
                break

        pom = Path(module_root) / "pom.xml"

        if gradle is not None:
            try:
                txt = gradle.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return

            # Repair common Kotlin DSL mistakes from earlier generations.
            if is_kts:
                # Convert accessor-style to add("testImplementation", ...) which avoids "unresolved reference" in some scripts.
                txt = re.sub(r'(?m)^\s*testImplementation\("([^"]+)"\)\s*$', r'    add("testImplementation", "\1")', txt)
                txt = re.sub(r"(?m)^\s*tasks\.test\s*\{\s*$", r"tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {", txt)

            dep_line = ""
            if junit_style == "junit4":
                dep_line = 'testImplementation "junit:junit:4.13.2"' if not is_kts else 'add("testImplementation", "junit:junit:4.13.2")'
            else:
                dep_line = 'testImplementation "org.junit.jupiter:junit-jupiter:5.10.2"' if not is_kts else 'add("testImplementation", "org.junit.jupiter:junit-jupiter:5.10.2")'

            changed = False
            has_junit_dep = (
                "junit:junit" in txt or
                "org.junit.jupiter:junit-jupiter" in txt or
                "org.junit.jupiter:junit-jupiter-api" in txt
            )
            if not has_junit_dep:
                # Insert into dependencies block if present; otherwise append a new one.
                m = re.search(r"(?m)^[ \t]*dependencies\s*\{", txt)
                if m:
                    insert_at = m.end()
                    txt = txt[:insert_at] + "\n    " + dep_line + txt[insert_at:]
                else:
                    txt = txt.rstrip() + f"\n\ndependencies {{\n    {dep_line}\n}}\n"
                changed = True

            # For JVM Gradle modules with JUnit5, enable useJUnitPlatform(). Skip Android modules.
            if junit_style == "junit5" and not self._is_android_gradle_module(module_root):
                if "useJUnitPlatform" not in txt:
                    if is_kts:
                        txt = txt.rstrip() + "\n\ntasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {\n    useJUnitPlatform()\n}\n"
                    else:
                        txt = txt.rstrip() + "\n\ntasks.withType(org.gradle.api.tasks.testing.Test).configureEach {\n    useJUnitPlatform()\n}\n"
                    changed = True

            if changed:
                try:
                    gradle.write_text(txt, encoding="utf-8")
                except Exception:
                    return
            return

        if pom.exists():
            try:
                txt = pom.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return

            changed = False
            if junit_style == "junit4":
                dep_xml = (
                    "    <dependency>\n"
                    "      <groupId>junit</groupId>\n"
                    "      <artifactId>junit</artifactId>\n"
                    "      <version>4.13.2</version>\n"
                    "      <scope>test</scope>\n"
                    "    </dependency>\n"
                )
                if "<artifactId>junit</artifactId>" in txt:
                    dep_xml = ""
            else:
                dep_xml = (
                    "    <dependency>\n"
                    "      <groupId>org.junit.jupiter</groupId>\n"
                    "      <artifactId>junit-jupiter</artifactId>\n"
                    "      <version>5.10.2</version>\n"
                    "      <scope>test</scope>\n"
                    "    </dependency>\n"
                )
                if "<artifactId>junit-jupiter</artifactId>" in txt or "<artifactId>junit-jupiter-api</artifactId>" in txt:
                    dep_xml = ""

            # Insert dependency into existing <dependencies> block if possible.
            if dep_xml:
                m = re.search(r"</dependencies>", txt)
                if m:
                    txt = txt[:m.start()] + dep_xml + txt[m.start():]
                else:
                    project_close = re.search(r"</project>", txt)
                    if project_close:
                        txt = txt[:project_close.start()] + f"  <dependencies>\n{dep_xml}  </dependencies>\n" + txt[project_close.start():]
                    else:
                        txt = txt.rstrip() + f"\n<dependencies>\n{dep_xml}</dependencies>\n"
                changed = True

            if junit_style == "junit5" and "maven-surefire-plugin" not in txt:
                surefire_xml = (
                    "      <plugin>\n"
                    "        <groupId>org.apache.maven.plugins</groupId>\n"
                    "        <artifactId>maven-surefire-plugin</artifactId>\n"
                    "        <version>3.2.5</version>\n"
                    "      </plugin>\n"
                )
                plugins_close = re.search(r"</plugins>", txt)
                if plugins_close:
                    txt = txt[:plugins_close.start()] + surefire_xml + txt[plugins_close.start():]
                else:
                    build_close = re.search(r"</build>", txt)
                    if build_close:
                        txt = txt[:build_close.start()] + f"    <plugins>\n{surefire_xml}    </plugins>\n" + txt[build_close.start():]
                    else:
                        project_close = re.search(r"</project>", txt)
                        build_block = f"  <build>\n    <plugins>\n{surefire_xml}    </plugins>\n  </build>\n"
                        if project_close:
                            txt = txt[:project_close.start()] + build_block + txt[project_close.start():]
                        else:
                            txt = txt.rstrip() + "\n" + build_block
                changed = True

            if changed:
                try:
                    pom.write_text(txt, encoding="utf-8")
                except Exception:
                    return

    async def generate_java_test_suite(self, project_path: str, provider: str) -> Dict[str, Any]:
        """
        Generate multiple JUnit files (when possible) so projects with no legacy tests
        still receive a meaningful baseline suite.
        """
        targets = self._collect_java_test_targets(project_path, limit=8)
        kotlin_targets: List[Dict[str, str]] = []
        if not targets:
            kotlin_targets = self._collect_kotlin_test_targets(project_path, limit=8)
        is_spring = self._is_spring_boot_project(project_path)

        generated_paths: List[str] = []
        affected_modules: Dict[str, str] = {}
        primary_path = ""
        primary_content = ""

        # Always add a minimal context smoke test for Spring Boot projects.
        if is_spring:
            base_pkg = self._detect_java_base_package(project_path) or "com.example"
            smoke_pkg = base_pkg
            smoke = (
                f"package {smoke_pkg};\n\n"
                "import org.junit.jupiter.api.Test;\n"
                "import static org.junit.jupiter.api.Assertions.*;\n\n"
                "class MigrationSmokeTest {\n"
                "    @Test\n"
                "    void build_smoke() {\n"
                "        // Basic sanity check after migration.\n"
                "        assertTrue(true);\n"
                "    }\n"
                "}\n"
            )
            p = self._write_java_test_file(project_path, smoke_pkg, "MigrationSmokeTest.java", smoke)
            generated_paths.append(p)
            primary_path = primary_path or p
            primary_content = primary_content or smoke

        for target in targets:
            pkg = target.get("package") or "llm"
            cls = target.get("class") or "Target"
            module_root = target.get("module_root") or project_path
            # Skip Gradle multi-project root "aggregators" (they commonly don't apply plugins).
            if self._is_gradle_root_aggregator(module_root, project_path):
                continue
            junit_style = "junit4" if self._is_android_gradle_module(module_root) else "junit5"
            affected_modules[module_root] = junit_style
            prompt = self._build_java_test_prompt(target, project_path, junit_style=junit_style)

            content = await self._call_llm(provider, prompt)

            if not content.strip():
                content = self._fallback_java_test(pkg, cls, junit_style=junit_style)

            # Ensure package declaration exists (LLM sometimes omits it).
            if not re.search(r"^\s*package\s+[\w.]+\s*;\s*$", content, re.MULTILINE):
                content = f"package {pkg};\n\n" + content.lstrip()

            content = self._coerce_junit_style(content, junit_style=junit_style)

            filename = f"{cls}Test.java"
            try:
                p = self._write_java_test_file(module_root, pkg, filename, content)
                generated_paths.append(p)
                if not primary_path:
                    primary_path = p
                    primary_content = content
            except OSError as e:
                logger.warning("Could not write test file %s/%s: %s", module_root, filename, e)
                continue

        # If no Java targets exist, generate Kotlin unit tests instead (common in Android projects).
        for target in kotlin_targets:
            pkg = target.get("package") or "llm"
            cls = target.get("class") or "Target"
            module_root = target.get("module_root") or project_path
            if self._is_gradle_root_aggregator(module_root, project_path):
                continue
            junit_style = "junit4" if self._is_android_gradle_module(module_root) else "junit5"
            affected_modules[module_root] = junit_style

            prompt = (
                "You are generating Kotlin unit tests for a migrated Kotlin/Android codebase.\n"
                "Constraints:\n"
                + ("- Use JUnit 4 (org.junit.Test + Assert).\n" if junit_style == "junit4" else "- Use JUnit 5 (org.junit.jupiter.api.Test).\n")
                + "- Avoid extra dependencies.\n"
                + f"- The test must be in package `{pkg}` and named `{cls}Test`.\n\n"
                + f"Target file: {target.get('relpath')}\n\n"
                + f"Source snippet:\n{target.get('snippet')}\n\n"
                + "Return only ONE Kotlin test source file (.kt), no explanation."
            )

            content = await self._call_llm(provider, prompt)
            if not content.strip():
                if junit_style == "junit4":
                    content = (
                        f"package {pkg}\n\n"
                        "import org.junit.Test\n"
                        "import org.junit.Assert.*\n\n"
                        f"class {cls}Test {{\n"
                        "    @Test\n"
                        "    fun generated_smoke_test() {\n"
                        "        assertTrue(true)\n"
                        "    }\n"
                        "}\n"
                    )
                else:
                    content = (
                        f"package {pkg}\n\n"
                        "import org.junit.jupiter.api.Test\n"
                        "import org.junit.jupiter.api.Assertions.*\n\n"
                        f"class {cls}Test {{\n"
                        "    @Test\n"
                        "    fun generated_smoke_test() {\n"
                        "        assertTrue(true)\n"
                        "    }\n"
                        "}\n"
                    )

            if not re.search(r"^\s*package\s+[\w.]+\s*$", content, re.MULTILINE):
                content = f"package {pkg}\n\n" + content.lstrip()

            filename = f"{cls}Test.kt"
            p = self._write_kotlin_test_file(module_root, pkg, filename, content)
            generated_paths.append(p)
            if not primary_path:
                primary_path = p
                primary_content = content

        # Keep a copy of the primary test for easy viewing in .llm_tests as well.
        if primary_content:
            self._write_artifact(project_path, f"generated_{provider}_junit_primary.java", primary_content)

        # Best-effort: ensure JUnit dependencies/config for affected modules so generated tests compile.
        for mod_root, style in affected_modules.items():
            try:
                self._ensure_junit_for_module(mod_root, style)
            except Exception:
                continue

        return {
            "primary_path": primary_path,
            "primary_content": primary_content,
            "paths": generated_paths,
        }

    def generate_migration_test_patches(self, project_path: str) -> str:
        """
        Create a unified diff for minimal, mechanical test migrations.
        - JUnit4 -> JUnit5
        - Mockito Matchers -> ArgumentMatchers (common rename)
        - javax.* -> jakarta.* (basic import rewrite)

        This does not apply patches automatically; it writes a diff artifact so teams can review.
        """
        diffs: List[str] = []
        for root in self._iter_java_test_roots(project_path):
            try:
                module_root = str(root.parents[2].resolve())
            except Exception:
                module_root = str(Path(project_path).resolve())

            junit_style = "junit4" if self._is_android_gradle_module(module_root) else "junit5"

            for java_file in sorted(root.rglob("*.java")):
                try:
                    original = java_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                updated = self._coerce_junit_style(original, junit_style)
                if updated == original:
                    continue

                rel = str(java_file.relative_to(Path(project_path))).replace("\\", "/")
                diff_lines = difflib.unified_diff(
                    original.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
                diffs.append("".join(diff_lines))

        return "\n".join(diffs).strip() + ("\n" if diffs else "")

    def _migrate_test_content_minimally(self, content: str) -> str:
        out = content

        # JUnit 4 -> 5 imports and annotations.
        out = re.sub(r"^\s*import\s+org\.junit\.Test\s*;\s*$", "import org.junit.jupiter.api.Test;", out, flags=re.MULTILINE)
        out = re.sub(r"^\s*import\s+org\.junit\.Before\s*;\s*$", "import org.junit.jupiter.api.BeforeEach;", out, flags=re.MULTILINE)
        out = re.sub(r"^\s*import\s+org\.junit\.After\s*;\s*$", "import org.junit.jupiter.api.AfterEach;", out, flags=re.MULTILINE)
        out = re.sub(r"^\s*import\s+org\.junit\.BeforeClass\s*;\s*$", "import org.junit.jupiter.api.BeforeAll;", out, flags=re.MULTILINE)
        out = re.sub(r"^\s*import\s+org\.junit\.AfterClass\s*;\s*$", "import org.junit.jupiter.api.AfterAll;", out, flags=re.MULTILINE)
        out = re.sub(r"^\s*import\s+org\.junit\.Ignore\s*;\s*$", "import org.junit.jupiter.api.Disabled;", out, flags=re.MULTILINE)

        out = re.sub(r"\@Before\b", "@BeforeEach", out)
        out = re.sub(r"\@After\b", "@AfterEach", out)
        out = re.sub(r"\@BeforeClass\b", "@BeforeAll", out)
        out = re.sub(r"\@AfterClass\b", "@AfterAll", out)
        out = re.sub(r"\@Ignore\b", "@Disabled", out)

        # Common Assert static calls: JUnit4 Assert -> JUnit5 Assertions (import change only).
        out = re.sub(r"^\s*import\s+org\.junit\.Assert\s*;\s*$", "import org.junit.jupiter.api.Assertions;", out, flags=re.MULTILINE)
        out = re.sub(r"^\s*import\s+static\s+org\.junit\.Assert\.\*\s*;\s*$", "import static org.junit.jupiter.api.Assertions.*;", out, flags=re.MULTILINE)

        # Mockito matchers rename: Matchers -> ArgumentMatchers.
        out = re.sub(r"\borg\.mockito\.Matchers\b", "org.mockito.ArgumentMatchers", out)

        # Javax -> Jakarta imports (common during Spring Boot 3 / Jakarta migration).
        out = re.sub(r"\bjavax\.", "jakarta.", out)

        return out

    async def generate_test_plan(self, project_path: str, provider: str, project_kind: str) -> str:
        samples = self._collect_sample_snippets(project_path)
        prompt = self._build_test_plan_prompt(samples, provider, project_kind, project_path)

        response = await self._call_llm(provider, prompt)

        return response or self._fallback_test_plan(project_kind)

    def _normalize_provider(self, provider: str) -> str:
        p = (provider or "").strip().lower()
        aliases = {
            "gpt4": "openai",
            "gpt-4": "openai",
            "gpt-4.1": "openai",
            "chatgpt": "openai",
            "openai": "openai",
            "groq": "groq",
            "hf": "huggingface",
            "huggingface": "huggingface",
            "fordllm": "fordllm",
            "ford": "fordllm",
            "ollama": "ollama",
            "offline": "offline",
            "template": "offline",
            "none": "offline",
        }
        return aliases.get(p, p or "offline")

    async def _call_llm(self, provider: str, prompt: str) -> str:
        provider = self._normalize_provider(provider)
        if provider == "deepseek":
            return await self._call_deepseek(prompt)
        if provider == "groq":
            return await self._call_groq(prompt)
        if provider == "huggingface":
            return await self._call_huggingface(prompt)
        if provider == "fordllm":
            return await self._call_fordllm(prompt)
        if provider == "ollama":
            return await self._call_ollama(prompt)
        if provider == "offline":
            return ""
        return await self._call_openai(prompt)

    def _provider_model_name(self, provider: str) -> str:
        provider = self._normalize_provider(provider)
        if provider == "groq":
            return self.groq_model or "groq"
        if provider == "huggingface":
            return self.huggingface_model or "huggingface"
        if provider == "fordllm":
            return os.getenv("FORDLLM_SUB_MODEL", "gemini-2.5-pro")
        if provider == "ollama":
            return self.ollama_model or "ollama"
        if provider == "deepseek":
            return "deepseek"
        if provider == "openai":
            return "gpt-4.1"
        return provider or "offline"

    async def summarize_test_results(
        self,
        provider: str,
        test_output: str,
        tests_run: int,
        tests_passed: int,
        tests_failed: int,
    ) -> Dict[str, Any]:
        """
        Summarize the latest automated test run using the selected LLM provider.

        Returns:
          { "summary": str, "insights": [str], "model_used": str }
        """
        model_used = self._provider_model_name(provider)
        summary = f"{tests_run} tests executed. {tests_passed} passed, {tests_failed} failed."
        insights: List[str] = []

        snippet = (test_output or "").strip()
        snippet = snippet[-2200:] if len(snippet) > 2200 else snippet

        prompt = (
            "You are a software QA expert. Summarize this automated test run.\n"
            f"Counts: run={tests_run}, passed={tests_passed}, failed={tests_failed}\n\n"
            "Logs (tail):\n"
            f"{snippet}\n\n"
            "Return JSON with fields:\n"
            "- summary: short 1-sentence summary\n"
            "- insights: array of short bullets\n"
        )

        try:
            response = await self._call_llm(provider, prompt)
            json_match = re.search(r"\{.*\}", response or "", re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                summary = parsed.get("summary", summary) or summary
                parsed_insights = parsed.get("insights")
                if isinstance(parsed_insights, list):
                    insights = [str(x) for x in parsed_insights if str(x).strip()]
                elif isinstance(parsed_insights, str) and parsed_insights.strip():
                    insights = [parsed_insights.strip()]
        except Exception:
            pass

        if not insights:
            if tests_failed > 0:
                insights.append("Investigate the failing tests; the log tail contains the error details.")
            elif tests_run > 0:
                insights.append("Test suite completed without failures.")
            else:
                insights.append("No tests were executed. Fix build/config errors first, then re-run tests.")

        return {"summary": summary, "insights": insights, "model_used": model_used}

    def _collect_sample_snippets(self, project_path: str) -> List[str]:
        snippets: List[str] = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                if file.endswith(".java"):
                    try:
                        path = os.path.join(root, file)
                        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                            lines = "".join(fh.readlines()[:40])
                        snippets.append(f"// {os.path.relpath(path, project_path)}\n{lines}")
                        if len(snippets) >= 3:
                            return snippets
                    except Exception:
                        continue
        return snippets

    def _detect_java_base_package(self, project_path: str) -> str:
        src_root = Path(project_path) / "src" / "main" / "java"
        if not src_root.exists():
            return ""
        for java_file in src_root.rglob("*.java"):
            try:
                text = java_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            m = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;\s*$", text, re.MULTILINE)
            if m:
                return m.group(1).strip()
        return ""

    def _build_prompt(self, snippets: List[str], provider: str, project_kind: str, project_path: str) -> str:
        snippet_text = "\n\n".join(snippets) if snippets else "// No sample code found."

        if project_kind == "java":
            base_pkg = self._detect_java_base_package(project_path) or "com.example"
            return (
                "You are generating Java unit tests for a migrated Java codebase. "
                "Generate a single JUnit 5 test class (one .java file) that compiles under Maven/Gradle. "
                "Focus on stable behavior tests (pure functions, parsing, validation, edge cases). "
                "If dependencies are unknown, avoid mocking frameworks and keep tests minimal but meaningful. "
                f"Use package `{base_pkg}.llm`.\n\n"
                f"Sample code:\n{snippet_text}\n\n"
                "Return only the Java source file, no explanation."
            )

        return (
            "You are generating Python pytest unit tests for a Python project. "
            "Write tests that assert key behaviors and cover edge cases. "
            "Use mocks/dummy data where necessary. "
            f"Provider: {provider.upper()}.\n\nSample code:\n{snippet_text}\n\n"
            "Return only a valid pytest module, no explanation."
        )

    def _build_test_plan_prompt(self, snippets: List[str], provider: str, project_kind: str, project_path: str) -> str:
        snippet_text = "\n\n".join(snippets) if snippets else "// No sample code found."
        kind_label = "Java" if project_kind == "java" else "Python"
        return (
            f"You are acting as both a developer and QA tester. Create a concise but complete test plan for a migrated {kind_label} project.\n"
            "Include:\n"
            "- Unit test inventory: key classes/functions and what to assert.\n"
            "- Automated test plan: integration/API checks (if applicable) and regression suite.\n"
            "- Manual test cases: steps + expected results for top user flows.\n"
            "- Version-migration focus: list of tests likely to break due to dependency/runtime version changes.\n\n"
            f"Sample code:\n{snippet_text}\n\n"
            "Return only Markdown, no explanation."
        )

    async def _call_openai(self, prompt: str) -> str:
        if self._openai_disabled_reason:
            if not self._openai_disabled_logged:
                logger.warning("OpenAI disabled (%s). Falling back to template tests.", self._openai_disabled_reason)
                self._openai_disabled_logged = True
            return ""
        if not self.openai_key:
            logger.warning("OPENAI_API_KEY missing, falling back to template tests.")
            return ""
        url = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4.1",
            "input": prompt,
            "temperature": 0.2,
            "max_output_tokens": 1500
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=60) as response:
                    if response.status != 200:
                        text = await response.text()
                        logger.error("OpenAI responded %s: %s", response.status, text)
                        if response.status == 429:
                            self._openai_disabled_reason = "quota_or_rate_limited"
                            if "insufficient_quota" in (text or ""):
                                self._openai_disabled_reason = "insufficient_quota"
                        elif response.status == 401:
                            self._openai_disabled_reason = "unauthorized"
                        return ""
                    data = await response.json()
                    return self._extract_openai_text(data)
        except Exception as exc:
            logger.error("OpenAI request failed: %s", exc)
            return ""

    async def _call_groq(self, prompt: str) -> str:
        """
        Calls Groq OpenAI-compatible Chat Completions API.
        Docs: https://console.groq.com/docs/api-reference (POST /openai/v1/chat/completions)
        """
        if not self.groq_key:
            logger.warning("GROQ_API_KEY missing, falling back to template tests.")
            return ""

        url = f"{self.groq_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        async def try_model(session: aiohttp.ClientSession, model_id: str) -> str:
            if model_id in self._groq_rate_limited_models:
                return ""
            if model_id in self._groq_decommissioned_models:
                return ""
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,
                "temperature": 0.2,
                "top_p": 0.9,
            }
            async with session.post(url, json=payload, headers=headers, timeout=90) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error("Groq responded %s: %s", response.status, text)
                    if response.status == 429:
                        self._groq_rate_limited_models.add(model_id)
                    if response.status == 400 and "model_decommissioned" in (text or ""):
                        self._groq_decommissioned_models.add(model_id)
                    # Some accounts/models may not be enabled; try next model.
                    return ""
                data = await response.json()
                try:
                    return (data["choices"][0]["message"]["content"] or "").strip()
                except Exception:
                    return ""

        try:
            async with aiohttp.ClientSession() as session:
                model_candidates = list(self.groq_models)
                if self.groq_model and self.groq_model not in model_candidates:
                    model_candidates.append(self.groq_model)

                for model_id in model_candidates:
                    out = await try_model(session, model_id)
                    if out.strip():
                        self.groq_model = model_id
                        return out
        except Exception as exc:
            logger.error("Groq request failed: %s", exc)
        return ""

    async def _call_huggingface(self, prompt: str) -> str:
        if not self.huggingface_key:
            logger.warning("HUGGINGFACE_API_KEY missing, falling back to template tests.")
            return ""

        router_base = (os.getenv("HUGGINGFACE_ROUTER_BASE_URL", "") or "https://router.huggingface.co").strip().rstrip("/")

        headers = {
            "Authorization": f"Bearer {self.huggingface_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload_textgen = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 1500,
                "temperature": 0.2,
                "top_p": 0.9,
                "do_sample": True,
                "return_full_text": False,
            },
        }

        async def try_model(session: aiohttp.ClientSession, model_id: str) -> str:
            if model_id in self._hf_chat_not_supported and model_id in self._hf_models_not_supported:
                return ""

            payload_chat = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,
                "temperature": 0.2,
                "top_p": 0.9,
            }

            # Preferred: router OpenAI-compatible endpoint (works for chat/instruct style models supported by providers).
            if model_id not in self._hf_chat_not_supported:
                url_chat = f"{router_base}/v1/chat/completions"
                async with session.post(url_chat, json=payload_chat, headers=headers, timeout=90) as response:
                    if response.status == 200:
                        data = await response.json()
                        try:
                            return (data["choices"][0]["message"]["content"] or "").strip()
                        except Exception:
                            return ""

                    # If the model isn't supported for the chat route, fall back to hf-inference/models for the same model.
                    if response.status == 400:
                        try:
                            data = await response.json()
                            code = (((data or {}).get("error") or {}).get("code") or "").strip()
                            if code == "model_not_supported":
                                if model_id not in self._hf_chat_not_supported:
                                    logger.warning("Hugging Face model not supported (chat): %s", model_id)
                                self._hf_chat_not_supported.add(model_id)
                        except Exception:
                            pass
                    else:
                        text = await response.text()
                        logger.error("Hugging Face responded %s: %s", response.status, text)

            # Fallback: router HF inference "models" endpoint (works for text-generation / seq2seq style models).
            if model_id in self._hf_models_not_supported:
                return ""

            url_models = f"{router_base}/hf-inference/models/{model_id}"
            async with session.post(url_models, json=payload_textgen, headers=headers, timeout=90) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list) and data:
                        first = data[0]
                        if isinstance(first, dict):
                            return (first.get("generated_text") or "").strip()
                    if isinstance(data, dict):
                        # Some endpoints return {"generated_text": "..."} or {"text": "..."} or {"error": "..."}.
                        if data.get("error"):
                            return ""
                        return (data.get("generated_text") or data.get("text") or "").strip()
                    return ""

                # Not available via hf-inference/models for this key/account.
                if response.status in (400, 404, 410):
                    if model_id not in self._hf_models_not_supported:
                        logger.warning("Hugging Face model not supported (hf-inference): %s", model_id)
                    self._hf_models_not_supported.add(model_id)
                    return ""

                text = await response.text()
                logger.error("Hugging Face responded %s: %s", response.status, text)
                return ""

        try:
            async with aiohttp.ClientSession() as session:
                # Try fallback list first, then legacy single-model setting if it's not already included.
                model_candidates = list(self.huggingface_models)
                if self.huggingface_model and self.huggingface_model not in model_candidates:
                    model_candidates.append(self.huggingface_model)

                for model_id in model_candidates:
                    out = await try_model(session, model_id)
                    if out.strip():
                        # Persist the last working model for reporting.
                        self.huggingface_model = model_id
                        return out
        except Exception as exc:
            logger.error("Hugging Face request failed: %s", exc)
        return ""

    async def _call_ollama(self, prompt: str) -> str:
        """
        Calls a locally-running Ollama instance (free/local models).
        Requires Ollama running on `OLLAMA_URL` (default http://127.0.0.1:11434).
        """
        if self._ollama_unavailable:
            return ""

        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=120) as response:
                    if response.status != 200:
                        text = await response.text()
                        logger.error("Ollama responded %s: %s", response.status, text)
                        return ""
                    data = await response.json()
                    if isinstance(data, dict):
                        return (data.get("response") or "").strip()
        except Exception as exc:
            logger.error("Ollama request failed: %s", exc)
            # Avoid spamming logs for every prompt when Ollama isn't running.
            if "cannot connect" in str(exc).lower() or "refused" in str(exc).lower():
                self._ollama_unavailable = True
        return ""

    async def _call_deepseek(self, prompt: str) -> str:
        if not self.deepseek_key:
            logger.warning("DEESEEK_API_KEY missing, falling back to template tests.")
            return ""
        url = "https://api.deepseek.ai/v1/completions"
        headers = {
            "Authorization": f"Bearer {self.deepseek_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deeplens-alpha",
            "prompt": prompt,
            "temperature": 0.15,
            "max_tokens": 1200
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=60) as response:
                    if response.status != 200:
                        text = await response.text()
                        logger.error("DeepSeek responded %s: %s", response.status, text)
                        return ""
                    data = await response.json()
                    return self._extract_deepseek_text(data)
        except Exception as exc:
            logger.error("DeepSeek request failed: %s", exc)
            return ""

    async def _call_fordllm(self, prompt: str) -> str:
        """Call FordLLM via OpenAI-compatible client with auto token refresh."""
        try:
            from services.fordllm_auth_service import fordllm_auth
            from openai import OpenAI

            base_url = os.getenv("FORDLLM_BASE_URL", "https://api.pivpn.core.ford.com/fordllmapi/api/v1")
            model = os.getenv("FORDLLM_MODEL", "fordllm-coding-model")
            sub_model = os.getenv("FORDLLM_SUB_MODEL", "gemini-2.5-pro")

            client = OpenAI(api_key=fordllm_auth.token, base_url=base_url)
            messages = [
                {"role": "system", "content": "You are an expert Java developer and test engineer."},
                {"role": "user", "content": prompt},
            ]

            completion = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=2000,
                    temperature=0.15,
                    extra_body={"models": [sub_model]},
                ),
            )
            return completion.choices[0].message.content or ""

        except Exception as exc:
            if "401" in str(exc) or "unauthorized" in str(exc).lower():
                logger.warning("FordLLM 401 in test pipeline – refreshing token …")
                try:
                    from services.fordllm_auth_service import fordllm_auth
                    fordllm_auth.refresh_token()
                    client = OpenAI(api_key=fordllm_auth.token, base_url=base_url)
                    completion = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: client.chat.completions.create(
                            model=model,
                            messages=messages,
                            max_tokens=2000,
                            temperature=0.15,
                            extra_body={"models": [sub_model]},
                        ),
                    )
                    return completion.choices[0].message.content or ""
                except Exception as retry_exc:
                    logger.error("FordLLM retry failed: %s", retry_exc)
            else:
                logger.error("FordLLM request failed: %s", exc)
            return ""

    def _extract_openai_text(self, data: Dict[str, Any]) -> str:
        # New responses endpoint uses output list
        if isinstance(data, dict):
            outputs = data.get("output") or []
            if isinstance(outputs, list) and outputs:
                first = outputs[0]
                content = first.get("content") or []
                if isinstance(content, list) and content:
                    return "".join(chunk.get("text", "") for chunk in content if isinstance(chunk, dict))
            # fallback to choices
            choices = data.get("choices") or []
            if isinstance(choices, list) and choices:
                message = choices[0].get("message") or {}
                content = message.get("content") or []
                if isinstance(content, list) and content:
                    return "".join(chunk.get("text", "") for chunk in content if isinstance(chunk, dict))
        return ""

    def _extract_deepseek_text(self, data: Dict[str, Any]) -> str:
        if isinstance(data, dict):
            text = data.get("text") or data.get("output") or ""
            if isinstance(text, str):
                return text
        return ""

    def _fallback_tests(self) -> str:
        return (
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def sample_value():\n"
            "    return 42\n\n"
            "def test_dummy(sample_value):\n"
            "    assert sample_value == 42\n"
        )

    def _fallback_test_plan(self, project_kind: str) -> str:
        if project_kind == "java":
            return (
                "# Manual & Automation Test Plan (Fallback)\n\n"
                "## Unit Tests\n"
                "- Add JUnit tests for parsing/validation/business rules.\n\n"
                "## Automated Tests\n"
                "- Run `mvn test` (or `gradle test`) as regression.\n\n"
                "## Manual Tests\n"
                "- Smoke: build, start app, verify critical flows.\n"
            )
        return (
            "# Manual & Automation Test Plan (Fallback)\n\n"
            "## Unit Tests\n"
            "- Add pytest unit tests for key functions.\n\n"
            "## Automated Tests\n"
            "- Run `pytest` as regression.\n\n"
            "## Manual Tests\n"
            "- Smoke: start app, verify critical flows.\n"
        )

    def _write_artifact(self, project_path: str, filename: str, content: str) -> str:
        target_dir = os.path.join(project_path, self.output_dir_name)
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return str(Path(path).resolve())

    def _write_tests(self, project_path: str, provider: str, project_kind: str, content: str) -> str:
        if project_kind == "java":
            # Java suites are generated via generate_java_test_suite().
            raise ValueError("Java tests must be written via generate_java_test_suite()")

        target_dir = os.path.join(project_path, self.output_dir_name)
        os.makedirs(target_dir, exist_ok=True)
        filename = f"test_llm_{provider.replace('/', '_')}.py"
        path = os.path.join(target_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return str(Path(path).resolve())

    async def _run_pytest(self, project_path: str) -> Dict[str, Any]:
        cmd = ["pytest", "--maxfail=1", "--disable-warnings"]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            output = (stdout.decode() + stderr.decode()).strip()
            tests_run, passed, failed = self._parse_pytest_summary(output)
            return {
                "exit_code": process.returncode,
                "output": output,
                "tests_run": tests_run,
                "tests_passed": passed,
                "tests_failed": failed
            }
        except FileNotFoundError:
            message = "pytest binary not found"
            logger.warning(message)
            return {
                "exit_code": -1,
                "output": message,
                "tests_run": 0,
                "tests_passed": 0,
                "tests_failed": 0
            }
        except Exception as exc:
            logger.error("pytest execution failed: %s", exc)
            return {
                "exit_code": -1,
                "output": f"pytest failed: {exc}",
                "tests_run": 0,
                "tests_passed": 0,
                "tests_failed": 0
            }

    async def _run_java_tests(self, project_path: str) -> Dict[str, Any]:
        """
        Run Java tests via Maven/Gradle (prefer wrappers) and parse results from JUnit XML reports.
        """
        timeout = int(os.getenv("JAVA_TEST_TIMEOUT_SEC", "300") or "300")
        return await run_java_tests(project_path, timeout_sec=timeout)

    def _parse_pytest_summary(self, output: str) -> (int, int, int):
        passed = int(re.search(r"(\d+)\s+passed", output).group(1)) if re.search(r"(\d+)\s+passed", output) else 0
        failed = int(re.search(r"(\d+)\s+failed", output).group(1)) if re.search(r"(\d+)\s+failed", output) else 0
        skipped = int(re.search(r"(\d+)\s+skipped", output).group(1)) if re.search(r"(\d+)\s+skipped", output) else 0
        xfailed = int(re.search(r"(\d+)\s+xfailed", output).group(1)) if re.search(r"(\d+)\s+xfailed", output) else 0
        return passed + failed + skipped + xfailed, passed, failed

    # _parse_maven_or_gradle_summary moved to services/java_test_runner.py

    async def _run_tool(self, binary: str, args: List[str], label: str) -> Dict[str, Any]:
        tool_path = shutil.which(binary)
        if not tool_path:
            return {"available": False, "message": f"{label} binary not found"}
        try:
            process = await asyncio.create_subprocess_exec(
                tool_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            return {
                "available": True,
                "exit_code": process.returncode,
                "stdout": stdout.decode().strip(),
                "stderr": stderr.decode().strip(),
                "label": label
            }
        except Exception as exc:
            logger.error("%s execution failed: %s", label, exc)
            return {"available": False, "message": f"{label} execution failed: {exc}"}

    async def _run_coverage(self, project_path: str, tests_path: str) -> Dict[str, Any]:
        coverage_binary = shutil.which("coverage")
        if not coverage_binary:
            return {"available": False, "message": "coverage not installed"}
        try:
            run_process = await asyncio.create_subprocess_exec(
                coverage_binary,
                "run",
                "-m",
                "pytest",
                "--maxfail=1",
                "--disable-warnings",
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await run_process.communicate()
            report_process = await asyncio.create_subprocess_exec(
                coverage_binary,
                "report",
                "--omit=*/site-packages/*",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            report_out, report_err = await report_process.communicate()
            return {
                "available": True,
                "run_exit_code": run_process.returncode,
                "run_log": (stdout.decode() + stderr.decode()).strip(),
                "report_output": (report_out.decode() + report_err.decode()).strip()
            }
        except Exception as exc:
            logger.error("coverage execution failed: %s", exc)
            return {"available": False, "message": f"coverage failed: {exc}"}


llm_test_pipeline = LLMTestPipelineService()
