from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Set

from models.microservice_readiness import (
    AnalysisDiagnostics,
    DetailedEligibilityReport,
    MicroserviceReadinessReport,
    MicroserviceScoreBreakdown,
    ServiceCandidate,
)
from services.repository_workspace_service import RepositoryWorkspace
from utils.java_analysis_utils import (
    common_package_prefix,
    infer_module_from_package,
    infer_module_from_path,
    parse_class_names_and_annotations,
    parse_imports,
    parse_package,
    sanitize_module_name,
    strip_java_comments,
    titleize_module_name,
    top_n_items,
)

logger = logging.getLogger(__name__)


STEREOTYPE_CONTROLLER = {"RestController", "Controller"}
STEREOTYPE_SERVICE = {"Service"}
STEREOTYPE_REPOSITORY = {"Repository"}
STEREOTYPE_ENTITY = {"Entity", "Embeddable", "MappedSuperclass", "Document"}
SPRING_BOOT_ANNOTATIONS = {"SpringBootApplication", "EnableAutoConfiguration"}
TRANSACTION_ANNOTATIONS = {"Transactional"}
ASYNC_ANNOTATIONS = {"Async"}
EVENT_ANNOTATIONS = {"KafkaListener", "RabbitListener", "JmsListener", "EventListener"}
SCHEDULE_ANNOTATIONS = {"Scheduled"}
INTEGRATION_ANNOTATIONS = {"FeignClient"}
INTEGRATION_IMPORT_MARKERS = (
    "RestTemplate",
    "WebClient",
    "FeignClient",
    "KafkaTemplate",
    "KafkaListener",
    "RabbitTemplate",
    "RabbitListener",
    "JmsTemplate",
    "JmsListener",
    "SqsAsyncClient",
    "S3Client",
)
SHARED_UTILITY_MARKERS = (".util.", ".utils.", ".common.", ".shared.")
CPU_INTENSIVE_MARKERS = ("parallelStream", "ForkJoinPool", "CompletableFuture", "ExecutorService")
IO_INTENSIVE_MARKERS = ("InputStream", "OutputStream", "Files.", "RestTemplate", "WebClient", "JdbcTemplate")
JOIN_QUERY_MARKERS = (" join ", " join fetch ", "@query", "nativequery")
DATABASE_DEPENDENCY_MARKERS = {
    "PostgreSQL": ("org.postgresql:postgresql", "postgresql"),
    "MySQL": ("mysql:mysql-connector-java", "mysql:mysql-connector-j", "com.mysql:mysql-connector-j", "mysql-connector"),
    "MariaDB": ("org.mariadb.jdbc:mariadb-java-client", "mariadb"),
    "Oracle": ("com.oracle.database.jdbc:ojdbc", "oracle.jdbc", "ojdbc"),
    "SQL Server": ("com.microsoft.sqlserver:mssql-jdbc", "sqlserver"),
    "DB2": ("com.ibm.db2:jcc", "db2jcc", "db2"),
    "H2": ("com.h2database:h2",),
    "HSQLDB": ("org.hsqldb:hsqldb", "hsqldb"),
    "Apache Derby": ("org.apache.derby:derby", "apache.derby"),
    "MongoDB": ("org.mongodb", "mongodb"),
    "Cassandra": ("cassandra", "datastax"),
    "Redis": ("redis", "lettuce", "jedis"),
    "Neo4j": ("neo4j",),
    "Couchbase": ("couchbase",),
    "DynamoDB": ("dynamodb",),
}
DATABASE_CONFIG_MARKERS = {
    "PostgreSQL": ("jdbc:postgresql:", "postgresql://"),
    "MySQL": ("jdbc:mysql:", "mysql://"),
    "MariaDB": ("jdbc:mariadb:", "mariadb://"),
    "Oracle": ("jdbc:oracle:", "oracle.jdbc"),
    "SQL Server": ("jdbc:sqlserver:", "sqlserver://"),
    "DB2": ("jdbc:db2:",),
    "H2": ("jdbc:h2:",),
    "HSQLDB": ("jdbc:hsqldb:",),
    "Apache Derby": ("jdbc:derby:",),
    "MongoDB": ("mongodb://", "spring.data.mongodb", "mongodb+srv://"),
    "Cassandra": ("spring.cassandra", "cassandra.contact-points", "cassandra:", "datastax-java-driver"),
    "Redis": ("spring.redis", "redis://", "lettuce", "jedis"),
    "Neo4j": ("spring.neo4j", "neo4j://", "bolt://"),
    "Couchbase": ("spring.couchbase", "couchbase://"),
    "DynamoDB": ("dynamodb", "amazonaws.com/dynamodb"),
}


