"""
Microservice Conversion Service
Orchestrates the full conversion of a monolithic Java/Spring Boot project
into independent microservice projects using FordLLM-powered boundary detection.

Flow:
  1. Analyze project structure (packages, controllers, entities, dependencies)
  2. Use FordLLM to propose intelligent service boundaries
  3. Generate independent Spring Boot projects per service
  4. Create shared library module for cross-cutting concerns
  5. Generate Docker, docker-compose, and API gateway configuration
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from models.microservice_readiness import (
    MicroserviceReadinessReport,
    ServiceCandidate,
)
from services.repository_workspace_service import RepositoryWorkspace

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MicroserviceProject:
    """Represents a generated microservice project."""
    name: str
    artifact_id: str
    base_package: str
    packages: List[str] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    controllers: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    repositories: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    has_database: bool = False
    has_messaging: bool = False
    has_scheduling: bool = False
    port: int = 8080
    description: str = ""
    class_tokens: List[str] = field(default_factory=list)
    dependencies_from_other_services: List[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    """Result of the full microservice conversion."""
    output_path: str
    services_created: List[str]
    shared_module: str
    docker_compose_path: str
    summary: str
    service_details: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACKAGE_RE = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([a-zA-Z0-9_.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum|record)\s+(\w+)")
ANNOTATION_RE = re.compile(r"@(\w+)")
REQUEST_MAPPING_RE = re.compile(
    r"@(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']",
)

SPRING_BOOT_STARTER = "org.springframework.boot:spring-boot-starter"
SPRING_WEB_STARTER = "org.springframework.boot:spring-boot-starter-web"
SPRING_DATA_JPA = "org.springframework.boot:spring-boot-starter-data-jpa"

SKIP_DIRS = {".git", ".gradle", ".idea", ".mvn", "build", "dist",
             "node_modules", "out", "target", "microservices-output"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower() or "service"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _parse_java_file(path: Path, root: Path) -> Dict[str, Any]:
    """Parse a Java source file and return structural metadata."""
    content = _read_text(path)
    if not content:
        return {}

    pkg_match = PACKAGE_RE.search(content)
    package_name = pkg_match.group(1) if pkg_match else ""
    imports = IMPORT_RE.findall(content)
    annotations = set(ANNOTATION_RE.findall(content))
    class_match = CLASS_RE.search(content)
    class_name = class_match.group(1) if class_match else path.stem

    route_paths: List[str] = []
    for m in REQUEST_MAPPING_RE.finditer(content):
        route_paths.append(m.group(1))

    return {
        "path": str(path.relative_to(root)),
        "abs_path": str(path),
        "package": package_name,
        "class_name": class_name,
        "imports": imports,
        "annotations": annotations,
        "is_controller": bool({"RestController", "Controller"} & annotations),
        "is_service": bool({"Service"} & annotations) or class_name.endswith(("Service", "ServiceImpl")),
        "is_repository": bool({"Repository"} & annotations) or class_name.endswith(("Repository", "Dao")),
        "is_entity": bool({"Entity", "Document", "Table"} & annotations),
        "is_config": bool({"Configuration", "EnableAutoConfiguration", "SpringBootApplication"} & annotations),
        "is_main_app": bool({"SpringBootApplication"} & annotations),
        "route_paths": route_paths,
        "content": content,
    }


def _scan_project(root: Path) -> List[Dict[str, Any]]:
    """Scan all Java files in a project."""
    files: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".java"):
                info = _parse_java_file(Path(dirpath) / fn, root)
                if info:
                    files.append(info)
    return files


def _detect_base_package(files: List[Dict[str, Any]]) -> str:
    """Find the dominant base package of the project."""
    packages = [f["package"] for f in files if f.get("package")]
    if not packages:
        return "com.example"
    # Find common prefix
    parts_list = [p.split(".") for p in packages]
    prefix: List[str] = []
    for tokens in zip(*parts_list):
        if len(set(tokens)) == 1:
            prefix.append(tokens[0])
        else:
            break
    return ".".join(prefix) if prefix else packages[0].rsplit(".", 1)[0]


def _detect_build_tool(root: Path) -> str:
    if (root / "pom.xml").exists():
        return "maven"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return "gradle"
    return "maven"


def _detect_java_version(root: Path) -> str:
    """Try to detect Java version from build files."""
    pom = root / "pom.xml"
    if pom.exists():
        content = _read_text(pom)
        m = re.search(r"<java\.version>(\d+)</java\.version>", content)
        if m:
            return m.group(1)
        m = re.search(r"<maven\.compiler\.source>(\d+)</maven\.compiler\.source>", content)
        if m:
            return m.group(1)
    for gradle_name in ("build.gradle", "build.gradle.kts"):
        gradle = root / gradle_name
        if gradle.exists():
            content = _read_text(gradle)
            m = re.search(r"sourceCompatibility\s*=\s*['\"]?(\d+)", content)
            if m:
                return m.group(1)
    return "17"


def _detect_spring_boot_version(root: Path) -> str:
    pom = root / "pom.xml"
    if pom.exists():
        content = _read_text(pom)
        m = re.search(r"<version>(\d+\.\d+\.\d+)</version>", content)
        # look for spring-boot-starter-parent version
        parent_match = re.search(
            r"spring-boot-starter-parent.*?<version>(\d+\.\d+\.\d+)</version>",
            content, re.DOTALL
        )
        if parent_match:
            return parent_match.group(1)
    return "3.2.5"


def _infer_domain_from_route(route: str) -> str:
    """Extract domain name from a REST route like /api/v1/orders -> orders."""
    parts = [p for p in route.strip("/").split("/") if p and p not in ("api", "v1", "v2", "v3")]
    return parts[0] if parts else ""


# ---------------------------------------------------------------------------
# LLM-powered boundary detection
# ---------------------------------------------------------------------------

async def _llm_propose_boundaries(
    files: List[Dict[str, Any]],
    base_package: str,
) -> List[Dict[str, Any]]:
    """Use FordLLM to propose microservice boundaries from project structure."""
    try:
        from services.fordllm_auth_service import fordllm_auth
        from openai import OpenAI

        base_url = os.getenv("FORDLLM_BASE_URL", "https://api.pivpn.core.ford.com/fordllmapi/api/v1")
        model = os.getenv("FORDLLM_MODEL", "fordllm-coding-model")
        sub_model = os.getenv("FORDLLM_SUB_MODEL", "gemini-2.5-pro")

        # Build a compact project summary for the LLM
        summary_lines: List[str] = []
        controllers: List[str] = []
        services_list: List[str] = []
        entities: List[str] = []
        repos: List[str] = []

        for f in files:
            pkg = f.get("package", "")
            cls = f.get("class_name", "")
            label = f"{pkg}.{cls}" if pkg else cls
            if f.get("is_controller"):
                routes = ", ".join(f.get("route_paths", [])[:3])
                controllers.append(f"  - {label} [routes: {routes}]" if routes else f"  - {label}")
            elif f.get("is_service"):
                services_list.append(f"  - {label}")
            elif f.get("is_entity"):
                entities.append(f"  - {label}")
            elif f.get("is_repository"):
                repos.append(f"  - {label}")

        summary = (
            f"Base package: {base_package}\n"
            f"Total Java files: {len(files)}\n\n"
            f"Controllers ({len(controllers)}):\n" + "\n".join(controllers[:30]) + "\n\n"
            f"Services ({len(services_list)}):\n" + "\n".join(services_list[:30]) + "\n\n"
            f"Entities ({len(entities)}):\n" + "\n".join(entities[:30]) + "\n\n"
            f"Repositories ({len(repos)}):\n" + "\n".join(repos[:30])
        )

        prompt = f"""You are a senior software architect specializing in microservice decomposition.

