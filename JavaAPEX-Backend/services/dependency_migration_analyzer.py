"""
Dependency Migration Analyzer - Expert enterprise implementation for validating migration accuracy and ecosystem compatibility.
"""
from __future__ import annotations

import re
import logging
import asyncio
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class DependencyNode:
    group_id: str
    artifact_id: str
    version: Optional[str] = None
    scope: Optional[str] = None
    origin: str = "direct"  # direct, inherited, transitive, plugin, buildscript
    module_path: str = ":"
    is_dynamic: bool = False
    variable_ref: Optional[str] = None
    is_plugin: bool = False
    raw_text: str = ""

    @property
    def coordinate(self) -> str:
        return f"{self.group_id}:{self.artifact_id}"

@dataclass
class ValidationReport:
    status: str = "SUCCESS"
    accuracyScore: float = 100.0
    riskLevel: str = "LOW"
    stabilityPercentage: float = 100.0
    upgradePercentage: float = 100.0

    # Sections requested for Enterprise Analysis
    exactIssuesFound: List[str] = field(default_factory=list)
    compatibilityReport: List[Dict[str, Any]] = field(default_factory=list)
    pluginSupportReport: List[Dict[str, Any]] = field(default_factory=list)
    dependencyAlignmentReport: List[Dict[str, Any]] = field(default_factory=list)
    correctedRecommendedConfiguration: Dict[str, str] = field(default_factory=dict)
    safeEnterpriseRecommendation: List[str] = field(default_factory=list)

    # Visualization & Summary
    dependencyUpgradeSummary: List[Dict[str, str]] = field(default_factory=list)
    incorrectMigrationDetection: List[Dict[str, str]] = field(default_factory=list)
    recommendedFixes: List[str] = field(default_factory=list)
    buildTestValidation: List[Dict[str, str]] = field(default_factory=list)

    # Internal trackers
    correctUpgrades: List[Dict[str, str]] = field(default_factory=list)
    incorrectReplacements: List[Dict[str, str]] = field(default_factory=list)
    missingDependencies: List[Dict[str, str]] = field(default_factory=list)
    duplicateDependencies: List[Dict[str, str]] = field(default_factory=list)
    legacyFrameworks: List[Dict[str, str]] = field(default_factory=list)
    syntaxIssues: List[Dict[str, str]] = field(default_factory=list)
    unnecessaryExplicitVersions: List[Dict[str, str]] = field(default_factory=list)

    # Categories for graph visualization
    directDependencies: List[Dict[str, Any]] = field(default_factory=list)
    pluginDependencies: List[Dict[str, Any]] = field(default_factory=list)
    internalProjectDependencies: List[Dict[str, Any]] = field(default_factory=list)
    transitiveDependencies: List[Dict[str, Any]] = field(default_factory=list)