@dataclass
class JavaFileFact:
    path: str
    package_name: str
    imports: List[str]
    module_name: str
    class_names: List[str] = field(default_factory=list)
    annotations: Set[str] = field(default_factory=set)
    is_controller: bool = False
    is_service: bool = False
    is_repository: bool = False
    is_entity: bool = False
    is_transactional: bool = False
    is_async: bool = False
    is_event_driven: bool = False
    is_scheduled: bool = False
    has_external_integration: bool = False
    route_domains: Set[str] = field(default_factory=set)
    shared_utility_imports: List[str] = field(default_factory=list)
    cpu_intensive: bool = False
    io_intensive: bool = False
    join_queries: int = 0


@dataclass
class ModuleSummary:
    name: str
    packages: Set[str] = field(default_factory=set)
    controllers: int = 0
    services: int = 0
    repositories: int = 0
    entities: int = 0
    transactional_classes: int = 0
    async_markers: int = 0
    event_markers: int = 0
    scheduled_jobs: int = 0
    external_integrations: Set[str] = field(default_factory=set)
    route_domains: Set[str] = field(default_factory=set)
    outgoing_dependencies: Set[str] = field(default_factory=set)
    entity_access_modules: Set[str] = field(default_factory=set)
    repository_access_modules: Set[str] = field(default_factory=set)
    shared_utility_imports: int = 0
    cpu_intensive: int = 0
    io_intensive: int = 0
    join_queries: int = 0


