"""Shared Gradle environment setup for Ford corporate network.

Used by both the functional test pipeline and the JaCoCo coverage service
to ensure Gradle projects can build behind the Ford proxy with:
  - init.gradle with mavenCentral() fallback (no BOM)
  - gradle.properties with proxy settings
  - Gradle wrapper URL patched from jfrog.ford.com → services.gradle.org
  - JFrog credentials from ~/.m2/settings.xml or FORD_JFROG_TOKEN env
  - JDK compatibility check (auto-download JDK 11 for Gradle ≤6)
  - Stale .gradle/wrapper lock cleanup
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def get_ford_proxy() -> Optional[str]:
    """Return the Ford corporate proxy URL if set."""
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
    )


def get_maven_opts() -> str:
    """Build MAVEN_OPTS for Ford network: proxy flags + wagon transport."""
    proxy = get_ford_proxy()
    if not proxy:
        return "-Dmaven.resolver.transport=wagon"
    p = urlparse(proxy)
    host = p.hostname or "internet.ford.com"
    port = str(p.port or 83)
    return (
        f"-Dmaven.resolver.transport=wagon "
        f"-Dhttp.proxyHost={host} -Dhttp.proxyPort={port} "
        f"-Dhttps.proxyHost={host} -Dhttps.proxyPort={port}"
    )


def get_maven_env() -> Dict[str, str]:
    """Return env vars for Maven subprocesses."""
    return {"MAVEN_OPTS": get_maven_opts()}


def get_jfrog_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Extract JFrog credentials from the environment or Maven settings.xml.

    Order of precedence:
      1. ARTIFACTORY_USERNAME / ARTIFACTORY_USER + ARTIFACTORY_PASSWORD (.env)
      2. ~/.m2/settings.xml <server> entry for jfrog/artifactory/ford
      3. FORD_JFROG_TOKEN (paired with a real username when one is known)

    NOTE: the project's .env uses ARTIFACTORY_USERNAME, so we accept BOTH
    that name and the older ARTIFACTORY_USER spelling.
    """
    user = os.environ.get("ARTIFACTORY_USERNAME") or os.environ.get("ARTIFACTORY_USER")
    pwd = os.environ.get("ARTIFACTORY_PASSWORD")
    if user and pwd:
        return user, pwd

    settings_path = Path.home() / ".m2" / "settings.xml"
    if settings_path.exists():
        try:
            import xml.etree.ElementTree as ET
            text = settings_path.read_text(encoding="utf-8", errors="ignore")
            root_el = ET.fromstring(text)
            ns = {"m": "http://maven.apache.org/SETTINGS/1.0.0"}
            servers = root_el.findall(".//m:server", ns)
            if not servers:
                servers = root_el.findall(".//server")
            for server in servers:
                sid = (
                    server.findtext("m:id", default="", namespaces=ns)
                    or server.findtext("id", default="")
                )
                if "jfrog" in sid.lower() or "artifactory" in sid.lower() or "ford" in sid.lower():
                    u = (
                        server.findtext("m:username", default="", namespaces=ns)
                        or server.findtext("username", default="")
                    )
                    p = (
                        server.findtext("m:password", default="", namespaces=ns)
                        or server.findtext("password", default="")
                    )
                    if u:
                        return u, p
        except Exception:
            pass

    # Fall back to a JFrog token.  Pair it with a real username when one is
    # known — JFrog rejects Basic auth that uses token:token.
    token = os.environ.get("FORD_JFROG_TOKEN") or pwd
    if token:
        return (user or token), token
    return None, None


def get_gradle_wrapper_opts() -> str:
    """Return -D system properties that let the Gradle *wrapper* bootstrap
    authenticate its distribution download (e.g. gradle-6.3-bin.zip) from
    Ford's internal JFrog Artifactory.

    The Gradle wrapper reads the system properties ``gradle.wrapperUser`` and
    ``gradle.wrapperPassword`` for HTTP Basic auth when downloading the
    distribution.  These are passed to the gradlew JVM via GRADLE_OPTS.  Using
    an env var (not a command line) means special characters in the token need
    no escaping.
    """
    user, pwd = get_jfrog_credentials()
    if not user or not pwd:
        return ""
    return f"-Dgradle.wrapperUser={user} -Dgradle.wrapperPassword={pwd}"


# Marker comment used to detect (and avoid re-appending) the dependency-variant
# disambiguation block inside a generated/existing init.gradle.
DEP_VARIANT_FIX_MARKER = "JAVAAPEX_DEP_VARIANT_FIX"