Analyze this Java Spring Boot monolith and propose optimal microservice boundaries.

PROJECT STRUCTURE:
{summary}

INSTRUCTIONS:
1. Identify 2-8 bounded contexts / microservice candidates
2. For each service, specify:
   - name: a clear service name (e.g. "order-service", "user-service")
   - packages: list of Java packages that belong to this service
   - description: one-line business purpose
   - needs_database: boolean
   - needs_messaging: boolean (Kafka/RabbitMQ for inter-service events)
3. Group related controllers, services, entities, and repositories together
4. Identify shared/common code that should go into a shared library

Return ONLY valid JSON with this structure:
{{
  "services": [
    {{
      "name": "user-service",
      "packages": ["{base_package}.user", "{base_package}.auth"],
      "description": "Handles user management and authentication",
      "needs_database": true,
      "needs_messaging": false
    }}
  ],
  "shared_packages": ["{base_package}.common", "{base_package}.config"],
  "reasoning": "Brief explanation of decomposition strategy"
}}"""

        client = OpenAI(api_key=fordllm_auth.token, base_url=base_url)

        loop = asyncio.get_event_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are an expert microservice architect. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
                temperature=0.2,
                extra_body={"models": [sub_model]},
            ),
        )

        response_text = completion.choices[0].message.content or ""
        # Extract JSON from response
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            logger.info("FordLLM proposed %d microservice boundaries", len(result.get("services", [])))
            return result.get("services", [])

    except Exception as exc:
        logger.warning("FordLLM boundary detection failed (%s), falling back to heuristics", exc)

    return []


def _infer_class_domain(class_name: str) -> str:
    """Extract the domain token from a class name by stripping common suffixes.

    e.g. VisitController -> visit, OwnerRepository -> owner,
         PetTypeFormatter -> pettype, VetController -> vet
    """
    suffixes = (
        "Controller", "RestController", "Service", "ServiceImpl",
        "Repository", "Dao", "Entity", "Dto", "Mapper", "Converter",
        "Formatter", "Validator", "Config", "Configuration",
        "Test", "Tests", "Spec", "Helper", "Utils", "Util",
    )
    name = class_name
    for s in suffixes:
        if name.endswith(s) and len(name) > len(s):
            name = name[: -len(s)]
            break
    return name.lower()


def _heuristic_boundaries(
    files: List[Dict[str, Any]],
    base_package: str,
) -> List[Dict[str, Any]]:
    """Heuristic-based microservice boundary detection as fallback.

    Strategy:
      1. Group files by sub-package after base_package (package-level domains).
      2. Within each package domain, further split by *class-name domain* so
         that e.g. Visit* and Owner* in the same ``owner`` package become
         separate services.
      3. Merge class-name domains that have only 1 file into their package
         domain (avoids micro-services with a single file).
      4. Fall back to route-based splitting if we still have < 2 services.
    """
    SHARED_DOMAINS = frozenset((
        "util", "utils", "common", "shared", "config", "configuration",
        "exception", "dto", "model", "models", "domain", "infrastructure",
        "base", "core", "security", "aop", "aspect", "filter", "interceptor",
    ))

    base_depth = len(base_package.split(".")) if base_package else 0

    # ---------- pass 1: package-level grouping ----------
    pkg_domain_map: Dict[str, List[Dict[str, Any]]] = {}
    for f in files:
        pkg = f.get("package", "")
        if not pkg:
            continue
        parts = pkg.split(".")
        pkg_domain = parts[base_depth] if len(parts) > base_depth else "core"
        if pkg_domain in SHARED_DOMAINS:
            pkg_domain = "_shared"
        pkg_domain_map.setdefault(pkg_domain, []).append(f)

    # ---------- pass 2: class-name sub-splitting ----------
    # For each package domain, detect whether multiple logical domains coexist
    # (e.g. Owner*, Visit*, Pet* all in the "owner" package).
    domain_files_map: Dict[str, List[Dict[str, Any]]] = {}

    for pkg_domain, pfiles in pkg_domain_map.items():
        if pkg_domain == "_shared":
            continue

        # Collect class-name domains present in this package domain
        cls_domains: Dict[str, List[Dict[str, Any]]] = {}
        for f in pfiles:
            cd = _infer_class_domain(f.get("class_name", ""))
            cls_domains.setdefault(cd, []).append(f)

        # Only sub-split if there are multiple distinct class-name domains
        # with at least one having a controller or entity (i.e. a real bounded context)
        meaningful = {
            cd: fls for cd, fls in cls_domains.items()
            if any(fl.get("is_controller") or fl.get("is_entity") for fl in fls)
        }

        if len(meaningful) >= 2:
            # Sub-split: each meaningful class-domain becomes its own service
            leftover: List[Dict[str, Any]] = []
            for cd, fls in cls_domains.items():
                if cd in meaningful and len(fls) >= 1:
                    domain_files_map.setdefault(cd, []).extend(fls)
                else:
                    leftover.extend(fls)
            # Assign leftover files to the largest sub-domain
            if leftover:
                biggest = max(meaningful.keys(), key=lambda k: len(meaningful[k]))
                domain_files_map.setdefault(biggest, []).extend(leftover)
        else:
            # Keep as a single domain
            domain_files_map.setdefault(pkg_domain, []).extend(pfiles)

    # ---------- pass 3: merge tiny domains (< 2 files and no controller) ----------
    final_map: Dict[str, List[Dict[str, Any]]] = {}
    merge_target: Optional[str] = None
    for domain, dfiles in sorted(domain_files_map.items(), key=lambda x: -len(x[1])):
        if merge_target is None:
            merge_target = domain
        has_ctrl = any(f.get("is_controller") for f in dfiles)
        has_entity = any(f.get("is_entity") for f in dfiles)
        if len(dfiles) < 2 and not has_ctrl and not has_entity and merge_target:
            final_map.setdefault(merge_target, []).extend(dfiles)
        else:
            final_map.setdefault(domain, []).extend(dfiles)

    # ---------- build service list ----------
    services: List[Dict[str, Any]] = []
    for domain, dfiles in sorted(final_map.items(), key=lambda x: -len(x[1])):
        has_entity = any(f.get("is_entity") for f in dfiles)
        packages = sorted(set(f.get("package", "") for f in dfiles if f.get("package")))
        # Also store class-name tokens for smarter file assignment later
        class_tokens = sorted(set(_infer_class_domain(f.get("class_name", "")) for f in dfiles))
        services.append({
            "name": f"{_sanitize(domain)}-service",
            "packages": packages,
            "class_tokens": class_tokens,
            "description": f"Handles {domain} domain logic",
            "needs_database": has_entity,
            "needs_messaging": False,
        })

    # ---------- route-based fallback ----------
    if len(services) < 2:
        route_domains: Dict[str, List[Dict[str, Any]]] = {}
        for f in files:
            for route in f.get("route_paths", []):
                domain = _infer_domain_from_route(route)
                if domain:
                    route_domains.setdefault(domain, []).append(f)
        for domain, domain_files in route_domains.items():
            if not any(s["name"].startswith(domain) for s in services):
                packages = sorted(set(f.get("package", "") for f in domain_files if f.get("package")))
                services.append({
                    "name": f"{_sanitize(domain)}-service",
                    "packages": packages,
                    "class_tokens": [domain],
                    "description": f"REST API for {domain}",
                    "needs_database": any(f.get("is_entity") for f in domain_files),
                    "needs_messaging": False,
                })

    return services[:8]


# ---------------------------------------------------------------------------
# Project scaffolding generators
# ---------------------------------------------------------------------------

def _generate_application_java(
    base_package: str,
    class_name: str,
) -> str:
    return f"""package {base_package};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

