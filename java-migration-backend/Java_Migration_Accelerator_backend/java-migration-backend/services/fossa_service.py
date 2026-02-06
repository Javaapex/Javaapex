
import os
import asyncio
import json
import shutil
from typing import Dict, Any

class FossaService:
    def __init__(self):
        # Load API Key
        self.fossa_api_key = os.getenv("FOSSA_API_KEY")
        if not self.fossa_api_key:
            print("[WARN] FOSSA_API_KEY not set. Run: export FOSSA_API_KEY=xxxx")

        # Project Locator (Optional)
        self.project_locator = os.getenv(
            "FOSSA_PROJECT_LOCATOR",
            "github+https://github.com/your-org/your-repo"
        )

    # ----------------------------
    # MAIN ANALYSIS FUNCTION
    # ----------------------------
    async def analyze_project(self, project_path: str = None) -> Dict[str, Any]:

        if project_path is None:
            project_path = os.getcwd()

        print(f"[INFO] Starting FOSSA scan on: {project_path}")

        result = {
            "compliance_status": "UNKNOWN",
            "licenses": {},
            "vulnerabilities": {},
            "dependencies": [],
            "analysis_url": None,
            "critical_issues": 0,
            "high_issues": 0,
            "medium_issues": 0,
            "low_issues": 0,
            "total_dependencies": 0
        }

        # Check CLI
        if not self._is_fossa_installed():
            raise Exception("[ERROR] FOSSA CLI NOT FOUND. Install: choco install fossa-cli or brew install fossa-cli")

        # Run FOSSA ANALYZE
        await self._run_fossa_analyze(project_path)

        # Run FOSSA TEST (policy + vulns)
        raw_json = await self._run_fossa_test(project_path)

        # Parse JSON
        result = self._parse_fossa_json(raw_json)

        # Add dashboard link
        result["analysis_url"] = self._build_dashboard_url()

        # Print result
        self._display_results(result)

        return result

    # ----------------------------
    # RUN FOSSA ANALYZE
    # ----------------------------
    async def _run_fossa_analyze(self, path):
        print("[INFO] Running: fossa analyze")

        process = await asyncio.create_subprocess_exec(
            "fossa", "analyze",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=path
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(stderr.decode())
            raise Exception("[ERROR] FOSSA analyze failed")

        print("[OK] Analyze completed")

    # ----------------------------
    # RUN FOSSA TEST JSON
    # ----------------------------
    async def _run_fossa_test(self, path) -> dict:
        print("[INFO] Running: fossa test --json")

        process = await asyncio.create_subprocess_exec(
            "fossa", "test", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=path
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(stderr.decode())
            raise Exception("[ERROR] FOSSA test failed")

        if not stdout:
            raise Exception("[ERROR] No JSON output from FOSSA")

        return json.loads(stdout.decode())

    # ----------------------------
    # PARSE JSON OUTPUT
    # ----------------------------
    def _parse_fossa_json(self, data: dict) -> Dict[str, Any]:

        result = {
            "compliance_status": data.get("status", "UNKNOWN"),
            "licenses": {},
            "vulnerabilities": {},
            "dependencies": [],
            "critical_issues": 0,
            "high_issues": 0,
            "medium_issues": 0,
            "low_issues": 0,
            "total_dependencies": 0
        }

        # Dependencies list
        deps = data.get("dependencies", [])
        result["dependencies"] = deps
        result["total_dependencies"] = len(deps)

        # Licenses
        license_map = {}
        for d in deps:
            lic = d.get("license", "UNKNOWN")
            license_map[lic] = license_map.get(lic, 0) + 1
        result["licenses"] = license_map

        # Vulnerabilities
        vulns = data.get("vulnerabilities", [])
        vuln_count = {"critical":0, "high":0, "medium":0, "low":0}

        for v in vulns:
            sev = v.get("severity", "low").lower()
            if sev in vuln_count:
                vuln_count[sev] += 1

        result["vulnerabilities"] = vuln_count
        result["critical_issues"] = vuln_count["critical"]
        result["high_issues"] = vuln_count["high"]
        result["medium_issues"] = vuln_count["medium"]
        result["low_issues"] = vuln_count["low"]

        return result

    # ----------------------------
    # CHECK FOSSA CLI
    # ----------------------------
    def _is_fossa_installed(self):
        return shutil.which("fossa") is not None

    # ----------------------------
    # DASHBOARD URL
    # ----------------------------
    def _build_dashboard_url(self):
        return f"https://app.fossa.com/projects/{self.project_locator}/overview"

    # ----------------------------
    # PRINT RESULTS
    # ----------------------------
    def _display_results(self, r):
        print("\n================ FOSSA REPORT ================")
        print("Compliance Status:", r["compliance_status"])
        print("Total Dependencies:", r["total_dependencies"])
        print("Licenses:", r["licenses"])
        print("Vulnerabilities:", r["vulnerabilities"])
        print("Critical:", r["critical_issues"])
        print("High:", r["high_issues"])
        print("Medium:", r["medium_issues"])
        print("Low:", r["low_issues"])
        print("Dashboard:", r["analysis_url"])
        print("============================================\n")

    def _get_simulated_results(self, project_path: str) -> Dict[str, Any]:
        """Return a small, deterministic simulated FOSSA result for UI/testing.

        The real integration runs the FOSSA CLI and parses output. During
        development we return a predictable shape so the frontend can render
        policy status, dependency counts, licenses and vulnerability summaries.
        """
        # Basic defaults
        result: Dict[str, Any] = {
            "compliance_status": "UNKNOWN",
            "licenses": {},
            "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "dependencies": [],
            "analysis_url": self._build_dashboard_url(),
            "critical_issues": 0,
            "high_issues": 0,
            "medium_issues": 0,
            "low_issues": 0,
            "total_dependencies": 0
        }

        try:
            # Count some simple signals from the project path
            if project_path and os.path.exists(project_path):
                print(f"[FOSSA_SIM] simulate for path: {project_path}")
                dep_count = 0
                # Maven pom.xml detection
                pom = os.path.join(project_path, 'pom.xml')
                if os.path.exists(pom):
                    try:
                        with open(pom, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            dep_count += content.count('<dependency>')
                    except Exception:
                        dep_count += 0

                # Gradle build.gradle detection
                build_gradle = os.path.join(project_path, 'build.gradle')
                if os.path.exists(build_gradle):
                    try:
                        with open(build_gradle, 'r', encoding='utf-8', errors='ignore') as f:
                            for ln in f:
                                if 'implementation' in ln or 'compile' in ln or 'api ' in ln:
                                    dep_count += 1
                    except Exception:
                        dep_count += 0

         
                try:
                    if os.path.exists(pom):
                        try:
                            import xml.etree.ElementTree as ET
                            tree = ET.parse(pom)
                            root = tree.getroot()
                            # Count all dependency elements regardless of namespace
                            dep_elems = root.findall('.//dependency')
                            if not dep_elems:
                                # fallback: search by local-name ignoring namespace
                                dep_elems = [e for e in root.iter() if e.tag.endswith('dependency')]
                            dep_count += len(dep_elems)
                        except Exception:
                            # fallback to simple string count if XML parse fails
                            with open(pom, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                dep_count += content.count('<dependency>')
                except Exception:
                    pass

                # Parse build.gradle by scanning the dependencies block
                try:
                    if os.path.exists(build_gradle):
                        try:
                            in_deps = False
                            brace_level = 0
                            with open(build_gradle, 'r', encoding='utf-8', errors='ignore') as f:
                                for ln in f:
                                    s = ln.strip()
                                    if not in_deps and s.startswith('dependencies') and ('{' in s):
                                        in_deps = True
                                        brace_level = s.count('{') - s.count('}')
                                        continue
                                    if in_deps:
                                        brace_level += s.count('{') - s.count('}')
                                        if brace_level < 0:
                                            in_deps = False
                                            continue
                                        # Count common dependency declarations inside dependencies block
                                        if s.startswith("implementation") or s.startswith("compile") or s.startswith("api ") or s.startswith("compileOnly") or s.startswith("runtimeOnly"):
                                            dep_count += 1
                                # if dependencies block never opened, do a looser scan
                                if not in_deps:
                                    f.seek(0)
                                    for ln in f:
                                        if 'implementation(' in ln or 'api(' in ln or 'compile(' in ln:
                                            dep_count += 1
                        except Exception:
                            # best-effort: simple line scan fallback
                            with open(build_gradle, 'r', encoding='utf-8', errors='ignore') as f:
                                for ln in f:
                                    if 'implementation' in ln or 'compile' in ln or 'api ' in ln:
                                        dep_count += 1
                except Exception:
                    pass

                # Populate result using explicit dependency count only
                result['total_dependencies'] = int(dep_count)
                result['dependencies'] = []
                result['licenses'] = {}
                print(f"[FOSSA_SIM] detected dep_count={dep_count} (pom_exists={os.path.exists(pom)}, build_gradle_exists={os.path.exists(build_gradle)})")
                if dep_count == 0:
                    result['compliance_status'] = 'N/A'
                else:
                    result['compliance_status'] = 'PASSED'

                # Very small heuristic for vulnerabilities
                if dep_count > 10:
                    result['vulnerabilities'] = {"critical": 0, "high": 1, "medium": 2, "low": 0}
                    result['high_issues'] = 1
                    result['medium_issues'] = 2
                else:
                    result['vulnerabilities'] = {"critical": 0, "high": 0, "medium": 0, "low": 0}

                # Make licenses counts coherent (conservative: UNKNOWN if we can't detect)
                if dep_count > 0:
                    # conservative default: mark licenses unknown until real scan runs
                    result['licenses'] = {"UNKNOWN": dep_count}
                else:
                    result['licenses'] = {}

        except Exception:
            # If anything fails, return the default empty result
            pass

        return result


# ----------------------------
# RUN
# ----------------------------
if __name__ == "__main__":
    async def main():
        service = FossaService()
        result = await service.analyze_project()
        print(json.dumps(result, indent=4))

    asyncio.run(main())