def dependency_variant_fix_block() -> str:
    """Return a Groovy ``init.gradle`` block that resolves JVM-vs-Android variant
    ambiguity for libraries such as Google Guava.

    Modern Guava (and a handful of other libraries) publish Gradle Module
    Metadata with two runtime variants — ``jreRuntimeElements`` and
    ``androidRuntimeElements`` — distinguished only by the
    ``org.gradle.jvm.environment`` attribute.  A consumer that does not request
    that attribute makes Gradle fail with::

        Cannot choose between the following variants of com.google.guava:guava:
          - androidRuntimeElements
          - jreRuntimeElements

    Since every project migrated here targets the standard JVM (never Android),
    we pin ``org.gradle.jvm.environment = standard-jvm`` on every configuration.

    The block is intentionally defensive:
      * Gradle 7+ uses the typed ``TargetJvmEnvironment`` attribute.
      * Older Gradle falls back to the desugared String attribute.
      * Everything is wrapped in ``try/catch(Throwable)`` so the shim can never
        break a build (e.g. for already-resolved configurations).
    """
    return (
        f"\n// {DEP_VARIANT_FIX_MARKER} - force standard-JVM variant (fixes Guava android/jre ambiguity)\n"
        "allprojects { proj ->\n"
        "    proj.configurations.all { conf ->\n"
        "        try {\n"
        "            def gv = org.gradle.util.GradleVersion.current()\n"
        '            if (gv >= org.gradle.util.GradleVersion.version("7.0")) {\n'
        "                conf.attributes.attribute(\n"
        "                    org.gradle.api.attributes.java.TargetJvmEnvironment.TARGET_JVM_ENVIRONMENT_ATTRIBUTE,\n"
        "                    proj.objects.named(org.gradle.api.attributes.java.TargetJvmEnvironment,\n"
        "                                       org.gradle.api.attributes.java.TargetJvmEnvironment.STANDARD_JVM)\n"
        "                )\n"
        "            } else {\n"
        "                conf.attributes.attribute(\n"
        '                    org.gradle.api.attributes.Attribute.of("org.gradle.jvm.environment", String),\n'
        '                    "standard-jvm"\n'
        "                )\n"
        "            }\n"
        "        } catch (Throwable ignored) {\n"
        "            // Best-effort only - never fail the build because of the shim.\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def ensure_init_gradle_dependency_fixes(root: Path) -> None:
    """Idempotently ensure ``root/init.gradle`` contains the dependency-variant fix.

    Creates ``init.gradle`` if it does not exist, or appends the fix block to an
    existing file when the marker is absent.  Safe to call multiple times and
    alongside other init-script injections (e.g. the Gretty plugin block).
    """
    try:
        init_gradle = root / "init.gradle"
        existing = ""
        if init_gradle.exists():
            existing = init_gradle.read_text(encoding="utf-8", errors="ignore")
        if DEP_VARIANT_FIX_MARKER in existing:
            return
        # Write raw bytes to avoid a UTF-8 BOM, which crashes the Groovy parser.
        init_gradle.write_bytes((existing + dependency_variant_fix_block()).encode("utf-8"))
        logger.info("Applied Gradle dependency-variant fix to %s", init_gradle)
    except Exception as exc:  # never let the shim break setup
        logger.warning("Could not apply Gradle dependency-variant fix: %s", exc)


def setup_gradle_environment(root: Path) -> Dict[str, str]:
    """Prepare a Gradle project for building in the Ford network.

    Creates/patches:
      - init.gradle with mavenCentral() + gradlePluginPortal() (no UTF-8 BOM)
      - gradle.properties with proxy settings
      - gradle-wrapper.properties: patches jfrog.ford.com → services.gradle.org

    Returns extra env vars to pass to the Gradle subprocess.
    """
    extra_env: Dict[str, str] = {}

    # 1. JFrog credentials — export under BOTH names so build.gradle repos that
    #    reference either ARTIFACTORY_USER or ARTIFACTORY_USERNAME authenticate.
    user, pwd = get_jfrog_credentials()
    if user:
        extra_env["ARTIFACTORY_USER"] = user
        extra_env["ARTIFACTORY_USERNAME"] = user
        extra_env["ARTIFACTORY_PASSWORD"] = pwd or ""

    # 2. init.gradle
    init_gradle = root / "init.gradle"
    if not init_gradle.exists():
        init_content = (
            'allprojects {\n'
            '    buildscript {\n'
            '        repositories {\n'
            '            mavenCentral()\n'
            '            gradlePluginPortal()\n'
            '        }\n'
            '    }\n'
            '    repositories {\n'
            '        mavenCentral()\n'
            '        gradlePluginPortal()\n'
            '    }\n'
            '}\n'
        )
        init_gradle.write_bytes(init_content.encode("utf-8"))

    # 2b. Always ensure the dependency-variant fix is present (idempotent).
    #     Resolves the Guava android/jre variant ambiguity that aborts builds.
    ensure_init_gradle_dependency_fixes(root)

    # 3. gradle.properties — inject proxy
    proxy = get_ford_proxy()
    if proxy:
        p = urlparse(proxy)
        host = p.hostname or "internet.ford.com"
        port_str = str(p.port or 83)
        gp = root / "gradle.properties"
        existing = ""
        if gp.exists():
            existing = gp.read_text(encoding="utf-8", errors="ignore")
        if "systemProp.http.proxyHost" not in existing:
            proxy_block = (
                f"\nsystemProp.http.proxyHost={host}\n"
                f"systemProp.http.proxyPort={port_str}\n"
                f"systemProp.https.proxyHost={host}\n"
                f"systemProp.https.proxyPort={port_str}\n"
                # Internal Ford hosts (jfrog.ford.com, github.ford.com, …) must
                # bypass the corporate proxy or they return 403/timeouts.
                f"systemProp.http.nonProxyHosts=*.ford.com|localhost|127.0.0.1\n"
                f"systemProp.https.nonProxyHosts=*.ford.com|localhost|127.0.0.1\n"
            )
            gp.write_text(existing + proxy_block, encoding="utf-8")

    # 4. Patch gradle-wrapper.properties.  Keep the fast internal jfrog URL when
    #    we have credentials (the wrapper authenticates via GRADLE_OPTS); only
    #    rewrite to services.gradle.org when no credentials are available.
    patch_gradle_wrapper_url(root, has_credentials=bool(user and pwd))

    return extra_env


def patch_gradle_wrapper_url(root: Path, has_credentials: bool = False) -> None:
    """Ensure the Gradle wrapper can fetch its distribution on the Ford network.

    For every ``gradle-wrapper.properties`` under ``root`` that points at
    jfrog.ford.com:
      - If JFrog credentials are available, KEEP the internal URL — it is fast
        and reachable directly (NO_PROXY), and the wrapper authenticates using
        the gradle.wrapperUser/Password system properties (see
        :func:`get_gradle_wrapper_opts`).
      - Otherwise, rewrite the URL to the public services.gradle.org mirror,
        which needs no authentication.

    Recurses so multi-module projects with nested wrappers are all handled.
    """
    for wrapper_props in root.rglob("gradle-wrapper.properties"):
        try:
            wp_text = wrapper_props.read_text(encoding="utf-8", errors="ignore")
            if "jfrog.ford.com" not in wp_text:
                continue
            if has_credentials:
                logger.info(
                    "Keeping internal jfrog gradle distribution URL (wrapper authenticates): %s",
                    wrapper_props,
                )
                continue
            ver_match = re.search(r"gradle-(\d+\.\d+(?:\.\d+)?)-", wp_text)
            ver = ver_match.group(1) if ver_match else "6.3"
            new_url = f"https\\://services.gradle.org/distributions/gradle-{ver}-bin.zip"
            wp_text = re.sub(r"distributionUrl=.*", f"distributionUrl={new_url}", wp_text)
            wrapper_props.write_text(wp_text, encoding="utf-8")
            logger.info(
                "Patched %s: jfrog.ford.com → services.gradle.org (v%s)", wrapper_props, ver
            )
        except Exception as e:
            logger.debug("Could not patch %s: %s", wrapper_props, e)


def detect_gradle_major_version(root: Path) -> int:
    """Detect the Gradle major version from wrapper properties."""
    wrapper_props = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if wrapper_props.exists():
        try:
            wp = wrapper_props.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"gradle-(\d+)", wp)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    return 6  # default assumption