class MicroserviceReadinessAnalyzer:
    def __init__(self) -> None:
        self.max_file_content_bytes = int(os.getenv("REPO_FILE_CONTENT_MAX_BYTES", "262144"))

    def analyze(self, workspace: RepositoryWorkspace, analysis_data: Dict[str, Any]) -> MicroserviceReadinessReport:
        root = Path(workspace.workspace_path)
        java_files_total = int(analysis_data.get("java_file_count") or 0)
        logger.info("Starting microservice readiness analysis for %s at %s", workspace.repo, root)

        build_modules = self._detect_build_modules(root)
        facts = list(self._scan_java_facts(root))
        packages = [fact.package_name for fact in facts if fact.package_name]
        base_prefix = self._dominant_base_prefix(packages)

        for fact in facts:
            fact.module_name = self._resolve_module_name(fact, base_prefix, build_modules)

        module_summaries = self._build_module_summaries(facts, base_prefix)
        has_spring_boot = self._has_spring_boot(analysis_data, facts)
        database_technologies = self._detect_database_technologies(root, analysis_data)
        score_breakdown = self._score_modules(
            module_summaries=module_summaries,
            build_modules=build_modules,
            has_spring_boot=has_spring_boot,
        )
        final_score = self._weighted_score(score_breakdown)

        readiness_category = self._eligibility_category(final_score, has_spring_boot)
        recommended_architecture = self._recommended_architecture(final_score, module_summaries, has_spring_boot)
        service_candidates = self._service_candidates(module_summaries)
        coupling_issues = self._coupling_issues(module_summaries)
        database_concerns = self._database_concerns(module_summaries)
        scaling_candidates = self._scaling_candidates(module_summaries)
        strengths = self._strengths(module_summaries, has_spring_boot, service_candidates, build_modules)
        risks = self._risks(module_summaries, has_spring_boot, coupling_issues, database_concerns)
        recommended_strategy = self._migration_strategy(
            recommended_architecture,
            module_summaries,
            service_candidates,
            scaling_candidates,
            has_spring_boot,
        )
        observations = self._observations(
            module_summaries,
            analysis_data,
            has_spring_boot,
            build_modules,
            database_technologies,
        )
        diagnostics = AnalysisDiagnostics(
            java_files_total=java_files_total or len(facts),
            java_files_scanned=len(facts),
            package_count=len(set(packages)),
            detected_modules=len(module_summaries),
            cross_module_dependencies=sum(len(summary.outgoing_dependencies) for summary in module_summaries.values()),
            circular_dependencies=len(self._find_cycles(module_summaries)),
            external_integration_count=sum(len(summary.external_integrations) for summary in module_summaries.values()),
            scan_truncated=bool(java_files_total and len(facts) < java_files_total),
        )
        detailed_report = DetailedEligibilityReport(
            project_structure=self._project_structure_points(root, analysis_data, build_modules),
            package_structure=self._package_structure_points(base_prefix, module_summaries),
            module_boundaries=self._module_boundary_points(module_summaries),
            dependency_coupling=coupling_issues[:8],
            database_access_patterns=database_concerns[:8],
            communication_analysis=self._communication_points(module_summaries),
            deployment_independence=self._deployment_points(module_summaries, build_modules),
            scalability_indicators=scaling_candidates[:8],
        )

        summary = self._summary(
            project_name=workspace.repo,
            score=final_score,
            category=readiness_category,
            architecture=recommended_architecture,
            module_summaries=module_summaries,
            has_spring_boot=has_spring_boot,
        )

        return MicroserviceReadinessReport(
            projectName=workspace.repo,
            score=final_score,
            eligibility=readiness_category,
            recommendedArchitecture=recommended_architecture,
            summary=summary,
            strengths=strengths,
            risks=risks,
            serviceCandidates=service_candidates,
            couplingIssues=coupling_issues,
            databaseConcerns=database_concerns,
            scalingCandidates=scaling_candidates,
            recommendedMigrationStrategy=recommended_strategy,
            observations=observations,
            scoreBreakdown=score_breakdown,
            detailedEligibilityReport=detailed_report,
            architecturalObservations=observations,
            analysisDiagnostics=diagnostics,
            metadata={
                "springBootDetected": has_spring_boot,
                "dominantBasePackage": ".".join(base_prefix) if base_prefix else "",
                "buildModules": sorted(build_modules),
                "routeDomains": sorted({domain for summary in module_summaries.values() for domain in summary.route_domains}),
                "databaseTechnologies": database_technologies,
            },
        )

    def _scan_java_facts(self, root: Path) -> Iterable[JavaFileFact]:
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in {".git", ".gradle", ".idea", ".mvn", "build", "dist", "node_modules", "out", "target"} and not name.startswith(".")]
            for file_name in file_names:
                if not file_name.endswith(".java"):
                    continue
                file_path = Path(current_root) / file_name
                try:
                    with open(file_path, "rb") as source_file:
                        raw = source_file.read(self.max_file_content_bytes)
                except OSError:
                    logger.debug("Skipping unreadable Java file %s", file_path)
                    continue
                content = raw.decode("utf-8", errors="ignore")
                fact = self._build_fact(root, file_path, content)
                yield fact

    def _build_fact(self, root: Path, file_path: Path, content: str) -> JavaFileFact:
        cleaned = strip_java_comments(content)
        package_name = parse_package(cleaned)
        imports = parse_imports(cleaned)
        class_profiles = parse_class_names_and_annotations(cleaned)
        annotations = {annotation for profile in class_profiles for annotation in profile["annotations"]}
        class_names = [profile["name"] for profile in class_profiles]
        lower_content = cleaned.lower()
        relative_path = file_path.relative_to(root).as_posix()
        route_domains = self._extract_route_domains(cleaned)
        shared_utility_imports = [value for value in imports if any(marker in value for marker in SHARED_UTILITY_MARKERS)]
        integration_imports = {value.split(".")[-1] for value in imports if any(marker in value for marker in INTEGRATION_IMPORT_MARKERS)}
        return JavaFileFact(
            path=relative_path,
            package_name=package_name,
            imports=imports,
            module_name="root",
            class_names=class_names,
            annotations=annotations,
            is_controller=bool(STEREOTYPE_CONTROLLER & annotations) or bool(route_domains),
            is_service=bool(STEREOTYPE_SERVICE & annotations) or any(name.lower().endswith(("service", "manager", "facade")) for name in class_names),
            is_repository=bool(STEREOTYPE_REPOSITORY & annotations) or any(name.lower().endswith(("repository", "dao")) for name in class_names),
            is_entity=bool(STEREOTYPE_ENTITY & annotations) or "@Table" in cleaned,
            is_transactional=bool(TRANSACTION_ANNOTATIONS & annotations) or "@Transactional" in cleaned,
            is_async=bool(ASYNC_ANNOTATIONS & annotations) or "@Async" in cleaned,
            is_event_driven=bool(EVENT_ANNOTATIONS & annotations) or any(marker in cleaned for marker in ("KafkaListener", "RabbitListener", "JmsListener", "ApplicationEventPublisher")),
            is_scheduled=bool(SCHEDULE_ANNOTATIONS & annotations) or "@Scheduled" in cleaned,
            has_external_integration=bool(INTEGRATION_ANNOTATIONS & annotations) or bool(integration_imports),
            route_domains=route_domains,
            shared_utility_imports=shared_utility_imports,
            cpu_intensive=any(marker.lower() in lower_content for marker in (value.lower() for value in CPU_INTENSIVE_MARKERS)),
            io_intensive=any(marker.lower() in lower_content for marker in (value.lower() for value in IO_INTENSIVE_MARKERS)),
            join_queries=sum(lower_content.count(marker) for marker in JOIN_QUERY_MARKERS),
        )

    def _resolve_module_name(self, fact: JavaFileFact, base_prefix: List[str], build_modules: Set[str]) -> str:
        build_path_module = self._resolve_module_from_build_path(fact.path, build_modules)
        if build_path_module:
            return build_path_module
        if fact.package_name:
            module_name = infer_module_from_package(fact.package_name, base_prefix)
            if module_name != "root":
                return module_name
        if fact.route_domains:
            return sanitize_module_name(sorted(fact.route_domains)[0])
        return infer_module_from_path(fact.path)

    def _build_module_summaries(
        self,
        facts: List[JavaFileFact],
        base_prefix: List[str],
    ) -> Dict[str, ModuleSummary]:
        module_summaries: Dict[str, ModuleSummary] = {}
        for fact in facts:
            module_name = fact.module_name or self._resolve_module_name(fact, base_prefix, set())
            summary = module_summaries.setdefault(module_name, ModuleSummary(name=module_name))
            summary.packages.add(fact.package_name or "")
            summary.controllers += int(fact.is_controller)
            summary.services += int(fact.is_service)
            summary.repositories += int(fact.is_repository)
            summary.entities += int(fact.is_entity)
            summary.transactional_classes += int(fact.is_transactional)
            summary.async_markers += int(fact.is_async)
            summary.event_markers += int(fact.is_event_driven)
            summary.scheduled_jobs += int(fact.is_scheduled)
            summary.route_domains.update(fact.route_domains)
            summary.shared_utility_imports += len(fact.shared_utility_imports)
            summary.cpu_intensive += int(fact.cpu_intensive)
            summary.io_intensive += int(fact.io_intensive)
            summary.join_queries += fact.join_queries
            if fact.has_external_integration:
                summary.external_integrations.update(self._integration_labels(fact))

        for fact in facts:
            own_module = fact.module_name
            summary = module_summaries[own_module]
            for imported in fact.imports:
                imported_module = infer_module_from_package(imported.rsplit(".", 1)[0], base_prefix)
                if not imported_module or imported_module == own_module or imported_module == "root":
                    continue
                summary.outgoing_dependencies.add(imported_module)
                if ".entity" in imported.lower() or imported.endswith("Repository"):
                    summary.entity_access_modules.add(imported_module)
                if imported.endswith("Repository") or ".repository." in imported.lower() or imported.endswith("Dao"):
                    summary.repository_access_modules.add(imported_module)
        return module_summaries

    def _dominant_base_prefix(self, packages: List[str]) -> List[str]:
        unique_packages = sorted(set(pkg for pkg in packages if pkg))
        common_prefix = common_package_prefix(unique_packages)
        token_lists = [pkg.split(".") for pkg in unique_packages if pkg]
        if not token_lists:
            return common_prefix

        two_token_counts = Counter(tuple(tokens[:2]) for tokens in token_lists if len(tokens) >= 2)
        if two_token_counts:
            prefix_tokens, count = two_token_counts.most_common(1)[0]
            if count >= max(10, int(len(token_lists) * 0.35)):
                return list(prefix_tokens)
        return common_prefix

    def _resolve_module_from_build_path(self, relative_path: str, build_modules: Set[str]) -> str | None:
        if not build_modules:
            return None
        parts = [sanitize_module_name(part) for part in Path(relative_path).parts if part]
        if "src" not in parts:
            return None
        src_index = parts.index("src")
        for candidate in reversed(parts[:src_index]):
            if candidate in build_modules:
                return candidate
        return None

    def _has_spring_boot(self, analysis_data: Dict[str, Any], facts: List[JavaFileFact]) -> bool:
        for dependency in analysis_data.get("dependencies") or []:
            if not isinstance(dependency, dict):
                continue
            joined = f"{dependency.get('group_id', '')}:{dependency.get('artifact_id', '')}"
            if re.search(r"org\.springframework\.boot:|spring-boot", joined, re.I):
                return True
        return any(bool(SPRING_BOOT_ANNOTATIONS & fact.annotations) for fact in facts)

    def _score_modules(
        self,
        module_summaries: Dict[str, ModuleSummary],
        build_modules: Set[str],
        has_spring_boot: bool,
    ) -> List[MicroserviceScoreBreakdown]:
        module_count = len(module_summaries)
        deployable_modules = sum(1 for summary in module_summaries.values() if summary.controllers + summary.services + summary.repositories >= 3)
        cross_dependencies = sum(len(summary.outgoing_dependencies) for summary in module_summaries.values())
        cycles = self._find_cycles(module_summaries)
        shared_utility_total = sum(summary.shared_utility_imports for summary in module_summaries.values())
        cross_entity_access = sum(len(summary.entity_access_modules) for summary in module_summaries.values())
        scaling_signals = sum(
            summary.async_markers + summary.event_markers + summary.scheduled_jobs + summary.cpu_intensive + summary.io_intensive
            for summary in module_summaries.values()
        )
        failure_isolation_candidates = sum(1 for summary in module_summaries.values() if summary.external_integrations)

        domain_score = min(100, (16 if not has_spring_boot else 25) + module_count * 11 + deployable_modules * (8 if not has_spring_boot else 10))
        coupling_penalty = cross_dependencies * 6 + len(cycles) * 18 + min(shared_utility_total * 2, 18)
        coupling_score = max(0, 100 - coupling_penalty)
        db_penalty = cross_entity_access * 10 + sum(summary.join_queries for summary in module_summaries.values()) * 3
        db_score = max(0, 100 - min(85, db_penalty))
        scalability_score = min(100, 20 + scaling_signals * 8 + sum(bool(summary.external_integrations) for summary in module_summaries.values()) * 6)
        deployment_score = min(100, (20 if build_modules else 10) + deployable_modules * 14 + module_count * 6)
        failure_score = min(100, 25 + failure_isolation_candidates * 18 + sum(summary.scheduled_jobs for summary in module_summaries.values()) * 4)
        async_score = min(100, 10 + sum(summary.async_markers + summary.event_markers for summary in module_summaries.values()) * 12)

        if not has_spring_boot:
            domain_score = min(domain_score, 78)
            deployment_score = min(deployment_score, 72)
            scalability_score = min(scalability_score, 72)
            failure_score = min(failure_score, 68)
            async_score = min(async_score, 68)

        return [
            MicroserviceScoreBreakdown(name="Domain separation", score=domain_score, weight=20, summary=f"{module_count} candidate domains detected with {deployable_modules} strong bounded contexts."),
            MicroserviceScoreBreakdown(name="Coupling", score=coupling_score, weight=20, summary=f"{cross_dependencies} cross-module dependencies and {len(cycles)} circular dependency pairs detected."),
            MicroserviceScoreBreakdown(name="DB independence", score=db_score, weight=15, summary=f"{cross_entity_access} cross-module entity access patterns and join-heavy repositories were observed."),
            MicroserviceScoreBreakdown(name="Scalability", score=scalability_score, weight=15, summary=f"{scaling_signals} async, batch, CPU, or IO scaling indicators were found."),
            MicroserviceScoreBreakdown(name="Deployment independence", score=deployment_score, weight=10, summary=f"{len(build_modules) or module_count} module hints and {deployable_modules} independently shaped modules were detected."),
            MicroserviceScoreBreakdown(name="Failure isolation", score=failure_score, weight=10, summary=f"{failure_isolation_candidates} modules interact with external systems and may benefit from isolation."),
            MicroserviceScoreBreakdown(name="Async/event readiness", score=async_score, weight=10, summary="Messaging, scheduling, and asynchronous processing markers were evaluated."),
        ]

    def _weighted_score(self, breakdown: List[MicroserviceScoreBreakdown]) -> int:
        total_weight = sum(item.weight for item in breakdown) or 100
        weighted = sum(item.score * item.weight for item in breakdown) / total_weight
        return max(0, min(100, int(round(weighted))))

    def _eligibility_category(self, score: int, has_spring_boot: bool) -> str:
        if score >= 72:
            return "STRONGLY ELIGIBLE"
        if score >= 45:
            return "PARTIALLY ELIGIBLE"
        return "NOT ELIGIBLE"

    def _recommended_architecture(self, score: int, module_summaries: Dict[str, ModuleSummary], has_spring_boot: bool) -> str:
        module_count = len(module_summaries)
        if not has_spring_boot and score < 45:
            return "Keep Monolith"
        if score >= 78 and module_count >= 4:
            return "Full Microservices"
        if score >= 58 and module_count >= 3:
            return "Partial Microservices"
        if score >= 40:
            return "Modular Monolith"
        return "Keep Monolith"

    def _service_candidates(self, module_summaries: Dict[str, ModuleSummary]) -> List[ServiceCandidate]:
        candidates: List[ServiceCandidate] = []
        for summary in sorted(module_summaries.values(), key=lambda item: (item.controllers + item.services + item.repositories + item.entities), reverse=True):
            evidence: List[str] = []
            if summary.controllers:
                evidence.append(f"{summary.controllers} REST controller classes")
            if summary.services:
                evidence.append(f"{summary.services} service classes")
            if summary.repositories:
                evidence.append(f"{summary.repositories} repository classes")
            if summary.entities:
                evidence.append(f"{summary.entities} entity classes")
            if summary.external_integrations:
                evidence.append(f"External integrations: {', '.join(sorted(summary.external_integrations)[:3])}")
            if summary.route_domains:
                evidence.append(f"Route domains: {', '.join(sorted(summary.route_domains)[:3])}")
            if not evidence:
                continue
            scaling_signals: List[str] = []
            if summary.async_markers:
                scaling_signals.append("Async processing")
            if summary.event_markers:
                scaling_signals.append("Event-driven behavior")
            if summary.scheduled_jobs:
                scaling_signals.append("Scheduled/background jobs")
            if summary.cpu_intensive:
                scaling_signals.append("CPU-intensive work")
            if summary.io_intensive:
                scaling_signals.append("IO-intensive work")
            candidates.append(
                ServiceCandidate(
                    name=f"{titleize_module_name(summary.name)} Service",
                    packages=sorted(package for package in summary.packages if package)[:5],
                    evidence=evidence[:5],
                    scaling_signals=scaling_signals,
                    external_integrations=sorted(summary.external_integrations)[:5],
                    transactional=summary.transactional_classes > 0,
                )
            )
        return candidates[:8]

    def _coupling_issues(self, module_summaries: Dict[str, ModuleSummary]) -> List[str]:
        issues: List[str] = []
        cycles = self._find_cycles(module_summaries)
        for source, target in cycles[:8]:
            issues.append(f"Circular dependency detected between '{source}' and '{target}'.")
        for summary in sorted(module_summaries.values(), key=lambda item: len(item.outgoing_dependencies), reverse=True):
            if len(summary.outgoing_dependencies) >= 3:
                issues.append(
                    f"Module '{summary.name}' depends on {len(summary.outgoing_dependencies)} other modules: {', '.join(sorted(summary.outgoing_dependencies)[:5])}."
                )
            if summary.shared_utility_imports >= 5:
                issues.append(f"Module '{summary.name}' heavily relies on shared/common utilities ({summary.shared_utility_imports} imports).")
        return top_n_items(issues, limit=10)

    def _database_concerns(self, module_summaries: Dict[str, ModuleSummary]) -> List[str]:
        concerns: List[str] = []
        for summary in module_summaries.values():
            if summary.entity_access_modules:
                concerns.append(
                    f"Module '{summary.name}' accesses entities from other modules: {', '.join(sorted(summary.entity_access_modules)[:5])}."
                )
            if summary.repository_access_modules:
                concerns.append(
                    f"Module '{summary.name}' touches repositories outside its boundary: {', '.join(sorted(summary.repository_access_modules)[:5])}."
                )
            if summary.join_queries >= 2:
                concerns.append(f"Module '{summary.name}' contains {summary.join_queries} join-heavy query markers that may indicate shared database coupling.")
            if summary.transactional_classes >= 3 and summary.entity_access_modules:
                concerns.append(f"Module '{summary.name}' has broad transactional usage across module boundaries.")
        return top_n_items(concerns, limit=10)

    def _scaling_candidates(self, module_summaries: Dict[str, ModuleSummary]) -> List[str]:
        candidates: List[str] = []
        for summary in module_summaries.values():
            reasons: List[str] = []
            if summary.async_markers or summary.event_markers:
                reasons.append("async/event-driven workflows")
            if summary.scheduled_jobs:
                reasons.append("background jobs")
            if summary.cpu_intensive:
                reasons.append("CPU-intensive logic")
            if summary.io_intensive or summary.external_integrations:
                reasons.append("IO/external integration heavy")
            if reasons:
                candidates.append(f"{titleize_module_name(summary.name)} can be scaled independently due to {', '.join(reasons)}.")
        return top_n_items(candidates, limit=8)

    def _strengths(
        self,
        module_summaries: Dict[str, ModuleSummary],
        has_spring_boot: bool,
        service_candidates: List[ServiceCandidate],
        build_modules: Set[str],
    ) -> List[str]:
        strengths: List[str] = []
        if has_spring_boot:
            strengths.append("Spring Boot structure and stereotype annotations provide a strong foundation for modular analysis.")
        else:
            strengths.append("The repository still exposes structural signals that can be assessed independently of Spring Boot conventions.")
        if len(service_candidates) >= 3:
            strengths.append(f"{len(service_candidates)} strong service boundary candidates were identified from package and stereotype analysis.")
        if build_modules:
            strengths.append(f"Build configuration already exposes {len(build_modules)} module hints.")
        if any(candidate.scaling_signals for candidate in service_candidates):
            strengths.append("Async, event-driven, or scheduled processing markers suggest natural extraction opportunities.")
        if any(summary.controllers and summary.services and summary.repositories for summary in module_summaries.values()):
            strengths.append("Several modules already show controller-service-repository layering.")
        return top_n_items(strengths, limit=8)

    def _risks(
        self,
        module_summaries: Dict[str, ModuleSummary],
        has_spring_boot: bool,
        coupling_issues: List[str],
        database_concerns: List[str],
    ) -> List[str]:
        risks: List[str] = []
        if not has_spring_boot:
            risks.append("Spring Boot conventions were not detected, so framework-specific layering signals are weaker and confidence relies more on structural heuristics.")
        if coupling_issues:
            risks.extend(coupling_issues[:4])
        if database_concerns:
            risks.extend(database_concerns[:4])
        if len(module_summaries) <= 2:
            risks.append("Only a small number of domain-like modules were detected, which weakens bounded-context confidence.")
        return top_n_items(risks, limit=10)

    def _migration_strategy(
        self,
        recommended_architecture: str,
        module_summaries: Dict[str, ModuleSummary],
        service_candidates: List[ServiceCandidate],
        scaling_candidates: List[str],
        has_spring_boot: bool,
    ) -> List[str]:
        strategy: List[str] = []
        if recommended_architecture == "Keep Monolith":
            strategy.extend([
                "Stabilize the monolith first with clearer package boundaries and modular service interfaces.",
                "Measure coupling and database overlap before attempting extraction.",
            ])
        elif recommended_architecture == "Modular Monolith":
            strategy.extend([
                "Refactor into a modular monolith first with explicit module APIs and reduced cross-package dependencies.",
                "Standardize module ownership around controller-service-repository boundaries.",
            ])
        else:
            strategy.extend([
                "Start with a strangler approach and extract the most independent module first.",
                "Treat integration-heavy or background-processing modules as the first service candidates.",
                "Introduce API contracts and events between extracted modules before moving shared data ownership.",
            ])
        if not has_spring_boot:
            strategy.append("Add explicit module contracts and clear component boundaries first, because framework-level stereotypes are limited or absent.")
        if service_candidates:
            strategy.append(f"Pilot extraction with {service_candidates[0].name}.")
        if scaling_candidates:
            strategy.append("Prioritize independently scalable modules where async, scheduled, or integration-heavy workloads already exist.")
        return top_n_items(strategy, limit=8)

    def _observations(
        self,
        module_summaries: Dict[str, ModuleSummary],
        analysis_data: Dict[str, Any],
        has_spring_boot: bool,
        build_modules: Set[str],
        database_technologies: List[str],
    ) -> List[str]:
        observations: List[str] = []
        if analysis_data.get("build_tool"):
            observations.append(f"Build tool detected: {analysis_data.get('build_tool')}.")
        if build_modules:
            observations.append(f"Build configuration references module candidates: {', '.join(sorted(build_modules)[:6])}.")
        if database_technologies:
            if len(database_technologies) == 1:
                observations.append(f"Database technology detected: {database_technologies[0]}.")
            else:
                observations.append(f"Database technologies detected: {', '.join(database_technologies)}.")
        if has_spring_boot:
            observations.append("Spring Boot stereotypes were used as first-class evidence instead of only filename heuristics.")
        else:
            observations.append("Framework-agnostic heuristics were used because Spring Boot markers were not detected.")
        if any(summary.external_integrations for summary in module_summaries.values()):
            observations.append("External integrations are concentrated in specific modules, which improves failure-isolation opportunities.")
        if any(summary.entity_access_modules for summary in module_summaries.values()):
            observations.append("Some modules reach across database boundaries, so data ownership must be addressed before service extraction.")
        return top_n_items(observations, limit=10)

    def _summary(
        self,
        project_name: str,
        score: int,
        category: str,
        architecture: str,
        module_summaries: Dict[str, ModuleSummary],
        has_spring_boot: bool,
    ) -> str:
        if not has_spring_boot:
            return (
                f"{project_name} is not detected as a Spring Boot application, so the assessment relies on framework-agnostic structural heuristics. "
                f"It scored {score}/100 and is classified as {category}, with {len(module_summaries)} domain-like modules inferred."
            )
        module_count = len(module_summaries)
        return (
            f"{project_name} scored {score}/100 and is classified as {category}. "
            f"{module_count} domain-like modules were inferred, leading to a recommended target architecture of {architecture}."
        )

    def _find_cycles(self, module_summaries: Dict[str, ModuleSummary]) -> List[tuple[str, str]]:
        cycles: List[tuple[str, str]] = []
        for module_name, summary in module_summaries.items():
            for dependency in summary.outgoing_dependencies:
                target = module_summaries.get(dependency)
                if target and module_name in target.outgoing_dependencies and module_name < dependency:
                    cycles.append((module_name, dependency))
        return cycles

    def _detect_build_modules(self, root: Path) -> Set[str]:
        modules: Set[str] = set()
        pom_path = root / "pom.xml"
        if pom_path.exists():
            try:
                content = pom_path.read_text(encoding="utf-8", errors="ignore")
                modules.update(sanitize_module_name(value) for value in re.findall(r"<module>\s*([^<]+)\s*</module>", content))
            except OSError:
                logger.debug("Unable to read root pom.xml for module analysis")
        for settings_name in ("settings.gradle", "settings.gradle.kts"):
            settings_path = root / settings_name
            if not settings_path.exists():
                continue
            try:
                content = settings_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for include_match in re.findall(r"include\s*\((.*?)\)", content, re.DOTALL):
                modules.update(
                    sanitize_module_name(token.strip(" '\"").replace(":", "-"))
                    for token in include_match.split(",")
                    if token.strip()
                )
        return {value for value in modules if value and value != "root"}

    def _detect_database_technologies(self, root: Path, analysis_data: Dict[str, Any]) -> List[str]:
        detected: Set[str] = set()

        for dependency in analysis_data.get("dependencies") or []:
            if not isinstance(dependency, dict):
                continue
            group_id = str(dependency.get("group_id") or "").lower()
            artifact_id = str(dependency.get("artifact_id") or "").lower()
            joined = f"{group_id}:{artifact_id}".strip(":")
            for database_name, markers in DATABASE_DEPENDENCY_MARKERS.items():
                if any(marker in joined for marker in markers):
                    detected.add(database_name)

        config_file_names = {
            "application.properties",
            "application.yml",
            "application.yaml",
            "bootstrap.properties",
            "bootstrap.yml",
            "bootstrap.yaml",
            "persistence.xml",
        }
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = [
                name
                for name in dir_names
                if name not in {".git", ".gradle", ".idea", ".mvn", "build", "dist", "node_modules", "out", "target"}
                and not name.startswith(".")
            ]
            for file_name in file_names:
                if file_name not in config_file_names:
                    continue
                file_path = Path(current_root) / file_name
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore").lower()
                except OSError:
                    continue
                for database_name, markers in DATABASE_CONFIG_MARKERS.items():
                    if any(marker in content for marker in markers):
                        detected.add(database_name)

        ordered_names = [name for name in DATABASE_DEPENDENCY_MARKERS.keys() if name in detected]
        return ordered_names

    def _integration_labels(self, fact: JavaFileFact) -> Set[str]:
        labels: Set[str] = set()
        lowered_imports = " ".join(fact.imports).lower()
        if "feign" in lowered_imports or "FeignClient" in fact.annotations:
            labels.add("Feign / HTTP client")
        if "webclient" in lowered_imports or "resttemplate" in lowered_imports:
            labels.add("REST client")
        if "kafka" in lowered_imports or "KafkaListener" in fact.annotations:
            labels.add("Kafka")
        if "rabbit" in lowered_imports or "RabbitListener" in fact.annotations:
            labels.add("RabbitMQ")
        if "jms" in lowered_imports or "JmsListener" in fact.annotations:
            labels.add("JMS")
        return labels

    def _extract_route_domains(self, cleaned_content: str) -> Set[str]:
        domains: Set[str] = set()
        for pattern in (
            r"@(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\((.*?)\)",
            r"@Path\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
        ):
            for match in re.finditer(pattern, cleaned_content, re.DOTALL):
                raw_value = match.group(1) or ""
                path_match = re.search(r"(?:value|path)?\s*=?\s*\{?\s*[\"']([^\"']+)", raw_value)
                path_value = path_match.group(1) if path_match else raw_value
                segments = [segment for segment in re.split(r"[/{]+", path_value) if segment and segment not in {"api", "v1", "v2", "v3"}]
                if segments:
                    domains.add(sanitize_module_name(segments[0]))
        return domains

    def _project_structure_points(self, root: Path, analysis_data: Dict[str, Any], build_modules: Set[str]) -> List[str]:
        points = [
            f"Build tool: {analysis_data.get('build_tool') or 'unknown'}",
            f"Java files detected: {analysis_data.get('java_file_count') or 0}",
            f"Tests present: {'yes' if analysis_data.get('has_tests') else 'no'}",
        ]
        if build_modules:
            points.append(f"Build configuration exposes modules: {', '.join(sorted(build_modules)[:6])}")
        if analysis_data.get("structure", {}).get("has_src_main"):
            points.append("Standard src/main source layout detected.")
        return points

    def _package_structure_points(self, base_prefix: List[str], module_summaries: Dict[str, ModuleSummary]) -> List[str]:
        points: List[str] = []
        if base_prefix:
            points.append(f"Common base package: {'.'.join(base_prefix)}")
        for summary in sorted(module_summaries.values(), key=lambda item: len(item.packages), reverse=True)[:6]:
            package_samples = ", ".join(sorted(package for package in summary.packages if package)[:3])
            points.append(f"Module '{summary.name}' packages: {package_samples or 'package not declared'}")
        return points

    def _module_boundary_points(self, module_summaries: Dict[str, ModuleSummary]) -> List[str]:
        points: List[str] = []
        for summary in sorted(module_summaries.values(), key=lambda item: (item.controllers + item.services + item.repositories + item.entities), reverse=True)[:8]:
            points.append(
                f"{summary.name}: {summary.controllers} controllers, {summary.services} services, {summary.repositories} repositories, {summary.entities} entities."
            )
        return points

    def _communication_points(self, module_summaries: Dict[str, ModuleSummary]) -> List[str]:
        points: List[str] = []
        for summary in module_summaries.values():
            if summary.route_domains:
                points.append(f"{summary.name} exposes route domains: {', '.join(sorted(summary.route_domains)[:4])}.")
            if summary.external_integrations:
                points.append(f"{summary.name} integrates with: {', '.join(sorted(summary.external_integrations)[:4])}.")
            if summary.event_markers or summary.async_markers:
                points.append(f"{summary.name} has async/event-driven processing markers.")
        return top_n_items(points, limit=10)

    def _deployment_points(self, module_summaries: Dict[str, ModuleSummary], build_modules: Set[str]) -> List[str]:
        points: List[str] = []
        if build_modules:
            points.append(f"Build files already define {len(build_modules)} explicit modules.")
        for summary in module_summaries.values():
            if summary.controllers and summary.services and summary.repositories and len(summary.outgoing_dependencies) <= 2:
                points.append(f"{summary.name} looks close to an independently deployable slice.")
            if summary.scheduled_jobs:
                points.append(f"{summary.name} contains {summary.scheduled_jobs} scheduled/background jobs.")
        return top_n_items(points, limit=10)