@SpringBootApplication
@EnableDiscoveryClient
public class {class_name} {{

    public static void main(String[] args) {{
        SpringApplication.run({class_name}.class, args);
    }}
}}
"""


def _generate_application_yml(
    service_name: str,
    port: int,
    has_database: bool,
) -> str:
    lines = [
        f"spring:",
        f"  application:",
        f"    name: {service_name}",
        f"  profiles:",
        f"    active: default",
    ]
    if has_database:
        lines.extend([
            f"  datasource:",
            f"    url: jdbc:postgresql://localhost:5432/{service_name.replace('-', '_')}_db",
            f"    username: postgres",
            f"    password: postgres",
            f"    driver-class-name: org.postgresql.Driver",
            f"  jpa:",
            f"    hibernate:",
            f"      ddl-auto: update",
            f"    show-sql: false",
            f"    properties:",
            f"      hibernate:",
            f"        dialect: org.hibernate.dialect.PostgreSQLDialect",
        ])
    lines.extend([
        f"",
        f"server:",
        f"  port: {port}",
        f"",
        f"eureka:",
        f"  client:",
        f"    service-url:",
        f"      defaultZone: http://localhost:8761/eureka/",
        f"    register-with-eureka: true",
        f"    fetch-registry: true",
        f"  instance:",
        f"    prefer-ip-address: true",
        f"",
        f"management:",
        f"  endpoints:",
        f"    web:",
        f"      exposure:",
        f"        include: health,info,metrics",
    ])
    return "\n".join(lines) + "\n"


def _generate_pom_xml(
    group_id: str,
    artifact_id: str,
    service_name: str,
    spring_boot_version: str,
    java_version: str,
    has_database: bool,
    has_messaging: bool,
    parent_artifact_id: str = "",
) -> str:
    deps = [
        "        <dependency>\n"
        "            <groupId>org.springframework.boot</groupId>\n"
        "            <artifactId>spring-boot-starter-web</artifactId>\n"
        "        </dependency>",
        "        <dependency>\n"
        "            <groupId>org.springframework.boot</groupId>\n"
        "            <artifactId>spring-boot-starter-actuator</artifactId>\n"
        "        </dependency>",
        "        <dependency>\n"
        "            <groupId>org.springframework.cloud</groupId>\n"
        "            <artifactId>spring-cloud-starter-netflix-eureka-client</artifactId>\n"
        "        </dependency>",
        "        <dependency>\n"
        "            <groupId>org.springframework.boot</groupId>\n"
        "            <artifactId>spring-boot-starter-validation</artifactId>\n"
        "        </dependency>",
    ]

    if has_database:
        deps.append(
            "        <dependency>\n"
            "            <groupId>org.springframework.boot</groupId>\n"
            "            <artifactId>spring-boot-starter-data-jpa</artifactId>\n"
            "        </dependency>"
        )
        deps.append(
            "        <dependency>\n"
            "            <groupId>org.postgresql</groupId>\n"
            "            <artifactId>postgresql</artifactId>\n"
            "            <scope>runtime</scope>\n"
            "        </dependency>"
        )

    if has_messaging:
        deps.append(
            "        <dependency>\n"
            "            <groupId>org.springframework.kafka</groupId>\n"
            "            <artifactId>spring-kafka</artifactId>\n"
            "        </dependency>"
        )

    deps.append(
        "        <dependency>\n"
        "            <groupId>org.projectlombok</groupId>\n"
        "            <artifactId>lombok</artifactId>\n"
        "            <optional>true</optional>\n"
        "        </dependency>"
    )
    deps.append(
        "        <dependency>\n"
        "            <groupId>org.springframework.boot</groupId>\n"
        "            <artifactId>spring-boot-starter-test</artifactId>\n"
        "            <scope>test</scope>\n"
        "        </dependency>"
    )

    deps_xml = "\n".join(deps)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>{spring_boot_version}</version>
        <relativePath/>
    </parent>

    <groupId>{group_id}</groupId>
    <artifactId>{artifact_id}</artifactId>
    <version>1.0.0-SNAPSHOT</version>
    <name>{service_name}</name>
    <description>{service_name} microservice</description>

    <properties>
        <java.version>{java_version}</java.version>
        <spring-cloud.version>2023.0.1</spring-cloud.version>
    </properties>

    <dependencies>
{deps_xml}
    </dependencies>

    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.springframework.cloud</groupId>
                <artifactId>spring-cloud-dependencies</artifactId>
                <version>${{spring-cloud.version}}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
                <configuration>
                    <excludes>
                        <exclude>
                            <groupId>org.projectlombok</groupId>
                            <artifactId>lombok</artifactId>
                        </exclude>
                    </excludes>
                </configuration>
            </plugin>
        </plugins>
    </build>
</project>
"""