def detect_jdk_major_version() -> int:
    """Detect the major version of the system JDK on PATH."""
    java = shutil.which("java")
    if not java:
        return 0
    try:
        out = subprocess.check_output(
            [java, "-version"], stderr=subprocess.STDOUT, timeout=10
        ).decode(errors="replace")
        m = re.search(r'"(\d+)', out)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


# ── Minimum Gradle version required to RUN on a given JDK major version ──
# (Gradle versions older than this cannot launch on that JDK and will fail
#  with errors such as "Unsupported class file major version".)
_MIN_GRADLE_FOR_JDK: Dict[int, str] = {
    8: "5.0", 9: "5.0", 10: "5.0", 11: "5.0", 12: "5.4", 13: "6.0",
    14: "6.3", 15: "6.7", 16: "7.0", 17: "7.3", 18: "7.5", 19: "7.6",
    20: "8.3", 21: "8.5", 22: "8.8", 23: "8.10", 24: "8.14",
}


def _parse_jdk_major(version_str: str) -> Optional[int]:
    """Normalise a Java version string to its major version.

    Examples: "21.0.10" → 21, "1.8.0_482" → 8, "17" → 17.
    """
    if not version_str:
        return None
    v = version_str.strip().strip('"')
    if v.startswith("1."):
        parts = v.split(".")
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
        return None
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else None


def _version_ge(a: str, b: str) -> bool:
    """Return True when dotted version ``a`` >= ``b`` (e.g. "8.5" >= "8.3")."""
    def parts(v: str) -> List[int]:
        return [int(x) for x in re.findall(r"\d+", v)] or [0]
    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa >= pb


def _max_jdk_for_gradle(gradle_full: str) -> int:
    """Highest JDK major version the given Gradle version can launch on.

    Inverse of ``_MIN_GRADLE_FOR_JDK`` (e.g. Gradle 6.3 → 14, 7.3 → 17,
    8.5 → 21).  Used to decide whether a project *genuinely* needs a newer JDK
    (and therefore a Gradle upgrade), or whether an older, compatible JDK will
    do — the latter avoids the "Unsupported class file major version" crash.
    """
    best = 0
    for jdk_major, min_gradle in _MIN_GRADLE_FOR_JDK.items():
        if _version_ge(gradle_full, min_gradle):
            best = max(best, jdk_major)
    return best or 8


def _jdk_major_from_home(home: Path) -> Optional[int]:
    """Read a JDK's major version from its ``release`` file (fast) or
    fall back to invoking ``java -version``."""
    try:
        release = home / "release"
        if release.exists():
            for line in release.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("JAVA_VERSION="):
                    return _parse_jdk_major(line.split("=", 1)[1])
    except Exception:
        pass
    java_name = "java.exe" if os.name == "nt" else "java"
    java_exe = home / "bin" / java_name
    if java_exe.exists():
        try:
            out = subprocess.check_output(
                [str(java_exe), "-version"], stderr=subprocess.STDOUT, timeout=10
            ).decode(errors="replace")
            m = re.search(r'version "([^"]+)"', out)
            if m:
                return _parse_jdk_major(m.group(1))
        except Exception:
            pass
    return None