class DependencyMigrationAnalyzer:
    def __init__(self):
        self.testing_keywords = {"junit", "mockito", "test", "jacoco", "assertj", "hamcrest", "testng", "robolectric"}
        self.enterprise_lts_versions = {"11", "17", "21"}
        self.experimental_versions = {"22", "23", "24"}

        self.legacy_keywords = {
            "jsp": "javax.servlet.jsp",
            "angularjs": "angularjs",
            "jquery": "jquery",
            "servlet-api": "javax.servlet-api",
            "soap": "javax.xml.soap",
            "struts": "org.apache.struts",
            "hibernate-legacy": "org.hibernate:hibernate-core:3.",
            "ejb": "javax.ejb"
        }

        self.invalid_artifacts = {
            "spring-boot-starter-webmvc": "spring-boot-starter-web",
            "spring-boot-starter-webmvc-test": "spring-boot-starter-test",
            "log4j": "org.slf4j:slf4j-api",
            "javax.persistence-api": "jakarta.persistence-api",
            "javax.servlet-api": "jakarta.servlet-api",
            "javax.validation-api": "jakarta.validation-api",
            "javax.annotation-api": "jakarta.annotation-api",
            "javax.transaction-api": "jakarta.transaction-api",
            "javax.xml.bind-api": "jakarta.xml.bind-api",
            "javax.activation-api": "jakarta.activation-api",
            "javax.mail-api": "jakarta.mail-api",
            "javax.inject": "jakarta.inject-api",
            "mysql-connector-java": "mysql-connector-j",
            "h2": "com.h2database:h2",
            "poi": "org.apache.poi:poi"
        }

        self.java_compat_matrix = {
            "17": {
                "min_spring_boot": "3.0.0",
                "min_jacoco": "0.8.7",
                "min_mockito": "4.0.0",
                "min_gradle": "7.3",
                "min_surefire": "3.0.0-M5",
                "spotbugs_support": "4.5.0",
                "pmd_support": "6.40.0"
            },
            "21": {
                "min_spring_boot": "3.2.0",
                "min_jacoco": "0.8.11",
                "min_mockito": "5.0.0",
                "min_gradle": "8.5",
                "min_surefire": "3.2.0",
                "spotbugs_support": "4.8.0",
                "pmd_support": "7.0.0"
            }
        }

        self.production_stable_versions = {
            "spring_boot": "3.2.5",
            "java": "17",
            "mysql": "8.3.0",
            "lombok": "1.18.42",
            "jacoco": "0.8.11",
            "surefire": "3.2.5",
            "spotbugs": "4.8.5",
            "checkstyle": "10.15.0"
        }

    async def analyze_migration(self, project_path: str) -> Dict[str, Any]:
        """Initial baseline analysis."""
        report = ValidationReport()
        runtime = await self._resolve_runtime_state(project_path)
        static = self._parse_static_state(project_path)

        all_nodes = { (n.coordinate, n.module_path): n for n in (runtime + static) }.values()
        for n in all_nodes:
            d = asdict(n)
            if n.origin in ["runtime", "transitive"]: report.transitiveDependencies.append(d)
            elif n.origin == "plugin": report.pluginDependencies.append(d)
            elif n.origin == "internal": report.internalProjectDependencies.append(d)
            else: report.directDependencies.append(d)

        return asdict(report)

    async def validate_migration(self, baseline_report: Optional[Dict[str, Any]], migrated_path: str) -> Dict[str, Any]:
        """Full expert enterprise validation."""
        report = ValidationReport()
        target_java = self._detect_target_java(migrated_path)

        # 1. Resolve Migrated State
        mig_runtime = await self._resolve_runtime_state(migrated_path)
        mig_static = self._parse_static_state(migrated_path)

        # 2. Extract Baseline
        orig_nodes = []
        if baseline_report:
            for cat in ["directDependencies", "pluginDependencies", "internalProjectDependencies", "transitiveDependencies"]:
                for dep in baseline_report.get(cat, []):
                    orig_nodes.append(DependencyNode(
                        group_id=dep.get("group_id", ""),
                        artifact_id=dep.get("artifact_id", ""),
                        version=dep.get("version"),
                        scope=dep.get("scope"),
                        module_path=dep.get("module_path", ":"),
                        origin=dep.get("origin", "direct")
                    ))

        # 3. Validation Logic
        self._validate_java_version(target_java, report)
        self._detect_changes(orig_nodes, mig_runtime, mig_static, report)
        self._validate_java_spring_stack(migrated_path, mig_static, report)
        self._validate_static_analysis_tools(mig_static, target_java, report)
        self._validate_test_infrastructure(migrated_path, mig_static, report)
        self._check_legacy_and_syntax(migrated_path, mig_static, report)

        # 4. Final Scoring & Formatting
        self._finalize_expert_report(report, target_java=target_java)
        return asdict(report)

    def _validate_java_version(self, version: str, report: ValidationReport):
        """Rule: Prefer LTS, Flag Experimental."""
        if version in self.experimental_versions:
            report.exactIssuesFound.append(f"Experimental/Non-LTS Java version detected: Java {version}")
            report.compatibilityReport.append({
                "check": "Enterprise Java Policy",
                "issue": f"Java {version} is not an enterprise LTS version. Potential lack of ecosystem support for core plugins.",
                "severity": "MEDIUM"
            })
            report.recommendedFixes.append(f"Switch to a stable LTS version (Java 17 or 21) for production workloads.")
        elif version not in self.enterprise_lts_versions and int(version) < 17:
             report.exactIssuesFound.append(f"Legacy Java version: Java {version}")
             report.safeEnterpriseRecommendation.append("Modernize to at least Java 17 LTS to ensure security patches and library compatibility.")

    def _validate_static_analysis_tools(self, static: List[DependencyNode], java_ver: str, report: ValidationReport):
        """Rule: Validate SpotBugs, PMD, Checkstyle support for Java version."""
        tools = {
            "spotbugs": ("com.github.spotbugs", "spotbugs-maven-plugin"),
            "pmd": ("org.apache.maven.plugins", "maven-pmd-plugin"),
            "checkstyle": ("org.apache.maven.plugins", "maven-checkstyle-plugin")
        }

        for tool_key, (gid, aid) in tools.items():
            plugin = next((n for n in static if n.artifact_id == aid or n.artifact_id == f"{tool_key}-maven-plugin"), None)
            if plugin and plugin.version and java_ver in self.java_compat_matrix:
                matrix = self.java_compat_matrix[java_ver]
                min_ver = matrix.get(f"{tool_key}_support")
                if min_ver and not self._is_version_upgrade(min_ver, plugin.version):
                    report.exactIssuesFound.append(f"{tool_key.title()} version {plugin.version} may not fully support Java {java_ver}")
                    report.pluginSupportReport.append({
                        "plugin": aid,
                        "current": plugin.version,
                        "required": min_ver,
                        "status": "INCOMPATIBLE"
                    })
                    report.recommendedFixes.append(f"Upgrade {aid} to at least {min_ver} for Java {java_ver} support.")

    def _detect_changes(self, orig_nodes: List[DependencyNode], mig_run: List[DependencyNode], mig_static: List[DependencyNode], report: ValidationReport):
        orig_map = { (n.coordinate, n.module_path): n for n in orig_nodes }
        mig_all = mig_run + mig_static
        mig_map = {}

        # Detect duplicates and build mig_map
        for n in mig_all:
            key = (n.coordinate, n.module_path)
            if key in mig_map:
                report.duplicateDependencies.append({"dependency": n.coordinate, "module": n.module_path})
                report.exactIssuesFound.append(f"Duplicate dependency detected: {n.coordinate} in {n.module_path}")
            mig_map[key] = n

        # Check for downgrades, removals, incorrect replacements
        for key, orig in orig_map.items():
            coord, mod = key
            if key in mig_map:
                mig = mig_map[key]
                if mig.version and orig.version and mig.version != orig.version:
                    if self._is_version_upgrade(orig.version, mig.version):
                        report.correctUpgrades.append({"dependency": coord, "old": orig.version, "new": mig.version})
                        report.dependencyAlignmentReport.append({"dependency": coord, "status": "ALIGNED", "change": f"UPGRADE ({orig.version} -> {mig.version})"})
                    else:
                        issue = f"Dependency downgraded: {coord} ({orig.version} -> {mig.version})"
                        report.exactIssuesFound.append(f"CRITICAL: {issue}")
                        report.incorrectReplacements.append({"dependency": coord, "expected": orig.version, "actual": mig.version, "reason": "Downgrade"})
                        report.dependencyAlignmentReport.append({"dependency": coord, "status": "MISALIGNED", "issue": "DOWNGRADE"})
                else:
                    report.dependencyAlignmentReport.append({"dependency": coord, "status": "ALIGNED", "change": "UNCHANGED"})

                # Check for unnecessary explicit versions (if version matches baseline but is explicitly set)
                if "spring-boot-starter" in coord and mig.version and not orig.version:
                    report.unnecessaryExplicitVersions.append({"dependency": coord, "version": mig.version})
                    report.recommendedFixes.append(f"Remove explicit version for {coord} to let Spring Boot BOM manage it.")

            else:
                # Check for Jakarta replacement
                was_replaced = False
                for invalid, valid in self.invalid_artifacts.items():
                    if invalid in coord and any(valid in m.coordinate for m in mig_all):
                        was_replaced = True
                        report.dependencyAlignmentReport.append({"dependency": coord, "status": "ALIGNED", "change": f"MIGRATED to {valid}"})
                        break

                if not was_replaced:
                    is_test = any(kw in coord.lower() for kw in self.testing_keywords)
                    if is_test:
                        report.exactIssuesFound.append(f"CRITICAL: Test dependency removed: {coord}")
                        report.riskLevel = "HIGH"
                    report.missingDependencies.append({"dependency": coord, "type": "Test" if is_test else "Runtime"})
                    report.dependencyAlignmentReport.append({"dependency": coord, "status": "MISALIGNED", "issue": "MISSING"})

    def _validate_java_spring_stack(self, path: str, static: List[DependencyNode], report: ValidationReport):
        target_java = self._detect_target_java(path)
        boot_node = next((n for n in static if "spring-boot" in n.artifact_id), None)

        if boot_node and boot_node.version and target_java in self.java_compat_matrix:
            matrix = self.java_compat_matrix[target_java]
            if not self._is_version_upgrade(matrix["min_spring_boot"], boot_node.version):
                report.exactIssuesFound.append(f"Incompatible Spring Boot version: {boot_node.version} on Java {target_java}")
                report.compatibilityReport.append({
                    "component": "Spring Boot",
                    "status": "INCOMPATIBLE",
                    "reason": f"Java {target_java} requires Spring Boot {matrix['min_spring_boot']} or higher."
                })
                report.recommendedFixes.append(f"Upgrade Spring Boot to {self.production_stable_versions['spring_boot']}")

        # Validate invalid starters
        for n in static:
            if n.artifact_id in ["spring-boot-starter-webmvc", "spring-boot-starter-webmvc-test"]:
                report.exactIssuesFound.append(f"Invalid Spring starter detected: {n.artifact_id}")
                correct = self.invalid_artifacts.get(n.artifact_id)
                report.incorrectMigrationDetection.append({"issue": f"Non-standard starter {n.artifact_id}", "replacement": correct})
                report.recommendedFixes.append(f"Replace {n.artifact_id} with {correct}")

    def _validate_test_infrastructure(self, path: str, static: List[DependencyNode], report: ValidationReport):
        """Rule: Ensure modern testing stack (JUnit 5, Mockito, JaCoCo, Surefire, Compiler)."""
        infra_checks = {
            "JaCoCo": any("jacoco" in n.coordinate.lower() for n in static) or any("jacoco" in n.artifact_id.lower() for n in static),
            "JUnit 5": any("junit-jupiter" in n.coordinate.lower() or "junit-vintage" in n.coordinate.lower() for n in static),
            "Mockito": any("mockito" in n.coordinate.lower() for n in static),
            "Surefire": any("maven-surefire-plugin" in n.artifact_id for n in static),
            "Compiler": any("maven-compiler-plugin" in n.artifact_id for n in static)
        }
        for name, present in infra_checks.items():
            if not present:
                report.exactIssuesFound.append(f"Missing {name} integration (Required for build/test integrity)")
                report.buildTestValidation.append({"infrastructure": name, "status": "MISSING"})
                report.recommendedFixes.append(f"Add and configure {name} to ensure successful migration validation.")
            else:
                report.buildTestValidation.append({"infrastructure": name, "status": "Present"})

        # Check for JUnit 4 remnants
        if any("junit:junit" in n.coordinate for n in static) and any("junit-jupiter" in n.coordinate for n in static):
            report.duplicateDependencies.append({"dependency": "junit:junit", "issue": "Legacy JUnit 4 alongside JUnit 5"})
            report.recommendedFixes.append("Remove legacy junit:junit dependency and consolidate to junit-jupiter.")

    def _finalize_expert_report(self, report: ValidationReport, target_java: str = "17"):
        # Calculate scores
        # Base score 100
        # -15 per CRITICAL issue, -10 per HIGH, -5 per MEDIUM
        criticals = sum(1 for issue in report.exactIssuesFound if "CRITICAL" in issue)
        mediums = len(report.pluginSupportReport) + len(report.incorrectReplacements)

        # Calculate Accuracy Score based on penalties
        score = 100.0 - (criticals * 15 + mediums * 5 + len(report.syntaxIssues) * 10 + len(report.duplicateDependencies) * 5)
        report.accuracyScore = max(0.0, score)

        # Calculate Stability Percentage (higher penalty for missing dependencies)
        report.stabilityPercentage = max(0.0, score - (len(report.missingDependencies) * 5))

        # Calculate Upgrade Percentage: (Correct Upgrades / Total Upgrades Attempted)
        total_upgrades = len(report.correctUpgrades) + len(report.incorrectReplacements)
        report.upgradePercentage = (len(report.correctUpgrades) / total_upgrades * 100.0) if total_upgrades > 0 else 100.0

        if report.accuracyScore < 60 or criticals > 0:
            report.riskLevel = "CRITICAL"
            report.status = "FAILED"
        elif report.accuracyScore < 80:
            report.riskLevel = "HIGH"
            report.status = "WARNING"
        elif report.accuracyScore < 95:
            report.riskLevel = "MEDIUM"
        else:
            report.riskLevel = "LOW"

        report.safeEnterpriseRecommendation.append(f"Ensure target stack is Java 17/21 LTS with Spring Boot 3.2.x.")
        if criticals:
            report.safeEnterpriseRecommendation.append("DO NOT DEPLOY: Critical build integrity risks detected.")

    # --- Utility Helpers ---
    def _is_version_upgrade(self, old: str, new: str) -> bool:
        def parse(v): return [int(i) for i in re.findall(r"\d+", v)]
        try: return parse(new) >= parse(old)
        except: return False

    def _detect_target_java(self, path: str) -> str:
        for p in Path(path).rglob("build.gradle*"):
            m = re.search(r"Compatibility\s*=?\s*['\"]?(\d+)['\"]?", p.read_text(errors="ignore"))
            if m: return m.group(1)
        return "17"

    async def _resolve_runtime_state(self, path: str) -> List[DependencyNode]:
        nodes = []
        gradlew = os.path.join(path, "gradlew.bat" if os.name == "nt" else "gradlew")
        if os.path.exists(gradlew):
            for task in ["dependencies", "buildEnvironment"]:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        gradlew, task, "--console=plain", cwd=path,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate()
                    nodes.extend(self._parse_gradle_tree(stdout.decode(errors="ignore"), "runtime" if task == "dependencies" else "plugin"))
                except Exception: pass
        return nodes

    def _parse_static_state(self, path: str) -> List[DependencyNode]:
        nodes = []
        root = Path(path)
        props = self._load_props(path)
        seen_paths: Set[str] = set()

        def add_file(candidate: Path) -> None:
            try:
                resolved = str(candidate.resolve())
            except Exception:
                resolved = str(candidate)
            if resolved in seen_paths or not candidate.is_file():
                return
            seen_paths.add(resolved)
            if candidate.name in ["build.gradle", "build.gradle.kts"]:
                nodes.extend(self._parse_gradle_file(candidate, props))
            elif candidate.name == "pom.xml":
                nodes.extend(self._parse_maven_file(candidate))
            elif candidate.name == "libs.versions.toml":
                nodes.extend(self._parse_toml_catalog(candidate))

        for pattern in ("pom.xml", "build.gradle", "build.gradle.kts", "libs.versions.toml"):
            for candidate in root.rglob(pattern):
                add_file(candidate)
        return nodes

    def _parse_gradle_tree(self, output: str, origin: str) -> List[DependencyNode]:
        nodes = []
        pattern = re.compile(r"[\s\|\+\-\\]+([a-zA-Z0-9\._\-]+):([a-zA-Z0-9\._\-]+):([a-zA-Z0-9\._\-]+)(?:\s+->\s+([a-zA-Z0-9\._\-]+))?")
        for line in output.splitlines():
            m = pattern.search(line)
            if m:
                g, a, v, uv = m.groups()
                nodes.append(DependencyNode(group_id=g, artifact_id=a, version=uv or v, origin=origin))
        return nodes

    def _parse_gradle_file(self, file: Path, props: dict) -> List[DependencyNode]:
        nodes = []
        content = file.read_text(errors="ignore")
        pat_string = re.compile(r"(\w+)\s*\(?['\"]([^:'\"\s]+):([^:'\"\s]+)(?::([^'\"\n\r)]+))?['\"]")
        for s, g, a, v in pat_string.findall(content):
            version = props.get(v.strip("$"), v) if v else None
            nodes.append(DependencyNode(group_id=g, artifact_id=a, version=version, scope=s, module_path=str(file.parent.name)))

        pat_plugin = re.compile(r"id\s+['\"]([^'\"]+)['\"](?:\s+version\s+['\"]([^'\"]+)['\"])?")
        for pid, pver in pat_plugin.findall(content):
            nodes.append(DependencyNode(group_id="plugin", artifact_id=pid, version=pver, origin="plugin", is_plugin=True, module_path=str(file.parent.name)))
        return nodes

    def _parse_maven_file(self, file: Path) -> List[DependencyNode]:
        nodes = []
        content = file.read_text(errors="ignore")
        deps = re.findall(r"<dependency>(.*?)</dependency>", content, re.DOTALL)
        for d in deps:
            g = re.search(r"<groupId>(.*?)</groupId>", d)
            a = re.search(r"<artifactId>(.*?)</artifactId>", d)
            v = re.search(r"<version>(.*?)</version>", d)
            if g and a: nodes.append(DependencyNode(group_id=g.group(1), artifact_id=a.group(1), version=v.group(1) if v else None, module_path=str(file.parent.name)))
        return nodes

    def _parse_toml_catalog(self, file: Path) -> List[DependencyNode]:
        nodes = []
        try:
            content = file.read_text(errors="ignore")
            lib_section = re.search(r"\[libraries\](.*?)(?:\[|$)", content, re.DOTALL)
            if lib_section:
                for line in lib_section.group(1).splitlines():
                    if "=" in line:
                        g = re.search(r'group\s*=\s*["\']([^"\']+)["\']', line)
                        a = re.search(r'name\s*=\s*["\']([^"\']+)["\']', line)
                        v = re.search(r'version(?:\.ref)?\s*=\s*["\']([^"\']+)["\']', line)
                        if g and a:
                            nodes.append(DependencyNode(group_id=g.group(1), artifact_id=a.group(1), version=v.group(1) if v else None, origin="catalog"))
        except: pass
        return nodes

    def _load_props(self, path: str) -> dict:
        p = {}
        pf = os.path.join(path, "gradle.properties")
        if os.path.exists(pf):
            with open(pf, "r") as f:
                for l in f:
                    if "=" in l:
                        k, v = l.split("=", 1)
                        p[k.strip()] = v.strip()
        return p

    def _check_legacy_and_syntax(self, path: str, static: List[DependencyNode], report: ValidationReport):
        for n in static:
            for framework, artifact in self.legacy_keywords.items():
                if artifact in n.coordinate:
                    report.legacyFrameworks.append({"framework": framework, "artifact": n.coordinate})
        for p in Path(path).rglob("build.gradle*"):
            if "TODO" in p.read_text(errors="ignore"):
                report.syntaxIssues.append({"file": str(p.name), "issue": "Unresolved placeholder"})
