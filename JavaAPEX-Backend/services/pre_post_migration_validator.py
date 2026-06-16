"""
Pre/Post Migration Functional Test Validator
=============================================
Runs compile checks and functional tests BEFORE and AFTER migration,
producing a comparison report so users can measure migration quality.

Workflow:
  1. PRE-MIGRATION:  Clone/backup → compile check → run existing tests → snapshot
  2. MIGRATION:       (handled by migration_orchestrator)
  3. POST-MIGRATION: Compile check → inject generated tests → run tests → compare

Usage (standalone):
    validator = PrePostMigrationValidator()
    pre = await validator.run_pre_migration(project_path)
    # ... migration happens ...
    post = await validator.run_post_migration(project_path, pre_snapshot=pre)
    report = validator.compare(pre, post)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot data classes
# ---------------------------------------------------------------------------

@dataclass
class CompileResult:
    success: bool = False
    exit_code: int = -1
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    compiled_modules: List[str] = field(default_factory=list)
    class_files_count: int = 0
    duration_sec: float = 0.0


@dataclass
class TestResult:
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_skipped: int = 0
    test_files: List[str] = field(default_factory=list)
    failures: List[Dict[str, str]] = field(default_factory=list)
    duration_sec: float = 0.0


@dataclass
class MigrationSnapshot:
    phase: str = ""              # "pre" or "post"
    timestamp: str = ""
    project_path: str = ""
    build_system: str = ""       # "gradle" or "maven"
    java_version: str = ""
    compile: CompileResult = field(default_factory=CompileResult)
    tests: TestResult = field(default_factory=TestResult)
    source_file_count: int = 0
    test_file_count: int = 0
    functional_tests_injected: int = 0
    errors_detail: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core Validator
# ---------------------------------------------------------------------------

class PrePostMigrationValidator:
    """Runs compile + test checks before and after migration."""

    GRADLE_WRAPPERS = ["gradlew.bat", "gradlew"]
    MAVEN_WRAPPERS = ["mvnw.cmd", "mvnw"]
    COMPILE_TIMEOUT = 300   # 5 min
    TEST_TIMEOUT = 600      # 10 min

    # ── Public API ────────────────────────────────────────────────────────

    async def run_pre_migration(
        self,
        project_path: str,
        backup_path: Optional[str] = None,
    ) -> MigrationSnapshot:
        """
        Run compile check and existing tests on the ORIGINAL source.
        Optionally creates a backup for later comparison.
        """
        root = Path(project_path).resolve()
        snapshot = MigrationSnapshot(
            phase="pre",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            project_path=str(root),
        )

        # Detect build system
        snapshot.build_system = self._detect_build_system(root)
        snapshot.java_version = self._detect_java_version()
        snapshot.source_file_count = self._count_files(root, "src/main", ".java")
        snapshot.test_file_count = self._count_files(root, "src/test", ".java")

        # Create backup if requested
        if backup_path:
            self._create_backup(root, Path(backup_path))

        # Compile
        logger.info("[PRE-MIGRATION] Running compile check on %s ...", root)
        snapshot.compile = await self._run_compile(root, snapshot.build_system)

        # Run existing tests
        logger.info("[PRE-MIGRATION] Running existing tests on %s ...", root)
        snapshot.tests = await self._run_tests(root, snapshot.build_system)

        logger.info(
            "[PRE-MIGRATION] Done: compile=%s tests_run=%d passed=%d failed=%d",
            snapshot.compile.success,
            snapshot.tests.tests_run,
            snapshot.tests.tests_passed,
            snapshot.tests.tests_failed,
        )
        return snapshot

    async def run_post_migration(
        self,
        project_path: str,
        pre_snapshot: Optional[MigrationSnapshot] = None,
        inject_functional_tests: bool = True,
    ) -> MigrationSnapshot:
        """
        Run compile check and tests on the MIGRATED source.
        Optionally injects generated functional tests first.
        """
        root = Path(project_path).resolve()
        snapshot = MigrationSnapshot(
            phase="post",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            project_path=str(root),
        )

        snapshot.build_system = self._detect_build_system(root)
        snapshot.java_version = self._detect_java_version()
        snapshot.source_file_count = self._count_files(root, "src/main", ".java")
        snapshot.test_file_count = self._count_files(root, "src/test", ".java")

        # Inject functional tests if available
        if inject_functional_tests:
            injected = self._inject_generated_tests(root)
            snapshot.functional_tests_injected = injected
            snapshot.test_file_count += injected

        # Compile
        logger.info("[POST-MIGRATION] Running compile check on %s ...", root)
        snapshot.compile = await self._run_compile(root, snapshot.build_system)

        # Collect compile errors for the comparison report
        if not snapshot.compile.success:
            snapshot.errors_detail = snapshot.compile.errors[:50]

        # Run tests
        logger.info("[POST-MIGRATION] Running tests on %s ...", root)
        snapshot.tests = await self._run_tests(root, snapshot.build_system)

        logger.info(
            "[POST-MIGRATION] Done: compile=%s tests_run=%d passed=%d failed=%d errors=%d",
            snapshot.compile.success,
            snapshot.tests.tests_run,
            snapshot.tests.tests_passed,
            snapshot.tests.tests_failed,
            len(snapshot.errors_detail),
        )
        return snapshot

    def compare(
        self,
        pre: MigrationSnapshot,
        post: MigrationSnapshot,
    ) -> Dict[str, Any]:
        """
        Compare pre and post migration snapshots and produce a report.
        """
        compile_delta = {
            "pre_success": pre.compile.success,
            "post_success": post.compile.success,
            "status": "PASS" if post.compile.success else (
                "REGRESSION" if pre.compile.success else "EXISTING_FAILURE"
            ),
            "pre_class_files": pre.compile.class_files_count,
            "post_class_files": post.compile.class_files_count,
            "new_errors": [e for e in post.compile.errors if e not in pre.compile.errors],
            "fixed_errors": [e for e in pre.compile.errors if e not in post.compile.errors],
        }

        test_delta = {
            "pre_run": pre.tests.tests_run,
            "post_run": post.tests.tests_run,
            "pre_passed": pre.tests.tests_passed,
            "post_passed": post.tests.tests_passed,
            "pre_failed": pre.tests.tests_failed,
            "post_failed": post.tests.tests_failed,
            "pass_rate_pre": (
                round(pre.tests.tests_passed / max(pre.tests.tests_run, 1) * 100, 1)
            ),
            "pass_rate_post": (
                round(post.tests.tests_passed / max(post.tests.tests_run, 1) * 100, 1)
            ),
            "new_failures": [
                f for f in post.tests.failures
                if f not in pre.tests.failures
            ],
        }

        # Overall migration health score (0-100)
        score = 0
        if post.compile.success:
            score += 40
        elif post.compile.class_files_count > 0:
            score += 20  # Partial compilation

        if post.tests.tests_run > 0:
            score += 20
            pass_pct = post.tests.tests_passed / max(post.tests.tests_run, 1)
            score += int(pass_pct * 40)

        return {
            "migration_health_score": min(score, 100),
            "compile": compile_delta,
            "tests": test_delta,
            "source_files": {
                "pre": pre.source_file_count,
                "post": post.source_file_count,
            },
            "test_files": {
                "pre": pre.test_file_count,
                "post": post.test_file_count,
                "injected": post.functional_tests_injected,
            },
            "post_migration_errors": post.errors_detail[:20],
            "pre_snapshot": asdict(pre),
            "post_snapshot": asdict(post),
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    def _detect_build_system(self, root: Path) -> str:
        if (root / "pom.xml").exists():
            return "maven"
        if any((root / f).exists() for f in ("build.gradle", "build.gradle.kts")):
            return "gradle"
        # Check subdirectories (multi-module)
        for sub in root.iterdir():
            if sub.is_dir():
                if (sub / "build.gradle").exists() or (sub / "build.gradle.kts").exists():
                    return "gradle"
                if (sub / "pom.xml").exists():
                    return "maven"
        return "unknown"

    def _detect_java_version(self) -> str:
        try:
            r = subprocess.run(
                ["java", "-version"], capture_output=True, text=True, timeout=10
            )
            output = r.stderr or r.stdout
            for line in output.splitlines():
                if "version" in line.lower():
                    return line.strip()
        except Exception:
            pass
        return "unknown"

    def _count_files(self, root: Path, subdir: str, ext: str) -> int:
        search_root = root
        # Try common project layouts
        for candidate in [root / subdir, root]:
            if candidate.is_dir():
                search_root = candidate
                break
        try:
            return sum(1 for _ in search_root.rglob(f"*{ext}"))
        except Exception:
            return 0

    def _create_backup(self, root: Path, backup: Path) -> None:
        try:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(root, backup, dirs_exist_ok=True)
            logger.info("Created pre-migration backup at %s", backup)
        except Exception as e:
            logger.warning("Failed to create backup: %s", e)

    def _inject_generated_tests(self, root: Path) -> int:
        """Copy generated functional test templates into the project's test directory."""
        templates_dir = Path(__file__).parent.parent / "templates" / "functional_tests"
        if not templates_dir.is_dir():
            return 0

        # Find the correct test source directory
        test_dirs = [
            root / "src" / "test" / "java",
            # Multi-module: look for *WAR/src/test/java
        ]
        for sub in root.iterdir():
            if sub.is_dir() and (sub / "src" / "test" / "java").is_dir():
                test_dirs.append(sub / "src" / "test" / "java")

        target_test_dir = None
        for td in test_dirs:
            if td.is_dir():
                target_test_dir = td
                break

        if not target_test_dir:
            # Create one
            target_test_dir = root / "src" / "test" / "java"
            target_test_dir.mkdir(parents=True, exist_ok=True)

        injected = 0
        for template in templates_dir.rglob("*.java"):
            try:
                # Detect package from file content
                pkg_dir = self._detect_package_dir(template)
                dest_dir = target_test_dir / pkg_dir
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_file = dest_dir / template.name
                if not dest_file.exists():
                    shutil.copy2(template, dest_file)
                    injected += 1
                    logger.info("Injected functional test: %s", dest_file.relative_to(root))
            except Exception as e:
                logger.warning("Failed to inject test %s: %s", template.name, e)

        return injected

    def _detect_package_dir(self, java_file: Path) -> str:
        """Read a .java file and extract its package as a directory path."""
        try:
            with open(java_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("package "):
                        pkg = line.replace("package ", "").rstrip(";").strip()
                        return pkg.replace(".", os.sep)
        except Exception:
            pass
        return "com" + os.sep + "generated" + os.sep + "tests"

    async def _run_compile(self, root: Path, build_system: str) -> CompileResult:
        """Run a compile check using the project's build system."""
        result = CompileResult()
        start = time.time()

        cmd = self._build_compile_command(root, build_system)
        if not cmd:
            result.errors.append(f"No build system detected ({build_system})")
            result.duration_sec = time.time() - start
            return result

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.COMPILE_TIMEOUT
            )
            result.exit_code = proc.returncode or 0
            result.success = result.exit_code == 0

            output = (stdout or b"").decode("utf-8", errors="ignore")
            err_output = (stderr or b"").decode("utf-8", errors="ignore")
            combined = output + "\n" + err_output

            # Extract compile errors
            for line in combined.splitlines():
                lower = line.lower()
                if "error:" in lower or "error " in lower:
                    result.errors.append(line.strip()[:200])
                elif "warning:" in lower:
                    result.warnings.append(line.strip()[:200])

            # Count generated .class files
            result.class_files_count = sum(
                1 for _ in root.rglob("*.class")
            )

            # Detect compiled modules (multi-module)
            for class_dir in root.rglob("build/classes/java/main"):
                if any(class_dir.rglob("*.class")):
                    module_name = str(
                        class_dir.relative_to(root)
                    ).split(os.sep)[0]
                    result.compiled_modules.append(module_name)

        except asyncio.TimeoutError:
            result.errors.append(f"Compile timed out after {self.COMPILE_TIMEOUT}s")
        except Exception as e:
            result.errors.append(f"Compile exception: {e}")

        result.duration_sec = round(time.time() - start, 2)
        return result

    async def _run_tests(self, root: Path, build_system: str) -> TestResult:
        """Run tests using the project's build system."""
        result = TestResult()
        start = time.time()

        cmd = self._build_test_command(root, build_system)
        if not cmd:
            result.duration_sec = time.time() - start
            return result

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.TEST_TIMEOUT
            )

            output = (stdout or b"").decode("utf-8", errors="ignore")
            err_output = (stderr or b"").decode("utf-8", errors="ignore")
            combined = output + "\n" + err_output

            # Parse test results from output
            result = self._parse_test_output(combined, root, build_system)

        except asyncio.TimeoutError:
            result.failures.append({"test": "TIMEOUT", "message": f"Tests timed out after {self.TEST_TIMEOUT}s"})
        except Exception as e:
            result.failures.append({"test": "EXCEPTION", "message": str(e)})

        result.duration_sec = round(time.time() - start, 2)
        return result

    def _build_compile_command(self, root: Path, build_system: str) -> Optional[List[str]]:
        if build_system == "gradle":
            wrapper = self._find_wrapper(root, self.GRADLE_WRAPPERS)
            if wrapper:
                return [str(wrapper), "compileJava", "--continue", "--no-daemon", "-q"]
            return ["gradle", "compileJava", "--continue", "--no-daemon", "-q"]
        elif build_system == "maven":
            wrapper = self._find_wrapper(root, self.MAVEN_WRAPPERS)
            if wrapper:
                return [str(wrapper), "compile", "-q"]
            return ["mvn", "compile", "-q"]
        return None

    def _build_test_command(self, root: Path, build_system: str) -> Optional[List[str]]:
        if build_system == "gradle":
            wrapper = self._find_wrapper(root, self.GRADLE_WRAPPERS)
            if wrapper:
                return [str(wrapper), "test", "--continue", "--no-daemon", "-q"]
            return ["gradle", "test", "--continue", "--no-daemon", "-q"]
        elif build_system == "maven":
            wrapper = self._find_wrapper(root, self.MAVEN_WRAPPERS)
            if wrapper:
                return [str(wrapper), "test", "-q"]
            return ["mvn", "test", "-q"]
        return None

    def _find_wrapper(self, root: Path, wrappers: List[str]) -> Optional[Path]:
        for w in wrappers:
            path = root / w
            if path.exists():
                return path
        # Check parent (multi-module)
        for w in wrappers:
            path = root.parent / w
            if path.exists():
                return path
        return None

    def _parse_test_output(self, output: str, root: Path, build_system: str) -> TestResult:
        """Parse test results from build tool output + XML reports."""
        result = TestResult()

        # Try parsing JUnit XML reports first
        xml_results = self._parse_junit_xml_reports(root)
        if xml_results:
            return xml_results

        # Fallback: parse from console output
        import re
        for line in output.splitlines():
            # Gradle: "BUILD SUCCESSFUL" / "X tests completed, Y failed"
            m = re.search(r"(\d+)\s+tests?\s+completed", line, re.IGNORECASE)
            if m:
                result.tests_run = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", line, re.IGNORECASE)
            if m:
                result.tests_failed = int(m.group(1))
            m = re.search(r"(\d+)\s+passed", line, re.IGNORECASE)
            if m:
                result.tests_passed = int(m.group(1))
            m = re.search(r"(\d+)\s+skipped", line, re.IGNORECASE)
            if m:
                result.tests_skipped = int(m.group(1))

            # Maven: "Tests run: X, Failures: Y, Errors: Z, Skipped: W"
            m = re.match(
                r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
                line.strip(),
            )
            if m:
                result.tests_run = int(m.group(1))
                result.tests_failed = int(m.group(2)) + int(m.group(3))
                result.tests_skipped = int(m.group(4))
                result.tests_passed = result.tests_run - result.tests_failed - result.tests_skipped

        if result.tests_run > 0 and result.tests_passed == 0:
            result.tests_passed = result.tests_run - result.tests_failed - result.tests_skipped

        return result

    def _parse_junit_xml_reports(self, root: Path) -> Optional[TestResult]:
        """Parse JUnit XML reports from build/test-results or target/surefire-reports."""
        import xml.etree.ElementTree as ET

        report_dirs = [
            root / "build" / "test-results",
            root / "target" / "surefire-reports",
        ]
        # Multi-module
        for sub in root.iterdir():
            if sub.is_dir():
                report_dirs.append(sub / "build" / "test-results")
                report_dirs.append(sub / "target" / "surefire-reports")

        xml_files = []
        for rd in report_dirs:
            if rd.is_dir():
                xml_files.extend(rd.rglob("TEST-*.xml"))

        if not xml_files:
            return None

        result = TestResult()
        for xml_file in xml_files:
            try:
                tree = ET.parse(xml_file)
                root_elem = tree.getroot()
                result.tests_run += int(root_elem.get("tests", 0))
                result.tests_failed += int(root_elem.get("failures", 0)) + int(root_elem.get("errors", 0))
                result.tests_skipped += int(root_elem.get("skipped", 0))
                result.test_files.append(str(xml_file.name))

                # Collect failure details
                for testcase in root_elem.findall(".//testcase"):
                    failure = testcase.find("failure")
                    error = testcase.find("error")
                    if failure is not None or error is not None:
                        elem = failure if failure is not None else error
                        result.failures.append({
                            "test": f"{testcase.get('classname', '')}.{testcase.get('name', '')}",
                            "message": (elem.get("message", "") or "")[:200],
                        })
            except Exception as e:
                logger.debug("Failed to parse %s: %s", xml_file, e)

        result.tests_passed = result.tests_run - result.tests_failed - result.tests_skipped
        return result


# ---------------------------------------------------------------------------
# Standalone CLI for testing
# ---------------------------------------------------------------------------

async def _main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Pre/Post Migration Validator")
    parser.add_argument("project_path", help="Path to the Java project")
    parser.add_argument("--phase", choices=["pre", "post", "both"], default="both")
    parser.add_argument("--output", default="migration_validation_report.json")
    args = parser.parse_args()

    validator = PrePostMigrationValidator()

    if args.phase in ("pre", "both"):
        pre = await validator.run_pre_migration(args.project_path)
        print(json.dumps(asdict(pre), indent=2))

    if args.phase == "both":
        post = await validator.run_post_migration(args.project_path, pre_snapshot=pre)
        report = validator.compare(pre, post)
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to {args.output}")
        print(f"Migration Health Score: {report['migration_health_score']}/100")

    if args.phase == "post":
        post = await validator.run_post_migration(args.project_path)
        print(json.dumps(asdict(post), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