def detect_installed_jdks() -> Dict[int, str]:
    """Discover every JDK installed on this machine.

    Returns a mapping of ``{major_version: java_home}`` built from:
      - the active ``java`` on PATH
      - JAVA_HOME and any JAVA_<N>_HOME environment variables
      - ~/.jdks/* (IntelliJ), Program Files vendors, /usr/lib/jvm, /opt/jdks
    """
    found: Dict[int, str] = {}
    candidates: List[Path] = []

    jx = shutil.which("java")
    if jx:
        p = Path(jx).resolve()
        if p.parent.name.lower() == "bin":
            candidates.append(p.parent.parent)

    for key, val in os.environ.items():
        if not val:
            continue
        if key == "JAVA_HOME" or re.fullmatch(r"JAVA_\d+_HOME", key):
            candidates.append(Path(val))

    home = Path.home()
    local_programs = home / "AppData" / "Local" / "Programs"
    search_dirs = [
        home / ".jdks",
        Path(r"C:\Program Files\Java"),
        Path(r"C:\Program Files\Eclipse Adoptium"),
        Path(r"C:\Program Files\Microsoft"),
        Path(r"C:\Program Files\Amazon Corretto"),
        Path(r"C:\Program Files\Zulu"),
        Path(r"C:\Program Files\BellSoft"),
        # Per-user installs (installers increasingly default here, no admin rights)
        local_programs / "Eclipse Adoptium",
        local_programs / "Java",
        local_programs / "Microsoft",
        local_programs / "Amazon Corretto",
        local_programs / "Zulu",
        Path("/usr/lib/jvm"),
        Path("/opt/jdks"),
        Path("/Library/Java/JavaVirtualMachines"),
    ]
    for d in search_dirs:
        try:
            if not d.exists():
                continue
            for sub in d.iterdir():
                if not sub.is_dir():
                    continue
                mac_home = sub / "Contents" / "Home"
                if mac_home.exists():
                    candidates.append(mac_home)
                candidates.append(sub)
        except Exception:
            continue

    for c in candidates:
        try:
            if not (c / "bin").exists():
                continue
            major = _jdk_major_from_home(c)
            if major and major not in found:
                found[major] = str(c)
        except Exception:
            continue
    return found


def detect_gradle_full_version(root: Path) -> str:
    """Return the full Gradle version from the wrapper (e.g. "8.5"), default "6.3"."""
    wrapper_props = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if wrapper_props.exists():
        try:
            wp = wrapper_props.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"gradle-(\d+\.\d+(?:\.\d+)?)-(?:bin|all)\.zip", wp)
            if m:
                return m.group(1)
        except Exception:
            pass
    return "6.3"


