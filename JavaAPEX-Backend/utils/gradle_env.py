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
    """Extract JFrog credentials from Maven settings.xml or environment."""
    user = os.environ.get("ARTIFACTORY_USER")
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

    token = os.environ.get("FORD_JFROG_TOKEN")
    if token:
        return token, token
    return None, None


def setup_gradle_environment(root: Path) -> Dict[str, str]:
    """Prepare a Gradle project for building in the Ford network.

    Creates/patches:
      - init.gradle with mavenCentral() + gradlePluginPortal() (no UTF-8 BOM)
      - gradle.properties with proxy settings
      - gradle-wrapper.properties: patches jfrog.ford.com → services.gradle.org

    Returns extra env vars to pass to the Gradle subprocess.
    """
    extra_env: Dict[str, str] = {}

    # 1. JFrog credentials
    user, pwd = get_jfrog_credentials()
    if user:
        extra_env["ARTIFACTORY_USER"] = user
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
            )
            gp.write_text(existing + proxy_block, encoding="utf-8")

    # 4. Patch gradle-wrapper.properties
    patch_gradle_wrapper_url(root)

    return extra_env


def patch_gradle_wrapper_url(root: Path) -> None:
    """Replace jfrog.ford.com distribution URL with services.gradle.org."""
    wrapper_props = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if not wrapper_props.exists():
        return
    try:
        wp_text = wrapper_props.read_text(encoding="utf-8", errors="ignore")
        if "jfrog.ford.com" in wp_text:
            ver_match = re.search(r"gradle-(\d+\.\d+(?:\.\d+)?)-", wp_text)
            ver = ver_match.group(1) if ver_match else "6.3"
            new_url = f"https\\://services.gradle.org/distributions/gradle-{ver}-bin.zip"
            wp_text = re.sub(r"distributionUrl=.*", f"distributionUrl={new_url}", wp_text)
            wrapper_props.write_text(wp_text, encoding="utf-8")
            logger.info("Patched gradle-wrapper.properties: jfrog.ford.com → services.gradle.org (v%s)", ver)
    except Exception as e:
        logger.debug("Could not patch gradle-wrapper.properties: %s", e)


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
    """Detect the major version of the system JDK."""
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


def ensure_compatible_jdk(gradle_major: int) -> Optional[str]:
    """If system JDK is too new for the Gradle version, download JDK 11.

    Returns the path to java.exe if downloaded, or None if system JDK is fine.
    """
    sys_jdk = detect_jdk_major_version()
    max_jdk = {6: 14, 7: 17, 8: 21}.get(gradle_major, 99)
    if sys_jdk <= max_jdk:
        return None

    cache_dir = Path.home() / ".javaapex" / "jdk-cache" / "jdk11"
    if cache_dir.exists():
        for java_exe in cache_dir.rglob("java.exe" if os.name == "nt" else "java"):
            if java_exe.is_file():
                return str(java_exe)

    logger.info("System JDK %d is too new for Gradle %d — downloading JDK 11...", sys_jdk, gradle_major)
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


def build_gradle_env(
    root: Path,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Optional[str]]:
    """Full Gradle env setup for Ford network.

    Returns (env_dict, java_exe_or_None).
    Handles: init.gradle, proxy, JFrog creds, wrapper URL, JDK compat, stale locks.
    """
    # Clean up stale locks from prior failed builds
    cleanup_stale_gradle_locks(root)

    # Setup Ford-specific Gradle environment
    gradle_extra = setup_gradle_environment(root)

    # Detect Gradle version and ensure compatible JDK
    gradle_major = detect_gradle_major_version(root)
    java_exe = ensure_compatible_jdk(gradle_major)

    # Build final env
    env = os.environ.copy()
    env.update(gradle_extra)
    if extra_env:
        env.update(extra_env)

    if java_exe:
        java_home = str(Path(java_exe).parent.parent)
        env["JAVA_HOME"] = java_home
        env["PATH"] = str(Path(java_exe).parent) + os.pathsep + env.get("PATH", "")
        logger.info("Using JDK 11 at %s for Gradle %d", java_home, gradle_major)

    return env, java_exe
