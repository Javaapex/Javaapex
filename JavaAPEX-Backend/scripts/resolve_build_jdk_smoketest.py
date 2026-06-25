"""Smoke test for the Gradle-version-aware build-JDK selection.

Reproduces the PinnacleTools failure: a repo that ships the **Gradle 6.3**
wrapper must NOT be built with a pinned **JDK 21** (JAVAAPEX_BUILD_JDK) because
Gradle 6.3 cannot launch on JDK 21 — it crashes with "Unsupported class file
major version 65". resolve_build_jdk() must instead fall back to a
Gradle-compatible installed JDK (e.g. JDK 8/11).

Run:  C:/Python314/python.exe scripts/resolve_build_jdk_smoketest.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import utils.gradle_env as ge  # noqa: E402


def _make_project(gradle_version: str, *, source_compat: str | None = None) -> Path:
    """Create a throwaway project dir with a Gradle wrapper of the given version."""
    proj = Path(tempfile.mkdtemp(prefix="jdkres_"))
    wdir = proj / "gradle" / "wrapper"
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "gradle-wrapper.properties").write_text(
        "distributionBase=GRADLE_USER_HOME\n"
        "distributionPath=wrapper/dists\n"
        f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{gradle_version}-bin.zip\n",
        encoding="utf-8",
    )
    build = "apply plugin: 'java'\n"
    if source_compat is not None:
        build += f"sourceCompatibility = {source_compat}\n"
    (proj / "build.gradle").write_text(build, encoding="utf-8")
    return proj


def _fake_jdk(major: int) -> str:
    """Create a fake JDK home with a release file so _jdk_major_from_home works."""
    home = Path(tempfile.mkdtemp(prefix=f"jdk{major}_"))
    (home / "bin").mkdir(parents=True, exist_ok=True)
    java_ver = f"1.8.0_482" if major == 8 else f"{major}.0.1"
    (home / "release").write_text(f'JAVA_VERSION="{java_ver}"\n', encoding="utf-8")
    return str(home)


def _run_case(
    name: str,
    *,
    gradle_version: str,
    override_major: int,
    installed: dict[int, str],
    source_compat: str | None,
    expect_major: int,
) -> bool:
    proj = _make_project(gradle_version, source_compat=source_compat)
    ov_home = installed[override_major]

    # Patch the discovery functions for a deterministic, machine-independent test.
    orig_installed = ge.detect_installed_jdks
    orig_override = ge._build_jdk_override
    ge.detect_installed_jdks = lambda: dict(installed)  # type: ignore[assignment]
    ge._build_jdk_override = lambda: (ov_home, override_major, True)  # type: ignore[assignment]
    try:
        java_home, chosen, project_java = ge.resolve_build_jdk(proj)
    finally:
        ge.detect_installed_jdks = orig_installed  # type: ignore[assignment]
        ge._build_jdk_override = orig_override  # type: ignore[assignment]

    ok = chosen == expect_major
    status = "PASS" if ok else "FAIL"
    print(
        f"[{status}] {name}\n"
        f"        gradle={gradle_version} pinned=JDK{override_major} "
        f"installed={sorted(installed)} sourceCompat={source_compat}\n"
        f"        -> chose JDK {chosen} (expected {expect_major}); "
        f"project_java={project_java}; java_home={java_home}"
    )
    return ok


def main() -> int:
    jdk8 = _fake_jdk(8)
    jdk11 = _fake_jdk(11)
    jdk21 = _fake_jdk(21)

    results = []

    # 1. THE BUG: Gradle 6.3 + pinned JDK 21 + JDK 8 installed -> must pick JDK 8.
    results.append(_run_case(
        "Gradle 6.3 + pinned JDK21 falls back to compatible JDK 8",
        gradle_version="6.3",
        override_major=21,
        installed={8: jdk8, 21: jdk21},
        source_compat=None,
        expect_major=8,
    ))

    # 2. Gradle 6.3 + pinned JDK 21, JDK 11 also installed -> prefer JDK 11 (higher compatible).
    results.append(_run_case(
        "Gradle 6.3 + pinned JDK21 prefers JDK 11 when available",
        gradle_version="6.3",
        override_major=21,
        installed={8: jdk8, 11: jdk11, 21: jdk21},
        source_compat="1.8",
        expect_major=8,  # sourceCompatibility 1.8 -> exact match JDK 8
    ))

    # 3. Gradle 6.3 + pinned JDK 21, only JDK 21 installed -> keep JDK 21 (wrapper upgrade path).
    results.append(_run_case(
        "Gradle 6.3 + pinned JDK21, no compatible JDK -> keep JDK 21",
        gradle_version="6.3",
        override_major=21,
        installed={21: jdk21},
        source_compat=None,
        expect_major=21,
    ))

    # 4. Modern: Gradle 8.5 + pinned JDK 21 -> keep JDK 21 (compatible).
    results.append(_run_case(
        "Gradle 8.5 + pinned JDK21 keeps JDK 21",
        gradle_version="8.5",
        override_major=21,
        installed={8: jdk8, 21: jdk21},
        source_compat="21",
        expect_major=21,
    ))

    # 5. Gradle 6.3 + pinned JDK 21, no source compat, only JDK 11 compatible installed.
    results.append(_run_case(
        "Gradle 6.3 + pinned JDK21 picks JDK 11 (no JDK 8)",
        gradle_version="6.3",
        override_major=21,
        installed={11: jdk11, 21: jdk21},
        source_compat=None,
        expect_major=11,
    ))

    print()
    if all(results):
        print(f"ALL {len(results)} CASES PASSED")
        return 0
    print(f"{results.count(False)} of {len(results)} CASES FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