def detect_project_java_version(root: Path) -> Optional[int]:
    """Infer the Java version a Gradle project targets.

    Parses every build.gradle(.kts) and gradle.properties for:
      - sourceCompatibility / targetCompatibility (numbers, JavaVersion.VERSION_x,
        or ${propertyName} references)
      - JavaLanguageVersion.of(N) toolchains
      - property assignments such as ``javaVersion = '21'``
    Returns the highest version found, or None when undetermined.
    """
    prop_vals: Dict[str, int] = {}
    files: List[Path] = []
    try:
        files = list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts"))
    except Exception:
        files = []
    gp = root / "gradle.properties"
    if gp.exists():
        files.append(gp)

    texts: List[str] = []
    for f in files:
        try:
            texts.append(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue

    # Pass 1 — collect property assignments (javaVersion = '21', ext.foo = 17 …)
    for txt in texts:
        for m in re.finditer(r"""(\w+)\s*=\s*['"]?(\d+(?:\.\d+)?)['"]?""", txt):
            name, val = m.group(1), m.group(2)
            low = name.lower()
            if "version" in low or "java" in low or "jdk" in low:
                mj = _parse_jdk_major(val)
                if mj:
                    prop_vals[name] = mj

    def _resolve_expr(expr: str) -> Optional[int]:
        expr = expr.strip().strip(';').strip().strip('"\'')
        ref = re.search(r"\$\{?(\w+)\}?", expr)
        if ref and ref.group(1) in prop_vals:
            return prop_vals[ref.group(1)]
        ver = re.search(r"VERSION_(\d+)(?:_(\d+))?", expr)
        if ver:
            return int(ver.group(2)) if ver.group(2) else int(ver.group(1))
        # Capture decimal forms too (e.g. ``1.8``) so _parse_jdk_major maps
        # them correctly (1.8 → 8) instead of truncating to the leading ``1``.
        num = re.match(r"(\d+(?:\.\d+)?)", expr)
        if num:
            return _parse_jdk_major(num.group(1))
        if expr in prop_vals:
            return prop_vals[expr]
        return None

    # Pass 2 — resolve compatibility / toolchain declarations
    versions: List[int] = []
    for txt in texts:
        for m in re.finditer(r"(?:source|target)Compatibility\s*=?\s*(.+)", txt):
            v = _resolve_expr(m.group(1))
            if v:
                versions.append(v)
        for m in re.finditer(r"JavaLanguageVersion\.of\(\s*['\"]?(\d+)['\"]?\s*\)", txt):
            versions.append(int(m.group(1)))
        for m in re.finditer(r"languageVersion\s*=?\s*(.+)", txt):
            v = _resolve_expr(m.group(1))
            if v:
                versions.append(v)

    if versions:
        return max(versions)
    if prop_vals:
        # Prefer a clearly java-related property when present.
        java_props = [v for k, v in prop_vals.items() if "java" in k.lower() or "jdk" in k.lower()]
        return max(java_props) if java_props else None
    return None


# Environment variables (highest → lowest priority) the user can set to force a
# specific local JDK for builds.  This is the deterministic, user-controllable
# fix for "Unsupported class file major version" — point it at e.g. a JDK 21
# install and every Gradle/Maven build will launch with that JDK regardless of
# any stray older JDKs (such as a JDK 8 in ~/.jdks) on the machine.
_BUILD_JDK_ENV_VARS = ("JAVAAPEX_BUILD_JDK", "GRADLE_JAVA_HOME", "BUILD_JAVA_HOME", "JAVA_HOME")


def _build_jdk_override() -> Tuple[Optional[str], Optional[int], bool]:
    """Return ``(java_home, major, is_explicit)`` for a JDK pinned via env var.

    ``is_explicit`` is True when one of the dedicated build-JDK vars is set
    (JAVAAPEX_BUILD_JDK / GRADLE_JAVA_HOME / BUILD_JAVA_HOME) — those are an
    absolute override.  When only JAVA_HOME is set, ``is_explicit`` is False
    so callers may still bump to a higher installed JDK if the project needs it.
    """
    for var in _BUILD_JDK_ENV_VARS:
        val = os.environ.get(var)
        if not val:
            continue
        home = Path(val.strip().strip('"'))
        java_name = "java.exe" if os.name == "nt" else "java"
        if not (home / "bin" / java_name).exists():
            logger.warning("Build-JDK env var %s=%s is not a valid JDK home (no bin/%s)", var, val, java_name)
            continue
        major = _jdk_major_from_home(home)
        if major:
            logger.info("Using build JDK from %s: %s (Java %d)", var, home, major)
            return str(home), major, (var != "JAVA_HOME")
    return None, None, False


def resolve_build_jdk(root: Path) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Pick the right JDK to build this project with.

    Returns ``(java_home, chosen_major, project_java)``:
      - A JDK pinned via env var (JAVAAPEX_BUILD_JDK / GRADLE_JAVA_HOME /
        BUILD_JAVA_HOME / JAVA_HOME) is preferred — this lets the user force a
        local JDK (e.g. JDK 21) and avoids picking up a stray older JDK.
      - **But** a pinned JDK is only honoured when the project's Gradle version
        can actually launch on it.  A repo that ships the Gradle 6.3 wrapper
        cannot run on JDK 21 — Gradle 6.3 fails immediately with "Unsupported
        class file major version 65" during the configuration phase.  When the
        override is too new for the project's Gradle (and the project itself
        does not require such a new JDK), we fall back to the best installed
        JDK the Gradle version supports instead of crashing.
      - When the project declares a target Java version, choose the smallest
        installed JDK that is >= that version (e.g. JDK 21 for a Java 21 repo).
      - Otherwise choose the highest installed JDK the project's Gradle can run on.
    """
    installed = detect_installed_jdks()
    project_java = detect_project_java_version(root)
    gradle_full = detect_gradle_full_version(root)

    def _gradle_runs_on(jdk_major: int) -> bool:
        """True when the project's Gradle version can launch on this JDK."""
        return _version_ge(gradle_full, _MIN_GRADLE_FOR_JDK.get(jdk_major, "99"))

    # Installed JDKs the project's Gradle can actually run on (highest first).
    gradle_ok = sorted((j for j in installed if _gradle_runs_on(j)), reverse=True)

    def _pick_compatible(prefer_at_least: Optional[int]) -> Optional[int]:
        """Best Gradle-compatible installed JDK, meeting ``prefer_at_least`` when possible."""
        if not gradle_ok:
            return None
        if prefer_at_least:
            meets = sorted(j for j in gradle_ok if j >= prefer_at_least)
            if meets:
                return meets[0]
        return gradle_ok[0]

    # ── User-pinned JDK from env (the "use local jdk stored in env" path) ──
    ov_home, ov_major, ov_explicit = _build_jdk_override()
    if ov_home and ov_major:
        if _gradle_runs_on(ov_major):
            # Override is compatible with the project's Gradle — honour it.
            if ov_explicit:
                return ov_home, ov_major, project_java
            # JAVA_HOME: use it unless the project needs a newer JDK than it
            # provides AND a suitable newer JDK is actually installed.
            if not project_java or ov_major >= project_java:
                return ov_home, ov_major, project_java
            higher = sorted(j for j in installed if j >= project_java)
            if higher:
                return installed[higher[0]], higher[0], project_java
            return ov_home, ov_major, project_java

        # ── Override JDK is too NEW for this project's Gradle version ──
        # (e.g. JDK 21 pinned via JAVAAPEX_BUILD_JDK but the repo ships the
        # Gradle 6.3 wrapper → "Unsupported class file major version 65").
        # A project that merely TARGETS Java 8 does NOT need JDK 21 — only a
        # project whose target Java exceeds what its Gradle can ever launch on
        # truly requires the newer JDK (and a Gradle upgrade with it).
        gradle_max_jdk = _max_jdk_for_gradle(gradle_full)
        project_requires_new = bool(project_java) and project_java > gradle_max_jdk
        if not project_requires_new:
            # 1) Prefer an already-installed JDK the old Gradle can run on.
            chosen = _pick_compatible(project_java)
            if chosen:
                logger.warning(
                    "Pinned build JDK %d is too new for the project's Gradle %s "
                    "(needs Gradle >= %s). Building with installed JDK %d instead "
                    "to avoid 'Unsupported class file major version'.",
                    ov_major, gradle_full,
                    _MIN_GRADLE_FOR_JDK.get(ov_major, "?"), chosen,
                )
                return installed[chosen], chosen, project_java
            # 2) None installed → download a compatible JDK (e.g. JDK 11) rather
            #    than forcing the old Gradle onto JDK 21 (which crashes during
            #    configuration with "Unsupported class file major version 65").
            prov_home, prov_major = _provision_compatible_jdk(gradle_full, project_java)
            if prov_home and prov_major:
                logger.warning(
                    "Pinned build JDK %d is too new for Gradle %s and no compatible "
                    "JDK is installed — provisioned JDK %d to build this legacy "
                    "project instead of crashing on JDK %d.",
                    ov_major, gradle_full, prov_major, ov_major,
                )
                return prov_home, prov_major, project_java
        # 3) The project genuinely needs a newer JDK than its Gradle supports, or
        #    no compatible JDK could be provisioned (offline) → keep the override
        #    and let ensure_wrapper_supports_jdk upgrade Gradle to launch on it.
        logger.warning(
            "Pinned build JDK %d is too new for Gradle %s; keeping JDK %d and "
            "relying on a Gradle wrapper upgrade.",
            ov_major, gradle_full, ov_major,
        )
        return ov_home, ov_major, project_java

    if not installed:
        # No JDK installed at all → try to provision one the project can use.
        prov_home, prov_major = _provision_compatible_jdk(gradle_full, project_java)
        if prov_home and prov_major:
            return prov_home, prov_major, project_java
        return None, None, project_java

    if project_java:
        eligible = sorted(j for j in installed if j >= project_java)
        # Prefer an eligible JDK the project's Gradle can also launch on.
        runnable = [j for j in eligible if _gradle_runs_on(j)]
        if runnable:
            chosen = runnable[0]
        elif eligible:
            chosen = eligible[0]  # newer JDK needed; wrapper upgrade follows
        else:
            chosen = max(installed)
    else:
        runnable = sorted(
            (j for j in installed if _gradle_runs_on(j)),
            reverse=True,
        )
        if runnable:
            chosen = runnable[0]
        else:
            # Every installed JDK is too new for the project's (old) Gradle →
            # provision a compatible one instead of crashing on the newest JDK.
            prov_home, prov_major = _provision_compatible_jdk(gradle_full, project_java)
            if prov_home and prov_major:
                return prov_home, prov_major, project_java
            chosen = max(installed)

    return installed[chosen], chosen, project_java


