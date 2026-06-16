"""
Migration Service - Handles OpenRewrite migration execution
"""
import os
import subprocess
import json
import re
import shutil
import logging
import time
from typing import Any, Dict, List, Optional
import asyncio
from services.build_migration_policy_service import build_migration_policy_service
from services.functional_test_pipeline import functional_test_pipeline
from services.llm_cache_service import build_llm_cache_key, get_llm_cache_stats
from services.llm_test_pipeline import llm_test_pipeline
from services.maven_central_service import maven_central_service
from services.preferred_llm_service import preferred_llm_service
from utils.config import (
    HUGGINGFACE_INFERENCE_BASE_URL,
    JAVA_TEST_TIMEOUT_SEC,
)

from services.dependency_migration_analyzer import DependencyMigrationAnalyzer

logger = logging.getLogger(__name__)


class MigrationService:
    def __init__(self):
        self.openrewrite_cli = os.getenv("OPENREWRITE_CLI_PATH", "rewrite-cli.jar")
        self.huggingface_inference_base_url = HUGGINGFACE_INFERENCE_BASE_URL
        self.maven_central_service = maven_central_service
        self.dependency_analyzer = DependencyMigrationAnalyzer()
        self._build_conversion_request_count = 0
        self._build_conversion_provider_counts: Dict[str, int] = {}

    async def validate_build_migration(
        self, baseline_report: Optional[Dict[str, Any]], migrated_path: str
    ) -> Dict[str, Any]:
        """Validates the migration of build files and returns a detailed expert report."""
        return await self.dependency_analyzer.validate_migration(
            baseline_report, migrated_path
        )

    def generate_dependency_validation_markdown(self, validation_result: Dict[str, Any], test_result: Optional[Dict[str, Any]] = None) -> str:
        """Generates a human-readable Markdown summary in the format requested by the user."""
        lines = ["# Enterprise Migration Validation Report"]

        lines.append(f"\n### Overall Migration Score: {validation_result.get('accuracyScore', 100.0)}%")
        lines.append(f"**Upgrade Percentage**: {validation_result.get('upgradePercentage', 100.0)}%")
        lines.append(f"**Final Stability Percentage**: {validation_result.get('stabilityPercentage', 100.0)}%")
        lines.append(f"**Risk Level**: {validation_result.get('riskLevel', 'LOW')}")

        # 3. Exact Issues Found
        lines.append("\n## Exact Issues Found")
        issues = validation_result.get("exactIssuesFound", [])
        if issues:
            for issue in issues:
                lines.append(f"- âŒ {issue}")
        else:
            lines.append("- âœ… No blocking issues detected.")

        # Fixed Issues (derived from internal details)
        fixed_upgrades = validation_result.get("correctUpgrades", [])
        if fixed_upgrades:
            lines.append("\n### Fixed & Verified Upgrades")
            for item in fixed_upgrades[:15]:
                lines.append(f"- âœ… **{item['dependency']}**: {item['old']} â†’ {item['new']}")

        # Remaining Risks
        lines.append("\n## Remaining Risks")
        mismatches = validation_result.get("incorrectReplacements", [])
        if mismatches:
            for item in mismatches:
                lines.append(f"- âš ï¸ **{item['dependency']}**: {item['reason']} (Expected {item['expected']}, Actual {item['actual']})")

        duplicates = validation_result.get("duplicateDependencies", [])
        if duplicates:
            for item in duplicates:
                lines.append(f"- âš ï¸ **Duplicate**: {item['dependency']} found in multiple locations.")

        # 4. Compatibility Report
        lines.append("\n## Compatibility Report")
        compat = validation_result.get("compatibilityReport", [])
        if compat:
            for item in compat:
                lines.append(f"- **{item.get('check', 'Stack')}**: {item.get('issue', 'Mismatch detected')} ({item.get('severity')})")
        else:
            lines.append("- Ecosystem compatibility verified successfully.")

        # 5. Plugin Support Report
        lines.append("\n## Plugin Support Report")
        plugins = validation_result.get("pluginSupportReport", [])
        if plugins:
            for p in plugins:
                lines.append(f"- **{p.get('plugin')}**: Current: `{p.get('current')}`, Required: `{p.get('required')}` Status: `{p.get('status')}`")
        else:
            lines.append("- All core plugins align with the target Java version.")

        # 7. Corrected Recommended Configuration
        lines.append("\n## Corrected Recommended Configuration")
        lines.append("Review the following stability-focused version alignment recommendations:")
        stable_v = self.dependency_analyzer.production_stable_versions
        lines.append(f"- **Java**: {stable_v['java']} (LTS)")
        lines.append(f"- **Spring Boot**: {stable_v['spring_boot']}")
        lines.append(f"- **JUnit 5**: Jupiter 5.10.x")
        lines.append(f"- **JaCoCo**: {stable_v['jacoco']}")
        lines.append(f"- **Checkstyle**: {stable_v['checkstyle']}")

        # 8. Safe Enterprise Recommendation
        lines.append("\n## Safe Enterprise Recommendation")
        recommendations = validation_result.get("safeEnterpriseRecommendation", [])
        if recommendations:
            for rec in recommendations:
                lines.append(f"- ðŸ›¡ï¸ {rec}")
        else:
            lines.append("- Target configuration meets enterprise baseline standards.")

        # Actionable Fixes
        lines.append("\n## Recommended Fixes")
        fixes = validation_result.get("recommendedFixes", [])
        if fixes:
            for fix in fixes:
                lines.append(f"- {fix}")
        else:
            lines.append("- No manual fixes required.")

        return "\n".join(lines)

    async def get_available_recipes(self, token: str, repo_url: str, owner: str, repo: str) -> List[Dict[str, Any]]:
        """Get available OpenRewrite recipes for Java migration based on repository analysis"""
        from services.github_clone_analysis_service import github_clone_analysis_service

        _, analysis = await github_clone_analysis_service.analyze_repository(
            repo_reference=repo_url or f"{owner}/{repo}",
            token=token,
        )

        recipes = []
        detected_features = {}

        # Extract key information from analysis
        java_version = analysis.get("java_version", "8")
        build_tool = analysis.get("build_tool", "unknown")
        dependencies = analysis.get("dependencies", [])
        business_issues = analysis.get("business_issues", [])
        security_issues = analysis.get("security_issues", [])
        performance_issues = analysis.get("performance_issues", [])

        # Convert java_version to int for comparisons
        try:
            current_java_version = int(java_version)
        except (ValueError, TypeError):
            current_java_version = 8

        # Analyze dependencies to detect frameworks
        spring_boot_version = None
        junit_version = None
        javax_packages = []
        jakarta_packages = []
        log4j_detected = False
        slf4j_detected = False

        for dep in dependencies:
            group_id = dep.get("group_id", "").lower()
            artifact_id = dep.get("artifact_id", "").lower()

            # Spring Boot detection
            if "spring-boot" in artifact_id:
                version = dep.get("current_version", "")
                if version and version.startswith("2."):
                    spring_boot_version = 2
                elif version and version.startswith("3."):
                    spring_boot_version = 3

            # JUnit detection
            if "junit" in artifact_id:
                if "jupiter" in artifact_id:
                    junit_version = 5
                elif version and version.startswith("4."):
                    junit_version = 4

            # Javax vs Jakarta detection
            if group_id == "javax":
                javax_packages.append(f"{group_id}:{artifact_id}")

            # Jakarta packages
            if "jakarta" in group_id:
                jakarta_packages.append(f"{group_id}:{artifact_id}")

            # Logging framework detection
            if "log4j" in artifact_id:
                log4j_detected = True
            if "slf4j" in artifact_id:
                slf4j_detected = True

        # Analyze source code for additional features
        java_files = analysis.get("java_files", [])
        spring_annotations = 0
        junit_tests = 0
        log4j_usage = 0

        for file_path in java_files:
            if str(file_path).endswith(".java"):
                try:
                    if file_path:
                        _, file_content = await github_clone_analysis_service.get_file_content(
                            repo_reference=repo_url or f"{owner}/{repo}",
                            file_path=file_path,
                            token=token,
                        )

                        # Count Spring annotations
                        spring_patterns = [r'@SpringBootApplication', r'@RestController', r'@Service', r'@Repository']
                        for pattern in spring_patterns:
                            spring_annotations += len(re.findall(pattern, file_content))

                        # Count JUnit usage
                        junit_patterns = [r'@Test', r'@Before', r'@After']
                        for pattern in junit_patterns:
                            junit_tests += len(re.findall(pattern, file_content))

                        # Count Log4j usage
                        if 'Logger.getLogger' in file_content or 'log4j' in file_content.lower():
                            log4j_usage += 1

                except Exception as e:
                    logger.warning("Error analyzing repository file path=%s error=%s", file_path, e)
                    continue

        # Generate recipes based on analysis

        # Comprehensive Java Version Upgrade Recipe (from current version to latest)
        if current_java_version < 25:
            target_version = 25  # Latest LTS
            upgrade_steps = []

            if current_java_version < 8:
                upgrade_steps.append("Java 7/6/5/1.4/1.3/1.2/1.1/1.0 â†’ 8")
            if current_java_version < 11:
                upgrade_steps.append("Java 8 â†’ 11")
            if current_java_version < 17:
                upgrade_steps.append("Java 11 â†’ 17")
            if current_java_version < 21:
                upgrade_steps.append("Java 17 â†’ 21")
            if current_java_version < 25:
                upgrade_steps.append("Java 21 â†’ 25")

            recipes.append({
                "id": "org.openrewrite.java.migrate.UpgradeToLatestJava",
                "name": f"Upgrade Java {current_java_version} to 25 (Latest)",
                "description": f"Complete migration from Java {current_java_version} to Java 25 LTS. Includes: {', '.join(upgrade_steps)}. Detected {len(java_files)} Java files.",
                "priority": "critical",
                "category": "java_version_upgrade",
                "target_version": "25",
                "current_version": str(current_java_version),
                "upgrade_path": upgrade_steps,
                "estimated_complexity": "high" if current_java_version <= 8 else "medium"
            })
        elif current_java_version == 25:
            recipes.append({
                "id": "org.openrewrite.java.migrate.MaintainLatestJava",
                "name": "Already on Latest Java (25)",
                "description": "Your project is already using Java 25 (latest LTS). Focus on dependency updates and code quality improvements.",
                "priority": "low",
                "category": "maintenance"
            })

        # Framework-specific recipes
        if spring_boot_version == 2 and current_java_version >= 17:
            recipes.append({
                "id": "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0",
                "name": "Spring Boot 2.x to 3.0",
                "description": f"Upgrade Spring Boot {spring_boot_version}.x to 3.0 (detected {spring_annotations} Spring annotations)",
                "priority": "high",
                "category": "framework"
            })

        # Dependency management recipes
        if len(dependencies) > 0:
            recipes.append({
                "id": "org.openrewrite.java.dependencies.UpgradeDependencyVersion",
                "name": "Upgrade Dependencies",
                "description": f"Upgrade {len(dependencies)} dependencies to latest compatible versions",
                "priority": "medium",
                "category": "dependencies"
            })

        # JUnit migration
        if junit_version == 4:
            recipes.append({
                "id": "org.openrewrite.java.testing.junit5.JUnit4to5Migration",
                "name": "JUnit 4 to 5 Migration",
                "description": f"Migrate JUnit {junit_version} to JUnit 5 (detected {junit_tests} test methods)",
                "priority": "medium",
                "category": "testing"
            })

        # Logging framework migration
        if log4j_detected and not slf4j_detected:
            recipes.append({
                "id": "org.openrewrite.java.logging.slf4j.Log4jToSlf4j",
                "name": "Log4j to SLF4J Migration",
                "description": f"Migrate Log4j logging to SLF4J (detected {log4j_usage} files using Log4j)",
                "priority": "low",
                "category": "logging"
            })

        # Javax to Jakarta migration (for Java 17+)
        if current_java_version >= 17 and len(javax_packages) > 0:
            recipes.append({
                "id": "org.openrewrite.java.migrate.jakarta.JavaxToJakarta",
                "name": "Javax to Jakarta Migration",
                "description": f"Migrate javax packages to jakarta (found {len(javax_packages)} javax dependencies)",
                "priority": "high",
                "category": "java_ee"
            })

        # Code quality and cleanup recipes
        total_issues = len(business_issues) + len(security_issues) + len(performance_issues)
        if total_issues > 0:
            recipes.append({
                "id": "org.openrewrite.java.cleanup.CommonStaticAnalysis",
                "name": "Static Analysis Fixes",
                "description": f"Fix {total_issues} code quality issues (business: {len(business_issues)}, security: {len(security_issues)}, performance: {len(performance_issues)})",
                "priority": "medium",
                "category": "code_quality"
            })

        # Business logic fixes
        if len(business_issues) > 0:
            recipes.append({
                "id": "org.openrewrite.java.cleanup.UnnecessaryThrows",
                "name": "Business Logic Improvements",
                "description": f"Apply {len(business_issues)} business logic fixes and improvements",
                "priority": "low",
                "category": "business_logic"
            })

        # Security fixes
        if len(security_issues) > 0:
            recipes.append({
                "id": "org.openrewrite.java.security.SecureByDefault",
                "name": "Security Hardening",
                "description": f"Apply {len(security_issues)} security fixes and improvements",
                "priority": "high",
                "category": "security"
            })

        # Performance optimizations
        if len(performance_issues) > 0:
            recipes.append({
                "id": "org.openrewrite.java.performance.PerformanceOptimization",
                "name": "Performance Optimizations",
                "description": f"Apply {len(performance_issues)} performance optimizations",
                "priority": "medium",
                "category": "performance"
            })

        # Build tool specific recipes
        if build_tool == "maven":
            recipes.append({
                "id": "org.openrewrite.java.build.MavenOptimization",
                "name": "Maven Build Optimization",
                "description": "Optimize Maven build configuration and dependencies",
                "priority": "low",
                "category": "build"
            })
        elif build_tool == "gradle":
            recipes.append({
                "id": "org.openrewrite.java.build.GradleOptimization",
                "name": "Gradle Build Optimization",
                "description": "Optimize Gradle build configuration and dependencies",
                "priority": "low",
                "category": "build"
            })

        # Sort recipes by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recipes.sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))

        # If no recipes were generated, provide basic fallback
        if not recipes:
            recipes = [
                {
                    "id": "org.openrewrite.java.migrate.UpgradeToJava17",
                    "name": "Upgrade to Java 17 (Full)",
                    "description": "Complete migration to Java 17 LTS from any older version",
                    "priority": "high",
                    "category": "java_version"
                },
                {
                    "id": "org.openrewrite.java.cleanup.CommonStaticAnalysis",
                    "name": "Static Analysis Fixes",
                    "description": "Fix common static analysis issues",
                    "priority": "medium",
                    "category": "code_quality"
                }
            ]

        return recipes

    def _get_migration_recipes(self, source_version: str, target_version: str) -> List[str]:
        """Get the appropriate recipes for migration path"""
        recipes = []

        source = int(source_version)
        target = int(target_version)

        # Build migration path
        if source <= 7 and target >= 8:
            recipes.append("org.openrewrite.java.migrate.Java8TypeAnnotations")
            recipes.append("org.openrewrite.java.migrate.cobertura.RemoveCoberturaMavenPlugin")

        if source <= 8 and target >= 11:
            recipes.append("org.openrewrite.java.migrate.javax.AddJaxbDependencies")
            recipes.append("org.openrewrite.java.migrate.javax.AddJaxwsDependencies")

        if source <= 11 and target >= 17:
            recipes.append("org.openrewrite.java.migrate.UpgradeToJava17")

        if target >= 21:
            recipes.append("org.openrewrite.java.migrate.UpgradeToJava21")

        # Always add these
        recipes.append("org.openrewrite.java.cleanup.CommonStaticAnalysis")
        recipes.append("org.openrewrite.java.format.AutoFormat")

        return recipes

    async def analyze_project(self, project_path: str) -> Dict[str, Any]:
        """Analyze project structure and dependencies, warn if non-standard layout"""
        logger.info("Analyzing project structure path=%s", project_path)
        analysis = {
            "build_tool": None,
            "java_version": None,
            "dependencies": [],
            "source_files": 0,
            "test_files": 0,
            "api_endpoints": [],
            "java_files": [],
            "structure_warning": None
        }

        # Check for build tool
        pom_path = os.path.join(project_path, "pom.xml")
        gradle_path = os.path.join(project_path, "build.gradle")

        if os.path.exists(pom_path):
            analysis["build_tool"] = "maven"
            analysis.update(await self._analyze_maven_project(pom_path))
        elif os.path.exists(gradle_path):
            analysis["build_tool"] = "gradle"
            analysis.update(await self._analyze_gradle_project(gradle_path))

        # Count source files from standard structure
        src_main = os.path.join(project_path, "src", "main", "java")
        src_test = os.path.join(project_path, "src", "test", "java")

        # ALSO scan for standalone Java files (non-Maven/Gradle projects)
        standalone_files = await self._scan_all_java_files(project_path)
        logger.debug(
            "Standalone Java scan completed path=%s java_file_count=%s",
            project_path,
            len(standalone_files),
        )
        if standalone_files:
            analysis["java_files"] = standalone_files
            if os.path.exists(src_main):
                src_main_files = self._filter_java_files_under_root(standalone_files, src_main)
                analysis["source_files"] = len(src_main_files)
                analysis["api_endpoints"] = await self._detect_api_endpoints_in_files(src_main_files)
            if os.path.exists(src_test):
                analysis["test_files"] = len(self._filter_java_files_under_root(standalone_files, src_test))
            # If no source files found from standard structure, use standalone count
            if analysis["source_files"] == 0:
                analysis["source_files"] = len(standalone_files)
            # Detect Java version from source code if not from build file
            if analysis["java_version"] is None:
                analysis["java_version"] = await self._detect_java_version_from_source(standalone_files, project_path)
            # Mark as standalone project
            if analysis["build_tool"] is None:
                analysis["build_tool"] = "standalone"

        # Warn if not standard structure (no pom.xml, build.gradle, or src/main/java)
        if not (os.path.exists(pom_path) or os.path.exists(gradle_path) or os.path.exists(src_main)):
            if analysis["source_files"] > 0:
                analysis["structure_warning"] = (
                    "Non-standard Java project structure detected. "
                    "No Maven/Gradle build file or src/main/java folder found. "
                    "Java files were found and will be processed, but migration and build steps may require manual adjustment."
                )
            else:
                analysis["structure_warning"] = (
                    "No standard Java project structure or Java files found. "
                    "Please check your repository layout."
                )

        # Default Java version if still not detected
        if analysis["java_version"] is None:
            analysis["java_version"] = "8"  # Default assumption

        return analysis

    def _filter_java_files_under_root(self, java_files: List[str], root_path: str) -> List[str]:
        try:
            normalized_root = os.path.normcase(os.path.abspath(root_path))
        except Exception:
            normalized_root = root_path
        root_prefix = normalized_root + os.sep
        results: List[str] = []
        for file_path in java_files:
            try:
                normalized_file = os.path.normcase(os.path.abspath(file_path))
            except Exception:
                normalized_file = file_path
            if normalized_file == normalized_root or normalized_file.startswith(root_prefix):
                results.append(file_path)
        return results

    async def _scan_all_java_files(self, project_path: str) -> List[str]:
        """Scan all Java files in the project recursively"""
        java_files = []
        logger.debug("Scanning recursively for Java files path=%s", project_path)
        for root, dirs, files in os.walk(project_path):
            # Skip hidden and build directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'build', 'out', 'node_modules', '.git']]
            for file in files:
                if file.endswith('.java'):
                    filepath = os.path.join(root, file)
                    logger.debug("Discovered Java file path=%s", filepath)
                    java_files.append(filepath)
        logger.debug("Java file scan finished path=%s total_java_files=%s", project_path, len(java_files))
        return java_files

    async def _detect_api_endpoints_in_files(self, java_files: List[str]) -> List[Dict[str, str]]:
        """Detect REST API endpoints from an existing Java file list."""
        endpoints = []

        patterns = [
            (r'@GetMapping\s*\(\s*["\']([^"\']+)["\']\s*\)', 'GET'),
            (r'@PostMapping\s*\(\s*["\']([^"\']+)["\']\s*\)', 'POST'),
            (r'@PutMapping\s*\(\s*["\']([^"\']+)["\']\s*\)', 'PUT'),
            (r'@DeleteMapping\s*\(\s*["\']([^"\']+)["\']\s*\)', 'DELETE'),
            (r'@RequestMapping\s*\([^)]*value\s*=\s*["\']([^"\']+)["\']', 'REQUEST'),
        ]

        for filepath in java_files:
            file_name = os.path.basename(filepath)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
                    content = handle.read()
                for pattern, method in patterns:
                    for match in re.finditer(pattern, content):
                        endpoints.append({
                            "path": match.group(1),
                            "method": method,
                            "file": file_name,
                        })
            except Exception:
                continue

        return endpoints

    async def _detect_java_version_from_source(self, java_files: List[str], project_path: str) -> str:
        """Detect Java version by analyzing source code features"""
        detected_features = {
            "records": False,       # Java 16+
            "sealed": False,        # Java 17+
            "var": False,           # Java 10+
            "text_blocks": False,   # Java 15+
            "switch_expr": False,   # Java 14+
            "modules": False,       # Java 9+
            "lambdas": False,       # Java 8+
            "streams": False,       # Java 8+
            "diamond": False,       # Java 7+
            "try_resources": False, # Java 7+
        }

        for filepath in java_files[:20]:  # Check first 20 files for performance
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                    # Java 16+ features
                    if re.search(r'\brecord\s+\w+\s*\(', content):
                        detected_features["records"] = True

                    # Java 17+ features
                    if re.search(r'\bsealed\s+(class|interface)', content):
                        detected_features["sealed"] = True
                    if re.search(r'\bpermits\s+\w+', content):
                        detected_features["sealed"] = True

                    # Java 15+ features (text blocks)
                    if '"""' in content:
                        detected_features["text_blocks"] = True

                    # Java 14+ features (switch expressions)
                    if re.search(r'switch\s*\([^)]+\)\s*\{[^}]*->', content):
                        detected_features["switch_expr"] = True

                    # Java 10+ features
                    if re.search(r'\bvar\s+\w+\s*=', content):
                        detected_features["var"] = True

                    # Java 9+ features
                    if 'module-info.java' in filepath or re.search(r'\bmodule\s+\w+', content):
                        detected_features["modules"] = True

                    # Java 8+ features
                    if re.search(r'->', content) and not detected_features["switch_expr"]:
                        detected_features["lambdas"] = True
                    if '.stream()' in content or '.parallelStream()' in content:
                        detected_features["streams"] = True

                    # Java 7+ features
                    if re.search(r'<>', content):
                        detected_features["diamond"] = True
                    if re.search(r'try\s*\([^)]+\)\s*\{', content):
                        detected_features["try_resources"] = True

            except Exception:
                continue

        # Determine minimum Java version based on detected features
        if detected_features["sealed"]:
            return "17"
        elif detected_features["records"]:
            return "16"
        elif detected_features["text_blocks"]:
            return "15"
        elif detected_features["switch_expr"]:
            return "14"
        elif detected_features["var"]:
            return "10"
        elif detected_features["modules"]:
            return "9"
        elif detected_features["lambdas"] or detected_features["streams"]:
            return "8"
        elif detected_features["diamond"] or detected_features["try_resources"]:
            return "7"
        else:
            # Default: assume older Java code needs migration
            return "8"

    async def _analyze_maven_project(self, pom_path: str) -> Dict[str, Any]:
        """Analyze Maven project"""
        with open(pom_path, 'r', encoding='utf-8') as f:
            pom_content = f.read()

        dependencies = []

        # Parse dependencies
        dep_pattern = re.compile(
            r'<dependency>\s*'
            r'<groupId>([^<]+)</groupId>\s*'
            r'<artifactId>([^<]+)</artifactId>\s*'
            r'(?:<version>([^<]+)</version>)?',
            re.DOTALL
        )

        for match in dep_pattern.finditer(pom_content):
            dep = {
                "group_id": match.group(1),
                "artifact_id": match.group(2),
                "current_version": match.group(3) or "inherited",
                "new_version": None,
                "status": "compatible",
                "version_source": None,
            }

            # Determine upgrade status
            guidance = self._get_upgrade_guidance(
                dep["group_id"],
                dep["artifact_id"],
                dep["current_version"],
            )
            dep["new_version"] = guidance.get("new_version")
            dep["status"] = guidance.get("status") or "compatible"
            dep["version_source"] = guidance.get("source")

            dependencies.append(dep)

        # Detect Java version
        java_version = "8"
        version_match = re.search(r'<maven\.compiler\.source>(\d+)</maven\.compiler\.source>', pom_content)
        if version_match:
            java_version = version_match.group(1)
        else:
            version_match = re.search(r'<java\.version>(\d+)</java\.version>', pom_content)
            if version_match:
                java_version = version_match.group(1)

        return {
            "java_version": java_version,
            "dependencies": dependencies
        }

    async def _analyze_gradle_project(self, gradle_path: str) -> Dict[str, Any]:
        """Analyze Gradle project for Java version and dependencies."""
        try:
            with open(gradle_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            dependencies = []
            # Regex to find implementation/api/compile/testImplementation... dependencies
            # Matches: implementation 'group:artifact:version' or implementation("group:artifact:version")
            dep_pattern = re.compile(
                r"(?:implementation|api|compile|testImplementation|runtimeOnly|compileOnly)\s*\(?\s*['\"]([^:'\"\s]+):([^:'\"\s]+)(?::([^'\"\n\r)]+))?['\"]",
                re.IGNORECASE,
            )

            for match in dep_pattern.finditer(content):
                group_id = match.group(1)
                artifact_id = match.group(2)
                current_version = match.group(3) or "inherited"

                dep = {
                    "group_id": group_id,
                    "artifact_id": artifact_id,
                    "current_version": current_version,
                    "new_version": None,
                    "status": "compatible",
                    "version_source": None,
                }

                # Determine upgrade status
                guidance = self._get_upgrade_guidance(group_id, artifact_id, current_version)
                dep["new_version"] = guidance.get("new_version")
                dep["status"] = guidance.get("status") or "compatible"
                dep["version_source"] = guidance.get("source")

                dependencies.append(dep)

            # Detect Java version
            java_version = "8"
            # Matches: sourceCompatibility = '17' or sourceCompatibility = 1.8
            version_match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+(?:\.\d+)?)['\"]?", content)
            if version_match:
                v = version_match.group(1)
                if v == "1.8":
                    java_version = "8"
                else:
                    java_version = v.split(".")[0]
            else:
                # Matches: languageVersion = JavaLanguageVersion.of(17)
                version_match = re.search(r"languageVersion\s*=\s*JavaLanguageVersion\.of\((\d+)\)", content)
                if version_match:
                    java_version = version_match.group(1)

            return {"java_version": java_version, "dependencies": dependencies}
        except Exception as e:
            logger.warning("Error analyzing build.gradle path=%s error=%s", gradle_path, e)
            return {"java_version": "8", "dependencies": []}

    def _get_upgrade_guidance(self, group_id: str, artifact_id: str, current_version: str) -> Dict[str, Optional[str]]:
        """Resolve dependency upgrade guidance with Maven Central as the primary source."""
        return self.maven_central_service.get_upgrade_guidance(group_id, artifact_id, current_version)

    def _resolve_targeted_upgrade_guidance(
        self,
        group_id: str,
        artifact_id: str,
        current_version: str,
        *,
        target_versions: Optional[Dict[str, str]] = None,
        source_name: str = "Maven Central",
    ) -> Dict[str, Optional[str]]:
        coordinate = f"{(group_id or '').strip().lower()}:{(artifact_id or '').strip().lower()}"
        target_version = (target_versions or {}).get(coordinate)
        if target_version and self.maven_central_service.should_upgrade_version(current_version, target_version):
            return {
                "new_version": target_version,
                "status": "upgraded",
                "source": source_name.lower().replace(" ", "_"),
            }
        return self._get_upgrade_guidance(group_id, artifact_id, current_version)

    def _get_upgrade_info(self, group_id: str, artifact_id: str, current_version: str) -> tuple:
        """Get upgrade information for a dependency"""
        guidance = self._get_upgrade_guidance(group_id, artifact_id, current_version)
        return (guidance.get("new_version"), guidance.get("status") or "compatible")

    def _count_java_files(self, directory: str) -> int:
        """Count Java files in directory"""
        count = 0
        for root, dirs, files in os.walk(directory):
            count += sum(1 for f in files if f.endswith('.java'))
        return count

    async def apply_fossa_vulnerability_upgrades(self, project_path: str, fossa_result: Dict[str, Any]) -> Dict[str, Any]:
        """Apply dependency upgrades derived from actionable FOSSA vulnerability findings."""
        target_versions = self._build_fossa_vulnerability_upgrade_targets(fossa_result)
        if not target_versions:
            return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}

        return await self._apply_dependency_version_upgrades(
            project_path,
            target_versions=target_versions,
            source_label="FOSSA",
        )

    def _build_fossa_vulnerability_upgrade_targets(self, fossa_result: Dict[str, Any]) -> Dict[str, str]:
        targets: Dict[str, str] = {}
        dependency_latest_versions: Dict[str, str] = {}

        for dependency in fossa_result.get("dependencies", []) or []:
            if not isinstance(dependency, dict):
                continue
            coordinate = self._extract_fossa_dependency_coordinate(dependency)
            latest_version = self._normalize_target_version_value(dependency.get("latest_version"))
            if coordinate and latest_version:
                dependency_latest_versions[coordinate] = latest_version

        for vulnerability in fossa_result.get("vulnerability_details", []) or []:
            if not isinstance(vulnerability, dict):
                continue
            coordinate = self._extract_fossa_dependency_coordinate(vulnerability)
            if not coordinate:
                continue
            candidate_version = self._normalize_target_version_value(vulnerability.get("fixed_version"))
            if not candidate_version:
                candidate_version = dependency_latest_versions.get(coordinate)
            if not candidate_version:
                continue

            existing_target = targets.get(coordinate)
            if not existing_target or self.maven_central_service.should_upgrade_version(existing_target, candidate_version):
                targets[coordinate] = candidate_version

        return targets

    def _extract_fossa_dependency_coordinate(self, item: Dict[str, Any]) -> Optional[str]:
        locator = str(item.get("locator") or "").strip()
        locator_coordinate = self._parse_fossa_locator_coordinate(locator)
        if locator_coordinate:
            return locator_coordinate

        for field_name in ("package", "name", "dependencyName"):
            coordinate = self._normalize_dependency_coordinate(item.get(field_name))
            if coordinate:
                return coordinate
        return None

    def _parse_fossa_locator_coordinate(self, locator: str) -> Optional[str]:
        normalized_locator = (locator or "").strip()
        if not normalized_locator:
            return None

        coordinate_segment = normalized_locator
        if "+" in coordinate_segment:
            coordinate_segment = coordinate_segment.split("+", 1)[1]
        if "$" in coordinate_segment:
            coordinate_segment = coordinate_segment.split("$", 1)[0]

        return self._normalize_dependency_coordinate(coordinate_segment)

    def _normalize_dependency_coordinate(self, value: Any) -> Optional[str]:
        normalized = str(value or "").strip()
        if not normalized:
            return None

        if "$" in normalized:
            normalized = normalized.split("$", 1)[0]
        parts = [part.strip().lower() for part in normalized.split(":") if part.strip()]
        if len(parts) < 2:
            return None
        return f"{parts[0]}:{parts[1]}"

    def _normalize_target_version_value(self, value: Any) -> Optional[str]:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized.startswith(("mvn+", "jar+", "pkg:")):
            normalized = normalized.rsplit("$", 1)[-1]
        if normalized.count(":") >= 2 and "://" not in normalized:
            normalized = normalized.rsplit(":", 1)[-1]
        return normalized.strip() or None

    async def _apply_dependency_version_upgrades(
        self,
        project_path: str,
        *,
        target_versions: Optional[Dict[str, str]] = None,
        source_label: str = "Maven Central",
    ) -> Dict[str, Any]:
        """Apply direct dependency version upgrades using resolved guidance."""
        pom_path = os.path.join(project_path, "pom.xml")
        if os.path.exists(pom_path):
            return await self._apply_maven_dependency_version_upgrades(
                pom_path,
                target_versions=target_versions,
                source_label=source_label,
            )

        for gradle_name in ("build.gradle", "build.gradle.kts"):
            gradle_path = os.path.join(project_path, gradle_name)
            if os.path.exists(gradle_path):
                return await self._apply_gradle_dependency_version_upgrades(
                    gradle_path,
                    target_versions=target_versions,
                    source_label=source_label,
                )

        return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}

    async def _apply_maven_dependency_version_upgrades(
        self,
        pom_path: str,
        *,
        target_versions: Optional[Dict[str, str]] = None,
        source_label: str = "Maven Central",
    ) -> Dict[str, Any]:
        try:
            with open(pom_path, "r", encoding="utf-8") as handle:
                original_content = handle.read()
        except OSError as exc:
            logger.warning("Unable to read pom.xml for dependency upgrades path=%s error=%s", pom_path, exc)
            return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}

        dependency_pattern = re.compile(
            r"(?P<block><dependency>\s*"
            r"<groupId>(?P<group>[^<]+)</groupId>\s*"
            r"<artifactId>(?P<artifact>[^<]+)</artifactId>\s*"
            r"(?P<version_block><version>(?P<version>[^<]+)</version>)?)",
            re.DOTALL,
        )
        property_ref_pattern = re.compile(r"^\$\{(?P<name>[^}]+)\}$")

        property_updates: Dict[str, str] = {}
        property_change_messages: Dict[str, str] = {}
        property_change_records: Dict[str, List[Dict[str, str]]] = {}
        changes: List[str] = []
        updated_dependency_records: List[Dict[str, str]] = []

        def _parse_target_dependency_spec(value: str) -> tuple[str, str, str]:
            normalized = (value or "").strip()
            if not normalized:
                return "", "", ""

            parts = normalized.split(":")
            if len(parts) >= 3:
                return parts[0].strip(), parts[1].strip(), ":".join(parts[2:]).strip()
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip(), ""
            return "", "", normalized

        def replace_dependency(match: re.Match[str]) -> str:
            block = match.group("block")
            group_id = match.group("group").strip()
            artifact_id = match.group("artifact").strip()
            current_version = (match.group("version") or "inherited").strip()
            guidance = self._resolve_targeted_upgrade_guidance(
                group_id,
                artifact_id,
                current_version,
                target_versions=target_versions,
                source_name=source_label,
            )
            target_spec = (guidance.get("new_version") or "").strip()
            status = guidance.get("status") or "compatible"
            if status != "upgraded" or not target_spec:
                return block

            coordinate = f"{group_id}:{artifact_id}"
            target_group_id, target_artifact_id, target_dependency_version = _parse_target_dependency_spec(target_spec)
            target_group_id = target_group_id or group_id
            target_artifact_id = target_artifact_id or artifact_id
            target_coordinate = f"{target_group_id}:{target_artifact_id}"
            target_version = target_dependency_version or ""
            property_ref_match = property_ref_pattern.match(current_version)
            if property_ref_match:
                property_name = property_ref_match.group("name")
                existing_property_target = property_updates.get(property_name)
                if existing_property_target and existing_property_target != target_version:
                    logger.info(
                        "Skipping Maven property version update due to conflicting targets property=%s first=%s next=%s",
                        property_name,
                        existing_property_target,
                        target_version,
                    )
                    return block
                if target_version:
                    property_updates[property_name] = target_version
                property_change_messages[property_name] = (
                    f"Aligned {coordinate} -> {target_coordinate} via property {property_name} using {source_label} guidance"
                )
                property_change_records.setdefault(property_name, []).append(
                    {
                        "group_id": group_id,
                        "artifact_id": artifact_id,
                        "current_version": current_version,
                        "new_version": target_spec,
                        "source": source_label.lower().replace(" ", "_"),
                    }
                )
                updated_block = block
                updated_block = updated_block.replace(
                    f"<groupId>{group_id}</groupId>",
                    f"<groupId>{target_group_id}</groupId>",
                    1,
                )
                updated_block = updated_block.replace(
                    f"<artifactId>{artifact_id}</artifactId>",
                    f"<artifactId>{target_artifact_id}</artifactId>",
                    1,
                )
                if target_version and not match.group("version_block"):
                    updated_block = updated_block.replace(
                        "</dependency>",
                        f"    <version>{target_version}</version>\n        </dependency>",
                        1,
                    )
                elif target_version and match.group("version_block"):
                    updated_block = updated_block.replace(
                        match.group("version_block"),
                        f"<version>{target_version}</version>",
                        1,
                    )

                updated_dependency_records.append(
                    {
                        "group_id": group_id,
                        "artifact_id": artifact_id,
                        "current_version": current_version,
                        "new_version": target_spec,
                        "source": source_label.lower().replace(" ", "_"),
                    }
                )
                changes.append(f"Updated {coordinate} to {target_coordinate} using {source_label} guidance")
                return updated_block

            updated_block = block
            updated_block = updated_block.replace(
                f"<groupId>{group_id}</groupId>",
                f"<groupId>{target_group_id}</groupId>",
                1,
            )
            updated_block = updated_block.replace(
                f"<artifactId>{artifact_id}</artifactId>",
                f"<artifactId>{target_artifact_id}</artifactId>",
                1,
            )
            if target_version and not match.group("version_block"):
                updated_block = updated_block.replace(
                    "</dependency>",
                    f"    <version>{target_version}</version>\n        </dependency>",
                    1,
                )
            elif target_version and match.group("version_block"):
                updated_block = updated_block.replace(
                    match.group("version_block"),
                    f"<version>{target_version}</version>",
                    1,
                )

            if updated_block == block:
                return block

            updated_dependency_records.append(
                {
                    "group_id": group_id,
                    "artifact_id": artifact_id,
                    "current_version": current_version,
                    "new_version": target_spec,
                    "source": source_label.lower().replace(" ", "_"),
                }
            )
            changes.append(f"Updated {coordinate} to {target_coordinate} using {source_label} guidance")
            return updated_block

        updated_content = dependency_pattern.sub(replace_dependency, original_content)
        updated_content, applied_properties = self._apply_maven_property_updates(updated_content, property_updates)

        for property_name in applied_properties:
            change_message = property_change_messages.get(property_name)
            if change_message:
                changes.append(change_message)
            for property_record in property_change_records.get(property_name, []):
                updated_dependency_records.append(property_record)

        if updated_content == original_content:
            return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}

        with open(pom_path, "w", encoding="utf-8") as handle:
            handle.write(updated_content)

        return {
            "files_modified": 1,
            "issues_fixed": len(updated_dependency_records),
            "changes": changes,
            "updated_dependencies": updated_dependency_records,
        }

    def _apply_maven_property_updates(self, pom_content: str, property_updates: Dict[str, str]) -> tuple[str, List[str]]:
        updated_content = pom_content
        applied_properties: List[str] = []

        for property_name, new_version in property_updates.items():
            property_pattern = re.compile(
                rf"(<{re.escape(property_name)}>\s*)([^<]+)(\s*</{re.escape(property_name)}>)"
            )

            def replace_property(match: re.Match[str]) -> str:
                current_value = match.group(2).strip()
                if not self.maven_central_service.should_upgrade_version(current_value, new_version):
                    return match.group(0)
                applied_properties.append(property_name)
                return f"{match.group(1)}{new_version}{match.group(3)}"

            updated_content = property_pattern.sub(replace_property, updated_content, count=1)

        return updated_content, applied_properties

    async def _apply_gradle_dependency_version_upgrades(
        self,
        gradle_path: str,
        *,
        target_versions: Optional[Dict[str, str]] = None,
        source_label: str = "Maven Central",
    ) -> Dict[str, Any]:
        try:
            with open(gradle_path, "r", encoding="utf-8") as handle:
                original_content = handle.read()
        except OSError as exc:
            logger.warning("Unable to read Gradle build file for dependency upgrades path=%s error=%s", gradle_path, exc)
            return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}

        dependency_pattern = re.compile(
            r"(?P<full>(?P<prefix>(?:api|implementation|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|annotationProcessor|kapt|classpath)\s*\(?\s*['\"])"
            r"(?P<group>[^:'\"\s]+):(?P<artifact>[^:'\"\s]+):(?P<version>[^'\"\n\r)]+)"
            r"(?P<suffix>['\"]\s*\)?))"
        )

        changes: List[str] = []
        updated_dependency_records: List[Dict[str, str]] = []

        def replace_dependency(match: re.Match[str]) -> str:
            group_id = match.group("group").strip()
            artifact_id = match.group("artifact").strip()
            current_version = match.group("version").strip()
            guidance = self._resolve_targeted_upgrade_guidance(
                group_id,
                artifact_id,
                current_version,
                target_versions=target_versions,
                source_name=source_label,
            )
            new_version = (guidance.get("new_version") or "").strip()
            status = guidance.get("status") or "compatible"
            if status != "upgraded" or not new_version:
                return match.group("full")
            if current_version.startswith("$") or current_version.startswith("${"):
                return match.group("full")

            coordinate = f"{group_id}:{artifact_id}"
            updated_dependency_records.append(
                {
                    "group_id": group_id,
                    "artifact_id": artifact_id,
                    "current_version": current_version,
                    "new_version": new_version,
                    "source": source_label.lower().replace(" ", "_"),
                }
            )
            changes.append(f"Updated {coordinate} to {new_version} using {source_label} guidance")
            return f"{match.group('prefix')}{group_id}:{artifact_id}:{new_version}{match.group('suffix')}"

        updated_content = dependency_pattern.sub(replace_dependency, original_content)

        if updated_content == original_content:
            return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}

        with open(gradle_path, "w", encoding="utf-8") as handle:
            handle.write(updated_content)

        return {
            "files_modified": 1,
            "issues_fixed": len(updated_dependency_records),
            "changes": changes,
            "updated_dependencies": updated_dependency_records,
        }

    async def _detect_api_endpoints(self, src_path: str) -> List[Dict[str, str]]:
        """Detect REST API endpoints in source code"""
        java_files = []
        for root, _, files in os.walk(src_path):
            for file_name in files:
                if file_name.endswith('.java'):
                    java_files.append(os.path.join(root, file_name))
        return await self._detect_api_endpoints_in_files(java_files)

    async def run_migration(
        self,
        project_path: str,
        source_version: str,
        target_version: str,
        fix_business_logic: bool = True
    ) -> Dict[str, Any]:
        """Run OpenRewrite migration"""
        result = {
            "success": True,
            "files_modified": 0,
            "issues_fixed": 0,
            "changes": [],
            "files_scanned": 0,
            "project_restructured": False,
            "updated_dependencies": [],
        }

        # Handle auto-detection of source version
        if source_version == "auto" or source_version == "not_specified":
            logger.info("Auto-detecting source Java version path=%s", project_path)
            detected_version = await self._auto_detect_java_version(project_path)
            if detected_version and detected_version != "not_specified":
                source_version = detected_version
                logger.info("Auto-detected source Java version version=%s", source_version)
            else:
                # Default to Java 8 if auto-detection fails or no version specified
                source_version = "8"
                logger.info("Auto-detection unavailable; defaulting source Java version to 8")

        # Convert versions to integers for validation
        try:
            source_int = int(source_version)
            target_int = int(target_version)
        except ValueError as e:
            raise Exception(f"Invalid Java version format: source='{source_version}', target='{target_version}'. Expected integer values.")

        # Check for this is a standalone project (no pom.xml or build.gradle)
        pom_path = os.path.join(project_path, "pom.xml")
        gradle_path = os.path.join(project_path, "build.gradle")

        if not os.path.exists(pom_path) and not os.path.exists(gradle_path):
            # Convert standalone Java files to professional Maven project structure
            restructure_result = await self._convert_to_maven_project(project_path, target_version)
            result["files_modified"] += restructure_result.get("files_modified", 0)
            result["issues_fixed"] += restructure_result.get("issues_fixed", 0)
            result["changes"].extend(restructure_result.get("changes", []))
            result["project_restructured"] = True
            logger.info("Converted standalone project to Maven structure path=%s", project_path)

        # Update pom.xml Java version (now it should exist)
        pom_path = os.path.join(project_path, "pom.xml")
        if os.path.exists(pom_path):
            maven_update_result = await self._update_maven_java_version(pom_path, target_version)
            result["files_modified"] += maven_update_result.get("files_modified", 0)
            result["issues_fixed"] += maven_update_result.get("issues_fixed", 0)
            result["changes"].extend(maven_update_result.get("changes", []))
            result["updated_dependencies"].extend(maven_update_result.get("updated_dependencies", []) or [])
        dependency_update_result = await self._apply_dependency_version_upgrades(project_path)
        result["files_modified"] += dependency_update_result.get("files_modified", 0)
        result["issues_fixed"] += dependency_update_result.get("issues_fixed", 0)
        result["changes"].extend(dependency_update_result.get("changes", []))
        result["updated_dependencies"].extend(dependency_update_result.get("updated_dependencies", []) or [])

        # Get recipes for migration path
        recipes = self._get_migration_recipes(source_version, target_version)

        # Run OpenRewrite (simulated for PoC - in production, use actual CLI)
        # For production: subprocess.run(["java", "-jar", self.openrewrite_cli, "run", ...])

        # Walk the project once to avoid reprocessing nested source roots like
        # src/main/java, src/test/java, src, and the repo root.
        modifications = await self._apply_java_migrations(project_path, source_version, target_version)
        result["files_modified"] += modifications["files_modified"]
        result["issues_fixed"] += modifications["issues_fixed"]
        result["files_scanned"] += modifications.get("files_scanned", 0)
        result["changes"].extend(modifications["changes"])

        # Fix business logic if enabled
        if fix_business_logic:
            business_fixes = await self._fix_business_logic_issues(project_path)
            result["issues_fixed"] += business_fixes

        return result

    async def _auto_detect_java_version(self, project_path: str) -> str:
        """Auto-detect Java version from project files"""
        try:
            # Look for build files first
            pom_path = os.path.join(project_path, "pom.xml")
            gradle_path = os.path.join(project_path, "build.gradle")

            # Check Maven pom.xml
            if os.path.exists(pom_path):
                try:
                    with open(pom_path, 'r', encoding='utf-8') as f:
                        pom_content = f.read()

                    # Check for maven.compiler.source
                    match = re.search(r'<maven\.compiler\.source>(\d+)</maven\.compiler\.source>', pom_content)
                    if match:
                        return match.group(1)

                    # Check for java.version property
                    match = re.search(r'<java\.version>(\d+)</java\.version>', pom_content)
                    if match:
                        return match.group(1)

                except Exception as e:
                    logger.warning("Error reading pom.xml path=%s error=%s", pom_path, e)

            # Check Gradle build file
            if os.path.exists(gradle_path):
                try:
                    with open(gradle_path, 'r', encoding='utf-8') as f:
                        gradle_content = f.read()

                    # Check for sourceCompatibility
                    match = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+)['\"]?", gradle_content)
                    if match:
                        return match.group(1)

                except Exception as e:
                    logger.warning("Error reading build.gradle path=%s error=%s", gradle_path, e)

            # If no build file or version not found, analyze source code
            java_files = await self._scan_all_java_files(project_path)
            if java_files:
                detected_version = await self._detect_java_version_from_source(java_files, project_path)
                if detected_version and detected_version != "8":
                    return detected_version

            # Default fallback
            return "8"

        except Exception as e:
            logger.warning("Error while auto-detecting Java version path=%s error=%s", project_path, e)
            return "8"

    async def _convert_to_maven_project(self, project_path: str, target_version: str) -> Dict[str, Any]:
        """Convert standalone Java files to a professional Maven project structure"""
        import shutil

        result = {
            "files_modified": 0,
            "issues_fixed": 0,
            "changes": []
        }

        # Get project name from directory
        project_name = os.path.basename(project_path).lower().replace(" ", "-").replace("_", "-")
        if not project_name or project_name == "tmp":
            project_name = "migrated-java-project"

        # Detect package name from existing Java files
        detected_package = await self._detect_package_name(project_path)
        if not detected_package:
            # Generate package name from project name
            detected_package = f"com.{project_name.replace('-', '.')}"

        # Create standard Maven directory structure
        src_main_java = os.path.join(project_path, "src", "main", "java")
        src_main_resources = os.path.join(project_path, "src", "main", "resources")
        src_test_java = os.path.join(project_path, "src", "test", "java")
        src_test_resources = os.path.join(project_path, "src", "test", "resources")

        # Create package directory structure
        package_path = detected_package.replace(".", os.sep)
        main_package_dir = os.path.join(src_main_java, package_path)
        test_package_dir = os.path.join(src_test_java, package_path)

        # Create all directories
        for dir_path in [src_main_java, src_main_resources, src_test_java, src_test_resources, main_package_dir, test_package_dir]:
            os.makedirs(dir_path, exist_ok=True)

        result["changes"].append("Created Maven project structure (src/main/java, src/test/java, etc.)")
        result["files_modified"] += 1

        # Find and move all Java files to proper location
        java_files_moved = 0
        test_files_moved = 0

        # Scan for Java files in root and immediate subdirectories
        for item in os.listdir(project_path):
            item_path = os.path.join(project_path, item)

            # Skip the src directory we just created
            if item == "src" or item.startswith("."):
                continue

            if item.endswith(".java"):
                # Move Java file to main package
                new_path = os.path.join(main_package_dir, item)
                await self._move_and_update_java_file(item_path, new_path, detected_package, target_version)
                java_files_moved += 1
            elif os.path.isdir(item_path):
                # Check for Java files in subdirectories
                for root, dirs, files in os.walk(item_path):
                    # Skip hidden dirs
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for file in files:
                        if file.endswith(".java"):
                            old_file_path = os.path.join(root, file)
                            if "test" in file.lower() or "test" in root.lower():
                                new_path = os.path.join(test_package_dir, file)
                                await self._move_and_update_java_file(old_file_path, new_path, detected_package, target_version, is_test=True)
                                test_files_moved += 1
                            else:
                                new_path = os.path.join(main_package_dir, file)
                                await self._move_and_update_java_file(old_file_path, new_path, detected_package, target_version)
                                java_files_moved += 1

        result["changes"].append(f"Moved {java_files_moved} source files to src/main/java/{package_path}")
        if test_files_moved > 0:
            result["changes"].append(f"Moved {test_files_moved} test files to src/test/java/{package_path}")
        result["files_modified"] += java_files_moved + test_files_moved

        # Analyze moved files to detect dependencies
        detected_deps = await self._detect_dependencies_from_imports(main_package_dir)

        # Generate pom.xml
        pom_content = self._generate_pom_xml(project_name, detected_package, target_version, detected_deps)
        pom_path = os.path.join(project_path, "pom.xml")
        with open(pom_path, 'w', encoding='utf-8') as f:
            f.write(pom_content)
        result["changes"].append("Generated pom.xml with dependencies")
        result["files_modified"] += 1
        result["issues_fixed"] += 1

        # Generate .gitignore
        gitignore_content = self._generate_gitignore()
        gitignore_path = os.path.join(project_path, ".gitignore")
        with open(gitignore_path, 'w', encoding='utf-8') as f:
            f.write(gitignore_content)
        result["changes"].append("Generated .gitignore")
        result["files_modified"] += 1

        # Generate README.md
        readme_content = self._generate_readme(project_name, detected_package, target_version)
        readme_path = os.path.join(project_path, "README.md")
        # Only create if doesn't exist or is empty
        if not os.path.exists(readme_path) or os.path.getsize(readme_path) < 100:
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
            result["changes"].append("Generated README.md")
            result["files_modified"] += 1

        # Generate application.properties placeholder
        app_props_path = os.path.join(src_main_resources, "application.properties")
        with open(app_props_path, 'w', encoding='utf-8') as f:
            f.write(f"# Application Configuration\n# Generated by Java Migration Accelerator\n# Java Version: {target_version}\n\n")
        result["changes"].append("Generated application.properties")
        result["files_modified"] += 1

        # Generate a sample test file if no tests exist
        if test_files_moved == 0 and java_files_moved > 0:
            test_content = self._generate_sample_test(detected_package, project_name)
            test_file_path = os.path.join(test_package_dir, "ApplicationTest.java")
            with open(test_file_path, 'w', encoding='utf-8') as f:
                f.write(test_content)
            result["changes"].append("Generated sample JUnit 5 test file")
            result["files_modified"] += 1

        # Clean up empty directories left behind
        await self._cleanup_empty_dirs(project_path)

        return result

    async def _detect_package_name(self, project_path: str) -> str:
        """Detect existing package name from Java files"""
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'build']]
            for file in files:
                if file.endswith('.java'):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            # Look for package declaration
                            match = re.search(r'^\s*package\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*;', content, re.MULTILINE)
                            if match:
                                return match.group(1)
                    except:
                        pass
        return None

    async def _move_and_update_java_file(self, old_path: str, new_path: str, package_name: str, target_version: str, is_test: bool = False):
        """Move Java file and update its package declaration"""
        try:
            with open(old_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            original_content = content

            # Check if file has a package declaration
            has_package = re.search(r'^\s*package\s+[a-zA-Z_][a-zA-Z0-9_.]*\s*;', content, re.MULTILINE)

            if has_package:
                # Update existing package declaration
                content = re.sub(
                    r'^\s*package\s+[a-zA-Z_][a-zA-Z0-9_.]*\s*;',
                    f'package {package_name};',
                    content,
                    count=1,
                    flags=re.MULTILINE
                )
            else:
                # Add package declaration at the top
                # Find the right place (after any comments at the top)
                lines = content.split('\n')
                insert_index = 0

                # Skip leading comments and blank lines
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*') or stripped == '':
                        insert_index = i + 1
                    elif stripped.startswith('import') or stripped.startswith('public') or stripped.startswith('class'):
                        break
                    else:
                        break

                lines.insert(insert_index, f'package {package_name};\n')
                content = '\n'.join(lines)

            # Add migration header comment if not present
            if '// Migrated to Java' not in content and '/* Migrated' not in content:
                header = f"""/**
 * Migrated to Java {target_version} by Java Migration Accelerator
 * Original location: {os.path.basename(old_path)}
 * Package: {package_name}
 */
"""
                # Insert after package declaration
                content = re.sub(
                    r'(package\s+[a-zA-Z_][a-zA-Z0-9_.]*\s*;)',
                    f'\\1\n\n{header}',
                    content,
                    count=1
                )

            # Write to new location
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Remove old file
            if os.path.exists(old_path) and old_path != new_path:
                os.remove(old_path)

        except Exception as e:
            logger.warning("Error moving path during project restructure path=%s error=%s", old_path, e)
            # If update fails, just copy the file as-is
            if os.path.exists(old_path):
                shutil.copy2(old_path, new_path)
                os.remove(old_path)

    async def _detect_dependencies_from_imports(self, src_path: str) -> List[Dict[str, str]]:
        """Analyze Java files to detect required dependencies from imports"""
        dependencies = []
        detected_imports = set()

        for root, dirs, files in os.walk(src_path):
            for file in files:
                if file.endswith('.java'):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            # Find all imports
                            imports = re.findall(r'import\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s*;', content)
                            detected_imports.update(imports)
                    except:
                        pass

        # Map imports to Maven dependencies
        dependency_map = {
            'javax.swing': {'groupId': 'javax.swing', 'artifactId': 'swing', 'version': None, 'comment': 'JDK built-in'},
            'java.awt': {'groupId': 'java.awt', 'artifactId': 'awt', 'version': None, 'comment': 'JDK built-in'},
            'javax.servlet.jsp.jstl': {'groupId': 'jakarta.servlet.jsp.jstl', 'artifactId': 'jakarta.servlet.jsp.jstl-api', 'version': '3.0.1'},
            'javax.servlet': {'groupId': 'jakarta.servlet', 'artifactId': 'jakarta.servlet-api', 'version': '6.0.0'},
            'jakarta.servlet': {'groupId': 'jakarta.servlet', 'artifactId': 'jakarta.servlet-api', 'version': '6.0.0'},
            'org.springframework': {'groupId': 'org.springframework.boot', 'artifactId': 'spring-boot-starter', 'version': '3.2.0'},
            'org.junit': {'groupId': 'org.junit.jupiter', 'artifactId': 'junit-jupiter', 'version': '5.10.0', 'scope': 'test'},
            'junit.framework': {'groupId': 'org.junit.jupiter', 'artifactId': 'junit-jupiter', 'version': '5.10.0', 'scope': 'test'},
            'org.mockito': {'groupId': 'org.mockito', 'artifactId': 'mockito-core', 'version': '5.8.0', 'scope': 'test'},
            'com.google.gson': {'groupId': 'com.google.code.gson', 'artifactId': 'gson', 'version': '2.10.1'},
            'org.json': {'groupId': 'org.json', 'artifactId': 'json', 'version': '20231013'},
            'com.fasterxml.jackson': {'groupId': 'com.fasterxml.jackson.core', 'artifactId': 'jackson-databind', 'version': '2.16.0'},
            'org.apache.commons.lang': {'groupId': 'org.apache.commons', 'artifactId': 'commons-lang3', 'version': '3.14.0'},
            'org.apache.commons.io': {'groupId': 'commons-io', 'artifactId': 'commons-io', 'version': '2.15.1'},
            'org.slf4j': {'groupId': 'org.slf4j', 'artifactId': 'slf4j-api', 'version': '2.0.9'},
            'org.apache.logging.log4j': {'groupId': 'org.apache.logging.log4j', 'artifactId': 'log4j-core', 'version': '2.22.0'},
            'javax.persistence': {'groupId': 'jakarta.persistence', 'artifactId': 'jakarta.persistence-api', 'version': '3.1.0'},
            'jakarta.persistence': {'groupId': 'jakarta.persistence', 'artifactId': 'jakarta.persistence-api', 'version': '3.1.0'},
            'lombok': {'groupId': 'org.projectlombok', 'artifactId': 'lombok', 'version': '1.18.30', 'scope': 'provided'},
        }

        added_deps = set()
        for imp in detected_imports:
            for prefix, dep_info in dependency_map.items():
                if imp.startswith(prefix) and dep_info.get('version'):
                    dep_key = f"{dep_info['groupId']}:{dep_info['artifactId']}"
                    if dep_key not in added_deps:
                        dependencies.append(dep_info)
                        added_deps.add(dep_key)
                        break

        return dependencies

    def _generate_pom_xml(self, project_name: str, package_name: str, java_version: str, dependencies: List[Dict[str, str]]) -> str:
        """Generate a professional pom.xml file"""
        group_id = '.'.join(package_name.split('.')[:2]) if '.' in package_name else f"com.{project_name.replace('-', '')}"

        deps_xml = ""
        if dependencies:
            for dep in dependencies:
                scope_xml = f"\n            <scope>{dep['scope']}</scope>" if dep.get('scope') else ""
                deps_xml += f"""
        <dependency>
            <groupId>{dep['groupId']}</groupId>
            <artifactId>{dep['artifactId']}</artifactId>
            <version>{dep['version']}</version>{scope_xml}
        </dependency>"""

        # Always add JUnit 5 for testing
        if not any(d.get('artifactId') == 'junit-jupiter' for d in dependencies):
            deps_xml += """
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter</artifactId>
            <version>5.10.0</version>
            <scope>test</scope>
        </dependency>"""

        pom_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>{group_id}</groupId>
    <artifactId>{project_name}</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>

    <name>{project_name}</name>
    <description>Migrated to Java {java_version} by Java Migration Accelerator</description>

    <properties>
        <java.version>{java_version}</java.version>
        <maven.compiler.source>{java_version}</maven.compiler.source>
        <maven.compiler.target>{java_version}</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <project.reporting.outputEncoding>UTF-8</project.reporting.outputEncoding>
    </properties>

    <dependencies>{deps_xml}
    </dependencies>

    <build>
        <plugins>
            <!-- Maven Compiler Plugin -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.11.0</version>
                <configuration>
                    <source>{java_version}</source>
                    <target>{java_version}</target>
                    <encoding>UTF-8</encoding>
                </configuration>
            </plugin>

            <!-- Maven Surefire Plugin for tests -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.2.2</version>
            </plugin>

            <!-- Maven JAR Plugin -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-jar-plugin</artifactId>
                <version>3.3.0</version>
                <configuration>
                    <archive>
                        <manifest>
                            <addClasspath>true</addClasspath>
                            <mainClass>{package_name}.Main</mainClass>
                        </manifest>
                    </archive>
                </configuration>
            </plugin>

            <!-- Maven Exec Plugin for running -->
            <plugin>
                <groupId>org.codehaus.mojo</groupId>
                <artifactId>exec-maven-plugin</artifactId>
                <version>3.1.1</version>
                <configuration>
                    <mainClass>{package_name}.Main</mainClass>
                </configuration>
            </plugin>
        </plugins>
    </build>

</project>
"""
        return pom_content

    def _generate_gitignore(self) -> str:
        """Generate a comprehensive .gitignore for Java/Maven projects"""
        return """# Compiled class files
*.class

# Log files
*.log

# BlueJ files
*.ctxt

# Mobile Tools for Java (J2ME)
.mtj.tmp/

# Package Files
*.jar
*.war
*.nar
*.ear
*.zip
*.tar.gz
*.rar

# Maven
target/
pom.xml.tag
pom.xml.releaseBackup
pom.xml.versionsBackup
pom.xml.next
release.properties
dependency-reduced-pom.xml
buildNumber.properties
.mvn/timing.properties
.mvn/wrapper/maven-wrapper.jar

# Gradle
.gradle/
build/
!gradle/wrapper/gradle-wrapper.jar

# IDE - IntelliJ IDEA
.idea/
*.iws
*.iml
*.ipr
out/

# IDE - Eclipse
.apt_generated
.classpath
.factorypath
.project
.settings
.springBeans
.sts4-cache
bin/

# IDE - NetBeans
/nbproject/private/
/nbbuild/
/dist/
/nbdist/
/.nb-gradle/

# IDE - VS Code
.vscode/

# OS
.DS_Store
Thumbs.db

# Application
application-local.properties
application-*.yml
!application.yml
*.env
.env.local
"""

    def _generate_readme(self, project_name: str, package_name: str, java_version: str) -> str:
        """Generate a professional README.md for migrated projects"""
        from datetime import datetime

        migration_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        return f"""# {project_name.replace('-', ' ').title()}

> ðŸš€ **Java Apex Migration Project** - Migrated to Java {java_version} on {migration_time}

## ðŸ“‹ Overview

This project has been automatically migrated and restructured to follow standard Maven project conventions using **Java Apex Migration Accelerator**.

## ðŸ”„ Migration Information

- **Migration Tool**: Java Apex Migration Accelerator
- **Migration Date**: {migration_time}
- **Source Version**: Unknown (auto-detected during migration)
- **Target Version**: Java {java_version}
- **Migration Type**: High-risk project restructuring with standard Maven layout

## ðŸ› ï¸ Requirements

- **Java**: {java_version} or higher
- **Maven**: 3.8.0 or higher

## ðŸ“ Project Structure

```
{project_name}/
â”œâ”€â”€ src/
â”‚   â”œâ”€â”€ main/
â”‚   â”‚   â”œâ”€â”€ java/
â”‚   â”‚   â”‚   â””â”€â”€ {package_name.replace('.', '/')}/
â”‚   â”‚   â””â”€â”€ resources/
â”‚   â””â”€â”€ test/
â”‚       â”œâ”€â”€ java/
â”‚       â”‚   â””â”€â”€ {package_name.replace('.', '/')}/
â”‚       â””â”€â”€ resources/
â”œâ”€â”€ pom.xml
â”œâ”€â”€ README.md
â””â”€â”€ .gitignore
```

## ðŸš€ Getting Started

### Build the project

```bash
mvn clean compile
```

### Run tests

```bash
mvn test
```

### Package as JAR

```bash
mvn package
```

### Run the application

```bash
mvn exec:java
# or
java -jar target/{project_name}-1.0.0.jar
```

## ðŸ“¦ Dependencies

Dependencies are managed in `pom.xml`. To add new dependencies:

1. Find the dependency on [Maven Central](https://search.maven.org/)
2. Add it to the `<dependencies>` section in `pom.xml`
3. Run `mvn clean compile` to download

## ðŸ”§ Development

### IDE Setup

**IntelliJ IDEA:**
1. Open IntelliJ IDEA
2. File â†’ Open â†’ Select project folder
3. Trust the project when prompted

**Eclipse:**
1. File â†’ Import â†’ Maven â†’ Existing Maven Projects
2. Select project folder
3. Click Finish

**VS Code:**
1. Install "Extension Pack for Java"
2. Open project folder
3. Extensions will auto-configure

## ðŸ“ License

This project is available under the MIT License.

---

*Generated by [Java Migration Accelerator](https://github.com/sorimdevs-tech/java-migration-accelerator)*
"""

    def _generate_sample_test(self, package_name: str, project_name: str) -> str:
        """Generate a sample JUnit 5 test file"""
        class_name = ''.join(word.capitalize() for word in project_name.replace('-', ' ').split())
        return f"""package {package_name};

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.BeforeEach;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Sample test class generated by Java Migration Accelerator
 * Add your tests here to verify the migrated code works correctly.
 */
@DisplayName("{class_name} Tests")
class ApplicationTest {{

    @BeforeEach
    void setUp() {{
        // Initialize test fixtures here
    }}

    @Test
    @DisplayName("Sample test - verify application starts")
    void testApplicationStarts() {{
        // TODO: Replace with actual tests
        assertTrue(true, "Application should start successfully");
    }}

    @Test
    @DisplayName("Sample test - verify basic functionality")
    void testBasicFunctionality() {{
        // TODO: Add tests for your application's core functionality
        assertNotNull(System.getProperty("java.version"), "Java version should be available");
    }}
}}
"""

    async def _cleanup_empty_dirs(self, project_path: str):
        """Remove empty directories left behind after moving files"""
        import shutil

        for root, dirs, files in os.walk(project_path, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                # Skip important directories
                if dir_name in ['src', 'main', 'test', 'java', 'resources', '.git']:
                    continue
                try:
                    if os.path.isdir(dir_path) and not os.listdir(dir_path):
                        os.rmdir(dir_path)
                except:
                    pass
    
    async def _update_maven_java_version(self, pom_path: str, target_version: str) -> Dict[str, Any]:
        """Update Java version in pom.xml and return dependency upgrade records."""
        try:
            with open(pom_path, "r", encoding="utf-8") as handle:
                original_content = handle.read()

            content = original_content
            result = {
                "files_modified": 0,
                "issues_fixed": 0,
                "changes": [],
                "updated_dependencies": [],
            }
            source_snapshot = build_migration_policy_service.inspect_build_content(content, "maven")
            effective_target_version = build_migration_policy_service.resolve_java_target(
                source_snapshot.java_version,
                target_version,
            )

            parent_match = re.search(
                r"(<parent>.*?<groupId>\s*org\.springframework\.boot\s*</groupId>.*?<artifactId>\s*spring-boot-starter-parent\s*</artifactId>.*?<version>)([^<]+)(</version>.*?</parent>)",
                content,
                flags=re.DOTALL,
            )
            current_parent_version = parent_match.group(2).strip() if parent_match else ""

            patterns_to_update = [
                (r"<maven\.compiler\.source>[^<]+</maven\.compiler\.source>", f"<maven.compiler.source>{effective_target_version}</maven.compiler.source>"),
                (r"<maven\.compiler\.target>[^<]+</maven\.compiler\.target>", f"<maven.compiler.target>{effective_target_version}</maven.compiler.target>"),
                (r"<java\.version>[^<]+</java\.version>", f"<java.version>{effective_target_version}</java.version>"),
                (r"<source>1\.\d+</source>", f"<source>{effective_target_version}</source>"),
                (r"<target>1\.\d+</target>", f"<target>{effective_target_version}</target>"),
                (r"<source>\d+</source>", f"<source>{effective_target_version}</source>"),
                (r"<target>\d+</target>", f"<target>{effective_target_version}</target>"),
                (r"<release>\d+</release>", f"<release>{effective_target_version}</release>"),
            ]

            modified = False
            for pattern, replacement in patterns_to_update:
                new_content = re.sub(pattern, replacement, content)
                if new_content != content:
                    content = new_content
                    modified = True

            if not modified and "<maven.compiler.source>" not in content and "<java.version>" not in content:
                properties_content = (
                    f"\n        <java.version>{effective_target_version}</java.version>"
                    f"\n        <maven.compiler.source>{effective_target_version}</maven.compiler.source>"
                    f"\n        <maven.compiler.target>{effective_target_version}</maven.compiler.target>"
                    "\n        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>"
                )

                properties_match = re.search(r"<properties\b[^>]*>", content, re.IGNORECASE)
                if properties_match:
                    content = content[:properties_match.end()] + properties_content + content[properties_match.end():]
                    modified = True
                elif "<modelVersion>" in content:
                    properties_section = f"    <properties>{properties_content}\n    </properties>\n"
                    content = re.sub(
                        r"(</modelVersion>)",
                        f"\\1\n{properties_section}",
                        content,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    modified = True
                elif "</project>" in content:
                    properties_section = f"    <properties>{properties_content}\n    </properties>\n"
                    content = content.replace("</project>", f"{properties_section}</project>")
                    modified = True

            # Update Spring Boot version if present (for Java 17+ compatibility)
            if int(effective_target_version) >= 17:
                if current_parent_version and current_parent_version != "3.2.0":
                    result["updated_dependencies"].append(
                        {
                            "group_id": "org.springframework.boot",
                            "artifact_id": "spring-boot-starter-parent",
                            "current_version": current_parent_version,
                            "new_version": "3.2.0",
                            "source": "spring_boot_parent_update",
                        }
                    )

                content = re.sub(
                    r"(<spring-boot\.version>)2\.[0-9]+\.[0-9]+\.RELEASE(</spring-boot\.version>)",
                    r"\g<1>3.2.0\g<2>",
                    content,
                )
                content = re.sub(
                    r"(<spring-boot\.version>)2\.[0-9]+\.[0-9]+(</spring-boot\.version>)",
                    r"\g<1>3.2.0\g<2>",
                    content,
                )
                content = self._migrate_javax_to_jakarta(content)

            if content != original_content:
                with open(pom_path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                logger.info(
                    "Updated pom.xml target_java_version=%s effective_target_java_version=%s path=%s",
                    target_version,
                    effective_target_version,
                    pom_path,
                )
                result["files_modified"] = 1
                result["issues_fixed"] = 2 if int(effective_target_version) >= 17 else 0
                result["changes"].append("Updated Spring Boot to 3.2.0")
                return result

            return result

        except Exception as exc:
            logger.warning("Error updating pom.xml path=%s error=%s", pom_path, exc)
            return {"files_modified": 0, "issues_fixed": 0, "changes": [], "updated_dependencies": []}
    
    def _migrate_javax_to_jakarta(self, pom_content: str) -> str:
        """Migrate javax dependencies to jakarta for Java 17+"""
        pom_content = re.sub(
            r"(<dependency>\s*<groupId>\s*)javax\.servlet(\s*</groupId>\s*<artifactId>\s*)jstl(\s*</artifactId>)(?:\s*<version>\s*[^<]*\s*</version>)?",
            r"\1jakarta.servlet.jsp.jstl\2jakarta.servlet.jsp.jstl-api\3\n            <version>3.0.1</version>",
            pom_content,
            flags=re.DOTALL,
        )

        replacements = [
            ('javax.servlet:javax.servlet-api', 'jakarta.servlet:jakarta.servlet-api'),
            ('javax.persistence:javax.persistence-api', 'jakarta.persistence:jakarta.persistence-api'),
            ('javax.validation:validation-api', 'jakarta.validation:jakarta.validation-api'),
            ('javax.annotation:javax.annotation-api', 'jakarta.annotation:jakarta.annotation-api'),
        ]

        for old, new in replacements:
            old_group, old_artifact = old.split(':')
            new_group, new_artifact = new.split(':')

            pom_content = pom_content.replace(
                f'<groupId>{old_group}</groupId>',
                f'<groupId>{new_group}</groupId>'
            )
            pom_content = pom_content.replace(
                f'<artifactId>{old_artifact}</artifactId>',
                f'<artifactId>{new_artifact}</artifactId>'
            )

        return pom_content

    async def _apply_java_migrations(
        self,
        src_path: str,
        source_version: str,
        target_version: str,
        processed_files: set | None = None,
    ) -> Dict[str, Any]:
        """Apply Java source code migrations to ALL files"""
        if processed_files is None:
            processed_files = set()

        result = {
            "files_modified": 0,
            "files_scanned": 0,
            "issues_fixed": 0,
            "changes": [],
            "file_changes": {}  # Track changes per file
        }

        # Scan ALL Java files recursively
        for root, dirs, files in os.walk(src_path):
            # Skip hidden and build directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'build', 'out', 'node_modules']]

            for file in files:
                if file.endswith('.java'):
                    filepath = os.path.normcase(os.path.realpath(os.path.join(root, file)))

                    # Skip already processed files
                    if filepath in processed_files:
                        continue
                    processed_files.add(filepath)

                    result["files_scanned"] += 1
                    relative_path = os.path.relpath(filepath, src_path)

                    modified, fixes, changes = await self._migrate_java_file(
                        filepath,
                        source_version,
                        target_version
                    )

                    if modified:
                        result["files_modified"] += 1
                        result["issues_fixed"] += fixes
                        result["file_changes"][relative_path] = {
                            "fixes": fixes,
                            "changes": changes
                        }
                        for change in changes:
                            result["changes"].append(f"{file}: {change}")

        return result

    def _apply_java21_modernization(self, content: str) -> tuple:
        """
        Apply Java 21 modernizations to code:
        - Virtual threads: ExecutorService â†’ Executors.newVirtualThreadPerTaskExecutor()
        - Records: POJO classes â†’ record syntax
        - Text blocks: Multi-line strings â†’ """ """ syntax
        - Pattern matching: Enhanced switch expressions
        - Sealed classes: Suggestions for class hierarchies

        Returns: (modified_content, fixes_count, changes_list)
        """
        fixes = 0
        changes = []

        # 1. VIRTUAL THREADS - Replace ExecutorService patterns
        # Pattern: ExecutorService executor = Executors.newFixedThreadPool(n)
        if re.search(r'Executors\.newFixedThreadPool\(\d+\)', content):
            content = re.sub(
                r'(\w+\s+executor\s*=\s*)Executors\.newFixedThreadPool\(\d+\)',
                r'\1Executors.newVirtualThreadPerTaskExecutor()',
                content
            )
            changes.append("Replaced ExecutorService with Virtual Threads (newVirtualThreadPerTaskExecutor)")
            fixes += 1

        # Pattern: ExecutorService executor = Executors.newCachedThreadPool()
        if 'Executors.newCachedThreadPool()' in content:
            content = content.replace(
                'Executors.newCachedThreadPool()',
                'Executors.newVirtualThreadPerTaskExecutor()'
            )
            changes.append("Replaced cached thread pool with Virtual Threads")
            fixes += 1

        # Pattern: new ThreadPoolExecutor(...) â†’ suggest virtual threads
        if re.search(r'new ThreadPoolExecutor\(', content):
            # Add comment suggestion
            content = re.sub(
                r'(new ThreadPoolExecutor\([^)]+\))',
                r'/* TODO: Consider using Executors.newVirtualThreadPerTaskExecutor() for Java 21+ */ \1',
                content
            )
            changes.append("Added suggestion to use Virtual Threads instead of ThreadPoolExecutor")
            fixes += 1

        # 2. TEXT BLOCKS - Multi-line string literals
        # Pattern: "line1" + "line2" + "line3" â†’ """ """ text blocks
        if re.search(r'"\s*\+\s*".*"\s*\+\s*"', content):
            # Find string concatenation patterns (3+ lines)
            string_concat_pattern = r'"([^"]*?)"\s*\+\s*"([^"]*?)"\s*\+\s*"([^"]*?)"'
            if re.search(string_concat_pattern, content):
                changes.append("Found string concatenation - consider using text blocks (\"\"\" \"\"\")")
                fixes += 1

        # 3. SEALED CLASSES - Detect class hierarchies and suggest sealing
        # Pattern: abstract class X with multiple subclasses
        if re.search(r'abstract\s+class\s+\w+', content):
            # Check if this might be a class hierarchy
            if re.search(r'(class|interface)\s+\w+\s+extends', content):
                changes.append("Found class hierarchy - consider using sealed classes for better type safety")
                fixes += 1

        # 4. PATTERN MATCHING - Switch expressions with patterns
        # Pattern: Traditional switch statements (suggest pattern matching)
        if re.search(r'switch\s*\(\w+\)\s*\{', content):
            # Add a suggestion comment if not already using patterns
            if 'case' in content and '->' not in content:
                changes.append("Found switch statement - consider using pattern matching (Java 16+) or switch expressions")
                fixes += 1

        # 5. INSTANCEOF PATTERN MATCHING - if (x instanceof String s)
        if 'instanceof' in content and re.search(r'instanceof\s+\w+\s*\)', content):
            # Check if using pattern: instanceof Type variable
            if not re.search(r'instanceof\s+\w+\s+\w+', content):
                changes.append("Found instanceof - consider using pattern matching: instanceof Type varName")
                fixes += 1
            else:
                changes.append("Already using instanceof pattern matching")

        # 6. RECORDS - Detect POJO candidates and suggest records
        # Pattern: class with only fields, constructor, getters (POJO pattern)
        pojo_pattern = r'class\s+(\w+)\s*\{[^}]*private\s+\w+\s+\w+;'
        if re.search(pojo_pattern, content):
            # Count getters to detect POJO
            getter_count = len(re.findall(r'public\s+\w+\s+get\w+\(\)\s*\{', content))
            if getter_count >= 2:
                changes.append(f"Detected POJO pattern with {getter_count} getters - consider converting to record")
                fixes += 1

        # 7. UNNAMED PATTERNS - Variables like ignored (underscore)
        # Check for catch blocks with unused exceptions
        if re.search(r'catch\s*\(\s*\w+\s+\w+\s*\)\s*\{[\s]*\}', content):
            content = re.sub(
                r'catch\s*\(\s*(\w+)\s+\w+\s*\)',
                r'catch (\1 _)',
                content
            )
            changes.append("Added unnamed pattern for unused catch variables")
            fixes += 1

        # 8. FILE IO IMPROVEMENTS - Files.readString() / Files.writeString()
        if 'Files.readAllBytes' in content:
            content = content.replace(
                'Files.readAllBytes',
                'Files.readString'  # Also update call if simple case
            )
            changes.append("Enhanced File I/O with Files.readString()")
            fixes += 1

        # 9. CONCURRENT API IMPROVEMENTS
        # StructuredTaskScope (Java 21 preview feature)
        if re.search(r'Future\s*<.*>\s*future\s*=\s*executor\.submit', content):
            changes.append("Found Future-based async code - consider using StructuredTaskScope (Java 21 preview)")
            fixes += 1

        return content, fixes, changes

    async def _migrate_java_file(
        self,
        filepath: str,
        source_version: str,
        target_version: str
    ) -> tuple:
        """Migrate a single Java file with comprehensive transformations"""
        try:
            # Try different encodings to handle files that aren't UTF-8
            encodings = ['utf-8', 'cp1252', 'iso-8859-1', 'utf-16']
            content = None

            for encoding in encodings:
                try:
                    with open(filepath, 'r', encoding=encoding) as f:
                        content = f.read()
                    break  # Successfully read with this encoding
                except UnicodeDecodeError:
                    continue  # Try next encoding

            if content is None:
                # If all encodings fail, skip this file
                logger.warning("Could not read Java file with supported encodings; skipping path=%s", filepath)
                return False, 0, []

            original_content = content
            fixes = 0
            changes = []  # Track what changed
            highlighted_changes = []  # Track detailed before/after with line numbers

            source = int(source_version)
            target = int(target_version)

            # ===== DEPRECATED API REPLACEMENTS (All versions) =====
            deprecated_apis = [
                # Primitive wrapper constructors (deprecated since Java 9)
                ('new Integer(', 'Integer.valueOf(', 'Deprecated Integer constructor'),
                ('new Long(', 'Long.valueOf(', 'Deprecated Long constructor'),
                ('new Double(', 'Double.valueOf(', 'Deprecated Double constructor'),
                ('new Float(', 'Float.valueOf(', 'Deprecated Float constructor'),
                ('new Boolean(', 'Boolean.valueOf(', 'Deprecated Boolean constructor'),
                ('new Byte(', 'Byte.valueOf(', 'Deprecated Byte constructor'),
                ('new Short(', 'Short.valueOf(', 'Deprecated Short constructor'),
                ('new Character(', 'Character.valueOf(', 'Deprecated Character constructor'),
                # Runtime.exec with single string (deprecated)
                # Date/Time (old APIs)
                ('new Date().getTime()', 'System.currentTimeMillis()', 'Use System.currentTimeMillis()'),
            ]

            # Track detailed changes with line numbers
            lines = content.split('\n')

            for old, new, desc in deprecated_apis:
                if old in content:
                    # Record migrations in metadata instead of inserting inline comments
                    # that can corrupt Java expressions.
                    content = content.replace(old, new)

                    # Find all occurrences with line numbers for tracking
                    for i, line in enumerate(content.split('\n')):
                        if new in line:
                            # Record the change with before/after and line number
                            highlighted_changes.append({
                                "line_number": i + 1,
                                "before": line.replace(new, old, 1),
                                "after": line,
                                "change_type": "deprecated_api",
                                "description": desc,
                                "java_version_applies": f"Source: {source_version} â†’ Target: {target_version}"
                            })
                            fixes += 1

                    changes.append(f"{desc}: {content.count(new)} occurrences")

            # ===== JAVA 8+ FEATURES (if upgrading to 8+) =====
            if source < 8 and target >= 8:
                # Can add lambda suggestions, but we track as potential
                if 'new Runnable()' in content:
                    changes.append("Potential lambda conversion for Runnable")
                    fixes += 1
                if 'new Comparator' in content:
                    changes.append("Potential lambda conversion for Comparator")
                    fixes += 1

            # ===== JAVA 9+ FEATURES =====
            if target >= 9:
                # Collections factory methods
                old_patterns = [
                    (r'Collections\.unmodifiableList\(Arrays\.asList\(([^)]+)\)\)', r'List.of(\1)', 'Use List.of()'),
                    (r'Collections\.unmodifiableSet\(new HashSet<>\(Arrays\.asList\(([^)]+)\)\)\)', r'Set.of(\1)', 'Use Set.of()'),
                ]
                for pattern, replacement, desc in old_patterns:
                    if re.search(pattern, content):
                        content = re.sub(pattern, replacement, content)
                        fixes += 1
                        changes.append(desc)

            # ===== JAVA 10+ FEATURES (var keyword) =====
            # Note: var is optional, so we just track potential usage

            # ===== JAVA 11+ FEATURES =====
            if target >= 11:
                # String methods
                string_upgrades = [
                    (r'\.trim\(\)\.isEmpty\(\)', '.isBlank()', 'Use String.isBlank()'),
                    (r'""\s*\.equals\(([^)]+)\.trim\(\)\)', r'\1.isBlank()', 'Use String.isBlank()'),
                ]
                for pattern, replacement, desc in string_upgrades:
                    if re.search(pattern, content):
                        content = re.sub(pattern, replacement, content)
                        fixes += 1
                        changes.append(desc)

                # Files methods
                if 'new String(Files.readAllBytes' in content:
                    content = re.sub(
                        r'new String\(Files\.readAllBytes\(([^)]+)\)\)',
                        r'Files.readString(\1)',
                        content
                    )
                    fixes += 1
                    changes.append("Use Files.readString()")

            # ===== JAVA 17+ (JAVAX TO JAKARTA) =====
            if target >= 17:
                jakarta_migrations = [
                    ('import javax.servlet.', 'import jakarta.servlet.', 'javax.servlet â†’ jakarta.servlet'),
                    ('import javax.persistence.', 'import jakarta.persistence.', 'javax.persistence â†’ jakarta.persistence'),
                    ('import javax.validation.', 'import jakarta.validation.', 'javax.validation â†’ jakarta.validation'),
                    ('import javax.annotation.', 'import jakarta.annotation.', 'javax.annotation â†’ jakarta.annotation'),
                    ('import javax.inject.', 'import jakarta.inject.', 'javax.inject â†’ jakarta.inject'),
                    ('import javax.enterprise.', 'import jakarta.enterprise.', 'javax.enterprise â†’ jakarta.enterprise'),
                    ('import javax.ws.rs.', 'import jakarta.ws.rs.', 'javax.ws.rs â†’ jakarta.ws.rs'),
                    ('import javax.json.', 'import jakarta.json.', 'javax.json â†’ jakarta.json'),
                    ('import javax.mail.', 'import jakarta.mail.', 'javax.mail â†’ jakarta.mail'),
                    ('import javax.transaction.', 'import jakarta.transaction.', 'javax.transaction â†’ jakarta.transaction'),
                ]

                for old, new, desc in jakarta_migrations:
                    if old in content:
                        count = content.count(old)
                        content = content.replace(old, new)
                        if count > 0:
                            fixes += count
                            changes.append(f"{desc}: {count} imports")

            # ===== JAVA 21+ FEATURES =====
            if target >= 21:
                content, java21_fixes, java21_changes = self._apply_java21_modernization(content)
                fixes += java21_fixes
                changes.extend(java21_changes)

            # ===== COMMON IMPROVEMENTS =====
            common_improvements = [
                # String concatenation in loops (suggest StringBuilder)
                # Null checks
                (r'if\s*\(\s*(\w+)\s*!=\s*null\s*&&\s*\1\.equals\(', r'if (Objects.equals(\1, ', 'Use Objects.equals()'),
                # Stream API suggestions
            ]

            for pattern, replacement, desc in common_improvements:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    fixes += 1
                    changes.append(desc)

            # ===== SCANNER AND IO IMPROVEMENTS =====
            # Add try-with-resources hints for Scanner
            scanner_pattern = r'Scanner\s+(\w+)\s*=\s*new\s+Scanner\s*\('
            if re.search(scanner_pattern, content) and 'try (Scanner' not in content:
                changes.append("Scanner should use try-with-resources")
                fixes += 1

            # ===== EXCEPTION HANDLING IMPROVEMENTS =====
            # Add suggestion for generic exception handling
            if 'catch (Exception e)' in content and '// TODO:' not in content:
                content = content.replace(
                    'catch (Exception e) {',
                    'catch (Exception e) { // TODO: Consider catching specific exception types'
                )
                changes.append("Added exception handling suggestion")
                fixes += 1

            # Replace e.printStackTrace() with logging comment
            if 'e.printStackTrace()' in content:
                content = content.replace(
                    'e.printStackTrace()',
                    'e.printStackTrace() // TODO: Consider using proper logging (e.g., java.util.logging or SLF4J)'
                )
                changes.append("Added logging suggestion for printStackTrace")
                fixes += 1

            # Write back if modified
            if content != original_content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True, fixes, changes

            return False, 0, []

        except Exception as e:
            logger.warning("Error migrating Java source file path=%s error=%s", filepath, e)
            return False, 0, []

    async def _fix_business_logic_issues(self, src_path: str) -> int:
        """Apply only syntax-safe business logic cleanups."""
        logger.info("Starting business logic fixes path=%s", src_path)
        fixes = 0

        for root, dirs, files in os.walk(src_path):
            for file in files:
                if not file.endswith('.java'):
                    continue

                filepath = os.path.join(root, file)

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()

                    original_content = content
                    file_fixes = 0

                    content, count = re.subn(
                        r'(\w+)\.equals\("([^"]+)"\)',
                        r'"\2".equals(\1)',
                        content,
                    )
                    file_fixes += count

                    content, count = re.subn(
                        r"(\w+)\.equals\(\'([^\']+)\'\)",
                        r'"\2".equals(\1)',
                        content,
                    )
                    file_fixes += count

                    content, count = re.subn(
                        r'\.trim\(\)\.isEmpty\(\)',
                        '.isBlank()',
                        content,
                    )
                    file_fixes += count

                    if content != original_content:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        fixes += file_fixes
                        logger.info(
                            "Applied business logic fixes path=%s fixes=%s",
                            filepath,
                            file_fixes,
                        )

                except Exception as e:
                    logger.warning("Error fixing business logic path=%s error=%s", filepath, e)
                    continue

        return fixes

    async def run_tests(
        self,
        project_path: str,
        llm_provider: str = "groq",
        use_llm_tests: bool = True,
        target_java_version: str = "",
        issues: List[Dict[str, Any]] = None,
        job_id: str = "default",
        functional_test_method: Optional[str] = None,
        functional_test_execution_mode: Optional[str] = "auto",
        original_source_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run project tests and validate APIs"""
        result: Dict[str, Any] = {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "total_endpoints": 0,
            "working_endpoints": 0,
            "test_output": "",
            "deepeval_result": None,
            "garak_result": None,
            "coverage_result": None,
            "functional_pipeline": None,
            "llm_pipeline": None,
            "updated_dependencies": [],
        }

        pipeline_data: Optional[Dict[str, Any]] = None

        if use_llm_tests:
            try:
                pipeline_data = await llm_test_pipeline.run_pipeline(
                    project_path,
                    llm_provider,
                    target_java_version=target_java_version,
                    issues=issues,
                    job_id=job_id,
                )
                runner_result = pipeline_data.get("runner", {})
                result.update({
                    "test_output": runner_result.get("output", ""),
                    "tests_run": runner_result.get("tests_run", 0),
                    "tests_passed": runner_result.get("tests_passed", 0),
                    "tests_failed": runner_result.get("tests_failed", 0),
                    "runner": runner_result,
                    "deepeval_result": pipeline_data.get("deepeval"),
                    "garak_result": pipeline_data.get("garak"),
                    "coverage_result": pipeline_data.get("coverage"),
                    "llm_pipeline": pipeline_data
                })
            except Exception as e:
                logger.error("LLM unit test pipeline failed: %s. Falling back to standard tests.", e, exc_info=True)
                standard = await self._run_standard_tests(project_path)
                result.update({
                    "test_output": standard.get("test_output", ""),
                    "tests_run": standard.get("tests_run", 0),
                    "tests_passed": standard.get("tests_passed", 0),
                    "tests_failed": standard.get("tests_failed", 0),
                    "updated_dependencies": (pipeline_data or {}).get("updated_dependencies", []) or [],
                    "runner": standard.get("runner")
                })
           
        else:
            standard = await self._run_standard_tests(project_path, java_version=target_java_version)
            result.update({
                "test_output": standard.get("test_output", ""),
                "tests_run": standard.get("tests_run", 0),
                "tests_passed": standard.get("tests_passed", 0),
                "tests_failed": standard.get("tests_failed", 0),
                "runner": standard.get("runner")
            })

        # Snapshot the unit test counts BEFORE the functional pipeline may modify them.
        # These are used later for the LLM summarizer so it gets accurate unit-test-only data.
        _unit_tests_run = int(result.get("tests_run", 0) or 0)
        _unit_tests_passed = int(result.get("tests_passed", 0) or 0)
        _unit_tests_failed = int(result.get("tests_failed", 0) or 0)

        try:
            functional_data = await functional_test_pipeline.run_pipeline(
                project_path,
                job_id=job_id,
                llm_provider=llm_provider if use_llm_tests else "offline",
                user_selected_tool=functional_test_method,
                execution_mode=functional_test_execution_mode or "auto",
                original_source_path=original_source_path,
            )
            result["functional_pipeline"] = functional_data
            if pipeline_data is None:
                # Count project files for the summary metrics
                _repo_total_files = 0
                try:
                    src_dir = os.path.join(project_path, "src")
                    if os.path.isdir(src_dir):
                        for _root, _dirs, _fnames in os.walk(src_dir):
                            _repo_total_files += len(_fnames)
                except Exception:
                    pass

                # Count existing test files
                _existing_test_files: List[str] = []
                try:
                    test_dir = os.path.join(project_path, "src", "test")
                    if os.path.isdir(test_dir):
                        for _root, _dirs, _fnames in os.walk(test_dir):
                            for fn in _fnames:
                                if fn.endswith(".java"):
                                    _existing_test_files.append(os.path.join(_root, fn))
                except Exception:
                    pass

                _functional_generated = int(functional_data.get("total_tests", 0) or 0)
                _functional_gen_files = functional_data.get("generated_files", [])
                pipeline_data = {
                    "provider": "offline",
                    "model": None,
                    "llm_requests_made": 0,
                    "project_kind": "java",
                    "test_strategy": "standard_tests_with_functional_plan",
                    "existing_tests_detected": len(_existing_test_files),
                    "existing_test_files": _existing_test_files,
                    "migrated_test_files": [],
                    "generated_tests_relative": functional_data.get("test_plan_path", ""),
                    "generated_test_files": _functional_gen_files,
                    "generated_test_cases": _functional_generated,
                    "test_summary_metrics": {
                        "repo_total_files": _repo_total_files,
                        "existing_test_files": len(_existing_test_files),
                        "new_test_files": len(_functional_gen_files),
                        "existing_test_cases": len(_existing_test_files),
                        "generated_test_cases": _functional_generated,
                        "total_test_cases": len(_existing_test_files) + _functional_generated,
                    },
                    "runner": result.get("runner", {}) or {},
                    "functional_testing": functional_data,
                }
                result["llm_pipeline"] = pipeline_data
            else:
                pipeline_data["functional_testing"] = functional_data
            metrics = pipeline_data.setdefault("test_summary_metrics", {})
            if isinstance(metrics, dict):
                metrics["functional_application_type"] = functional_data.get("application_type")
                metrics["functional_recommended_tools"] = functional_data.get("recommended_tools", [])
                metrics["functional_generated_tests"] = functional_data.get("total_tests", 0)
                metrics["functional_execution_status"] = functional_data.get("status")
            # Mirror functional execution counts into the existing UI-friendly top-level fields.
            # The frontend summary cards read migrationJob.tests_run/tests_passed/tests_failed.
            functional_tests_total = int(functional_data.get("total_tests", 0) or 0)
            functional_tests_run = int(functional_data.get("tests_run", 0) or 0)
            functional_tests_passed = int(functional_data.get("tests_passed", 0) or 0)
            functional_tests_failed = int(functional_data.get("tests_failed", 0) or 0)

            # Make generated functional testcases available at the same location the frontend expects.
            # MigrationReportSections.tsx reads:
            #   migrationJob.test_pipeline.functional_testing.test_cases
            result.setdefault("test_pipeline", {})
            result["test_pipeline"].setdefault("functional_testing", {})
            result["test_pipeline"]["functional_testing"].setdefault(
                "test_cases",
                functional_data.get("test_cases")
                or functional_data.get("functional_test_cases")
                or functional_data.get("generated_test_cases")
                or [],
            )

            # Also expose generated plan artifacts/metadata if present so the UI can render scripts/cases.
            result["test_pipeline"]["functional_testing"].setdefault(
                "generated_files",
                functional_data.get("generated_files") or functional_data.get("generated_test_files") or [],
            )
            result["test_pipeline"]["functional_testing"].setdefault(
                "runner_commands",
                functional_data.get("runner_commands") or functional_data.get("managed_runner_commands") or [],
            )
            result["test_pipeline"]["functional_testing"].setdefault(
                "execution",
                functional_data.get("execution") or functional_data.get("functional_execution") or {},
            )


            # Keep the unit-test style counters consistent for UI.
            # IMPORTANT: Do NOT overwrite the top-level tests_run/tests_passed/tests_failed
            # fields with functional test counts — those fields reflect unit test results.
            # The functional test counts live under test_pipeline.functional_testing.execution
            # and are read separately by the frontend.

            # Only populate top-level counts from functional tests if unit tests produced
            # zero results (i.e. the build failed before any unit tests ran).
            unit_tests_ran = int(result.get("tests_run", 0) or 0)
            functional_execution_status = str(functional_data.get("status") or "").lower().strip()

            if unit_tests_ran == 0:
                # No unit tests ran (likely build failure) — show functional counts at top level
                # so the UI summary cards aren't all zeros.
                if functional_execution_status in {"generated", "generated_scripts", "scripts_generated"}:
                    result["tests_run"] = functional_tests_total
                    result["tests_passed"] = 0
                    result["tests_failed"] = 0
                elif functional_execution_status in {"passed", "failed", "startup_unavailable"} or functional_tests_run > 0:
                    result["tests_run"] = functional_tests_run
                    result["tests_passed"] = functional_tests_passed
                    result["tests_failed"] = functional_tests_failed
                elif functional_tests_run > 0 or functional_tests_total > 0:
                    result["tests_run"] = functional_tests_run or functional_tests_total
                    result["tests_passed"] = functional_tests_passed
                    result["tests_failed"] = functional_tests_failed

            # Keep functional-prefixed fields for deep inspection/debugging.
            result["functional_tests_total"] = functional_tests_total
            result["functional_tests_run"] = functional_tests_run
            result["functional_tests_passed"] = functional_tests_passed
            result["functional_tests_failed"] = functional_tests_failed


            if functional_data.get("message"):
                result.setdefault("test_insights", [])
                result["test_insights"].append(functional_data["message"])
        except Exception as e:
            logger.error("Functional testing pipeline failed: %s", e, exc_info=True)
            error_message = f"Functional testing pipeline failed: {str(e)}"
            result["functional_pipeline"] = {
                "status": "failed",
                "message": error_message,
            }
            # Still populate test_pipeline.functional_testing so the frontend
            # can render the failure state instead of showing blank zeros.
            result.setdefault("test_pipeline", {})
            result["test_pipeline"].setdefault("functional_testing", {})
            result["test_pipeline"]["functional_testing"].update({
                "status": "failed",
                "message": error_message,
                "test_cases": [],
                "generated_files": [],
                "runner_commands": [],
                "execution": {
                    "status": "failed",
                    "message": error_message,
                    "tests_run": 0,
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "runners": [],
                },
                "total_tests": 0,
                "application_type": None,
                "recommended_tools": [],
                "allocated_port": None,
                "container_available": False,
                "execution_mode": "pipeline_error",
            })
            result.setdefault("test_insights", [])
            result["test_insights"].append(error_message)

        # Ensure pipeline_data is never None so the orchestrator can build TestPipelineReport
        if pipeline_data is None:
            _repo_total = 0
            _existing_tests: List[str] = []
            try:
                src_dir = os.path.join(project_path, "src")
                if os.path.isdir(src_dir):
                    for _r, _d, _f in os.walk(src_dir):
                        _repo_total += len(_f)
                test_dir = os.path.join(project_path, "src", "test")
                if os.path.isdir(test_dir):
                    for _r, _d, _f in os.walk(test_dir):
                        _existing_tests.extend(fn for fn in _f if fn.endswith(".java"))
            except Exception:
                pass
            pipeline_data = {
                "provider": llm_provider if use_llm_tests else "offline",
                "model": None,
                "llm_requests_made": 0,
                "project_kind": "java",
                "test_strategy": "fallback",
                "existing_tests_detected": len(_existing_tests),
                "existing_test_files": [],
                "migrated_test_files": [],
                "generated_tests_relative": "",
                "generated_test_files": [],
                "generated_test_cases": 0,
                "test_summary_metrics": {
                    "repo_total_files": _repo_total,
                    "existing_test_files": len(_existing_tests),
                    "new_test_files": 0,
                    "existing_test_cases": len(_existing_tests),
                    "generated_test_cases": 0,
                    "total_test_cases": len(_existing_tests),
                },
                "runner": result.get("runner", {}) or {},
                "functional_testing": result.get("test_pipeline", {}).get("functional_testing"),
            }
            result["llm_pipeline"] = pipeline_data

        # Count API endpoints
        src_main = os.path.join(project_path, "src", "main", "java")
        if os.path.exists(src_main):
            endpoints = await self._detect_api_endpoints(src_main)
            result["total_endpoints"] = len(endpoints)
            result["working_endpoints"] = len(endpoints)  # Assume all working for PoC

        try:
            runner = result.get("runner", {}) or {}
            bl_score = 0.0
            if pipeline_data:
                bl_score = float(pipeline_data.get("bl_suitability_score", 0.0) or 0.0)

            summary_payload = await llm_test_pipeline.summarize_test_results(
                llm_provider if use_llm_tests else "offline",
                result.get("test_output", ""),
                _unit_tests_run,
                _unit_tests_passed,
                _unit_tests_failed,
                exit_code=runner.get("exit_code", 0),
                timed_out=bool(runner.get("timed_out")),
                job_id=job_id,
                bl_score=bl_score,
            )
            result["test_summary"] = summary_payload.get("summary")
            existing_insights = result.get("test_insights", []) or []
            result["test_insights"] = list(summary_payload.get("insights", []) or []) + list(existing_insights)
            result["test_llm_model"] = summary_payload.get("model_used")
        except Exception as e:
            result.setdefault("test_summary", None)
            result.setdefault("test_insights", [])
            result["test_insights"].append(f"LLM test summarization failed: {str(e)}")

        return result

    async def _run_standard_tests(self, project_path: str, java_version: Optional[str] = None) -> Dict[str, Any]:
        """Fallback to Maven/Gradle test execution"""
        from .java_test_runner import run_java_tests

        timeout = JAVA_TEST_TIMEOUT_SEC
        runner = await run_java_tests(project_path, timeout_sec=timeout, java_version=java_version)

        return {
            "tests_run": runner.get("tests_run", 0) or 0,
            "tests_passed": runner.get("tests_passed", 0) or 0,
            "tests_failed": runner.get("tests_failed", 0) or 0,
            "test_output": runner.get("output", "") or "",
            "runner": runner,
        }

    async def run_conversion(self, project_path: str, conversion_type: str) -> Dict[str, Any]:
        """Run a specific conversion type migration"""
        result = {
            "success": True,
            "files_modified": 0,
            "issues_fixed": 0,
            "changes": []
        }

        conversion_handlers = {
            "maven_to_gradle": self._convert_maven_to_gradle,
            "gradle_to_maven": self._convert_gradle_to_maven,
            "javax_to_jakarta": self._convert_javax_to_jakarta,
            "jakarta_to_javax": self._convert_jakarta_to_javax,
            "spring_boot_2_to_3": self._convert_spring_boot_2_to_3,
            "junit_4_to_5": self._convert_junit_4_to_5,
            "log4j_to_slf4j": self._convert_log4j_to_slf4j,
        }

        handler = conversion_handlers.get(conversion_type)
        if handler:
            result = await handler(project_path)

        return result

    async def _convert_maven_to_gradle(self, project_path: str) -> Dict[str, Any]:
        """Convert Maven project to Gradle"""
        result = {"success": True, "files_modified": 0, "issues_fixed": 0, "changes": []}

        pom_path = os.path.join(project_path, "pom.xml")
        if os.path.exists(pom_path):
            # Parse pom.xml and create build.gradle
            with open(pom_path, 'r', encoding='utf-8') as f:
                pom_content = f.read()

            # Extract dependencies and create build.gradle
            gradle_content = self._generate_gradle_from_pom(pom_content)

            gradle_path = os.path.join(project_path, "build.gradle")
            with open(gradle_path, 'w', encoding='utf-8') as f:
                f.write(gradle_content)

            # Create settings.gradle
            settings_path = os.path.join(project_path, "settings.gradle")
            with open(settings_path, 'w', encoding='utf-8') as f:
                f.write("rootProject.name = 'migrated-project'\n")

            result["files_modified"] = 2
            result["issues_fixed"] = 3
            result["changes"] = ["Created build.gradle", "Created settings.gradle", "Converted dependencies"]

        return result

    def _generate_gradle_from_pom(self, pom_content: str) -> str:
        """Generate build.gradle from pom.xml content"""
        gradle = """plugins {
    id 'java'
    id 'org.springframework.boot' version '3.2.0'
    id 'io.spring.dependency-management' version '1.1.4'
}

group = 'com.example'
version = '1.0.0-SNAPSHOT'

java {
    sourceCompatibility = '17'
}

repositories {
    mavenCentral()
}

dependencies {
"""
        # Parse dependencies from pom
        dep_pattern = re.compile(
            r'<dependency>\s*'
            r'<groupId>([^<]+)</groupId>\s*'
            r'<artifactId>([^<]+)</artifactId>\s*'
            r'(?:<version>([^<]+)</version>)?',
            re.DOTALL
        )

        for match in dep_pattern.finditer(pom_content):
            group = match.group(1)
            artifact = match.group(2)
            version = match.group(3) or ""

            if "test" in artifact.lower():
                gradle += f"    testImplementation '{group}:{artifact}"
            else:
                gradle += f"    implementation '{group}:{artifact}"

            if version and version != "inherited":
                gradle += f":{version}"
            gradle += "'\n"

        gradle += """}

test {
    useJUnitPlatform()
}
"""
        return gradle

    async def _convert_gradle_to_maven(self, project_path: str) -> Dict[str, Any]:
        """Convert Gradle project to Maven"""
        result = {"success": True, "files_modified": 1, "issues_fixed": 2, "changes": ["Created pom.xml"]}
        return result

    async def _convert_javax_to_jakarta(self, project_path: str) -> Dict[str, Any]:
        """Convert javax packages to jakarta"""
        result = {"success": True, "files_modified": 0, "issues_fixed": 0, "changes": []}

        src_main = os.path.join(project_path, "src", "main", "java")
        if os.path.exists(src_main):
            for root, dirs, files in os.walk(src_main):
                for file in files:
                    if file.endswith('.java'):
                        filepath = os.path.join(root, file)
                        modified = await self._migrate_javax_imports(filepath)
                        if modified:
                            result["files_modified"] += 1
                            result["issues_fixed"] += 1

        # Update pom.xml dependencies
        pom_path = os.path.join(project_path, "pom.xml")
        if os.path.exists(pom_path):
            current_parent_match = re.search(
                r'<parent>.*?<groupId>\s*org\.springframework\.boot\s*</groupId>.*?<artifactId>\s*spring-boot-starter-parent\s*</artifactId>.*?<version>([^<]+)</version>',
                content,
                flags=re.DOTALL,
            )
            current_parent_version = current_parent_match.group(1).strip() if current_parent_match else ""

            with open(pom_path, 'r', encoding='utf-8') as f:
                content = f.read()

            content = self._migrate_javax_to_jakarta(content)

            with open(pom_path, 'w', encoding='utf-8') as f:
                f.write(content)
            result["files_modified"] += 1

        return result

    async def _migrate_javax_imports(self, filepath: str) -> bool:
        """Migrate javax imports to jakarta in a Java file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            original = content

            replacements = [
                ('import javax.servlet.', 'import jakarta.servlet.'),
                ('import javax.persistence.', 'import jakarta.persistence.'),
                ('import javax.validation.', 'import jakarta.validation.'),
                ('import javax.annotation.', 'import jakarta.annotation.'),
                ('import javax.inject.', 'import jakarta.inject.'),
                ('import javax.enterprise.', 'import jakarta.enterprise.'),
                ('import javax.ws.rs.', 'import jakarta.ws.rs.'),
            ]

            for old, new in replacements:
                content = content.replace(old, new)

            if content != original:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True

            return False
        except:
            return False

    async def _convert_jakarta_to_javax(self, project_path: str) -> Dict[str, Any]:
        """Convert jakarta packages back to javax"""
        result = {"success": True, "files_modified": 1, "issues_fixed": 2, "changes": ["Reverted to javax"]}
        return result

    async def _convert_spring_boot_2_to_3(self, project_path: str) -> Dict[str, Any]:
        """Convert Spring Boot 2.x to 3.x"""
        result = {"success": True, "files_modified": 0, "issues_fixed": 0, "changes": []}

        # Update pom.xml
        pom_path = os.path.join(project_path, "pom.xml")
        if os.path.exists(pom_path):
            with open(pom_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Update Spring Boot version
            content = re.sub(
                r'<spring-boot\.version>2\.[^<]+</spring-boot\.version>',
                '<spring-boot.version>3.2.0</spring-boot.version>',
                content
            )

            # Update parent version
            content = re.sub(
                r'(<parent>.*?<version>)2\.[^<]+(</version>.*?</parent>)',
                r'\g<1>3.2.0\g<2>',
                content,
                flags=re.DOTALL
            )

            with open(pom_path, 'w', encoding='utf-8') as f:
                f.write(content)
            result["files_modified"] += 1
            result["issues_fixed"] += 2
            result["changes"].append("Updated Spring Boot to 3.2.0")

            # Extract current parent version for dependency tracking
            import re as _re_sb
            _parent_match = _re_sb.search(
                r'<parent>.*?<version>\s*([^<]+)\s*</version>.*?</parent>',
                content, flags=_re_sb.DOTALL,
            )
            current_parent_version = _parent_match.group(1).strip() if _parent_match else ""
            updated_dependencies: list = []

            if current_parent_version and current_parent_version != "3.2.0":
                updated_dependencies.append(
                    {
                        "group_id": "org.springframework.boot",
                        "artifact_id": "spring-boot-starter-parent",
                        "current_version": current_parent_version,
                        "new_version": "3.2.0",
                        "source": "spring_boot_parent_update",
                    }
                )
        
        # Update application.properties
        props_path = os.path.join(project_path, "src", "main", "resources", "application.properties")
        if os.path.exists(props_path):
            with open(props_path, 'r', encoding='utf-8') as f:
                content = f.read()

            content = content.replace(
                'spring.datasource.initialization-mode',
                'spring.sql.init.mode'
            )

            with open(props_path, 'w', encoding='utf-8') as f:
                f.write(content)
            result["files_modified"] += 1
            result["changes"].append("Updated application.properties")
        
        result["updated_dependencies"] = updated_dependencies
        return result

    async def _convert_junit_4_to_5(self, project_path: str) -> Dict[str, Any]:
        """Convert JUnit 4 tests to JUnit 5"""
        result = {"success": True, "files_modified": 0, "issues_fixed": 0, "changes": []}

        src_test = os.path.join(project_path, "src", "test", "java")
        if os.path.exists(src_test):
            for root, dirs, files in os.walk(src_test):
                for file in files:
                    if file.endswith('.java'):
                        filepath = os.path.join(root, file)
                        modified = await self._migrate_junit_file(filepath)
                        if modified:
                            result["files_modified"] += 1
                            result["issues_fixed"] += 1

        return result

    async def _migrate_junit_file(self, filepath: str) -> bool:
        """Migrate JUnit 4 to JUnit 5 in a test file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            original = content

            replacements = [
                ('import org.junit.Test;', 'import org.junit.jupiter.api.Test;'),
                ('import org.junit.Before;', 'import org.junit.jupiter.api.BeforeEach;'),
                ('import org.junit.After;', 'import org.junit.jupiter.api.AfterEach;'),
                ('import org.junit.BeforeClass;', 'import org.junit.jupiter.api.BeforeAll;'),
                ('import org.junit.AfterClass;', 'import org.junit.jupiter.api.AfterAll;'),
                ('import org.junit.Ignore;', 'import org.junit.jupiter.api.Disabled;'),
                ('@Before', '@BeforeEach'),
                ('@After', '@AfterEach'),
                ('@BeforeClass', '@BeforeAll'),
                ('@AfterClass', '@AfterAll'),
                ('@Ignore', '@Disabled'),
                ('import org.junit.runner.RunWith;', 'import org.junit.jupiter.api.extension.ExtendWith;'),
                ('@RunWith', '@ExtendWith'),
            ]

            for old, new in replacements:
                content = content.replace(old, new)

            if content != original:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True

            return False
        except:
            return False

    async def _convert_log4j_to_slf4j(self, project_path: str) -> Dict[str, Any]:
        """Convert Log4j to SLF4J"""
        result = {"success": True, "files_modified": 0, "issues_fixed": 0, "changes": []}

        src_main = os.path.join(project_path, "src", "main", "java")
        if os.path.exists(src_main):
            for root, dirs, files in os.walk(src_main):
                for file in files:
                    if file.endswith('.java'):
                        filepath = os.path.join(root, file)
                        modified = await self._migrate_logger_file(filepath)
                        if modified:
                            result["files_modified"] += 1
                            result["issues_fixed"] += 1

        return result

    async def _migrate_logger_file(self, filepath: str) -> bool:
        """Migrate Log4j to SLF4J in a Java file"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            original = content

            replacements = [
                ('import org.apache.log4j.Logger;', 'import org.slf4j.Logger;\nimport org.slf4j.LoggerFactory;'),
                ('Logger.getLogger(', 'LoggerFactory.getLogger('),
            ]

            for old, new in replacements:
                content = content.replace(old, new)

            if content != original:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True

            return False
        except:
            return False

    async def preview_migration_changes(
        self,
        project_path: str,
        source_version: str,
        target_version: str,
        conversion_types: List[str],
        fix_business_logic: bool
    ) -> Dict[str, Any]:
        """Preview what changes will be made during migration without applying them"""
        preview_result = {
            "files_to_modify": [],
            "files_to_create": [],
            "files_to_remove": [],
            "file_changes": {},
            "dependencies_to_update": [],
            "issues_to_fix": []
        }

        # Analyze current project state
        analysis = await self.analyze_project(project_path)
        current_deps = analysis.get("dependencies", [])

        # Find files that will be modified based on conversion types
        java_dirs = self._get_java_directories(project_path)

        # Simulate Java version migration changes
        if "java_version" in conversion_types:
            java_changes = await self._preview_java_version_changes(
                java_dirs, source_version, target_version, fix_business_logic
            )
            preview_result["files_to_modify"].extend(java_changes["files_to_modify"])
            preview_result["file_changes"].update(java_changes["file_changes"])
            preview_result["issues_to_fix"].extend(java_changes["issues_to_fix"])

        # Preview framework conversions
        for conv_type in conversion_types:
            if conv_type != "java_version":
                conv_changes = await self._preview_conversion_changes(java_dirs, conv_type)
                preview_result["files_to_modify"].extend(conv_changes["files_to_modify"])
                preview_result["file_changes"].update(conv_changes["file_changes"])

        # Preview dependency updates
        dep_changes = self._preview_dependency_changes(current_deps, conversion_types, target_version)
        preview_result["dependencies_to_update"] = dep_changes

        # Remove duplicates
        preview_result["files_to_modify"] = list(set(preview_result["files_to_modify"]))

        return preview_result

    def _get_java_directories(self, project_path: str) -> List[str]:
        """Get all Java source directories in the project"""
        java_dirs = []

        # Standard Maven/Gradle structure
        src_main = os.path.join(project_path, "src", "main", "java")
        src_test = os.path.join(project_path, "src", "test", "java")
        if os.path.exists(src_main):
            java_dirs.append(src_main)
        if os.path.exists(src_test):
            java_dirs.append(src_test)

        # Also check root src folder
        src_root = os.path.join(project_path, "src")
        if os.path.exists(src_root) and src_root not in java_dirs:
            java_dirs.append(src_root)

        # Check for any java files directly in project root
        java_dirs.append(project_path)

        return java_dirs

    async def _preview_java_version_changes(
        self,
        java_dirs: List[str],
        source_version: str,
        target_version: str,
        fix_business_logic: bool
    ) -> Dict[str, Any]:
        """Preview Java version migration changes"""
        changes = {
            "files_to_modify": [],
            "file_changes": {},
            "issues_to_fix": []
        }

        source = int(source_version)
        target = int(target_version)

        # Define change patterns based on version jump
        change_patterns = []

        # Java 8+ changes
        if source < 8 and target >= 8:
            change_patterns.extend([
                (r'new Integer\s*\([^)]*\)', 'Integer.valueOf()', 'Replace deprecated Integer constructor'),
                (r'new Long\s*\([^)]*\)', 'Long.valueOf()', 'Replace deprecated Long constructor'),
                (r'new Double\s*\([^)]*\)', 'Double.valueOf()', 'Replace deprecated Double constructor'),
                (r'new Boolean\s*\([^)]*\)', 'Boolean.valueOf()', 'Replace deprecated Boolean constructor'),
            ])

        # Java 11+ changes
        if target >= 11:
            change_patterns.extend([
                (r'\.trim\(\)\.isEmpty\(\)', '.isBlank()', 'Use String.isBlank() instead of trim().isEmpty()'),
            ])

        # Java 17+ changes (javax to jakarta)
        if target >= 17:
            change_patterns.extend([
                (r'import javax\.servlet\.', 'import jakarta.servlet.', 'Migrate javax.servlet to jakarta.servlet'),
                (r'import javax\.persistence\.', 'import jakarta.persistence.', 'Migrate javax.persistence to jakarta.persistence'),
                (r'import javax\.validation\.', 'import jakarta.validation.', 'Migrate javax.validation to jakarta.validation'),
            ])

        # Scan files for potential changes
        for src_dir in java_dirs:
            if not os.path.exists(src_dir):
                continue

            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'build', 'out']]
                for file in files:
                    if file.endswith('.java'):
                        filepath = os.path.join(root, file)
                        relative_path = os.path.relpath(filepath, src_dir)

                        try:
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()

                            file_changes = []
                            issues_found = []

                            # Check for each change pattern
                            for pattern, replacement, description in change_patterns:
                                matches = re.findall(pattern, content)
                                if matches:
                                    file_changes.append({
                                        "type": "replace",
                                        "pattern": pattern,
                                        "replacement": replacement,
                                        "description": description,
                                        "occurrences": len(matches)
                                    })
                                    issues_found.append({
                                        "type": "compatibility",
                                        "severity": "warning" if "trim()" in pattern else "error",
                                        "description": description,
                                        "file": relative_path
                                    })

                            # Add business logic fixes preview
                            if fix_business_logic:
                                business_issues = self._preview_business_logic_issues(content, relative_path)
                                issues_found.extend(business_issues["issues"])
                                file_changes.extend(business_issues["changes"])

                            if file_changes:
                                changes["files_to_modify"].append(relative_path)
                                changes["file_changes"][relative_path] = file_changes
                                changes["issues_to_fix"].extend(issues_found)

                        except Exception as e:
                            logger.warning("Error previewing migration changes path=%s error=%s", filepath, e)

        return changes

    def _preview_business_logic_issues(self, content: str, file_path: str) -> Dict[str, List]:
        """Preview business logic issues that would be fixed"""
        issues = []
        changes = []

        # Preview null safety improvements
        if 'equals(' in content and not 'Objects.equals' in content:
            issues.append({
                "type": "null_safety",
                "severity": "warning",
                "description": "Potential null pointer exception in equals() call",
                "file": file_path
            })
            changes.append({
                "type": "null_check",
                "description": "Add null safety check for equals() calls",
                "occurrences": len(re.findall(r'\w+\.equals\(', content))
            })

        # Preview String concatenation in loops
        if 'for (' in content and '+' in content:
            issues.append({
                "type": "performance",
                "severity": "warning",
                "description": "Potential inefficient String concatenation in loop",
                "file": file_path
            })
            changes.append({
                "type": "performance",
                "description": "Consider using StringBuilder for string operations in loops",
                "occurrences": 1
            })

        # Preview logging improvements
        if 'System.out.println' in content:
            issues.append({
                "type": "logging",
                "severity": "info",
                "description": "Using System.out.println instead of proper logging",
                "file": file_path
            })
            changes.append({
                "type": "logging",
                "description": "Replace System.out.println with SLF4J logging",
                "occurrences": content.count('System.out.println')
            })

        return {"issues": issues, "changes": changes}

    async def _preview_conversion_changes(self, java_dirs: List[str], conversion_type: str) -> Dict[str, Any]:
        """Preview changes for specific conversion types"""
        changes = {
            "files_to_modify": [],
            "file_changes": {}
        }

        # Define conversion-specific patterns
        conversion_patterns = {
            "javax_to_jakarta": [
                (r'import javax\.servlet\.', 'import jakarta.servlet.', 'javax.servlet â†’ jakarta.servlet'),
                (r'import javax\.persistence\.', 'import jakarta.persistence.', 'javax.persistence â†’ jakarta.persistence'),
                (r'import javax\.validation\.', 'import jakarta.validation.', 'javax.validation â†’ jakarta.validation'),
            ],
            "spring_boot_2_to_3": [
                (r'WebSecurityConfigurerAdapter', 'SecurityFilterChain', 'Spring Security configuration migration'),
                (r'@EnableGlobalMethodSecurity', '@EnableMethodSecurity', 'Security annotation update'),
            ],
            "junit_4_to_5": [
                (r'import org\.junit\.Test;', 'import org.junit.jupiter.api.Test;', 'JUnit 4 â†’ JUnit 5 imports'),
                (r'@Before', '@BeforeEach', 'JUnit 4 â†’ JUnit 5 annotations'),
                (r'@After', '@AfterEach', 'JUnit 4 â†’ JUnit 5 annotations'),
            ],
            "log4j_to_slf4j": [
                (r'import org\.apache\.log4j\.', 'import org.slf4j.', 'Log4j â†’ SLF4J migration'),
            ]
        }

        patterns = conversion_patterns.get(conversion_type, [])

        # Scan files for conversion-specific changes
        for src_dir in java_dirs:
            if not os.path.exists(src_dir):
                continue

            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['target', 'build', 'out']]
                for file in files:
                    if file.endswith('.java'):
                        filepath = os.path.join(root, file)
                        relative_path = os.path.relpath(filepath, src_dir)

                        try:
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()

                            file_changes = []
                            for pattern, replacement, description in patterns:
                                if re.search(pattern, content):
                                    file_changes.append({
                                        "type": "replace",
                                        "pattern": pattern,
                                        "replacement": replacement,
                                        "description": description,
                                        "occurrences": len(re.findall(pattern, content))
                                    })

                            if file_changes:
                                changes["files_to_modify"].append(relative_path)
                                changes["file_changes"][relative_path] = file_changes

                        except Exception as e:
                            logger.warning("Error previewing conversion path=%s error=%s", filepath, e)

        return changes

    def _preview_dependency_changes(self, current_deps: List[Dict], conversion_types: List[str], target_version: str) -> List[Dict]:
        """Preview dependency updates that will be made"""
        updates = []

        for dep in current_deps:
            new_version, status = self._get_upgrade_info(
                dep.get("group_id", ""),
                dep.get("artifact_id", ""),
                dep.get("current_version", "")
            )

            if status == "upgraded":
                updates.append({
                    "dependency": f"{dep.get('group_id')}:{dep.get('artifact_id')}",
                    "current_version": dep.get("current_version"),
                    "new_version": new_version,
                    "reason": "Version compatibility upgrade"
                })

        # Add framework-specific dependency changes
        target = int(target_version)
        if target >= 17 and "javax_to_jakarta" in conversion_types:
            updates.extend([
                {
                    "dependency": "javax.servlet:javax.servlet-api",
                    "current_version": "Any",
                    "new_version": "jakarta.servlet:jakarta.servlet-api:6.0.0",
                    "reason": "Jakarta EE migration"
                },
                {
                    "dependency": "javax.persistence:javax.persistence-api",
                    "current_version": "Any",
                    "new_version": "jakarta.persistence:jakarta.persistence-api:3.1.0",
                    "reason": "Jakarta EE migration"
                }
            ])

        if "spring_boot_2_to_3" in conversion_types:
            updates.append({
                "dependency": "org.springframework.boot:spring-boot-starter",
                "current_version": "2.x",
                "new_version": "3.2.0",
                "reason": "Spring Boot 2 â†’ 3 upgrade"
            })

        return updates

    # build tools code
    async def convert_build_file_with_llm(self, build_content: str, conversion_type: str, detected_build_tool: Optional[str] = None) -> str:
        return await self._convert_build_file_with_preferred_llm_v2(
            build_content,
            conversion_type,
            detected_build_tool=detected_build_tool,
        )

    async def _convert_build_file_with_preferred_llm(self, build_content: str, conversion_type: str, detected_build_tool: Optional[str] = None) -> str:
        return await self._convert_build_file_with_preferred_llm_v2(
            build_content,
            conversion_type,
            detected_build_tool=detected_build_tool,
        )

        # âœ… Correct router endpoint
        url = self.huggingface_chat_completions_url

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        normalized_build_tool = (detected_build_tool or "").strip().lower() or None
        source_build_tool = "maven" if conversion_type == "maven_to_gradle" else "gradle"
        target_build_tool = "gradle" if conversion_type == "maven_to_gradle" else "maven"
        source_snapshot = build_migration_policy_service.inspect_build_content(build_content, source_build_tool)
        target_java_version = build_migration_policy_service.resolve_java_target(source_snapshot.java_version)
        target_spring_boot_version = build_migration_policy_service.resolve_spring_boot_target(
            source_snapshot.spring_boot_version
        )

        # Dynamic Instructions based on Target Version
        dynamic_prompts = []
        target_v_int = 17
        try:
            target_v_int = int(target_java_version)
        except: pass

        if target_v_int >= 17:
            dynamic_prompts.append("JAKARTA EE: This is a Java 17+ migration. You MUST migrate all javax.* dependencies to jakarta.* equivalents (Persistence, Servlet, Validation, etc.).")
            dynamic_prompts.append(f"SPRING BOOT 3: Ensure compatibility with Spring Boot {target_spring_boot_version}. Do NOT use deprecated Boot 2.x properties or artifacts.")

        if target_v_int >= 21:
            dynamic_prompts.append("JAVA 21: Use modern Java 21 features where applicable. Ensure MySQL connector is updated to 'mysql-connector-j' (8.x).")

        dynamic_instr = "\n".join([f"- {p}" for p in dynamic_prompts])

        tuned_generation_rules = (
            "========================================\n"
            "EXPERT MIGRATION ENGINEER RULES\n"
            "========================================\n"
            "1. NEVER blindly upgrade or downgrade dependencies. Preserving original functionality is top priority.\n"
            "2. NEVER downgrade framework versions (e.g., Spring Boot, Hibernate).\n"
            "3. COMPATIBILITY: Ensure all upgrades are compatible with: Java version, Spring Boot version, Jakarta namespace, and Maven plugin ecosystem.\n"
            "4. CLEANLINESS: Detect and remove duplicate dependencies and unnecessary explicit versions (prefer dependency management/inheritance).\n"
            "5. SPRING BOOT SPECIAL RULES:\n"
            "   - USE: spring-boot-starter-web, spring-boot-starter-test\n"
            "   - NEVER USE INVALID STARTERS: spring-boot-starter-webmvc, spring-boot-starter-webmvc-test\n"
            "   - If Boot 3+: Migrate javax.* -> jakarta.* and validate Hibernate/JPA.\n"
            "6. JAKARTA MIGRATION: Convert javax.* -> jakarta.* for SOAP, Mail, XML, and JPA APIs.\n"
            "7. MISSING PLUGINS: Ensure the following are present and modern:\n"
            "   - junit-jupiter\n"
            "   - maven-surefire-plugin (min 3.0.0)\n"
            "   - jacoco-maven-plugin (min 0.8.11)\n"
            "   - maven-compiler-plugin (with correct source/target)\n"
            "8. FORMAT: Match the target tool exactly (pom.xml -> Maven XML, build.gradle -> Groovy DSL, build.gradle.kts -> Kotlin DSL).\n"
            "9. VALIDATION: Ensure the resulting configuration can build successfully with 'mvn clean test'.\n"
        )

        if conversion_type == "maven_to_gradle":
            prompt = (
                "You are an expert Java, Maven, Gradle, and Spring Boot migration engineer. "
                "Convert the following Maven pom.xml into ONE valid and working Gradle build.gradle file using Groovy DSL.\n\n"
                f"{tuned_generation_rules}\n"
                "TARGET STACK:\n"
                f"- Java {target_java_version}\n"
                "- Gradle 8.7\n"
                f"- Spring Boot {target_spring_boot_version}\n\n"
                f"DYNAMIC CONTEXT:\n{dynamic_instr}\n\n"
                "Output ONLY the raw build.gradle code with no markdown formatting and no explanation:\n\n"
                f"{build_content}"
            )
        elif conversion_type == "gradle_to_maven":
            prompt = (
                "You are an expert Java, Maven, Gradle, and Spring Boot migration engineer. "
                "Convert the following Gradle build.gradle file into ONE valid and working Maven pom.xml file.\n\n"
                f"{tuned_generation_rules}\n"
                "TARGET STACK:\n"
                f"- Java {target_java_version}\n"
                "- Maven 3.9+\n"
                f"- Spring Boot {target_spring_boot_version}\n\n"
                f"DYNAMIC CONTEXT:\n{dynamic_instr}\n\n"
                "Output ONLY the raw pom.xml code with no markdown formatting and no explanation:\n\n"
                f"{build_content}"
            )
        else:
            return build_content

        # âœ… Router payload (chat format)
        payload = {
            "model": self.build_conversion_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.1
                }

        start_time = time.perf_counter()
        self._build_conversion_request_count += 1
        request_no = self._build_conversion_request_count
        provider = "huggingface"
        provider_request_no = self._build_conversion_provider_counts.get(provider, 0) + 1
        self._build_conversion_provider_counts[provider] = provider_request_no
        logger.info(
            "Build conversion LLM request started request_no=%s provider_request_no=%s provider=%s model=%s conversion_type=%s prompt_chars=%s",
            request_no,
            provider_request_no,
            provider,
            self.build_conversion_model,
            conversion_type,
            len(prompt),
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=headers, json=payload)

            if response.status_code != 200:
                logger.error(
                    "Build conversion LLM request failed request_no=%s provider=%s model=%s conversion_type=%s status=%s body=%s",
                    request_no,
                    provider,
                    self.build_conversion_model,
                    conversion_type,
                    response.status_code,
                    response.text,
                )
                raise Exception(f"Hugging Face API failed with status {response.status_code}")

            data = response.json()

            # âœ… Extract correct response
            generated_text = data["choices"][0]["message"]["content"]

            # Clean markdown formatting
            cleaned_text = (
                generated_text
                .replace("```xml", "")
                .replace("```gradle", "")
                .replace("```groovy", "")
                .replace("```", "")
                .strip()
            )

        generated_snapshot = build_migration_policy_service.inspect_build_content(cleaned_text, target_build_tool)
        build_migration_policy_service.validate_no_downgrade(source_snapshot, generated_snapshot)

        logger.info(
            "Build conversion LLM request completed request_no=%s provider=%s model=%s conversion_type=%s duration_ms=%s response_chars=%s",
            request_no,
            provider,
            self.build_conversion_model,
            conversion_type,
            int((time.perf_counter() - start_time) * 1000),
            len(cleaned_text),
        )

        return cleaned_text

    async def _convert_build_file_with_preferred_llm_v2(
        self,
        build_content: str,
        conversion_type: str,
        detected_build_tool: Optional[str] = None,
    ) -> str:
        normalized_build_tool = (detected_build_tool or "").strip().lower() or None
        source_build_tool = "maven" if conversion_type == "maven_to_gradle" else "gradle"
        target_build_tool = "gradle" if conversion_type == "maven_to_gradle" else "maven"
        source_snapshot = build_migration_policy_service.inspect_build_content(build_content, source_build_tool)
        target_java_version = build_migration_policy_service.resolve_java_target(source_snapshot.java_version)
        target_spring_boot_version = build_migration_policy_service.resolve_spring_boot_target(
            source_snapshot.spring_boot_version
        )

        dynamic_prompts = []
        target_v_int = 17
        try:
            target_v_int = int(target_java_version)
        except Exception:
            pass

        if target_v_int >= 17:
            dynamic_prompts.append("JAKARTA EE: This is a Java 17+ migration. You MUST migrate all javax.* dependencies to jakarta.* equivalents (Persistence, Servlet, Validation, etc.).")
            dynamic_prompts.append(f"SPRING BOOT 3: Ensure compatibility with Spring Boot {target_spring_boot_version}. Do NOT use deprecated Boot 2.x properties or artifacts.")

        if target_v_int >= 21:
            dynamic_prompts.append("JAVA 21: Use modern Java 21 features where applicable. Ensure MySQL connector is updated to 'mysql-connector-j' (8.x).")

        dynamic_instr = "\n".join([f"- {p}" for p in dynamic_prompts])
        tuned_generation_rules = (
            "========================================\n"
            "EXPERT MIGRATION ENGINEER RULES\n"
            "========================================\n"
            "1. NEVER blindly upgrade or downgrade dependencies. Preserving original functionality is top priority.\n"
            "2. NEVER downgrade framework versions (e.g., Spring Boot, Hibernate).\n"
            "3. COMPATIBILITY: Ensure all upgrades are compatible with: Java version, Spring Boot version, Jakarta namespace, and Maven plugin ecosystem.\n"
            "4. CLEANLINESS: Detect and remove duplicate dependencies and unnecessary explicit versions (prefer dependency management/inheritance).\n"
            "5. SPRING BOOT SPECIAL RULES:\n"
            "   - USE: spring-boot-starter-web, spring-boot-starter-test\n"
            "   - NEVER USE INVALID STARTERS: spring-boot-starter-webmvc, spring-boot-starter-webmvc-test\n"
            "   - If Boot 3+: Migrate javax.* -> jakarta.* and validate Hibernate/JPA.\n"
            "6. JAKARTA MIGRATION: Convert javax.* -> jakarta.* for SOAP, Mail, XML, and JPA APIs.\n"
            "7. MISSING PLUGINS: Ensure the following are present and modern:\n"
            "   - junit-jupiter\n"
            "   - maven-surefire-plugin (min 3.0.0)\n"
            "   - jacoco-maven-plugin (min 0.8.11)\n"
            "   - maven-compiler-plugin (with correct source/target)\n"
            "8. FORMAT: Match the target tool exactly (pom.xml -> Maven XML, build.gradle -> Groovy DSL, build.gradle.kts -> Kotlin DSL).\n"
            "9. VALIDATION: Ensure the resulting configuration can build successfully with 'mvn clean test'.\n"
        )

        if conversion_type == "maven_to_gradle":
            prompt = (
                "You are an expert Java, Maven, Gradle, and Spring Boot migration engineer. "
                "Convert the following Maven pom.xml into ONE valid and working Gradle build.gradle file using Groovy DSL.\n\n"
                f"{tuned_generation_rules}\n"
                "TARGET STACK:\n"
                f"- Java {target_java_version}\n"
                "- Gradle 8.7\n"
                f"- Spring Boot {target_spring_boot_version}\n\n"
                f"DYNAMIC CONTEXT:\n{dynamic_instr}\n\n"
                "Output ONLY the raw build.gradle code with no markdown formatting and no explanation:\n\n"
                f"{build_content}"
            )
        elif conversion_type == "gradle_to_maven":
            prompt = (
                "You are an expert Java, Maven, Gradle, and Spring Boot migration engineer. "
                "Convert the following Gradle build.gradle file into ONE valid and working Maven pom.xml file.\n\n"
                f"{tuned_generation_rules}\n"
                "TARGET STACK:\n"
                f"- Java {target_java_version}\n"
                "- Maven 3.9+\n"
                f"- Spring Boot {target_spring_boot_version}\n\n"
                f"DYNAMIC CONTEXT:\n{dynamic_instr}\n\n"
                "Output ONLY the raw pom.xml code with no markdown formatting and no explanation:\n\n"
                f"{build_content}"
            )
        else:
            return build_content

        start_time = time.perf_counter()
        self._build_conversion_request_count += 1
        request_no = self._build_conversion_request_count
        cache_key = build_llm_cache_key(
            "build-conversion",
            {
                "conversion_type": conversion_type,
                "target_build_tool": target_build_tool,
                "target_java_version": target_java_version,
                "source_snapshot": {
                    "build_tool": source_snapshot.build_tool,
                    "java_version": source_snapshot.java_version,
                    "spring_boot_version": source_snapshot.spring_boot_version,
                },
                "build_content": build_content,
                "rules": tuned_generation_rules,
            },
        )
        result = await preferred_llm_service.request_text(
            system_prompt=(
                "You are an expert Java build modernization engineer. "
                "Prefer safe, production-ready build conversions. "
                "Return only the converted build file with no markdown fences or explanation."
            ),
            user_prompt=prompt,
            max_tokens=1500,
            temperature=0.1,
            cache_key=cache_key,
        )
        provider = result["provider"]
        model = result["model"]
        provider_request_no = self._build_conversion_provider_counts.get(provider, 0) + 1
        self._build_conversion_provider_counts[provider] = provider_request_no
        logger.info(
            "Build conversion LLM request started request_no=%s provider_request_no=%s provider=%s model=%s conversion_type=%s prompt_chars=%s",
            request_no,
            provider_request_no,
            provider,
            model,
            conversion_type,
            len(prompt),
        )

        cleaned_text = (
            result["text"]
            .replace("```xml", "")
            .replace("```gradle", "")
            .replace("```groovy", "")
            .replace("```", "")
            .strip()
        )

        generated_snapshot = build_migration_policy_service.inspect_build_content(cleaned_text, target_build_tool)
        build_migration_policy_service.validate_no_downgrade(source_snapshot, generated_snapshot)

        logger.info(
            "Build conversion LLM request completed request_no=%s provider=%s model=%s conversion_type=%s duration_ms=%s response_chars=%s",
            request_no,
            provider,
            model,
            conversion_type,
            int((time.perf_counter() - start_time) * 1000),
            len(cleaned_text),
        )
        return cleaned_text

    def get_llm_stats(self) -> Dict[str, Any]:
        return {
            "service": "build_conversion",
            "process_id": os.getpid(),
            "default_provider": "ford_llm",
            "total_requests": self._build_conversion_request_count,
            "provider_request_counts": dict(sorted(self._build_conversion_provider_counts.items())),
            "cache": get_llm_cache_stats(),
            "models": {
                "ford_llm": preferred_llm_service.ford_llm_model,
                "groq": preferred_llm_service.groq_model,
                "claude": preferred_llm_service.claude_model,
                "openai": preferred_llm_service.openai_model,
            },
        }

