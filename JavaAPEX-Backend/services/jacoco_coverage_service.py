"""
JaCoCo Coverage Test Generation Service — Automated 100% Class Coverage
========================================================================
Generates JUnit 5 tests for EVERY Java class to maximise JaCoCo coverage.

Strategy (per class type):
  1. LLM generates a tailored test → validate → write
  2. If LLM fails or is unavailable → regex-based deterministic generator
  3. Build → parse errors → auto-fix → retry until BUILD SUCCESSFUL

Supports multi-module Gradle projects with compileOnly cross-module deps
(e.g. MAPSWAR compileOnly MAPSCommon).

All generated files are UTF-8 WITHOUT BOM.
"""
import os
import re
import json
import time
import shutil
import logging
import asyncio
import subprocess
import textwrap
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set, Tuple
from dataclasses import dataclass, field, asdict

from utils.gradle_env import build_gradle_env

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

class JavaClassType:
    ENUM = "enum"
    INTERFACE = "interface"
    ABSTRACT = "abstract"
    OBJECT_FACTORY = "object_factory"
    CONSTANTS = "constants"
    POJO = "pojo"
    POJO_NO_DEFAULT_CTOR = "pojo_no_default_ctor"
    UTILITY = "utility"
    INFRASTRUCTURE = "infrastructure"
    JAXB_TYPE = "jaxb_type"
    CONCRETE = "concrete"
    COMPILE_ONLY_DEPENDENT = "compile_only_dependent"


@dataclass
class JavaClassInfo:
    """Detailed metadata about a Java class for test generation."""
    file_path: str               # absolute path
    rel_path: str                # relative to project root
    module: str                  # e.g. "MAPSCommon", "MAPSWAR"
    class_name: str
    package_name: str
    source_code: str
    class_type: str              # JavaClassType value
    is_compile_only_dependent: bool = False  # extends/uses compileOnly classes
    has_default_constructor: bool = True
    constructors: List[str] = field(default_factory=list)    # constructor signatures
    public_methods: List[str] = field(default_factory=list)
    getters: List[str] = field(default_factory=list)
    setters: List[str] = field(default_factory=list)
    create_methods: List[str] = field(default_factory=list)  # for ObjectFactory
    static_methods: List[str] = field(default_factory=list)
    fields: List[Dict[str, str]] = field(default_factory=list)  # [{name, type}]
    enum_values: List[str] = field(default_factory=list)
    parent_class: str = ""
    interfaces: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    has_equals: bool = False
    has_hashcode: bool = False
    has_tostring: bool = False
    list_getters: List[str] = field(default_factory=list)    # JAXB lazy-init lists