def ensure_wrapper_supports_jdk(root: Path, jdk_major: int) -> None:
    """Upgrade the Gradle wrapper version when it is too old to run on
    ``jdk_major`` (keeps the existing distribution host, e.g. jfrog.ford.com)."""
    min_ver = _MIN_GRADLE_FOR_JDK.get(jdk_major)
    if not min_ver:
        return
    wrapper_props = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if not wrapper_props.exists():
        return
    try:
        txt = wrapper_props.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"gradle-(\d+\.\d+(?:\.\d+)?)-((?:bin|all)\.zip)", txt)
        if not m:
            return
        cur = m.group(1)
        if _version_ge(cur, min_ver):
            return
        new_txt = re.sub(
            r"(gradle-)\d+\.\d+(?:\.\d+)?(-(?:bin|all)\.zip)",
            rf"\g<1>{min_ver}\g<2>",
            txt,
        )
        wrapper_props.write_text(new_txt, encoding="utf-8")
        logger.info(
            "Upgraded Gradle wrapper %s → %s so it can run on JDK %d", cur, min_ver, jdk_major
        )
    except Exception as e:
        logger.debug("Could not upgrade Gradle wrapper for JDK %d: %s", jdk_major, e)


def _write_gradle_java_home(root: Path, java_home: Path) -> None:
    """Pin the Gradle JVM + toolchain to ``java_home`` via gradle.properties.

    This is the deterministic fix for "Unsupported class file major version"
    errors: it forces Gradle to launch (and compile/test) with the chosen JDK
    instead of whatever JDK the backend process happens to expose.
    """
    gp = root / "gradle.properties"
    existing = gp.read_text(encoding="utf-8", errors="ignore") if gp.exists() else ""
    # Forward slashes avoid Java properties backslash-escaping issues on Windows.
    jh_str = str(java_home).replace("\\", "/")
    keep = [
        ln for ln in existing.splitlines()
        if not ln.strip().startswith("org.gradle.java.home")
        and not ln.strip().startswith("org.gradle.java.installations.paths")
        and not ln.strip().startswith("org.gradle.java.installations.auto-detect")
    ]
    keep.append(f"org.gradle.java.home={jh_str}")
    keep.append(f"org.gradle.java.installations.paths={jh_str}")
    keep.append("org.gradle.java.installations.auto-detect=true")
    gp.write_text("\n".join(keep).strip() + "\n", encoding="utf-8")


def ensure_compatible_jdk(gradle_major: int) -> Optional[str]:
    """Backward-compatible fallback: download JDK 11 only when the system JDK
    is too new for an OLD Gradle and no suitable JDK is already installed.

    Prefer :func:`resolve_build_jdk`, which selects an installed JDK that
    matches the project's target Java version.  This helper is retained for
    legacy callers and as a last resort.
    """
    # If a suitable installed JDK already exists, do not download anything.
    max_jdk = {6: 14, 7: 17, 8: 21}.get(gradle_major, 99)
    installed = detect_installed_jdks()
    suitable = sorted((j for j in installed if j <= max_jdk), reverse=True)
    if suitable:
        return str(Path(installed[suitable[0]]) / "bin" / ("java.exe" if os.name == "nt" else "java"))

    sys_jdk = detect_jdk_major_version()
    if sys_jdk and sys_jdk <= max_jdk:
        return None

    cache_dir = Path.home() / ".javaapex" / "jdk-cache" / "jdk11"
    if cache_dir.exists():
        for java_exe in cache_dir.rglob("java.exe" if os.name == "nt" else "java"):
            if java_exe.is_file():
                return str(java_exe)

    logger.info("No installed JDK <= %d for Gradle %d — downloading JDK 11...", max_jdk, gradle_major)
    arch = "x64"
    os_name = "windows" if os.name == "nt" else "linux"
    ext = "zip" if os.name == "nt" else "tar.gz"
    url = f"https://api.adoptium.net/v3/binary/latest/11/ga/{os_name}/{arch}/jdk/hotspot/normal/eclipse?project=jdk"
    try:
        import urllib.request
        proxy_url = get_ford_proxy()
        if proxy_url:
            handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            opener = urllib.request.build_opener(handler)
        else:
            opener = urllib.request.build_opener()
        cache_dir.mkdir(parents=True, exist_ok=True)
        archive = cache_dir / f"jdk11.{ext}"
        with opener.open(url, timeout=300) as resp:
            archive.write_bytes(resp.read())
        if ext == "zip":
            import zipfile
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(cache_dir)
        else:
            import tarfile
            with tarfile.open(archive) as tf:
                tf.extractall(cache_dir)
        archive.unlink(missing_ok=True)
        for java_exe in cache_dir.rglob("java.exe" if os.name == "nt" else "java"):
            if java_exe.is_file() and "bin" in str(java_exe):
                logger.info("JDK 11 ready at: %s", java_exe)
                return str(java_exe)
    except Exception as e:
        logger.warning("JDK 11 download failed: %s", e)
    return None