def _generate_dockerfile(artifact_id: str, port: int) -> str:
    return f"""FROM eclipse-temurin:17-jre-alpine

WORKDIR /app

COPY target/{artifact_id}-1.0.0-SNAPSHOT.jar app.jar

EXPOSE {port}

ENV JAVA_OPTS="-Xms256m -Xmx512m"

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
"""


def _generate_docker_compose(
    services: List[MicroserviceProject],
    project_name: str,
) -> str:
    lines = [
        f"# Docker Compose for {project_name} Microservices",
        "version: '3.8'",
        "",
        "services:",
        "",
        "  # --- Service Discovery ---",
        "  eureka-server:",
        "    image: steeltoeoss/eureka-server:latest",
        "    container_name: eureka-server",
        "    ports:",
        "      - '8761:8761'",
        "    networks:",
        "      - microservices-net",
        "    healthcheck:",
        "      test: ['CMD', 'curl', '-f', 'http://localhost:8761/actuator/health']",
        "      interval: 10s",
        "      timeout: 5s",
        "      retries: 5",
        "",
        "  # --- API Gateway ---",
        "  api-gateway:",
        "    build: ./api-gateway",
        "    container_name: api-gateway",
        "    ports:",
        "      - '8080:8080'",
        "    environment:",
        "      - EUREKA_CLIENT_SERVICEURL_DEFAULTZONE=http://eureka-server:8761/eureka/",
        "    depends_on:",
        "      eureka-server:",
        "        condition: service_healthy",
        "    networks:",
        "      - microservices-net",
        "",
    ]

    for svc in services:
        db_name = svc.artifact_id.replace("-", "_") + "_db"
        lines.extend([
            f"  # --- {svc.name} ---",
            f"  {svc.artifact_id}:",
            f"    build: ./{svc.artifact_id}",
            f"    container_name: {svc.artifact_id}",
            f"    ports:",
            f"      - '{svc.port}:{svc.port}'",
            f"    environment:",
            f"      - SPRING_PROFILES_ACTIVE=docker",
            f"      - EUREKA_CLIENT_SERVICEURL_DEFAULTZONE=http://eureka-server:8761/eureka/",
        ])
        if svc.has_database:
            lines.extend([
                f"      - SPRING_DATASOURCE_URL=jdbc:postgresql://{svc.artifact_id}-db:5432/{db_name}",
                f"      - SPRING_DATASOURCE_USERNAME=postgres",
                f"      - SPRING_DATASOURCE_PASSWORD=postgres",
            ])
        lines.extend([
            f"    depends_on:",
            f"      eureka-server:",
            f"        condition: service_healthy",
        ])
        if svc.has_database:
            lines.extend([
                f"      {svc.artifact_id}-db:",
                f"        condition: service_healthy",
            ])
        lines.extend([
            f"    networks:",
            f"      - microservices-net",
            f"",
        ])

        if svc.has_database:
            lines.extend([
                f"  {svc.artifact_id}-db:",
                f"    image: postgres:16-alpine",
                f"    container_name: {svc.artifact_id}-db",
                f"    environment:",
                f"      POSTGRES_DB: {db_name}",
                f"      POSTGRES_USER: postgres",
                f"      POSTGRES_PASSWORD: postgres",
                f"    ports:",
                f"      - '{svc.port + 1000}:5432'",
                f"    volumes:",
                f"      - {svc.artifact_id}-data:/var/lib/postgresql/data",
                f"    networks:",
                f"      - microservices-net",
                f"    healthcheck:",
                f"      test: ['CMD-SHELL', 'pg_isready -U postgres']",
                f"      interval: 5s",
                f"      timeout: 3s",
                f"      retries: 5",
                f"",
            ])

    lines.extend([
        "networks:",
        "  microservices-net:",
        "    driver: bridge",
        "",
        "volumes:",
    ])
    for svc in services:
        if svc.has_database:
            lines.append(f"  {svc.artifact_id}-data:")
    lines.append("")
    return "\n".join(lines)