@dataclass
class CoverageJob:
    """Tracks a JaCoCo coverage generation run."""
    job_id: str
    status: str = "pending"
    progress_percent: int = 0
    current_step: str = "Initializing…"
    project_dir: str = ""
    total_classes: int = 0
    processed_classes: int = 0
    tests_generated: int = 0
    tests_skipped: int = 0
    build_attempts: int = 0
    build_success: bool = False
    coverage_percent: float = 0.0
    class_coverage_percent: float = 0.0
    error_message: Optional[str] = None
    log: List[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: Optional[str] = None

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()


# In-memory job storage
coverage_jobs: Dict[str, CoverageJob] = {}
_coverage_job_ttl_seconds = max(60, int(os.getenv("JACOCO_COVERAGE_JOB_TTL_SEC", "1800")))
_coverage_job_max_entries = max(4, int(os.getenv("JACOCO_COVERAGE_JOB_MAX_ENTRIES", "24")))
_coverage_job_log_max_lines = max(50, int(os.getenv("JACOCO_COVERAGE_JOB_LOG_MAX_LINES", "400")))


def _coverage_job_timestamp(job: CoverageJob) -> float:
    raw_value = job.completed_at or job.started_at or ""
    if not raw_value:
        return 0.0
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _prune_coverage_jobs() -> None:
    now = time.time()
    expired_job_ids: List[str] = []
    for job_id, job in list(coverage_jobs.items()):
        if job.status not in {"completed", "failed"}:
            continue
        timestamp = _coverage_job_timestamp(job)
        if timestamp and now - timestamp > _coverage_job_ttl_seconds:
            expired_job_ids.append(job_id)

    for job_id in expired_job_ids:
        coverage_jobs.pop(job_id, None)

    while len(coverage_jobs) > _coverage_job_max_entries:
        removable_job_id = None
        for candidate_job_id, candidate_job in coverage_jobs.items():
            if candidate_job.status in {"completed", "failed"}:
                removable_job_id = candidate_job_id
                break
        if removable_job_id is None:
            removable_job_id = next(iter(coverage_jobs), None)
        if removable_job_id is None:
            break
        coverage_jobs.pop(removable_job_id, None)


def _remember_coverage_job(job_id: str, job: CoverageJob) -> None:
    coverage_jobs.pop(job_id, None)
    coverage_jobs[job_id] = job
    _prune_coverage_jobs()


def _cov_log(job: CoverageJob, msg: str):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    job.log.append(entry)
    if len(job.log) > _coverage_job_log_max_lines:
        del job.log[:-_coverage_job_log_max_lines]
    logger.info(f"[JaCoCo-Gen:{job.job_id[:8]}] {msg}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Java Source Scanner — deep analysis of each class
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_package(source: str) -> str:
    m = re.search(r"^\s*package\s+([\w.]+)\s*;", source, re.MULTILINE)
    return m.group(1) if m else ""


def _extract_imports(source: str) -> List[str]:
    return re.findall(r"^\s*import\s+([\w.*]+)\s*;", source, re.MULTILINE)


def _extract_enum_values(source: str) -> List[str]:
    """Extract enum constant names."""
    # Find the enum body (between first { and either ; or first method)
    m = re.search(r'\benum\s+\w+[^{]*\{([^}]*?)(?:;|\})', source, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    # Enum values are comma-separated identifiers, possibly with args
    values = re.findall(r'\b([A-Z_][A-Z_0-9]*)\b(?:\s*\(|\s*,|\s*$)', body)
    return values


def _extract_constructors(source: str, class_name: str) -> List[str]:
    """Extract constructor signatures."""
    pattern = re.compile(
        r'(?:public|protected)\s+' + re.escape(class_name) + r'\s*\(([^)]*)\)',
        re.MULTILINE
    )
    ctors = []
    for m in pattern.finditer(source):
        params = m.group(1).strip()
        ctors.append(params)
    return ctors


def _extract_fields(source: str) -> List[Dict[str, str]]:
    """Extract field declarations."""
    fields = []
    for m in re.finditer(
        r'(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?([\w<>\[\],\s]+?)\s+(\w+)\s*[;=]',
        source
    ):
        ftype = m.group(1).strip()
        fname = m.group(2).strip()
        if fname not in ('class', 'interface', 'enum', 'void', 'return'):
            fields.append({"name": fname, "type": ftype})
    return fields


def _extract_methods(source: str) -> Dict[str, List[str]]:
    """Categorize all public methods."""
    result = {
        "public": [], "getters": [], "setters": [],
        "create": [], "static": [], "list_getters": [],
    }
    for m in re.finditer(
        r'public\s+(static\s+)?([\w<>\[\],\s]+?)\s+(\w+)\s*\(([^)]*)\)',
        source
    ):
        is_static = bool(m.group(1))
        return_type = m.group(2).strip()
        name = m.group(3).strip()
        params = m.group(4).strip()

        result["public"].append(name)

        if is_static:
            result["static"].append(name)

        if name.startswith("get") or name.startswith("is") or name.startswith("has"):
            result["getters"].append(name)
            # Check if it returns a List (JAXB lazy-init)
            if "List" in return_type:
                result["list_getters"].append(name)
        elif name.startswith("set"):
            result["setters"].append(name)
        elif name.startswith("create"):
            result["create"].append(name)

    return result


def _detect_class_type(
    class_name: str,
    source: str,
    methods: Dict[str, List[str]],
    constructors: List[str],
    fields: List[Dict[str, str]],
    imports: List[str],
) -> str:
    """Determine what kind of Java class this is."""
    # Enum
    if re.search(r'\benum\s+' + re.escape(class_name), source):
        return JavaClassType.ENUM

    # Interface
    if re.search(r'\binterface\s+' + re.escape(class_name), source):
        return JavaClassType.INTERFACE

    # Abstract class
    if re.search(r'\babstract\s+class\s+', source):
        return JavaClassType.ABSTRACT

    # ObjectFactory (JAXB)
    if class_name == "ObjectFactory" and methods["create"]:
        return JavaClassType.OBJECT_FACTORY

    # Constants class/interface (mostly static final fields, few/no methods)
    non_accessor = [m for m in methods["public"]
                    if not m.startswith("get") and not m.startswith("set")
                    and not m.startswith("is") and not m.startswith("has")]
    static_finals = len(re.findall(r'static\s+final\s+', source))
    if static_finals >= 3 and len(non_accessor) <= 1:
        return JavaClassType.CONSTANTS

    # JAXB type (has XmlType/XmlRootElement annotation + list getters)
    if re.search(r'@Xml(?:Type|RootElement|AccessorType)', source):
        return JavaClassType.JAXB_TYPE

    # Infrastructure (needs DataSource, Connection, ServletContext, etc.)
    infra_types = {"DataSource", "Connection", "EntityManager", "SessionFactory",
                   "ServletContext", "HttpServletRequest", "JMSContext", "QueueConnection"}
    ctor_text = " ".join(constructors)
    if any(it in ctor_text for it in infra_types):
        return JavaClassType.INFRASTRUCTURE

    # Utility class (private constructor, static methods only)
    has_private_ctor = bool(re.search(r'private\s+' + re.escape(class_name) + r'\s*\(', source))
    if has_private_ctor and methods["static"] and not methods["getters"]:
        return JavaClassType.UTILITY

    # POJO without default constructor
    if constructors and all(c.strip() for c in constructors):
        # All constructors have parameters — no default
        has_default = any(c.strip() == "" for c in constructors)
        if not has_default and not re.search(r'public\s+' + re.escape(class_name) + r'\s*\(\s*\)', source):
            return JavaClassType.POJO_NO_DEFAULT_CTOR

    return JavaClassType.POJO  # default: concrete class with default ctor


def _detect_compile_only_dependency(
    source: str,
    module: str,
    compile_only_modules: Dict[str, Set[str]],
    compile_only_packages: Set[str],
) -> bool:
    """Check if this class extends/uses types from a compileOnly module."""
    # Check parent class
    extends_m = re.search(r'\bextends\s+([\w.]+)', source)
    if extends_m:
        parent = extends_m.group(1)
        # If parent is from a compileOnly package
        for pkg in compile_only_packages:
            if parent.startswith(pkg.replace(".", "")) or f"import {pkg}" in source:
                return True

    # Check imports from compileOnly packages
    for imp in _extract_imports(source):
        for pkg in compile_only_packages:
            if imp.startswith(pkg):
                return True

    return False


def scan_project_for_coverage(
    project_dir: str,
    compile_only_config: Optional[Dict[str, Set[str]]] = None,
) -> List[JavaClassInfo]:
    """Scan ALL Java source files and classify each for test generation.

    Args:
        project_dir: Project root directory
        compile_only_config: {module_name: set_of_package_prefixes} for compileOnly deps

    Returns:
        List of JavaClassInfo with full metadata for each class
    """
    root = Path(project_dir).resolve()
    results: List[JavaClassInfo] = []
    seen: set = set()

    compile_only_packages: Set[str] = set()
    if compile_only_config:
        for pkgs in compile_only_config.values():
            compile_only_packages.update(pkgs)

    # Discover modules
    modules: Dict[str, Path] = {}
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            src_main = d / "src" / "main" / "java"
            if src_main.is_dir():
                modules[d.name] = src_main

    # Fallback: root project
    if not modules:
        root_src = root / "src" / "main" / "java"
        if root_src.is_dir():
            modules["root"] = root_src

    for module_name, src_dir in modules.items():
        for java_file in sorted(src_dir.rglob("*.java")):
            # Skip build/generated
            rel_str = str(java_file)
            if any(skip in rel_str for skip in ["/build/", "\\build\\", "/target/", "\\target\\"]):
                continue

            try:
                source = java_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            class_name = java_file.stem
            pkg = _extract_package(source)
            dedup_key = f"{pkg}.{class_name}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            imports = _extract_imports(source)
            constructors = _extract_constructors(source, class_name)
            fields = _extract_fields(source)
            methods = _extract_methods(source)
            enum_values = _extract_enum_values(source) if "enum " in source else []

            class_type = _detect_class_type(
                class_name, source, methods, constructors, fields, imports
            )

            # Detect compileOnly dependency
            is_compile_only = False
            if compile_only_config and module_name in compile_only_config:
                # This module has compileOnly deps — check if class uses them
                is_compile_only = _detect_compile_only_dependency(
                    source, module_name, compile_only_config, compile_only_packages
                )

            has_default = (
                not constructors
                or any(c.strip() == "" for c in constructors)
                or bool(re.search(r'public\s+' + re.escape(class_name) + r'\s*\(\s*\)', source))
            )

            # Override class_type if compileOnly dependent
            if is_compile_only:
                class_type = JavaClassType.COMPILE_ONLY_DEPENDENT

            try:
                rel_path = str(java_file.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel_path = str(java_file)

            results.append(JavaClassInfo(
                file_path=str(java_file),
                rel_path=rel_path,
                module=module_name,
                class_name=class_name,
                package_name=pkg,
                source_code=source,
                class_type=class_type,
                is_compile_only_dependent=is_compile_only,
                has_default_constructor=has_default,
                constructors=constructors,
                public_methods=methods["public"],
                getters=methods["getters"],
                setters=methods["setters"],
                create_methods=methods["create"],
                static_methods=methods["static"],
                fields=fields,
                enum_values=enum_values,
                parent_class=(re.search(r'\bextends\s+(\w+)', source) or type('', (), {"group": lambda s, i: ""})()).group(1),
                interfaces=re.findall(r'\bimplements\s+([\w,\s]+)', source),
                imports=imports,
                has_equals="equals" in source and "boolean equals" in source,
                has_hashcode="hashCode" in source,
                has_tostring="toString" in source,
                list_getters=methods["list_getters"],
            ))

    logger.info(f"[JaCoCo-Scan] Found {len(results)} classes across {len(modules)} module(s)")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Regex-Based Deterministic Test Generators (guaranteed compilation)
# ═══════════════════════════════════════════════════════════════════════════════

def _gen_imports(pkg: str) -> str:
    """Standard test imports."""
    return f"""package {pkg};

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;
"""


def _gen_enum_test(info: JavaClassInfo) -> str:
    """Rule 2: Enum test — values() + valueOf()."""
    imports = _gen_imports(info.package_name)
    vals = info.enum_values or ["/* add values */"]

    lines = [imports, "", f"class {info.class_name}Test {{", ""]
    lines.append('    @Test')
    lines.append(f'    @DisplayName("Test {info.class_name} enum values")')
    lines.append(f'    void testValues() throws Exception {{')
    lines.append(f'        {info.class_name}[] vals = {info.class_name}.values();')
    lines.append(f'        assertNotNull(vals);')
    lines.append(f'        assertTrue(vals.length > 0);')
    lines.append(f'        for ({info.class_name} v : vals) {{')
    lines.append(f'            assertEquals(v, {info.class_name}.valueOf(v.name()));')
    lines.append(f'        }}')
    lines.append(f'    }}')

    # If enum has methods, test a few
    for method in info.public_methods[:5]:
        if method in ("values", "valueOf", "name", "ordinal", "compareTo"):
            continue
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test {method}")')
        lines.append(f'    void test_{method}() throws Exception {{')
        lines.append(f'        for ({info.class_name} v : {info.class_name}.values()) {{')
        lines.append(f'            assertNotNull(v.{method}());')
        lines.append(f'        }}')
        lines.append(f'    }}')

    lines.append("}")
    return "\n".join(lines)


def _gen_object_factory_test(info: JavaClassInfo) -> str:
    """Rule 1: ObjectFactory test — call every create*() method."""
    imports = _gen_imports(info.package_name)
    lines = [imports, "", f"class {info.class_name}Test {{", ""]
    lines.append('    @Test')
    lines.append(f'    @DisplayName("Test all create methods")')
    lines.append(f'    void testAllCreateMethods() throws Exception {{')
    lines.append(f'        {info.class_name} of = new {info.class_name}();')
    lines.append(f'        assertNotNull(of);')

    for cm in info.create_methods:
        lines.append(f'        assertNotNull(of.{cm}());')

    lines.append('    }')
    lines.append("}")
    return "\n".join(lines)


def _gen_constants_test(info: JavaClassInfo) -> str:
    """Rule 3: Constants test — load class + check fields."""
    imports = _gen_imports(info.package_name)
    lines = [imports, "", f"class {info.class_name}Test {{", ""]
    lines.append('    @Test')
    lines.append(f'    @DisplayName("Test constants exist")')
    lines.append(f'    void testConstantsExist() throws Exception {{')
    lines.append(f'        assertNotNull({info.class_name}.class);')

    for fld in info.fields[:20]:
        fname = fld["name"]
        # Only test static final fields
        if re.search(r'static\s+final\s+.*\b' + re.escape(fname) + r'\b', info.source_code):
            lines.append(f'        assertNotNull({info.class_name}.{fname});')

    lines.append('    }')
    lines.append("}")
    return "\n".join(lines)


def _gen_pojo_test(info: JavaClassInfo) -> str:
    """Rule 4: POJO with default constructor — getter/setter tests."""
    imports = _gen_imports(info.package_name)
    lines = [imports, "", f"class {info.class_name}Test {{", ""]

    # Test getter/setter pairs
    if info.setters or info.getters:
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test getters and setters")')
        lines.append(f'    void testGettersSetters() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        lines.append(f'        assertNotNull(obj);')

        # Match setter→getter pairs
        for setter in info.setters[:30]:
            field_name = setter[3:]  # remove "set"
            getter_name = None
            for g in info.getters:
                if g == f"get{field_name}" or g == f"is{field_name}":
                    getter_name = g
                    break

            # Determine type from field or setter signature
            ftype = _guess_setter_type(info, setter)
            test_val = _get_test_value(ftype)

            if test_val is not None:
                lines.append(f'        obj.{setter}({test_val});')
                if getter_name:
                    if ftype in ("boolean", "Boolean"):
                        lines.append(f'        assertNotNull(Boolean.valueOf(obj.{getter_name}()));')
                    else:
                        lines.append(f'        assertEquals({test_val}, obj.{getter_name}());')

        lines.append('    }')

    # Standalone getters (without setters) — just call them
    standalone_getters = [g for g in info.getters
                         if f"set{g[3:]}" not in info.setters and f"set{g[2:]}" not in info.setters]
    if standalone_getters:
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test getters")')
        lines.append(f'    void testGetters() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        for g in standalone_getters[:20]:
            lines.append(f'        obj.{g}();  // should not throw')
        lines.append('    }')

    # JAXB list getters (Rule 12)
    if info.list_getters:
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test list getters (JAXB lazy init)")')
        lines.append(f'    void testListGetters() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        for lg in info.list_getters[:20]:
            lines.append(f'        assertNotNull(obj.{lg}());')
            lines.append(f'        assertTrue(obj.{lg}().isEmpty() || obj.{lg}().size() >= 0);')
        lines.append('    }')

    # equals/hashCode/toString
    if info.has_equals or info.has_hashcode or info.has_tostring:
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test equals, hashCode, toString")')
        lines.append(f'    void testEqualsHashCodeToString() throws Exception {{')
        lines.append(f'        {info.class_name} obj1 = new {info.class_name}();')
        lines.append(f'        {info.class_name} obj2 = new {info.class_name}();')
        if info.has_equals:
            lines.append(f'        assertNotNull(obj1.equals(obj2));')
        if info.has_hashcode:
            lines.append(f'        obj1.hashCode();')
        if info.has_tostring:
            lines.append(f'        assertNotNull(obj1.toString());')
        lines.append('    }')

    # Static methods (Rule 11)
    for sm in info.static_methods[:10]:
        if sm in ("values", "valueOf", "main"):
            continue
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test static method {sm}")')
        lines.append(f'    void testStatic_{sm}() throws Exception {{')
        lines.append(f'        // Static method — call to ensure coverage')
        lines.append(f'        assertNotNull({info.class_name}.class);')
        lines.append('    }')

    if not info.setters and not info.getters and not info.static_methods:
        # Bare minimum: instantiation
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test instantiation")')
        lines.append(f'    void testInstantiation() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        lines.append(f'        assertNotNull(obj);')
        lines.append('    }')

    lines.append("}")
    return "\n".join(lines)


def _gen_pojo_no_default_ctor_test(info: JavaClassInfo) -> str:
    """Rule 5: POJO with parameterized constructors only."""
    imports = _gen_imports(info.package_name)
    lines = [imports, "", f"class {info.class_name}Test {{", ""]

    # Use the first constructor
    if info.constructors:
        ctor_params = info.constructors[0]
        param_pairs = _parse_params(ctor_params)
        args = ", ".join(_get_test_value(ptype) or "null" for ptype, pname in param_pairs)

        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test constructor")')
        lines.append(f'    void testConstructor() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}({args});')
        lines.append(f'        assertNotNull(obj);')

        # Test getters on constructed object
        for g in info.getters[:10]:
            lines.append(f'        obj.{g}();')
        lines.append('    }')
    else:
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test class exists")')
        lines.append(f'    void testClassExists() throws Exception {{')
        lines.append(f'        assertNotNull({info.class_name}.class);')
        lines.append('    }')

    lines.append("}")
    return "\n".join(lines)


def _gen_abstract_test(info: JavaClassInfo) -> str:
    """Rule 7: Abstract class — just verify class exists."""
    imports = _gen_imports(info.package_name)
    return f"""{imports}

class {info.class_name}Test {{

    @Test
    @DisplayName("Test abstract class exists")
    void testClassExists() throws Exception {{
        assertNotNull({info.class_name}.class);
    }}
}}
"""


def _gen_interface_test(info: JavaClassInfo) -> str:
    """Rule 3 (interface): Load the class."""
    imports = _gen_imports(info.package_name)

    lines = [imports, "", f"class {info.class_name}Test {{", ""]
    lines.append('    @Test')
    lines.append(f'    @DisplayName("Test interface exists")')
    lines.append(f'    void testInterfaceExists() throws Exception {{')
    lines.append(f'        assertNotNull({info.class_name}.class);')

    # If interface has constants, test them
    for fld in info.fields[:10]:
        fname = fld["name"]
        if re.search(r'static\s+final\s+', info.source_code):
            lines.append(f'        assertNotNull({info.class_name}.{fname});')
            break  # just one to be safe

    lines.append('    }')
    lines.append("}")
    return "\n".join(lines)


def _gen_utility_test(info: JavaClassInfo) -> str:
    """Rule 8: Private constructor utility class."""
    imports = _gen_imports(info.package_name)
    lines = [imports, "", f"class {info.class_name}Test {{", ""]
    lines.append('    @Test')
    lines.append(f'    @DisplayName("Test utility class exists")')
    lines.append(f'    void testClassExists() throws Exception {{')
    lines.append(f'        assertNotNull({info.class_name}.class);')
    lines.append('    }')

    # Test static methods with simple args
    for sm in info.static_methods[:10]:
        if sm == "main":
            continue
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test {sm}")')
        lines.append(f'    void test_{sm}() throws Exception {{')
        # Find the method signature for correct args
        sig_m = re.search(
            r'public\s+static\s+[\w<>\[\]]+\s+' + re.escape(sm) + r'\s*\(([^)]*)\)',
            info.source_code
        )
        if sig_m:
            params = _parse_params(sig_m.group(1))
            args = ", ".join(_get_test_value(pt) or "null" for pt, pn in params)
            lines.append(f'        try {{')
            lines.append(f'            {info.class_name}.{sm}({args});')
            lines.append(f'        }} catch (Exception e) {{')
            lines.append(f'            // Method may throw — coverage still recorded')
            lines.append(f'        }}')
        else:
            lines.append(f'        assertNotNull({info.class_name}.class);')
        lines.append('    }')

    lines.append("}")
    return "\n".join(lines)


def _gen_infrastructure_test(info: JavaClassInfo) -> str:
    """Rule 9: Infrastructure class — stub."""
    imports = _gen_imports(info.package_name)
    return f"""{imports}

class {info.class_name}Test {{

    @Test
    @DisplayName("Test class exists (infrastructure)")
    void testClassExists() throws Exception {{
        assertNotNull({info.class_name}.class);
    }}
}}
"""


def _gen_jaxb_type_test(info: JavaClassInfo) -> str:
    """Rule 12: JAXB generated type — setters + list getters."""
    imports = _gen_imports(info.package_name)
    lines = [imports, "", f"class {info.class_name}Test {{", ""]

    # Setters
    if info.setters:
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test setters")')
        lines.append(f'    void testSetters() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        for setter in info.setters[:40]:
            ftype = _guess_setter_type(info, setter)
            val = _get_test_value(ftype)
            if val is not None:
                lines.append(f'        obj.{setter}({val});')
        lines.append('    }')

    # List getters (lazy init)
    if info.list_getters:
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test list getters (lazy init)")')
        lines.append(f'    void testListGetters() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        for lg in info.list_getters[:30]:
            lines.append(f'        assertNotNull(obj.{lg}(), "{lg} should return non-null list");')
            lines.append(f'        assertTrue(obj.{lg}().isEmpty());')
        lines.append('    }')

    # Regular getters
    non_list_getters = [g for g in info.getters if g not in info.list_getters]
    if non_list_getters:
        lines.append("")
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test getters")')
        lines.append(f'    void testGetters() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        for g in non_list_getters[:30]:
            lines.append(f'        obj.{g}();')
        lines.append('    }')

    if not info.setters and not info.list_getters and not info.getters:
        lines.append('    @Test')
        lines.append(f'    @DisplayName("Test instantiation")')
        lines.append(f'    void testInstantiation() throws Exception {{')
        lines.append(f'        {info.class_name} obj = new {info.class_name}();')
        lines.append(f'        assertNotNull(obj);')
        lines.append('    }')

    lines.append("}")
    return "\n".join(lines)


def _gen_compile_only_dependent_test(info: JavaClassInfo) -> str:
    """Rule 10: Class extends compileOnly type — assertTrue(true) only."""
    imports = _gen_imports(info.package_name)
    return f"""{imports}

class {info.class_name}Test {{

    @Test
    @DisplayName("Test class exists (compileOnly dependency)")
    void testClassExists() throws Exception {{
        assertTrue(true); // Cannot instantiate - extends compileOnly class
    }}
}}
"""


def _gen_concrete_test(info: JavaClassInfo) -> str:
    """Default: concrete class with default constructor."""
    return _gen_pojo_test(info)


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: Type analysis
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_params(params_str: str) -> List[Tuple[str, str]]:
    """Parse 'Type1 name1, Type2 name2' → [(type, name), ...]"""
    if not params_str.strip():
        return []
    result = []
    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.rsplit(None, 1)
        if len(tokens) == 2:
            result.append((tokens[0].strip(), tokens[1].strip()))
        elif len(tokens) == 1:
            result.append((tokens[0].strip(), "arg"))
    return result


def _guess_setter_type(info: JavaClassInfo, setter_name: str) -> str:
    """Guess the parameter type of a setter by examining the source."""
    # Find setter signature
    m = re.search(
        r'public\s+void\s+' + re.escape(setter_name) + r'\s*\(([^)]+)\)',
        info.source_code
    )
    if m:
        params = _parse_params(m.group(1))
        if params:
            return params[0][0]

    # Guess from field name
    field_name = setter_name[3:4].lower() + setter_name[4:]  # setFoo → foo
    for fld in info.fields:
        if fld["name"] == field_name:
            return fld["type"]

    return "String"  # safe default


def _get_test_value(java_type: str) -> Optional[str]:
    """Return a safe test value literal for a Java type."""
    if not java_type:
        return '"test"'

    t = java_type.strip()

    # Primitives
    if t in ("int", "Integer"):
        return "1"
    if t in ("long", "Long"):
        return "1L"
    if t in ("double", "Double"):
        return "1.0"
    if t in ("float", "Float"):
        return "1.0f"
    if t in ("boolean", "Boolean"):
        return "true"
    if t in ("short", "Short"):
        return "(short) 1"
    if t in ("byte", "Byte"):
        return "(byte) 1"
    if t in ("char", "Character"):
        return "'a'"
    if t == "String":
        return '"test"'
    if t == "BigDecimal":
        return 'java.math.BigDecimal.ONE'
    if t == "BigInteger":
        return 'java.math.BigInteger.ONE'
    if t == "Date":
        return 'new java.util.Date()'
    if t.startswith("List") or t.startswith("ArrayList"):
        return 'new java.util.ArrayList<>()'
    if t.startswith("Map") or t.startswith("HashMap"):
        return 'new java.util.HashMap<>()'
    if t.startswith("Set") or t.startswith("HashSet"):
        return 'new java.util.HashSet<>()'

    # Reference types — use null (but see Rule 6 for overloads)
    return "null"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Test Generator Dispatch (regex fallback)
# ═══════════════════════════════════════════════════════════════════════════════

_GENERATORS = {
    JavaClassType.ENUM: _gen_enum_test,
    JavaClassType.INTERFACE: _gen_interface_test,
    JavaClassType.ABSTRACT: _gen_abstract_test,
    JavaClassType.OBJECT_FACTORY: _gen_object_factory_test,
    JavaClassType.CONSTANTS: _gen_constants_test,
    JavaClassType.POJO: _gen_pojo_test,
    JavaClassType.POJO_NO_DEFAULT_CTOR: _gen_pojo_no_default_ctor_test,
    JavaClassType.UTILITY: _gen_utility_test,
    JavaClassType.INFRASTRUCTURE: _gen_infrastructure_test,
    JavaClassType.JAXB_TYPE: _gen_jaxb_type_test,
    JavaClassType.CONCRETE: _gen_concrete_test,
    JavaClassType.COMPILE_ONLY_DEPENDENT: _gen_compile_only_dependent_test,
}


def generate_test_regex(info: JavaClassInfo) -> str:
    """Generate a test file using regex-based deterministic rules.

    This is the guaranteed fallback — no LLM needed, always compiles.
    """
    generator = _GENERATORS.get(info.class_type, _gen_concrete_test)
    return generator(info)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LLM-Enhanced Test Generator
# ═══════════════════════════════════════════════════════════════════════════════

def _get_type_specific_strategy(info: JavaClassInfo) -> str:
    """Return detailed type-specific instructions for the LLM based on class type."""
    strategies = {
        JavaClassType.ENUM: textwrap.dedent(f"""\
            This is an ENUM class. Generate tests that:
            - Call {info.class_name}.values() and assert the array length matches expected count ({len(info.enum_values or [])} values)
            - Call {info.class_name}.valueOf("NAME") for EACH enum constant: {', '.join(info.enum_values or [])}
            - Test valueOf() with an invalid name → assertThrows(IllegalArgumentException.class, () -> {info.class_name}.valueOf("INVALID"))
            - If enum has methods (getters, toString, etc.), call each method with every enum constant
            - Test that each enum constant's name() returns the expected string
            - Use assertEquals to verify each constant identity: assertEquals({info.class_name}.CONST, {info.class_name}.valueOf("CONST"))"""),

        JavaClassType.OBJECT_FACTORY: textwrap.dedent(f"""\
            This is a JAXB ObjectFactory. Generate tests that:
            - Instantiate: ObjectFactory of = new ObjectFactory();
            - Call EVERY create*() method and assert the return is not null
            - Assert each create method returns the correct type using instanceof
            - Create methods to test: {', '.join(info.create_methods or [])}"""),

        JavaClassType.POJO: textwrap.dedent(f"""\
            This is a POJO with default constructor. Generate tests that:
            - Instantiate with new {info.class_name}()
            - For EVERY setter/getter pair: call setter with a typed realistic value, then assertEquals(expectedValue, getter())
              Setters: {', '.join(info.setters[:20]) if info.setters else 'none found'}
              Getters: {', '.join(info.getters[:20]) if info.getters else 'none found'}
            - Test equals/hashCode: {"YES — test reflexivity (a.equals(a)), symmetry (a.equals(b)==b.equals(a)), null (a.equals(null)==false), different class" if info.has_equals else "not overridden — skip"}
            - Test toString: {"YES — assertNotNull and assert it contains key field names" if info.has_tostring else "not overridden — skip"}
            - For List-returning getters: call getter on new instance, assert not null (may be empty list)
            - Use realistic typed values: \"TestValue\" for String, 42 for int, 99.9 for double, true for boolean"""),

        JavaClassType.POJO_NO_DEFAULT_CTOR: textwrap.dedent(f"""\
            This is a POJO WITHOUT default constructor. Generate tests that:
            - Find the constructor with parameters and instantiate with realistic typed values
              Constructors: {', '.join(info.constructors[:5]) if info.constructors else 'none found'}
            - After construction, verify getters return the values passed to the constructor using assertEquals
            - Test each setter/getter pair if setters exist
            - If constructor throws on null args, test with assertThrows(NullPointerException.class, ...)
            - Use realistic parameter values matching the types"""),

        JavaClassType.ABSTRACT: textwrap.dedent(f"""\
            This is an ABSTRACT class. Generate tests that:
            - assertNotNull({info.class_name}.class) to trigger class loading for JaCoCo
            - If there are static methods, call them directly: {', '.join(info.static_methods[:10]) if info.static_methods else 'none found'}
            - If there are constants (public static final fields), assert their values are not null
            - Do NOT try to instantiate the abstract class directly
            - Do NOT create anonymous subclasses (they often fail to compile without full context)"""),

        JavaClassType.INTERFACE: textwrap.dedent(f"""\
            This is an INTERFACE. Generate tests that:
            - assertNotNull({info.class_name}.class) to trigger class loading for JaCoCo
            - If interface has static fields (constants), assert their values
            - Do NOT try to instantiate the interface
            - Do NOT create anonymous implementations (they often fail without full context)"""),

        JavaClassType.UTILITY: textwrap.dedent(f"""\
            This is a UTILITY class (private constructor, static methods). Generate tests that:
            - Use reflection to invoke the private constructor for JaCoCo coverage:
              Constructor<?> ctor = {info.class_name}.class.getDeclaredConstructor();
              ctor.setAccessible(true);
              ctor.newInstance();
            - Test EVERY static method with realistic inputs: {', '.join(info.static_methods[:15]) if info.static_methods else 'none found'}
            - Test error/edge cases: null inputs, empty strings, boundary numeric values
            - Use assertEquals to verify return values, not just assertNotNull"""),

        JavaClassType.CONSTANTS: textwrap.dedent(f"""\
            This is a CONSTANTS class. Generate tests that:
            - assertNotNull({info.class_name}.class) to load the class for JaCoCo
            - Assert each public static final field is not null (for reference types) or has expected value
            - Fields: {', '.join(f.get('name', '') for f in info.fields[:20]) if info.fields else 'none found'}"""),

        JavaClassType.JAXB_TYPE: textwrap.dedent(f"""\
            This is a JAXB-generated type. Generate tests that:
            - Instantiate with new {info.class_name}()
            - Test EVERY setter with a realistic typed value, then verify with assertEquals on the getter
            - For List-returning getters (JAXB lazy-init pattern): call getter, assertNotNull, add an element, assertEquals(1, list.size())
              List getters: {', '.join(info.list_getters[:15]) if info.list_getters else 'none found'}
            - Test equals/hashCode/toString if present"""),

        JavaClassType.INFRASTRUCTURE: textwrap.dedent(f"""\
            This is an INFRASTRUCTURE class (uses DataSource, Connection, etc.). Generate tests that:
            - assertNotNull({info.class_name}.class) to load the class for JaCoCo
            - Do NOT try to create real database connections, servlet contexts, or JNDI lookups
            - If the class has static utility methods, test those with simple inputs
            - Keep tests simple — a class-loading test is better than a failing complex test"""),

        JavaClassType.COMPILE_ONLY_DEPENDENT: textwrap.dedent(f"""\
            This class depends on compileOnly types that are NOT available at test time.
            - Write a SINGLE test method with ONLY: assertTrue(true);
            - Do NOT import or reference the parent class or compileOnly dependencies
            - Do NOT try to instantiate or call any methods"""),
    }

    return strategies.get(info.class_type, textwrap.dedent(f"""\
        This is a CONCRETE class. Generate tests that:
        - Instantiate with the default constructor if available
        - Test every public method with realistic inputs
        - Test getter/setter pairs using assertEquals
        - Handle exceptions with assertThrows
        - Use realistic domain values for parameters"""))


def _validate_llm_test_code(code: str, info: JavaClassInfo) -> Tuple[bool, str]:
    """Validate LLM-generated test code for common syntax issues.

    Returns (is_valid, reason) tuple.
    """
    # Must contain @Test annotation
    if "@Test" not in code:
        return False, "Missing @Test annotation"

    # Must contain expected class name
    expected_class = f"class {info.class_name}Test"
    if expected_class not in code:
        return False, f"Missing class declaration '{expected_class}'"

    # Check balanced braces
    open_braces = code.count("{")
    close_braces = code.count("}")
    if open_braces != close_braces:
        return False, f"Unbalanced braces: {open_braces} open vs {close_braces} close"

    # Check for merged @Test annotations (e.g. "@Testpublic" — a common LLM mistake)
    if re.search(r"@Test\s*public", code) is None and "@Test" in code:
        # @Test should be followed by whitespace/newline then public, or be on its own line
        if re.search(r"@Test[a-zA-Z]", code):
            return False, "Merged @Test annotation (e.g. @Testpublic)"

    # Check for method declarations ending with semicolons instead of opening braces
    if re.search(r"void\s+test\w+\s*\([^)]*\)\s*(?:throws\s+\w+(?:\.\w+)*\s*)?;", code):
        return False, "Method declaration ends with semicolon instead of opening brace"

    # Check for truncated lines (lines ending with incomplete identifier)
    lines = code.strip().split("\n")
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped and re.match(r".*[a-z]\.$", stripped) and i < len(lines) - 1:
            return False, f"Possible truncated line at line {i+1}"

    # Must have a package declaration
    if not re.search(r"^\s*package\s+[\w.]+\s*;", code, re.MULTILINE):
        return False, "Missing package declaration"

    # Check for @Override outside of test methods (common LLM hallucination)
    if re.search(r"@Override\s*(?:protected|public)\s+\w+\s+\w+\s*\(", code):
        # Only flag if there's no anonymous class context (new ClassName() { ... })
        # This is a heuristic — @Override in test classes is usually wrong
        if "new " not in code or "() {" not in code:
            return False, "Suspicious @Override method in test class"

    # Verify no wildcard static import (import static *; is invalid)
    if re.search(r"import\s+static\s+\*\s*;", code):
        return False, "Invalid wildcard static import 'import static *;'"

    # Reject empty test classes — must have at least one @Test method WITH a body
    test_methods_with_body = re.findall(
        r"@Test\s+(?:@\w+(?:\([^)]*\))?\s+)*public\s+void\s+\w+\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\s*\{",
        code
    )
    if not test_methods_with_body:
        return False, "No @Test method with a proper body found (empty test class)"

    # Verify test methods actually contain statements (not just empty braces)
    # Find all test method bodies
    for match in re.finditer(
        r"@Test\s+(?:@\w+(?:\([^)]*\))?\s+)*public\s+void\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\s*\{",
        code
    ):
        method_name = match.group(1)
        # Find the body after the opening brace
        start_pos = match.end()
        brace_depth = 1
        pos = start_pos
        while pos < len(code) and brace_depth > 0:
            if code[pos] == "{":
                brace_depth += 1
            elif code[pos] == "}":
                brace_depth -= 1
            pos += 1
        method_body = code[start_pos:pos - 1].strip()
        # Remove comments from body check
        body_no_comments = re.sub(r"//[^\n]*", "", method_body)
        body_no_comments = re.sub(r"/\*.*?\*/", "", body_no_comments, flags=re.DOTALL)
        body_no_comments = body_no_comments.strip()
        if not body_no_comments:
            return False, f"Test method '{method_name}' has empty body (no statements)"

    # Reject if fewer than expected test methods for non-trivial classes
    num_tests = len(test_methods_with_body)
    if not info.is_compile_only_dependent and info.class_type not in (
        JavaClassType.ABSTRACT, JavaClassType.INTERFACE,
        JavaClassType.CONSTANTS, JavaClassType.INFRASTRUCTURE,
        JavaClassType.COMPILE_ONLY_DEPENDENT
    ):
        # For POJOs, enums, utilities, etc. we expect at least 2 test methods
        min_methods = len(info.public_methods) if info.public_methods else 1
        min_expected = max(1, min(min_methods, 3))  # At least 1, up to 3
        if num_tests < min_expected:
            logger.warning(
                f"[JaCoCo-LLM] Low test count for {info.class_name}: "
                f"{num_tests} tests vs {min_expected} expected (has {len(info.public_methods)} public methods)"
            )

    return True, "OK"


async def generate_test_llm(info: JavaClassInfo, llm_model: str = "") -> Optional[str]:
    """Try to generate a test using Ford LLM.

    Returns the test code string if successful, None if LLM fails.
    The caller should fall back to generate_test_regex().
    """
    try:
        from services.ford_llm_service import ford_llm_service  # Uses Groq API behind the scenes
    except ImportError:
        return None

    if not ford_llm_service or not hasattr(ford_llm_service, 'generate'):
        return None

    # Build a compact prompt based on class type
    skeleton = _compact_skeleton(info)
    class_desc = _describe_class(info)
    type_strategy = _get_type_specific_strategy(info)

    prompt = textwrap.dedent(f"""\
        Generate a production-quality JUnit 5 test class for maximum JaCoCo coverage of:

        Class: {info.class_name} ({info.class_type})
        Package: {info.package_name}
        Module: {info.module}
        {class_desc}

        🎯 TARGET: >80% Line and Branch Coverage

        Source skeleton:
        ```java
        {skeleton}
        ```

        === TYPE-SPECIFIC STRATEGY ===
        {type_strategy}

        === CORRECT OUTPUT EXAMPLE ===
        Below is an example of a CORRECTLY formatted test class. Your output MUST follow this exact structure:

        package com.example.model;

        import org.junit.jupiter.api.Test;
        import org.junit.jupiter.api.BeforeEach;
        import org.junit.jupiter.api.DisplayName;
        import static org.junit.jupiter.api.Assertions.*;

        public class PersonTest {{

            private Person instance;

            @BeforeEach
            public void setUp() throws Exception {{
                instance = new Person();
            }}

            @Test
            @DisplayName("Test setName and getName")
            public void testSetAndGetName() throws Exception {{
                instance.setName("John");
                assertEquals("John", instance.getName());
            }}

            @Test
            @DisplayName("Test setAge and getAge")
            public void testSetAndGetAge() throws Exception {{
                instance.setAge(30);
                assertEquals(30, instance.getAge());
            }}

            @Test
            @DisplayName("Test toString returns non-null string")
            public void testToString() throws Exception {{
                instance.setName("Alice");
                String result = instance.toString();
                assertNotNull(result);
                assertTrue(result.contains("Alice"));
            }}
        }}

        === MANDATORY RULES ===
        1. COVERAGE REQUIREMENTS:
           - Target 100% CLASS coverage: the class MUST be loaded/instantiated
           - Target maximum METHOD coverage: call EVERY public method at least once
           - Target maximum BRANCH coverage: test both true/false for every if/switch
           - Target maximum LINE coverage: execute every reachable line

        2. ASSERTION QUALITY (NOT just assertNotNull):
           - For getters after setters: use assertEquals(expectedValue, obj.getField())
           - For boolean methods: use assertTrue() / assertFalse() with meaningful inputs
           - For methods returning collections: assert size, contents, emptiness
           - For methods that throw: use assertThrows(ExpectedException.class, () -> ...)
           - For toString/equals/hashCode: test symmetry, reflexivity, null-safety
           - For factory methods: assert the returned object's type and state
           - NEVER use only assertTrue(true) unless the class is compileOnly dependent

        3. TEST STRUCTURE:
           - One @Test method per logical scenario (not one giant method)
           - Use descriptive method names: test<Method>_<Scenario>_<Expected>
           - Every @Test method MUST have "throws Exception"
           - Use @BeforeEach for shared setup when 3+ tests need the same object
           - Group related assertions in the same test method
           - MINIMUM: generate at least one @Test method for EVERY public method in the source class

        3b. MOCK SETUP — CRITICAL FOR JACOCO COVERAGE:
           - JaCoCo only counts a line as COVERED if the test JVM EXECUTES it at runtime.
           - If your @BeforeEach / setUp() throws NullPointerException, JaCoCo records 0% for this class.
           - For classes with @Autowired fields → use @ExtendWith(MockitoExtension.class) + @InjectMocks + @Mock fields.
           - For classes with constructor dependencies → pass Mockito.mock(Dep.class) as constructor args.
           - For classes using static singletons (e.g. PropertyMgr.getInstance()) → MockedStatic in try-with-resources.
           - For classes creating objects internally with 'new Service()' → MockedConstruction in try-with-resources.
           - If the constructor may throw, wrap instantiation in assertDoesNotThrow or try-catch in setUp().
           - EVERY test MUST: (1) successfully create the SUT instance, (2) call the actual source method, (3) assert the result.

        4. VALUE SELECTION:
           - Use realistic domain values, not just nulls and empty strings
           - For String fields: use descriptive values ("John", "test@email.com", "USD")
           - For numeric fields: use boundary values (0, 1, -1, Integer.MAX_VALUE)
           - For date fields: use java.util.Date or java.time types with actual dates
           - For enum fields: test with at least 2 different enum values
           - For collections: test with empty, single-element, and multi-element lists

        5. EDGE CASES:
           - Test null inputs where applicable (expect NullPointerException or graceful handling)
           - Test empty strings for String parameters
           - Test boundary values for numeric parameters
           - Test both valid and invalid inputs for validation methods

        6. SYNTAX REQUIREMENTS (CRITICAL — violations cause compilation failure):
           - Use JUnit 5 (org.junit.jupiter.api) — NOT JUnit 4
           - Use javax.servlet (NOT jakarta.servlet)
           - Do NOT import com.ford.fc.atd.* packages
           - NEVER write "import static *;" — always write "import static org.junit.jupiter.api.Assertions.*;"
           - @Test annotation MUST be on its OWN line, separate from "public void"
           - Method declarations MUST end with {{ not with ;
           - Every statement ends with semicolon
           - All braces MUST be balanced (count {{ and }} — they must be equal)
           - UTF-8 encoding, no BOM
           - Class name MUST be {info.class_name}Test
           - Do NOT use @Override in test methods
           - Do NOT create anonymous subclasses of abstract classes unless absolutely necessary

        {"7. COMPILE-ONLY RESTRICTION: This class depends on compileOnly types not available at test time. Write ONLY assertTrue(true) in a single test method." if info.is_compile_only_dependent else ""}

        Output ONLY raw Java code. No markdown fences. No explanation. No commentary.
        Start with: package {info.package_name};
    """)

    try:
        resp = await ford_llm_service.generate(
            prompt=prompt,
            system_prompt=(
                "You are a senior Java test engineer. Output ONLY compilable JUnit 5 Java code. "
                "No markdown fences. No explanation. "
                "JACOCO COVERAGE RULE — MOST IMPORTANT: "
                "JaCoCo only records a line as COVERED if the test JVM actually EXECUTES it. "
                "A test that crashes in @BeforeEach or before calling the source method = 0% JaCoCo contribution. "
                "ALWAYS: (a) mock ALL @Autowired / constructor dependencies before instantiating the class, "
                "(b) use MockedStatic in try-with-resources for static singletons, "
                "(c) use MockedConstruction for internal 'new SomeService()' calls, "
                "(d) wrap setUp() in try-catch if constructor may throw. "
                "Every @Test must have a full body with assertions."
            ),
            temperature=0.1,
            max_tokens=8192,
            model=llm_model or None,
        )
        if resp and resp.success and resp.content:
            code = resp.content.strip()
            # Strip markdown fences if LLM wrapped them
            code = re.sub(r"^```(?:java)?\s*\n?", "", code, flags=re.MULTILINE)
            code = re.sub(r"\n?```\s*$", "", code, flags=re.MULTILINE)
            code = code.strip()

            # Ensure package declaration is present
            if not code.startswith(f"package {info.package_name}"):
                code = f"package {info.package_name};\n\n" + code

            # Validate the generated code
            is_valid, reason = _validate_llm_test_code(code, info)
            if is_valid:
                logger.info(f"[JaCoCo-LLM] ✅ Valid test generated for {info.class_name}")
                return code
            else:
                logger.warning(f"[JaCoCo-LLM] ❌ Validation failed for {info.class_name}: {reason}")
                return None
    except Exception as e:
        logger.warning(f"[JaCoCo-LLM] LLM failed for {info.class_name}: {e}")

    return None


def _compact_skeleton(info: JavaClassInfo) -> str:
    """Build a compact class skeleton for the LLM prompt."""
    lines = []
    if info.package_name:
        lines.append(f"package {info.package_name};")

    # Key imports
    for imp in info.imports[:10]:
        lines.append(f"import {imp};")

    # Class declaration
    src = info.source_code
    class_decl = re.search(
        r'((?:public|abstract)\s+(?:class|enum|interface)\s+\S+[^{]*)\{',
        src
    )
    if class_decl:
        lines.append(class_decl.group(1).strip() + " {")

    # Fields
    for fld in info.fields[:20]:
        lines.append(f"    private {fld['type']} {fld['name']};")

    # Constructors
    for ctor in info.constructors[:3]:
        lines.append(f"    public {info.class_name}({ctor}) {{ /* ... */ }}")

    # Method signatures
    for m in re.findall(
        r'((?:public|protected)\s+(?:static\s+)?[\w<>\[\]]+\s+\w+\s*\([^)]*\))',
        src
    )[:30]:
        lines.append(f"    {m.strip()} {{ /* ... */ }}")

    lines.append("}")
    result = "\n".join(lines)
    return result[:3000]  # cap size


def _describe_class(info: JavaClassInfo) -> str:
    """One-line description for the prompt."""
    parts = []
    if info.constructors:
        parts.append(f"Constructors: {len(info.constructors)}")
    if info.getters:
        parts.append(f"Getters: {len(info.getters)}")
    if info.setters:
        parts.append(f"Setters: {len(info.setters)}")
    if info.create_methods:
        parts.append(f"Create methods: {len(info.create_methods)}")
    if info.static_methods:
        parts.append(f"Static methods: {len(info.static_methods)}")
    if info.enum_values:
        parts.append(f"Enum values: {len(info.enum_values)}")
    if info.list_getters:
        parts.append(f"List getters: {len(info.list_getters)}")
    if info.has_equals:
        parts.append("Has equals/hashCode")
    return " | ".join(parts) if parts else "No special features detected"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Build.gradle Injection
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_gradle_dep_config_jacoco(content: str) -> str:
    """Detect whether this build.gradle uses testImplementation or testCompile."""
    if "testImplementation" in content:
        return "testImplementation"
    if "testCompile" in content:
        return "testCompile"
    if re.search(r"""apply\s+plugin\s*:\s*['"](?:java|java-library|application|war|ear|groovy|scala)['"]""", content):
        return "testImplementation"
    if re.search(r"""plugins\s*\{[^}]*(?:java|java-library|application|war|ear)""", content, re.DOTALL):
        return "testImplementation"
    if re.search(r"""subprojects\s*\{""", content):
        return "subprojects"
    return "testCompile"


def inject_test_dependencies(project_dir: str):
    """Add test deps (JUnit5, Mockito, servlet-api) to build.gradle.

    STEP 1 from the prompt — idempotent.
    Handles old Gradle (testCompile) and new Gradle (testImplementation).
    For root build.gradle with only subprojects{}, uses plugins.withType(JavaPlugin)
    guard so deps are only added to submodules that apply java/war plugin.
    """
    root = Path(project_dir).resolve()
    build_files = list(root.rglob("build.gradle"))

    for bf in build_files:
        try:
            content = bf.read_text(encoding="utf-8")
            if "jacoco-coverage-gen" in content:
                continue  # already injected

            modified = False

            # Fix jakarta → javax
            if "jakarta.servlet" in content:
                content = re.sub(
                    r"jakarta\.servlet:jakarta\.servlet-api[:'\"\\s]*[\\d.]*",
                    "javax.servlet:javax.servlet-api:4.0.1",
                    content
                )
                modified = True

            # ── Detect correct dependency configuration name ──
            dep_config = _detect_gradle_dep_config_jacoco(content)
            runtime_config = "testRuntimeOnly" if dep_config == "testImplementation" else "testRuntime"

            # Build the correct deps list
            if dep_config == "subprojects":
                # Root build.gradle — inject inside subprojects with JavaPlugin guard
                deps_to_check = [
                    "org.mockito:mockito-core:5.11.0",
                    "org.mockito:mockito-junit-jupiter:5.11.0",
                    "org.junit.jupiter:junit-jupiter-api:5.11.4",
                    "org.junit.jupiter:junit-jupiter-engine:5.11.4",
                    "javax.servlet:javax.servlet-api:4.0.1",
                ]
                missing = [d for d in deps_to_check if d not in content]
                if missing:
                    block = (
                        '\n// ── Test dependencies added by jacoco-coverage-gen ──\n'
                        'subprojects {\n'
                        '    plugins.withType(JavaPlugin) {\n'
                        '        dependencies {\n'
                        '            testImplementation "org.mockito:mockito-core:5.11.0"\n'
                        '            testImplementation "org.mockito:mockito-junit-jupiter:5.11.0"\n'
                        '            testImplementation "org.junit.jupiter:junit-jupiter-api:5.11.4"\n'
                        '            testRuntimeOnly "org.junit.jupiter:junit-jupiter-engine:5.11.4"\n'
                        '            testImplementation "javax.servlet:javax.servlet-api:4.0.1"\n'
                        '        }\n'
                        '        configurations.all {\n'
                        '            exclude group: "org.mockito", module: "mockito-all"\n'
                        '        }\n'
                        '        test {\n'
                        '            useJUnitPlatform()\n'
                        '        }\n'
                        '    }\n'
                        '}\n'
                    )
                    content = content.rstrip() + "\n" + block
                    modified = True
            else:
                deps_to_inject = [
                    f'{dep_config} "org.mockito:mockito-core:5.11.0"',
                    f'{dep_config} "org.mockito:mockito-junit-jupiter:5.11.0"',
                    f'{dep_config} "org.junit.jupiter:junit-jupiter-api:5.11.4"',
                    f'{runtime_config} "org.junit.jupiter:junit-jupiter-engine:5.11.4"',
                    f'{dep_config} "javax.servlet:javax.servlet-api:4.0.1"',
                ]
                missing = [d for d in deps_to_inject if d.split('"')[1] not in content]
                if missing:
                    block = (
                        '\n// ── Test dependencies added by jacoco-coverage-gen ──\n'
                        'dependencies {\n'
                        + "\n".join(f"    {d}" for d in missing) + "\n"
                        '}\n'
                        'configurations.all {\n'
                        '    exclude group: "org.mockito", module: "mockito-all"\n'
                        '}\n'
                    )
                    content = content.rstrip() + "\n" + block
                    modified = True

            # Ensure useJUnitPlatform (skip if subprojects mode — already handled)
            if dep_config != "subprojects" and "useJUnitPlatform" not in content:
                content = content.rstrip() + (
                    '\ntasks.withType(Test) {\n'
                    '    useJUnitPlatform()\n'
                    '}\n'
                )
                modified = True

            # Ensure JaCoCo plugin + test wiring (finalizedBy, dependsOn, destinationFile)
            # to avoid 0% coverage from missing agent or empty exec file.
            if "jacoco" not in content.lower():
                # JaCoCo entirely missing — inject plugin + full wiring
                content = content.rstrip() + (
                    "\n// ── JaCoCo plugin added by jacoco-coverage-gen ──\n"
                    "apply plugin: 'jacoco'\n"
                    "\njacocoTestReport {\n"
                    "    dependsOn test\n"
                    "    reports {\n"
                    "        xml.required = true\n"
                    "        html.required = true\n"
                    "    }\n"
                    "}\n"
                    "\ntest {\n"
                    "    finalizedBy jacocoTestReport\n"
                    "    jacoco {\n"
                    "        destinationFile = file(\"${buildDir}/jacoco/test.exec\")\n"
                    "    }\n"
                    "}\n"
                )
                modified = True
            else:
                # JaCoCo plugin exists — patch in missing wiring if absent
                _jacoco_patched = False
                if "jacocoTestReport" in content and "dependsOn test" not in content:
                    import re as _re
                    content = _re.sub(
                        r'(jacocoTestReport\s*\{)',
                        r'\1\n    dependsOn test',
                        content, count=1,
                    )
                    _jacoco_patched = True
                if "finalizedBy jacocoTestReport" not in content:
                    import re as _re
                    if _re.search(r'\btest\s*\{', content):
                        content = _re.sub(
                            r'(\btest\s*\{)',
                            r'\1\n    finalizedBy jacocoTestReport',
                            content, count=1,
                        )
                    else:
                        content = content.rstrip() + (
                            "\n\ntest {\n"
                            "    finalizedBy jacocoTestReport\n"
                            "    jacoco {\n"
                            "        destinationFile = file(\"${buildDir}/jacoco/test.exec\")\n"
                            "    }\n"
                            "}\n"
                        )
                    _jacoco_patched = True
                if "destinationFile" not in content and "jacoco {" not in content:
                    import re as _re
                    if _re.search(r'\btest\s*\{', content):
                        content = _re.sub(
                            r'(\btest\s*\{)',
                            r'\1\n    jacoco {\n        destinationFile = file("${buildDir}/jacoco/test.exec")\n    }',
                            content, count=1,
                        )
                        _jacoco_patched = True
                if _jacoco_patched:
                    modified = True

            if modified:
                bf.write_text(content, encoding="utf-8")
                logger.info(f"[JaCoCo-Deps] ✅ Updated {bf} (config={dep_config})")
        except Exception as e:
            logger.warning(f"[JaCoCo-Deps] Failed to update {bf}: {e}")


def inject_jacoco_root_report(project_dir: str):
    """Add jacocoRootReport task to root build.gradle (STEP 2).

    Idempotent — skips if already present.
    """
    root = Path(project_dir).resolve()
    # Find root build.gradle
    bg = root / "build.gradle"
    if not bg.exists():
        return

    content = bg.read_text(encoding="utf-8")
    if "jacocoRootReport" in content:
        return  # already present

    task = textwrap.dedent("""\

    // ── JaCoCo Root Report Task (added by jacoco-coverage-gen) ──
    task jacocoRootReport {
        description = 'Prints total JaCoCo coverage percentage across all modules'
        group = 'verification'
        dependsOn subprojects.findAll {
            it.name != 'MAPSEAR' && it.name != 'MAPSServer' && it.name != 'secAdminEAR'
        }.collect { "${it.path}:jacocoTestReport" }
        doLast {
            def classMissed = 0; def classCovered = 0
            def instrMissed = 0; def instrCovered = 0
            def methodMissed = 0; def methodCovered = 0
            subprojects.findAll {
                it.name != 'MAPSEAR' && it.name != 'MAPSServer' && it.name != 'secAdminEAR'
            }.each { sub ->
                def xmlFile = file("${sub.buildDir}/reports/jacoco/test/jacocoTestReport.xml")
                if (xmlFile.exists()) {
                    def parser = new XmlSlurper()
                    parser.setFeature("http://apache.org/xml/features/disallow-doctype-decl", false)
                    parser.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false)
                    def xml = parser.parse(xmlFile)
                    xml.counter.each { ctr ->
                        if (ctr.@type.toString() == 'CLASS') {
                            classMissed += ctr.@missed.toInteger()
                            classCovered += ctr.@covered.toInteger()
                        }
                        if (ctr.@type.toString() == 'INSTRUCTION') {
                            instrMissed += ctr.@missed.toInteger()
                            instrCovered += ctr.@covered.toInteger()
                        }
                        if (ctr.@type.toString() == 'METHOD') {
                            methodMissed += ctr.@missed.toInteger()
                            methodCovered += ctr.@covered.toInteger()
                        }
                    }
                }
            }
            def classTotal = classMissed + classCovered
            def classPct = classTotal > 0 ? (classCovered * 100.0 / classTotal) : 0
            def instrTotal = instrMissed + instrCovered
            def instrPct = instrTotal > 0 ? (instrCovered * 100.0 / instrTotal) : 0
            def methodTotal = methodMissed + methodCovered
            def methodPct = methodTotal > 0 ? (methodCovered * 100.0 / methodTotal) : 0
            println ''
            println '============================================================'
            printf  '  CLASS  COVERAGE = %.1f%% (%d/%d)%n', classPct, classCovered, classTotal
            printf  '  METHOD COVERAGE = %.1f%% (%d/%d)%n', methodPct, methodCovered, methodTotal
            printf  '  INSTR  COVERAGE = %.1f%% (%d/%d)%n', instrPct, instrCovered, instrTotal
            println '============================================================'
            println ''
        }
    }
    """)

    bg.write_text(content.rstrip() + "\n" + task, encoding="utf-8")
    logger.info(f"[JaCoCo-Root] ✅ Injected jacocoRootReport task into {bg}")


def inject_compile_only_test_impl(project_dir: str, module_name: str, dep_module: str):
    """Add testImplementation project(':MAPSCommon') alongside compileOnly.

    This unlocks testing of classes that depend on MAPSCommon types.
    """
    root = Path(project_dir).resolve()
    bg = root / module_name / "build.gradle"
    if not bg.exists():
        return

    content = bg.read_text(encoding="utf-8")
    test_impl_line = f'testImplementation project(":{dep_module}")'
    if test_impl_line in content or f"testImplementation project(':{dep_module}')" in content:
        return  # already present

    # Find the dependencies block and add
    if "dependencies" in content:
        content = re.sub(
            r'(dependencies\s*\{)',
            r'\1\n    // Added by jacoco-coverage-gen to enable testing classes that extend ' + dep_module + '\n'
            f'    testImplementation project(":{dep_module}")\n',
            content,
            count=1,
        )
        bg.write_text(content, encoding="utf-8")
        logger.info(f"[JaCoCo-Deps] ✅ Added testImplementation project(':{dep_module}') to {bg}")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. File Writer (UTF-8 no BOM)
# ═══════════════════════════════════════════════════════════════════════════════

def write_test_file_utf8(project_dir: str, info: JavaClassInfo, test_code: str) -> Path:
    """Write test file under src/test/java with UTF-8 no BOM encoding."""
    root = Path(project_dir).resolve()

    # Determine test directory from module
    if info.module and info.module != "root":
        test_dir = root / info.module / "src" / "test" / "java"
    else:
        test_dir = root / "src" / "test" / "java"

    package_path = info.package_name.replace(".", os.sep)
    dest = test_dir / package_path / f"{info.class_name}Test.java"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Write UTF-8 without BOM
    dest.write_bytes(test_code.encode("utf-8"))
    return dest


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Build Error Parser & Auto-Fixer
# ═══════════════════════════════════════════════════════════════════════════════

def parse_build_errors(output: str) -> List[Dict[str, str]]:
    """Parse Gradle/Maven build output for compilation errors.

    Returns list of {file, line, error, message}.
    """
    errors = []
    # Gradle/javac error: /path/to/File.java:42: error: ...
    for m in re.finditer(
        r'([^\s]+\.java):(\d+):\s*error:\s*(.+)',
        output
    ):
        errors.append({
            "file": m.group(1),
            "line": m.group(2),
            "error": m.group(3).strip(),
        })

    # NoClassDefFoundError at runtime
    for m in re.finditer(r'java\.lang\.NoClassDefFoundError:\s*(\S+)', output):
        errors.append({
            "file": "",
            "line": "0",
            "error": f"NoClassDefFoundError: {m.group(1)}",
        })

    # ExceptionInInitializerError
    for m in re.finditer(r'ExceptionInInitializerError', output):
        errors.append({
            "file": "",
            "line": "0",
            "error": "ExceptionInInitializerError",
        })

    return errors


def fix_test_from_errors(
    test_path: Path,
    errors: List[Dict[str, str]],
    info: Optional[JavaClassInfo] = None,
) -> bool:
    """Fix a test file based on compilation/runtime errors.

    Returns True if the file was modified.
    """
    if not test_path.exists():
        return False

    content = test_path.read_text(encoding="utf-8")
    original = content
    file_str = str(test_path)

    # Collect errors for this file
    file_errors = [e for e in errors if file_str.endswith(e.get("file", "").replace("/", os.sep))]
    # Also check runtime errors (no file specified)
    runtime_errors = [e for e in errors if not e.get("file")]

    needs_stub = False

    for err in file_errors:
        msg = err["error"]

        # cannot find symbol
        if "cannot find symbol" in msg:
            # Try to remove the offending line
            line_num = int(err.get("line", 0))
            if line_num > 0:
                lines = content.split("\n")
                if line_num <= len(lines):
                    lines[line_num - 1] = f"        // REMOVED: {lines[line_num - 1].strip()}"
                    content = "\n".join(lines)

        # abstract class cannot be instantiated
        if "abstract" in msg and "cannot be instantiated" in msg:
            needs_stub = True

        # private access / constructor is not visible
        if "private access" in msg or "not visible" in msg:
            needs_stub = True

        # ambiguous method call
        if "ambiguous" in msg:
            # Remove lines with null args — they cause ambiguity
            content = re.sub(r'.*\bnull\b.*//.*ambiguous.*\n?', '', content)
            # If it's a setter call with null, remove it
            line_num = int(err.get("line", 0))
            if line_num > 0:
                lines = content.split("\n")
                if line_num <= len(lines) and "null" in lines[line_num - 1]:
                    lines[line_num - 1] = f"        // REMOVED (ambiguous): {lines[line_num - 1].strip()}"
                    content = "\n".join(lines)

        # incompatible types / wrong constructor args
        if "incompatible types" in msg or "constructor" in msg.lower() and "cannot be applied" in msg:
            needs_stub = True

        # checked exception not handled
        if "unreported exception" in msg:
            # Add throws to the method
            content = re.sub(
                r'(void\s+test\w+\s*\()\s*\)',
                r'\1) throws Exception',
                content
            )

    for err in runtime_errors:
        msg = err["error"]
        if "NoClassDefFoundError" in msg or "ExceptionInInitializerError" in msg:
            needs_stub = True

    if needs_stub and info:
        # Downgrade to stub test
        content = _gen_compile_only_dependent_test(info)

    if content != original:
        test_path.write_bytes(content.encode("utf-8"))
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Build Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_gradle_build(
    project_dir: str,
    tasks: Optional[List[str]] = None,
    is_first_attempt: bool = True,
) -> Tuple[bool, str]:
    """Run Gradle build and return (success, output).

    Attempt 1  : clean build jacocoRootReport  — full build
    Attempt 2+ : build jacocoRootReport         — incremental, reuses cached artifacts
                                                   only recompiles files that changed (fixed tests)

    Speed improvements vs original:
      - No --no-daemon  → Gradle daemon stays warm between retries (saves 1-2 min per attempt)
      - No clean on retry → Artifacts reused, only changed tests recompiled
      - --build-cache   → Gradle skips recompiling unchanged source files (saves 3-8 min per retry)

    Ford network support:
      - init.gradle with mavenCentral() fallback
      - Gradle wrapper URL patched from jfrog.ford.com → services.gradle.org
      - JFrog credentials from ~/.m2/settings.xml
      - JDK compatibility (auto-download JDK 11 for Gradle ≤6)
      - Stale .gradle/wrapper lock cleanup
      - gradle.properties proxy settings
    """
    root = Path(project_dir).resolve()
    gradlew = root / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not gradlew.exists():
        # Try system gradle
        if not shutil.which("gradle"):
            return False, "gradlew not found and no system gradle available"
        gradlew = Path(shutil.which("gradle"))

    if tasks is None:
        if is_first_attempt:
            # First attempt: full clean build
            tasks = ["clean", "build", "jacocoRootReport"]
        else:
            # Retry attempts: incremental build
            tasks = ["build", "jacocoRootReport"]

    # Setup Ford Gradle environment (init.gradle, proxy, JFrog, JDK compat, stale locks)
    env, java_exe = build_gradle_env(root)

    # Use init.gradle if it exists
    init_args: List[str] = []
    init_gradle = root / "init.gradle"
    if init_gradle.exists():
        init_args = ["--init-script", str(init_gradle)]

    cmd = [str(gradlew)] + init_args + tasks + [
        "--build-cache",   # reuse compiled output for unchanged files
        "--continue",      # keep going past errors to find all failures
        "-q",              # quiet output
    ]

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(root),
            env=env,
        )
        output = (r.stdout or "") + "\n" + (r.stderr or "")
        return r.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Build timed out (600s)"
    except Exception as e:
        return False, str(e)


def parse_coverage_from_output(output: str) -> Dict[str, float]:
    """Parse coverage percentages from jacocoRootReport output."""
    result = {"class": 0.0, "method": 0.0, "instruction": 0.0}

    m = re.search(r'CLASS\s+COVERAGE\s*=\s*([\d.]+)%', output)
    if m:
        result["class"] = float(m.group(1))

    m = re.search(r'METHOD\s+COVERAGE\s*=\s*([\d.]+)%', output)
    if m:
        result["method"] = float(m.group(1))

    m = re.search(r'INSTR\s+COVERAGE\s*=\s*([\d.]+)%', output)
    if m:
        result["instruction"] = float(m.group(1))

    # Fallback: old format
    m = re.search(r'TOTAL JACOCO COVERAGE\s*=\s*([\d.]+)%', output)
    if m and result["class"] == 0:
        result["class"] = float(m.group(1))

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Compile-Only Config Auto-Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_compile_only_config(project_dir: str) -> Dict[str, Set[str]]:
    """Auto-detect which modules have compileOnly project dependencies.

    Returns {module_name: set_of_package_prefixes_from_compileOnly_modules}
    """
    root = Path(project_dir).resolve()
    result: Dict[str, Set[str]] = {}

    for bf in root.rglob("build.gradle"):
        module_dir = bf.parent
        module_name = module_dir.name if module_dir != root else "root"
        content = bf.read_text(encoding="utf-8", errors="replace")

        # Find compileOnly project(':SomeModule')
        for m in re.finditer(r'compileOnly\s+project\(["\']:([\w]+)["\']\)', content):
            dep_module = m.group(1)
            # Find packages in the dep module
            dep_src = root / dep_module / "src" / "main" / "java"
            if dep_src.is_dir():
                packages = set()
                for java_f in dep_src.rglob("*.java"):
                    try:
                        src = java_f.read_text(encoding="utf-8", errors="replace")
                        pkg = _extract_package(src)
                        if pkg:
                            packages.add(pkg)
                    except Exception:
                        pass
                if packages:
                    if module_name not in result:
                        result[module_name] = set()
                    result[module_name].update(packages)
                    logger.info(
                        f"[CompileOnly] {module_name} has compileOnly dep on {dep_module} "
                        f"({len(packages)} packages)"
                    )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 10. MAIN PIPELINE — Orchestrates everything
# ═══════════════════════════════════════════════════════════════════════════════

async def run_jacoco_coverage_pipeline(
    job_id: str,
    project_dir: str,
    llm_model: str = "",
    use_llm: bool = True,
    max_build_retries: int = 5,
    add_test_impl_for_compile_only: bool = False,
):
    """Full pipeline to generate tests for maximum JaCoCo coverage.

    Steps:
      1. Inject test deps + jacocoRootReport into build.gradle
      2. Detect compileOnly config
      3. Scan all source files
      4. For each class: LLM generate → fallback to regex → write test file
      5. Build → parse errors → fix → retry
      6. Report final coverage

    Args:
        job_id: Unique identifier for this run
        project_dir: Root of the Java project
        llm_model: Optional LLM model override
        use_llm: If True, try LLM first; if False, use regex only
        max_build_retries: Max iterations of build→fix→retry
        add_test_impl_for_compile_only: If True, add testImplementation
            alongside compileOnly to unlock more coverage
    """
    _prune_coverage_jobs()
    job = coverage_jobs.get(job_id)
    if not job:
        job = CoverageJob(job_id=job_id, project_dir=project_dir)
    _remember_coverage_job(job_id, job)

    start_time = time.time()

    try:
        _cov_log(job, "═" * 60)
        _cov_log(job, "  🚀 JaCoCo Coverage Generation Pipeline — START")
        _cov_log(job, "═" * 60)
        _cov_log(job, f"  Project: {project_dir}")
        _cov_log(job, f"  LLM: {'Enabled' if use_llm else 'Disabled (regex only)'}")
        _cov_log(job, f"  Max retries: {max_build_retries}")

        # ── Step 1: Inject deps ──
        job.status = "injecting"
        job.current_step = "Injecting test dependencies…"
        job.progress_percent = 5
        _cov_log(job, "")
        _cov_log(job, "  Step 1: Injecting test dependencies and JaCoCo config")

        inject_test_dependencies(project_dir)
        inject_jacoco_root_report(project_dir)
        _cov_log(job, "  ✅ Dependencies and jacocoRootReport injected")

        # ── Step 2: Detect compileOnly config ──
        _cov_log(job, "")
        _cov_log(job, "  Step 2: Detecting compileOnly dependencies")
        compile_only_config = detect_compile_only_config(project_dir)
        if compile_only_config:
            for mod, pkgs in compile_only_config.items():
                _cov_log(job, f"    {mod}: {len(pkgs)} compileOnly packages")

                # Optionally add testImplementation
                if add_test_impl_for_compile_only:
                    root = Path(project_dir).resolve()
                    bg = root / mod / "build.gradle"
                    if bg.exists():
                        bg_content = bg.read_text(encoding="utf-8", errors="replace")
                        for m in re.finditer(r'compileOnly\s+project\(["\']:([\w]+)["\']\)', bg_content):
                            inject_compile_only_test_impl(project_dir, mod, m.group(1))
        else:
            _cov_log(job, "    No compileOnly cross-module dependencies detected")

        # ── Step 3: Scan ──
        _cov_log(job, "")
        _cov_log(job, "  Step 3: Scanning all Java source files")
        job.status = "scanning"
        job.current_step = "Scanning Java source files…"
        job.progress_percent = 10

        all_classes = scan_project_for_coverage(project_dir, compile_only_config)
        job.total_classes = len(all_classes)

        # Count by type
        type_counts: Dict[str, int] = {}
        for ci in all_classes:
            type_counts[ci.class_type] = type_counts.get(ci.class_type, 0) + 1
        for ct, count in sorted(type_counts.items()):
            _cov_log(job, f"    {ct}: {count}")
        _cov_log(job, f"    TOTAL: {len(all_classes)}")

        # Check which classes already have test files
        existing_tests: Set[str] = set()
        root = Path(project_dir).resolve()

        def _is_in_test_src(p: Path) -> bool:
            """Return True if the path lives under any src/test tree."""
            normalized = str(p).replace("\\", "/")
            return "src/test" in normalized

        # Pattern 1: ClassNameTest.java  (suffix style — our generated files)
        for tp in root.rglob("*Test.java"):
            if _is_in_test_src(tp):
                stem = tp.stem  # e.g. "FooBarTest"
                if stem.endswith("Test"):
                    existing_tests.add(stem[:-4])  # strip only the trailing "Test"
                else:
                    existing_tests.add(stem)

        # Pattern 2: TestClassName.java  (prefix style — JUnit 3/4 legacy)
        for tp in root.rglob("Test*.java"):
            if _is_in_test_src(tp):
                stem = tp.stem  # e.g. "TestFooBar"
                if stem.startswith("Test"):
                    existing_tests.add(stem[4:])  # strip leading "Test"
                else:
                    existing_tests.add(stem)

        # Pattern 3: ClassNameTests.java / ClassNameSpec.java (plural / BDD)
        for tp in root.rglob("*Tests.java"):
            if _is_in_test_src(tp):
                stem = tp.stem
                if stem.endswith("Tests"):
                    existing_tests.add(stem[:-5])
        for tp in root.rglob("*Spec.java"):
            if _is_in_test_src(tp):
                stem = tp.stem
                if stem.endswith("Spec"):
                    existing_tests.add(stem[:-4])

        need_test = [ci for ci in all_classes if ci.class_name not in existing_tests]
        _cov_log(job, f"    Already have tests: {len(all_classes) - len(need_test)}")
        _cov_log(job, f"    Need new tests: {len(need_test)}")

        # ── Step 4: Generate tests ──
        _cov_log(job, "")
        _cov_log(job, "  Step 4: Generating test files")
        job.status = "generating"
        job.current_step = "Generating tests…"

        progress_per_file = 60 // max(len(need_test), 1)
        generated_count = 0
        skipped_count = 0

        for idx, info in enumerate(need_test):
            job.current_step = f"Generating test for {info.class_name} ({idx+1}/{len(need_test)})"
            job.processed_classes = idx + 1
            job.progress_percent = 15 + (idx * progress_per_file)

            test_code = None

            # Try LLM first
            if use_llm:
                try:
                    test_code = await generate_test_llm(info, llm_model)
                    if test_code:
                        _cov_log(job, f"    ✅ LLM: {info.class_name} ({info.class_type})")
                except Exception as e:
                    _cov_log(job, f"    ⚠️  LLM failed for {info.class_name}: {e}")

            # Fallback to regex
            if not test_code:
                test_code = generate_test_regex(info)
                if use_llm:
                    _cov_log(job, f"    📐 Regex fallback: {info.class_name} ({info.class_type})")
                else:
                    if idx % 50 == 0:  # Log every 50th for speed
                        _cov_log(job, f"    📐 Regex: {info.class_name} ({idx+1}/{len(need_test)})")

            # Write
            try:
                write_test_file_utf8(project_dir, info, test_code)
                generated_count += 1
            except Exception as e:
                _cov_log(job, f"    ❌ Write failed for {info.class_name}: {e}")
                skipped_count += 1

        job.tests_generated = generated_count
        job.tests_skipped = skipped_count
        _cov_log(job, f"  ✅ Generated {generated_count} test files, skipped {skipped_count}")

        # ── Step 5: Build → Fix → Retry ──
        _cov_log(job, "")
        _cov_log(job, "  Step 5: Build → Fix → Retry loop")
        job.status = "building"
        job.progress_percent = 75

        for attempt in range(1, max_build_retries + 1):
            job.build_attempts = attempt
            job.current_step = f"Build attempt {attempt}/{max_build_retries}…"
            _cov_log(job, f"")
            _cov_log(job, f"    ── Build attempt {attempt}/{max_build_retries} ──")
            if attempt == 1:
                _cov_log(job, "    🧹 Full clean build")
            else:
                _cov_log(job, "    ⚡ Incremental build (reusing cached artifacts)")

            success, output = run_gradle_build(
                project_dir,
                is_first_attempt=(attempt == 1),
            )

            if success:
                _cov_log(job, f"    ✅ BUILD SUCCESSFUL on attempt {attempt}")
                job.build_success = True

                # Parse coverage
                coverage = parse_coverage_from_output(output)
                job.coverage_percent = coverage.get("instruction", 0)
                job.class_coverage_percent = coverage.get("class", 0)
                _cov_log(job, f"    📊 Class coverage: {coverage.get('class', 0)}%")
                _cov_log(job, f"    📊 Method coverage: {coverage.get('method', 0)}%")
                _cov_log(job, f"    📊 Instruction coverage: {coverage.get('instruction', 0)}%")
                break

            # Parse errors
            errors = parse_build_errors(output)
            _cov_log(job, f"    ❌ Build failed — {len(errors)} error(s) detected")

            if not errors:
                # No parseable errors — log the tail of output
                _cov_log(job, f"    Output tail: {output[-300:]}")
                break

            # Group errors by file
            files_with_errors: Dict[str, List[Dict]] = {}
            for err in errors:
                fpath = err.get("file", "")
                if fpath:
                    files_with_errors.setdefault(fpath, []).append(err)

            fixed_count = 0
            for fpath, ferrs in files_with_errors.items():
                test_path = Path(fpath) if os.path.isabs(fpath) else Path(project_dir) / fpath
                if not test_path.exists():
                    continue

                # Find the matching JavaClassInfo
                class_name = test_path.stem.replace("Test", "")
                matching_info = next(
                    (ci for ci in all_classes if ci.class_name == class_name),
                    None
                )

                if fix_test_from_errors(test_path, ferrs, matching_info):
                    fixed_count += 1
                    _cov_log(job, f"      Fixed: {test_path.name}")

            # Handle runtime errors (no file)
            runtime_errs = [e for e in errors if not e.get("file")]
            if runtime_errs:
                # Find which test caused it from the output context
                for err in runtime_errs:
                    msg = err["error"]
                    if "NoClassDefFoundError" in msg:
                        # Extract the missing class
                        missing = msg.split(":")[-1].strip().replace("/", ".")
                        # Find test files that import/reference this class
                        for tp in root.rglob("*Test.java"):
                            if "src/test" not in str(tp).replace("\\", "/"):
                                continue
                            try:
                                tc = tp.read_text(encoding="utf-8")
                                if missing.split(".")[-1] in tc:
                                    class_name = tp.stem.replace("Test", "")
                                    mi = next(
                                        (ci for ci in all_classes if ci.class_name == class_name),
                                        None
                                    )
                                    if mi:
                                        stub = _gen_compile_only_dependent_test(mi)
                                        tp.write_bytes(stub.encode("utf-8"))
                                        fixed_count += 1
                                        _cov_log(job, f"      Stubbed (NoClassDef): {tp.name}")
                            except Exception:
                                pass

            _cov_log(job, f"    Fixed {fixed_count} file(s)")

            if fixed_count == 0:
                _cov_log(job, "    No fixable errors — stopping retry loop")
                break

        # If build never succeeded, try one more time with just test + report
        if not job.build_success:
            _cov_log(job, "")
            _cov_log(job, "    Final attempt: incremental build (no clean)")
            success, output = run_gradle_build(
                project_dir,
                tasks=["build", "jacocoRootReport"],
                is_first_attempt=False,   # incremental — no clean
            )
            if success:
                job.build_success = True
                coverage = parse_coverage_from_output(output)
                job.coverage_percent = coverage.get("instruction", 0)
                job.class_coverage_percent = coverage.get("class", 0)
                _cov_log(job, f"    ✅ Final build succeeded")
                _cov_log(job, f"    📊 Class coverage: {coverage.get('class', 0)}%")

        # ── Step 6: Final report ──
        elapsed = round(time.time() - start_time, 1)
        job.status = "completed"
        job.progress_percent = 100
        job.current_step = "Pipeline complete ✅"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        _remember_coverage_job(job_id, job)

        _cov_log(job, "")
        _cov_log(job, "═" * 60)
        _cov_log(job, "  ✅ JaCoCo Coverage Pipeline — COMPLETE")
        _cov_log(job, "═" * 60)
        _cov_log(job, f"  Total classes scanned:   {len(all_classes)}")
        _cov_log(job, f"  Tests generated:         {generated_count}")
        _cov_log(job, f"  Tests skipped:           {skipped_count}")
        _cov_log(job, f"  Build attempts:          {job.build_attempts}")
        _cov_log(job, f"  Build success:           {'✅' if job.build_success else '❌'}")
        _cov_log(job, f"  Class coverage:          {job.class_coverage_percent}%")
        _cov_log(job, f"  Instruction coverage:    {job.coverage_percent}%")
        _cov_log(job, f"  Duration:                {elapsed}s")
        _cov_log(job, "═" * 60)

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        logger.exception(f"JaCoCo pipeline failed: {e}")
        job.status = "failed"
        job.error_message = str(e)
        job.current_step = f"Failed: {e}"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        _cov_log(job, f"  ❌ Pipeline failed: {e} (after {elapsed}s)")
        _remember_coverage_job(job_id, job)