def _provision_compatible_jdk(
    gradle_full: str, prefer_at_least: Optional[int] = None
) -> Tuple[Optional[str], Optional[int]]:
    """Locate or download a JDK the project's (old) Gradle can actually launch on.

    Used when every *installed* JDK is too NEW for the project's Gradle version
    — e.g. only JDK 21 is present but the repo ships the Gradle 6.x wrapper,
    which crashes with "Unsupported class file major version 65" on JDK 21.
    Reuses :func:`ensure_compatible_jdk`, which prefers an already-installed
    compatible JDK and only downloads JDK 11 (honouring the Ford proxy) as a
    last resort.

    Returns ``(java_home, major)`` or ``(None, None)`` when nothing suitable
    could be provisioned (e.g. the machine is offline).
    """
    m = re.match(r"(\d+)", gradle_full or "")
    gradle_major = int(m.group(1)) if m else 6
    try:
        exe = ensure_compatible_jdk(gradle_major)
    except Exception as e:  # never let provisioning crash the build setup
        logger.warning("Compatible-JDK provisioning failed: %s", e)
        return None, None
    if not exe:
        return None, None
    home = Path(exe).resolve().parent.parent
    major = _jdk_major_from_home(home)
    if not major:
        return None, None
    # Re-validate: the provisioned JDK must launch this Gradle version and meet
    # the project's minimum Java target.
    if not _version_ge(gradle_full, _MIN_GRADLE_FOR_JDK.get(major, "99")):
        return None, None
    if prefer_at_least and major < prefer_at_least:
        return None, None
    return str(home), major


def cleanup_stale_gradle_locks(root: Path) -> None:
    """Remove stale Gradle wrapper lock files that prevent re-downloads.

    If a prior Gradle wrapper invocation crashed (e.g., JaCoCo build failure),
    it may leave .lck files in .gradle/wrapper/dists/ that permanently block
    the wrapper from re-downloading the distribution.
    """
    gradle_dists = root / ".gradle" / "wrapper" / "dists"
    if not gradle_dists.exists():
        return
    for lck in gradle_dists.rglob("*.lck"):
        try:
            lck.unlink()
            logger.info("Removed stale Gradle lock: %s", lck)
        except Exception:
            pass
    # Also remove partially downloaded zips
    for partial in gradle_dists.rglob("*.zip.part"):
        try:
            partial.unlink()
            logger.info("Removed partial Gradle download: %s", partial)
        except Exception:
            pass


def repair_gradle_build_files(root: Path) -> bool:
    """Repair known corruption patterns introduced by automated migration.

    The LLM-based migration step can replace a real Groovy map-literal opener
    ``name = [`` with a placeholder such as::

        library = [:] // Placeholder for truncated library map definition [
            atdAPI : "com.ford.fc.atd:atdAPI:1.3.0-SNAPSHOT",
            ...
        ]

    That is invalid Groovy — ``[:]`` is an *empty* map, so the following
    ``key : value,`` entries and the trailing ``]`` are dangling tokens.  The
    Groovy parser then reports a confusing error at the enclosing ``ext {``
    block (and the build never configures).  This restores the map opener so
    the existing entries form a valid literal again.

    Returns True when any file was modified.
    """
    changed_any = False
    # name = [:]  //<comment mentioning truncated/placeholder ending in `[`>
    corruption = re.compile(
        r'^(?P<prefix>[ \t]*(?:def[ \t]+|val[ \t]+|var[ \t]+)?[\w.]+[ \t]*=[ \t]*)'
        r'\[:\][ \t]*//[^\n]*?(?:truncat|placeholder)[^\n]*\[[ \t]*$',
        re.IGNORECASE | re.MULTILINE,
    )
    targets: List[Path] = []
    try:
        targets = list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts"))
    except Exception:
        return False
    for f in targets:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        new_text, n = corruption.subn(lambda m: m.group("prefix") + "[", text)
        if n:
            try:
                f.write_text(new_text, encoding="utf-8")
                changed_any = True
                logger.warning(
                    "Repaired %d corrupted truncated-map placeholder(s) in %s", n, f
                )
            except Exception as e:
                logger.debug("Could not repair %s: %s", f, e)
    return changed_any


# Gradle cache subdirectories that hold JDK-version-specific *compiled*
# bytecode/jars.  When the build JDK changes (e.g. we pin JDK 8 for a legacy
# Gradle 6.3 project after an earlier run used JDK 21), these caches still hold
# classes compiled for the OLD JDK.  An older Gradle/JDK then fails to read them
# with "Unsupported class file major version NN" during the *configuration*
# phase ("Could not open cp_proj / script generic class cache for ...").  We
# purge them so Gradle recompiles its build scripts with the freshly-pinned JDK.
# We never touch "modules-2" (downloaded dependencies) so there is no
# re-download cost.
_JDK_SENSITIVE_CACHE_DIRS: Tuple[str, ...] = (
    "scripts", "scripts-remapped", "generated-gradle-jars", "javaCompile",
    "cp_proj", "cp_settings", "cp_init", "cp_dsl", "kotlin-dsl",
)