def _generate_api_gateway_pom(group_id: str, spring_boot_version: str, java_version: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>{spring_boot_version}</version>
        <relativePath/>
    </parent>

    <groupId>{group_id}</groupId>
    <artifactId>api-gateway</artifactId>
    <version>1.0.0-SNAPSHOT</version>
    <name>API Gateway</name>

    <properties>
        <java.version>{java_version}</java.version>
        <spring-cloud.version>2023.0.1</spring-cloud.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.cloud</groupId>
            <artifactId>spring-cloud-starter-gateway</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.cloud</groupId>
            <artifactId>spring-cloud-starter-netflix-eureka-client</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
        </dependency>
    </dependencies>

    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.springframework.cloud</groupId>
                <artifactId>spring-cloud-dependencies</artifactId>
                <version>${{spring-cloud.version}}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
"""


def _generate_gateway_application_yml(services: List[MicroserviceProject]) -> str:
    lines = [
        "spring:",
        "  application:",
        "    name: api-gateway",
        "  cloud:",
        "    gateway:",
        "      discovery:",
        "        locator:",
        "          enabled: true",
        "          lower-case-service-id: true",
        "      routes:",
    ]
    for svc in services:
        route_id = svc.artifact_id
        lines.extend([
            f"        - id: {route_id}",
            f"          uri: lb://{svc.artifact_id}",
            f"          predicates:",
            f"            - Path=/api/{svc.artifact_id.replace('-service', '')}/**",
            f"          filters:",
            f"            - StripPrefix=0",
        ])

    lines.extend([
        "",
        "server:",
        "  port: 8080",
        "",
        "eureka:",
        "  client:",
        "    service-url:",
        "      defaultZone: http://localhost:8761/eureka/",
    ])
    return "\n".join(lines) + "\n"


def _generate_gateway_app_java(group_id: str) -> str:
    base = group_id.replace("-", ".")
    return f"""package {base}.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

@SpringBootApplication
@EnableDiscoveryClient
public class ApiGatewayApplication {{

    public static void main(String[] args) {{
        SpringApplication.run(ApiGatewayApplication.class, args);
    }}
}}
"""


def _generate_parent_pom(
    group_id: str,
    project_name: str,
    modules: List[str],
    spring_boot_version: str,
    java_version: str,
) -> str:
    module_xml = "\n".join(f"        <module>{m}</module>" for m in modules)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>{group_id}</groupId>
    <artifactId>{_sanitize(project_name)}-parent</artifactId>
    <version>1.0.0-SNAPSHOT</version>
    <packaging>pom</packaging>
    <name>{project_name} - Microservices Parent</name>

    <modules>
{module_xml}
    </modules>

    <properties>
        <java.version>{java_version}</java.version>
        <spring-boot.version>{spring_boot_version}</spring-boot.version>
    </properties>
</project>
"""


def _generate_readme(
    project_name: str,
    services: List[MicroserviceProject],
) -> str:
    lines = [
        f"# {project_name} — Microservices",
        "",
        "This project was automatically decomposed from a monolithic application into independent microservices.",
        "",
        "## Architecture",
        "",
        "| Service | Port | Database | Description |",
        "|---------|------|----------|-------------|",
        "| api-gateway | 8080 | — | Spring Cloud Gateway with Eureka discovery |",
    ]
    for svc in services:
        db = "PostgreSQL" if svc.has_database else "—"
        lines.append(f"| {svc.name} | {svc.port} | {db} | {svc.description} |")

    lines.extend([
        "",
        "## Quick Start",
        "",
        "```bash",
        "# Start all services with Docker Compose",
        "docker-compose up --build",
        "",
        "# Or build individually",
        "cd <service-name>",
        "mvn clean package -DskipTests",
        "java -jar target/<service-name>-1.0.0-SNAPSHOT.jar",
        "```",
        "",
        "## Service Discovery",
        "",
        "Eureka dashboard: http://localhost:8761",
        "",
        "## API Gateway",
        "",
        "All services are accessible through the API Gateway at http://localhost:8080",
        "",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main conversion class
# ---------------------------------------------------------------------------

class MicroserviceConversionService:
    """Orchestrates full monolith-to-microservices conversion."""

    async def convert(
        self,
        source_path: str,
        readiness_report: Optional[MicroserviceReadinessReport] = None,
        output_path: Optional[str] = None,
    ) -> ConversionResult:
        import tempfile

        root = Path(source_path).resolve()
        if output_path:
            out = Path(output_path).resolve()
        else:
            # Create output OUTSIDE the clone dir so it survives moves/pushes
            work_dir = os.getenv("WORK_DIR", os.path.join(tempfile.gettempdir(), "migrations"))
            ms_output_root = os.path.join(work_dir, "microservices_output")
            os.makedirs(ms_output_root, exist_ok=True)
            out = Path(ms_output_root) / f"{root.name}-microservices"

        logger.info("Starting microservice conversion for %s → %s", root, out)

        # 1. Scan the project
        files = _scan_project(root)
        if not files:
            raise ValueError(f"No Java files found in {root}")

        base_package = _detect_base_package(files)
        build_tool = _detect_build_tool(root)
        java_version = _detect_java_version(root)
        spring_boot_version = _detect_spring_boot_version(root)
        group_id = base_package.rsplit(".", 1)[0] if "." in base_package else base_package
        project_name = root.name

        logger.info(
            "Project: %s | base_package=%s | build=%s | java=%s | spring_boot=%s | files=%d",
            project_name, base_package, build_tool, java_version, spring_boot_version, len(files),
        )

        # Log detected components
        controllers = [f for f in files if f.get("is_controller")]
        entities = [f for f in files if f.get("is_entity")]
        services_found = [f for f in files if f.get("is_service")]
        repos_found = [f for f in files if f.get("is_repository")]
        logger.info(
            "Components found: controllers=%d, entities=%d, services=%d, repositories=%d",
            len(controllers), len(entities), len(services_found), len(repos_found),
        )
        for c in controllers[:10]:
            logger.info("  Controller: %s.%s  routes=%s", c.get("package"), c.get("class_name"), c.get("route_paths"))

        # 2. Determine service boundaries (LLM first, heuristic fallback)
        llm_boundaries = await _llm_propose_boundaries(files, base_package)
        if llm_boundaries:
            boundaries = llm_boundaries
            logger.info("Using LLM-proposed boundaries: %s", [b["name"] for b in boundaries])
        else:
            # Try to use readiness report candidates if available
            if readiness_report and readiness_report.serviceCandidates:
                boundaries = [
                    {
                        "name": _sanitize(c.name),
                        "packages": c.packages,
                        "description": ", ".join(c.evidence[:2]) if c.evidence else c.name,
                        "needs_database": c.transactional,
                        "needs_messaging": bool(c.scaling_signals),
                    }
                    for c in readiness_report.serviceCandidates
                ]
            else:
                boundaries = _heuristic_boundaries(files, base_package)
            logger.info("Using heuristic boundaries: %s", [b["name"] for b in boundaries])

        if not boundaries:
            # Last-resort: create one service per controller
            logger.warning("No boundaries from LLM or heuristics — falling back to per-controller split")
            for f in files:
                if f.get("is_controller"):
                    ctrl_name = f["class_name"].replace("Controller", "").lower()
                    ctrl_pkg = f.get("package", "")
                    if not any(b["name"].startswith(ctrl_name) for b in boundaries):
                        boundaries.append({
                            "name": f"{_sanitize(ctrl_name)}-service",
                            "packages": [ctrl_pkg] if ctrl_pkg else [],
                            "description": f"Service for {f['class_name']}",
                            "needs_database": False,
                            "needs_messaging": False,
                        })
        if not boundaries:
            raise ValueError("Could not identify any microservice boundaries")

        # 3. Build MicroserviceProject objects
        ms_projects: List[MicroserviceProject] = []
        base_port = 8081
        for i, boundary in enumerate(boundaries):
            name = boundary["name"]
            artifact_id = _sanitize(name)
            if not artifact_id.endswith("-service"):
                artifact_id = f"{artifact_id}-service"
                name = f"{name}-service" if not name.endswith("-service") else name

            svc_package = f"{base_package}.{artifact_id.replace('-', '.')}" if boundary.get("packages") else f"{base_package}.{artifact_id.replace('-service', '').replace('-', '')}"

            ms_projects.append(MicroserviceProject(
                name=name,
                artifact_id=artifact_id,
                base_package=svc_package,
                packages=boundary.get("packages", []),
                has_database=boundary.get("needs_database", False),
                has_messaging=boundary.get("needs_messaging", False),
                port=base_port + i,
                description=boundary.get("description", name),
                class_tokens=boundary.get("class_tokens", []),
            ))

        # 4. Assign files to services
        unassigned_files: List[Dict[str, Any]] = []
        for f in files:
            pkg = f.get("package", "")
            cls_domain = _infer_class_domain(f.get("class_name", ""))
            assigned = False
            best_ms = None
            best_score = 0

            for ms in ms_projects:
                score = 0
                # Match by explicit package list
                for svc_pkg in ms.packages:
                    if pkg == svc_pkg or pkg.startswith(svc_pkg + "."):
                        score = max(score, 10)
                        break
                    if "." not in svc_pkg and pkg.endswith("." + svc_pkg):
                        score = max(score, 8)
                        break

                # Match by artifact domain name against package suffix
                domain_token = ms.artifact_id.replace("-service", "").replace("-", "")
                if domain_token and (pkg.endswith("." + domain_token) or f".{domain_token}." in pkg):
                    score = max(score, 7)

                # Match by class-name domain tokens (from heuristic boundaries)
                class_tokens = ms.class_tokens or []
                if cls_domain and cls_domain in class_tokens:
                    score = max(score, 9)  # strong signal

                # Match by class-name domain vs artifact domain
                if cls_domain and cls_domain == domain_token:
                    score = max(score, 9)

                if score > best_score:
                    best_score = score
                    best_ms = ms

            if best_ms and best_score > 0:
                assigned = True
                best_ms.source_files.append(f["abs_path"])
                if f.get("is_controller"):
                    best_ms.controllers.append(f["class_name"])
                if f.get("is_entity"):
                    best_ms.entities.append(f["class_name"])
                    best_ms.has_database = True
                if f.get("is_repository"):
                    best_ms.repositories.append(f["class_name"])
                if f.get("is_service"):
                    best_ms.services.append(f["class_name"])

            if not assigned and not f.get("is_main_app"):
                unassigned_files.append(f)

        # 4b. Store class_tokens from boundaries on MicroserviceProject for matching
        # (already handled above via boundary dict; also try matching unassigned by
        #  class-name similarity to existing service entities/controllers)
        retry_unassigned: List[Dict[str, Any]] = []
        for f in unassigned_files:
            cls_domain = _infer_class_domain(f.get("class_name", ""))
            matched = False
            for ms in ms_projects:
                # Check if any existing entity/controller/service in this ms shares
                # the same class-name domain
                existing_domains = set()
                for cname in ms.controllers + ms.entities + ms.services + ms.repositories:
                    existing_domains.add(_infer_class_domain(cname))
                if cls_domain and cls_domain in existing_domains:
                    ms.source_files.append(f["abs_path"])
                    if f.get("is_controller"):
                        ms.controllers.append(f["class_name"])
                    if f.get("is_entity"):
                        ms.entities.append(f["class_name"])
                        ms.has_database = True
                    if f.get("is_repository"):
                        ms.repositories.append(f["class_name"])
                    if f.get("is_service"):
                        ms.services.append(f["class_name"])
                    matched = True
                    break
            if not matched:
                retry_unassigned.append(f)
        unassigned_files = retry_unassigned

        # 4c. Post-assignment validation: remove services with zero source files
        ms_projects = [ms for ms in ms_projects if ms.source_files]

        # Log assignment results
        for ms in ms_projects:
            logger.info(
                "Service '%s': %d files, controllers=%s, entities=%s, repos=%s, services=%s",
                ms.name, len(ms.source_files), ms.controllers, ms.entities,
                ms.repositories, ms.services,
            )
        logger.info("Unassigned files: %d", len(unassigned_files))

        # 5. Generate output
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        all_modules = [ms.artifact_id for ms in ms_projects] + ["api-gateway"]

        # Parent POM
        parent_pom = _generate_parent_pom(group_id, project_name, all_modules, spring_boot_version, java_version)
        (out / "pom.xml").write_text(parent_pom, encoding="utf-8")

        # Generate each service
        for ms in ms_projects:
            svc_dir = out / ms.artifact_id
            svc_dir.mkdir(parents=True, exist_ok=True)

            # POM
            pom = _generate_pom_xml(
                group_id, ms.artifact_id, ms.name,
                spring_boot_version, java_version,
                ms.has_database, ms.has_messaging,
            )
            (svc_dir / "pom.xml").write_text(pom, encoding="utf-8")

            # Source directories
            pkg_path = ms.base_package.replace(".", "/")
            src_main = svc_dir / "src" / "main" / "java" / pkg_path
            src_main.mkdir(parents=True, exist_ok=True)
            src_resources = svc_dir / "src" / "main" / "resources"
            src_resources.mkdir(parents=True, exist_ok=True)
            src_test = svc_dir / "src" / "test" / "java" / pkg_path
            src_test.mkdir(parents=True, exist_ok=True)

            # Application class
            app_class_name = "".join(
                w.capitalize() for w in ms.artifact_id.replace("-", " ").split()
            ) + "Application"
            app_java = _generate_application_java(ms.base_package, app_class_name)
            (src_main / f"{app_class_name}.java").write_text(app_java, encoding="utf-8")

            # application.yml
            app_yml = _generate_application_yml(ms.artifact_id, ms.port, ms.has_database)
            (src_resources / "application.yml").write_text(app_yml, encoding="utf-8")

            # Dockerfile
            dockerfile = _generate_dockerfile(ms.artifact_id, ms.port)
            (svc_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")

            # Copy source files
            for src_file in ms.source_files:
                src = Path(src_file)
                if not src.exists():
                    continue
                # Determine target path preserving package structure
                content = _read_text(src)
                pkg_match = PACKAGE_RE.search(content)
                if pkg_match:
                    file_pkg = pkg_match.group(1).replace(".", "/")
                    dest = svc_dir / "src" / "main" / "java" / file_pkg / src.name
                else:
                    dest = src_main / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

            # Copy shared/model files into each service so it compiles
            for uf in unassigned_files:
                src = Path(uf["abs_path"])
                if not src.exists():
                    continue
                content = _read_text(src)
                pkg_match = PACKAGE_RE.search(content)
                if pkg_match:
                    file_pkg = pkg_match.group(1).replace(".", "/")
                    dest = svc_dir / "src" / "main" / "java" / file_pkg / src.name
                else:
                    dest = src_main / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.copy2(src, dest)

            # Also copy original resource files (application.properties, templates, static, etc.)
            original_resources = root / "src" / "main" / "resources"
            if original_resources.exists():
                for res_item in original_resources.rglob("*"):
                    if res_item.is_file():
                        rel = res_item.relative_to(original_resources)
                        dest = src_resources / rel
                        if not dest.exists():
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(res_item, dest)

            # Service README
            readme_lines = [
                f"# {ms.name}",
                "",
                ms.description,
                "",
                f"**Port:** {ms.port}",
                f"**Base package:** `{ms.base_package}`",
                "",
                "## Components",
                f"- Controllers: {', '.join(ms.controllers) or 'None'}",
                f"- Services: {', '.join(ms.services) or 'None'}",
                f"- Entities: {', '.join(ms.entities) or 'None'}",
                f"- Repositories: {', '.join(ms.repositories) or 'None'}",
                "",
                "## Build & Run",
                "```bash",
                "mvn clean package -DskipTests",
                f"java -jar target/{ms.artifact_id}-1.0.0-SNAPSHOT.jar",
                "```",
            ]
            (svc_dir / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")

        # API Gateway
        gw_dir = out / "api-gateway"
        gw_dir.mkdir(parents=True, exist_ok=True)
        gw_pom = _generate_api_gateway_pom(group_id, spring_boot_version, java_version)
        (gw_dir / "pom.xml").write_text(gw_pom, encoding="utf-8")

        gw_pkg_path = f"{group_id.replace('-', '.')}/gateway".replace(".", "/")
        gw_src = gw_dir / "src" / "main" / "java" / gw_pkg_path
        gw_src.mkdir(parents=True, exist_ok=True)
        gw_resources = gw_dir / "src" / "main" / "resources"
        gw_resources.mkdir(parents=True, exist_ok=True)

        gw_app = _generate_gateway_app_java(group_id)
        (gw_src / "ApiGatewayApplication.java").write_text(gw_app, encoding="utf-8")
        gw_yml = _generate_gateway_application_yml(ms_projects)
        (gw_resources / "application.yml").write_text(gw_yml, encoding="utf-8")
        gw_dockerfile = _generate_dockerfile("api-gateway", 8080)
        (gw_dir / "Dockerfile").write_text(gw_dockerfile, encoding="utf-8")

        # Shared / Common module (unassigned files)
        if unassigned_files:
            shared_dir = out / "shared-common"
            shared_dir.mkdir(parents=True, exist_ok=True)
            for f in unassigned_files:
                src = Path(f["abs_path"])
                if not src.exists():
                    continue
                content = _read_text(src)
                pkg_match = PACKAGE_RE.search(content)
                if pkg_match:
                    file_pkg = pkg_match.group(1).replace(".", "/")
                    dest = shared_dir / "src" / "main" / "java" / file_pkg / src.name
                else:
                    dest = shared_dir / "src" / "main" / "java" / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

            shared_readme = [
                "# Shared Common Library",
                "",
                "Contains shared utilities, DTOs, and cross-cutting concerns",
                "that were not assigned to a specific microservice.",
                "",
                f"Total files: {len(unassigned_files)}",
            ]
            (shared_dir / "README.md").write_text("\n".join(shared_readme), encoding="utf-8")

        # Docker Compose
        compose = _generate_docker_compose(ms_projects, project_name)
        compose_path = out / "docker-compose.yml"
        compose_path.write_text(compose, encoding="utf-8")

        # Root README
        readme = _generate_readme(project_name, ms_projects)
        (out / "README.md").write_text(readme, encoding="utf-8")

        # Summary
        service_details = []
        for ms in ms_projects:
            service_details.append({
                "name": ms.name,
                "artifact_id": ms.artifact_id,
                "port": ms.port,
                "package": ms.base_package,
                "controllers": ms.controllers,
                "entities": ms.entities,
                "source_files": len(ms.source_files),
                "has_database": ms.has_database,
                "has_messaging": ms.has_messaging,
                "description": ms.description,
            })

        summary = (
            f"Successfully decomposed '{project_name}' into {len(ms_projects)} microservices "
            f"+ API Gateway + {'shared library' if unassigned_files else 'no shared module'}. "
            f"Total source files distributed: {sum(len(ms.source_files) for ms in ms_projects)}, "
            f"unassigned to shared: {len(unassigned_files)}."
        )
        logger.info(summary)

        return ConversionResult(
            output_path=str(out),
            services_created=[ms.artifact_id for ms in ms_projects],
            shared_module="shared-common" if unassigned_files else "",
            docker_compose_path=str(compose_path),
            summary=summary,
            service_details=service_details,
        )


# Global instance
microservice_conversion_service = MicroserviceConversionService()