def purge_jdk_sensitive_caches(
    root: Path, gradle_full: Optional[str], chosen_major: Optional[int]
) -> None:
    """Remove JDK-compiled Gradle script/class caches when the build JDK changes.

    This is the fix for the recurring *"Unsupported class file major version 65
    … could not configure root project / open Gradle's class caches"* failure:
    a previous run on JDK 21 leaves major-version-65 script classes in
    ``~/.gradle/caches/<version>/scripts`` (and friends); when we then correctly
    pin an older JDK (e.g. JDK 8 for Gradle 6.3) that older JVM cannot read the
    cached classes and the build dies in the configuration phase.

    Only the cheap-to-regenerate script/class caches are removed — the
    downloaded-dependency cache (``modules-2``) is preserved.  A per-project
    marker file records the JDK the caches were aligned to so repeated calls
    within a single pipeline run don't needlessly re-purge.
    """
    if not chosen_major:
        return

    marker = root / ".gradle" / ".javaapex_build_jdk"
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == str(chosen_major):
            return  # caches already aligned with this JDK
    except Exception:
        pass

    purged: List[str] = []

    # 1. Project-local cache (regenerable; holds no downloaded dependencies).
    proj_cache = root / ".gradle"
    if proj_cache.is_dir():
        try:
            shutil.rmtree(proj_cache, ignore_errors=True)
            purged.append(str(proj_cache))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Could not purge project cache %s: %s", proj_cache, exc)

    # 2. Global per-version script/class caches (keep modules-2 downloads).
    if gradle_full:
        gver_cache = Path.home() / ".gradle" / "caches" / gradle_full
        if gver_cache.is_dir():
            for name in _JDK_SENSITIVE_CACHE_DIRS:
                p = gver_cache / name
                if p.exists():
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                        purged.append(str(p))
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.debug("Could not purge cache %s: %s", p, exc)

    if purged:
        logger.info(
            "Purged %d JDK-stale Gradle cache dir(s) before building with JDK %s "
            "(prevents 'Unsupported class file major version'): %s",
            len(purged), chosen_major, ", ".join(purged),
        )

    # Record the JDK these caches will now be (re)built with.
    try:
        (root / ".gradle").mkdir(parents=True, exist_ok=True)
        marker.write_text(str(chosen_major), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Could not write build-JDK marker: %s", exc)


def build_gradle_env(
    root: Path,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Optional[str]]:
    """Full Gradle env setup for Ford network.

    Returns (env_dict, java_exe_or_None).
    Handles: init.gradle, proxy, JFrog creds, wrapper URL, JDK selection
    (project-Java-version aware), wrapper upgrade, and stale locks.
    """
    # Clean up stale locks from prior failed builds
    cleanup_stale_gradle_locks(root)

    # Repair build scripts corrupted by automated migration (e.g. a truncated
    # map literal rewritten as `name = [:] // Placeholder ... [`) — otherwise
    # Gradle fails to even parse build.gradle and never configures.
    repair_gradle_build_files(root)

    # Setup Ford-specific Gradle environment
    gradle_extra = setup_gradle_environment(root)

    # ── Pick the right JDK for THIS project ──
    # Selecting a JDK that matches the project's target Java version (e.g.
    # JDK 21 for a `sourceCompatibility = 21` repo) and pinning it via
    # org.gradle.java.home is what prevents "Unsupported class file major
    # version 65" — that error happens when Gradle is launched on an older
    # JDK (e.g. JDK 8) while the project compiles Java 21 bytecode.
    java_home, chosen_major, project_java = resolve_build_jdk(root)

    # Purge any JDK-version-stale Gradle caches BEFORE the build so the
    # configuration phase doesn't choke on "Unsupported class file major
    # version" while reading script classes a previous run compiled with a
    # different JDK (e.g. JDK 21 poison → JDK 8 reader for Gradle 6.3).
    purge_jdk_sensitive_caches(root, detect_gradle_full_version(root), chosen_major)

    # Make sure the wrapper's Gradle version can actually run on the chosen JDK.
    if chosen_major:
        ensure_wrapper_supports_jdk(root, chosen_major)

    # Build final env
    env = os.environ.copy()
    env.update(gradle_extra)
    if extra_env:
        env.update(extra_env)

    # Inject Gradle wrapper auth so the wrapper bootstrap can download its
    # distribution (e.g. gradle-8.5-bin.zip) from Ford's internal JFrog
    # Artifactory, which requires HTTP Basic auth (otherwise → HTTP 401).
    wrapper_opts = get_gradle_wrapper_opts()
    if wrapper_opts:
        existing_opts = (env.get("GRADLE_OPTS") or "").strip()
        env["GRADLE_OPTS"] = f"{existing_opts} {wrapper_opts}".strip()
        logger.info("Gradle wrapper auth enabled for internal JFrog distribution download")

    java_exe: Optional[str] = None
    if java_home:
        jh = Path(java_home)
        bin_dir = jh / "bin"
        java_name = "java.exe" if os.name == "nt" else "java"
        if (bin_dir / java_name).exists():
            java_exe = str(bin_dir / java_name)
            # Pin for the wrapper launcher (gradlew reads JAVA_HOME) …
            env["JAVA_HOME"] = str(jh)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            # … and for the Gradle daemon/toolchain (gradle.properties).
            _write_gradle_java_home(root, jh)
            logger.info(
                "Gradle will build with JDK %s at %s (project targets Java %s)",
                chosen_major, jh, project_java if project_java else "unknown",
            )
    else:
        logger.warning(
            "No installed JDK discovered for Gradle build at %s — "
            "falling back to the ambient JAVA_HOME/PATH", root,
        )

    return env, java_exe
